from __future__ import annotations

import importlib.util
import json
import ssl
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / ".agents" / "skills" / "literature-radar" / "scripts" / "academic_sources.py"
SPEC = importlib.util.spec_from_file_location("literature_radar_academic_sources", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
sources = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = sources
SPEC.loader.exec_module(sources)


ATOM = b"""<?xml version='1.0' encoding='UTF-8'?>
<feed xmlns='http://www.w3.org/2005/Atom' xmlns:arxiv='http://arxiv.org/schemas/atom'>
  <entry>
    <id>https://arxiv.org/abs/2608.12345v2</id>
    <updated>2026-08-29T12:00:00Z</updated>
    <published>2026-08-28T12:00:00Z</published>
    <title>Verified Optical Paper</title>
    <summary>Verified abstract.</summary>
    <author><name>Example Author</name></author>
    <arxiv:doi>10.1234/example</arxiv:doi>
  </entry>
</feed>
"""


def semantic_body(title: str = "Semantic Paper") -> bytes:
    return json.dumps(
        {
            "data": [
                {
                    "paperId": "paper-1",
                    "title": title,
                    "authors": [{"name": "Example Author"}],
                    "year": 2026,
                    "publicationDate": "2026-08-28",
                    "venue": "Test Venue",
                    "externalIds": {"DOI": "10.1234/example", "ArXiv": "2608.12345"},
                    "url": "https://www.semanticscholar.org/paper/paper-1",
                    "openAccessPdf": {"url": "https://example.org/paper.pdf"},
                    "abstract": "Verified abstract.",
                }
            ]
        }
    ).encode("utf-8")


class SequenceRequester:
    def __init__(self, responses: list[object]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, object]] = []

    def __call__(
        self,
        url: str,
        *,
        headers: dict[str, str],
        context: ssl.SSLContext,
        timeout: float,
    ) -> object:
        self.calls.append(
            {
                "url": url,
                "headers": dict(headers),
                "verify_mode": context.verify_mode,
                "check_hostname": context.check_hostname,
                "timeout": timeout,
            }
        )
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


def test_arxiv_certifi_atom_and_official_evidence_are_success() -> None:
    requester = SequenceRequester(
        [
            sources.HttpResponse(200, {}, ATOM),
            sources.HttpResponse(200, {}, b"<html>official arXiv evidence</html>"),
        ]
    )
    client = sources.ArxivClient(
        requester=requester,
        environment_diagnostic=lambda: {
            "route": "default_ca_environment",
            "status": "failed",
            "diagnostic": True,
            "active_tls_route": "certifi",
        },
    )

    result = client.search("diffractive optical computing", limit=1)

    assert result.status == "success"
    assert result.warning is None
    assert result.result_count == 1
    assert result.items[0]["arxiv_id"] == "2608.12345"
    assert result.items[0]["official_evidence"]["status"] == "success"
    assert result.routes[0]["status"] == "failed"
    assert result.routes[0]["diagnostic"] is True
    assert result.routes[1] == {
        "route": "atom_api",
        "status": "success",
        "tls": "certifi",
        "result_count": 1,
    }
    assert result.routes[2]["status"] == "success"
    assert all(call["verify_mode"] == ssl.CERT_REQUIRED for call in requester.calls)
    assert all(call["check_hostname"] is True for call in requester.calls)


def test_arxiv_official_evidence_failure_is_degraded() -> None:
    requester = SequenceRequester(
        [
            sources.HttpResponse(200, {}, ATOM),
            sources.HttpResponse(503, {}, b"unavailable"),
        ]
    )

    result = sources.ArxivClient(requester=requester).search("optical", limit=1)

    assert result.status == "degraded"
    assert result.result_count == 1
    assert result.warning is not None


def test_semantic_scholar_sends_api_key_without_exposing_it() -> None:
    secret = "unit-test-key-not-a-secret"
    requester = SequenceRequester(
        [sources.HttpResponse(200, {}, semantic_body())]
    )
    client = sources.SemanticScholarClient(api_key=secret, requester=requester)

    result = client.search("optical computing", limit=1)
    serialized = json.dumps(result.to_payload())

    assert result.status == "success"
    assert requester.calls[0]["headers"]["x-api-key"] == secret
    assert result.routes[0]["authentication"] == "api_key"
    assert secret not in serialized
    assert "x-api-key" not in serialized.casefold()


def test_semantic_scholar_rate_limit_and_query_dedup() -> None:
    now = [0.0]
    sleeps: list[float] = []

    def sleep(value: float) -> None:
        sleeps.append(value)
        now[0] += value

    requester = SequenceRequester(
        [
            sources.HttpResponse(200, {}, semantic_body("First")),
            sources.HttpResponse(200, {}, semantic_body("Second")),
        ]
    )
    client = sources.SemanticScholarClient(
        requester=requester,
        monotonic=lambda: now[0],
        sleep=sleep,
    )

    first = client.search(" Optical   Computing ", limit=1)
    duplicate = client.search("optical computing", limit=1)
    second = client.search("different query", limit=1)

    assert duplicate is first
    assert second.status == "success"
    assert len(requester.calls) == 2
    assert sleeps == [1.0]


def test_semantic_scholar_honors_retry_after_then_succeeds() -> None:
    now = [0.0]
    sleeps: list[float] = []

    def sleep(value: float) -> None:
        sleeps.append(value)
        now[0] += value

    requester = SequenceRequester(
        [
            sources.HttpResponse(429, {"Retry-After": "2"}, b""),
            sources.HttpResponse(200, {}, semantic_body()),
        ]
    )
    client = sources.SemanticScholarClient(
        requester=requester,
        monotonic=lambda: now[0],
        sleep=sleep,
    )

    result = client.search("optical", limit=1)

    assert result.status == "success"
    assert result.attempts == 2
    assert sleeps == [2.0]
    assert result.routes[0]["retry_after_honored"] is True
    assert result.routes[0]["retry_delay_seconds"] == 2.0


def test_semantic_scholar_uses_bounded_backoff_and_degraded_fallback() -> None:
    now = [0.0]
    sleeps: list[float] = []

    def sleep(value: float) -> None:
        sleeps.append(value)
        now[0] += value

    requester = SequenceRequester(
        [
            sources.HttpResponse(429, {}, b""),
            sources.HttpResponse(429, {}, b""),
            sources.HttpResponse(429, {}, b""),
        ]
    )
    client = sources.SemanticScholarClient(
        requester=requester,
        monotonic=lambda: now[0],
        sleep=sleep,
    )

    result = client.search("optical", limit=1, fallback_available=True)

    assert result.status == "degraded"
    assert result.attempts == 3
    assert result.result_count == 0
    assert sleeps == [1.0, 2.0]
    assert "Other sources supplied usable evidence" in result.warning


def test_semantic_scholar_without_fallback_is_failed() -> None:
    requester = SequenceRequester(
        [sources.HttpResponse(429, {}, b"")]
    )
    client = sources.SemanticScholarClient(
        requester=requester,
        max_attempts=1,
    )

    result = client.search("optical", limit=1)

    assert result.status == "failed"


def test_api_key_reads_only_named_environment_value() -> None:
    assert sources.semantic_scholar_api_key({}) is None
    assert sources.semantic_scholar_api_key(
        {"SEMANTIC_SCHOLAR_API_KEY": "  secret  "}
    ) == "secret"


def test_source_script_never_disables_tls_verification() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert "verify=False" not in source
    assert "CERT_NONE" not in source
    assert "check_hostname = False" not in source
    assert "certifi.where()" in source
