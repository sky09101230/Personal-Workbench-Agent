from __future__ import annotations

import argparse
import json
import os
import re
import ssl
import sys
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Callable, Mapping, Protocol, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

import certifi


ROOT = Path(__file__).resolve().parents[4]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from workbench_agent.config import load_env_file  # noqa: E402


ARXIV_API_URL = "https://export.arxiv.org/api/query"
SEMANTIC_SCHOLAR_API_URL = "https://api.semanticscholar.org/graph/v1/paper/search"
USER_AGENT = "Personal-Workbench-Literature-Radar/0.2"
SOURCE_STATES = {"success", "degraded", "failed", "not_attempted"}
_TRANSIENT_STATUSES = {429, 500, 502, 503, 504}
_ARXIV_NAMESPACE = {
    "atom": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
}


class SourceNetworkError(RuntimeError):
    pass


@dataclass(frozen=True)
class HttpResponse:
    status: int
    headers: Mapping[str, str]
    body: bytes


class Requester(Protocol):
    def __call__(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        context: ssl.SSLContext,
        timeout: float,
    ) -> HttpResponse:
        ...


@dataclass(frozen=True)
class SourceResult:
    name: str
    status: str
    attempts: int
    routes: tuple[dict[str, object], ...]
    result_count: int
    warning: str | None
    items: tuple[dict[str, object], ...] = ()

    def __post_init__(self) -> None:
        if self.status not in SOURCE_STATES:
            raise ValueError(f"invalid source status: {self.status}")

    def to_payload(self, *, include_items: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "name": self.name,
            "status": self.status,
            "attempts": self.attempts,
            "routes": [dict(route) for route in self.routes],
            "result_count": self.result_count,
            "warning": self.warning,
        }
        if include_items:
            payload["items"] = [dict(item) for item in self.items]
        return payload


@dataclass
class RateLimiter:
    min_interval: float
    monotonic: Callable[[], float] = time.monotonic
    sleep: Callable[[float], None] = time.sleep
    _last_request_at: float | None = field(default=None, init=False)

    def wait(self) -> None:
        now = self.monotonic()
        if self._last_request_at is not None:
            remaining = self.min_interval - (now - self._last_request_at)
            if remaining > 0:
                self.sleep(remaining)
                now = self.monotonic()
        self._last_request_at = now


class ArxivClient:
    def __init__(
        self,
        *,
        requester: Requester = None,
        timeout: float = 20.0,
        environment_diagnostic: Callable[[], dict[str, object]] | None = None,
    ) -> None:
        self.requester = requester or _request
        self.timeout = timeout
        self.context = ssl.create_default_context(cafile=certifi.where())
        self.environment_diagnostic = environment_diagnostic or default_ca_diagnostic
        self._cache: dict[tuple[str, int, int], SourceResult] = {}

    def search(
        self,
        query: str,
        *,
        limit: int = 5,
        evidence_limit: int | None = None,
    ) -> SourceResult:
        normalized_query = _normalized_query(query)
        if not normalized_query:
            raise ValueError("arXiv query must not be empty")
        if not 1 <= limit <= 100:
            raise ValueError("arXiv limit must be between 1 and 100")
        verify_count = limit if evidence_limit is None else evidence_limit
        if not 1 <= verify_count <= limit:
            raise ValueError("arXiv evidence_limit must be between 1 and limit")
        cache_key = (normalized_query, limit, verify_count)
        if cache_key in self._cache:
            return self._cache[cache_key]

        routes: list[dict[str, object]] = [self.environment_diagnostic()]
        attempts = 0
        parameters = urlencode(
            {
                "search_query": f'all:"{query.strip()}"',
                "start": 0,
                "max_results": limit,
                "sortBy": "submittedDate",
                "sortOrder": "descending",
            }
        )
        try:
            attempts += 1
            response = self.requester(
                f"{ARXIV_API_URL}?{parameters}",
                headers={"User-Agent": USER_AGENT, "Accept": "application/atom+xml"},
                context=self.context,
                timeout=self.timeout,
            )
        except SourceNetworkError as exc:
            result = SourceResult(
                name="arxiv",
                status="failed",
                attempts=attempts,
                routes=tuple(
                    routes
                    + [
                        {
                            "route": "atom_api",
                            "status": "failed",
                            "tls": "certifi",
                            "error": _safe_error_code(exc),
                        }
                    ]
                ),
                result_count=0,
                warning="The arXiv Atom API returned no usable evidence over verified TLS.",
            )
            self._cache[cache_key] = result
            return result

        if response.status != 200:
            result = SourceResult(
                name="arxiv",
                status="failed",
                attempts=attempts,
                routes=tuple(
                    routes
                    + [
                        {
                            "route": "atom_api",
                            "status": "failed",
                            "tls": "certifi",
                            "http_status": response.status,
                        }
                    ]
                ),
                result_count=0,
                warning=f"The arXiv Atom API returned HTTP {response.status}.",
            )
            self._cache[cache_key] = result
            return result

        try:
            items = _parse_arxiv_atom(response.body)
        except (ET.ParseError, ValueError):
            result = SourceResult(
                name="arxiv",
                status="failed",
                attempts=attempts,
                routes=tuple(
                    routes
                    + [
                        {
                            "route": "atom_api",
                            "status": "failed",
                            "tls": "certifi",
                            "error": "invalid_atom",
                        }
                    ]
                ),
                result_count=0,
                warning="The arXiv Atom response could not be parsed safely.",
            )
            self._cache[cache_key] = result
            return result

        routes.append(
            {
                "route": "atom_api",
                "status": "success" if items else "failed",
                "tls": "certifi",
                "result_count": len(items),
            }
        )
        if not items:
            result = SourceResult(
                name="arxiv",
                status="failed",
                attempts=attempts,
                routes=tuple(routes),
                result_count=0,
                warning="The arXiv Atom API returned no usable evidence for this query.",
            )
            self._cache[cache_key] = result
            return result

        verified = 0
        evidence_failures = 0
        enriched: list[dict[str, object]] = []
        for index, item in enumerate(items):
            materialized = dict(item)
            if index < verify_count:
                try:
                    attempts += 1
                    evidence_response = self.requester(
                        str(item["primary_url"]),
                        headers={"User-Agent": USER_AGENT, "Accept": "text/html"},
                        context=self.context,
                        timeout=self.timeout,
                    )
                    evidence_ok = 200 <= evidence_response.status < 400
                except SourceNetworkError:
                    evidence_response = None
                    evidence_ok = False
                materialized["official_evidence"] = {
                    "status": "success" if evidence_ok else "failed",
                    "url": item["primary_url"],
                }
                if evidence_ok:
                    verified += 1
                else:
                    evidence_failures += 1
            enriched.append(materialized)

        routes.append(
            {
                "route": "official_evidence",
                "status": "success" if verified == verify_count else "degraded" if verified else "failed",
                "verified_count": verified,
                "requested_count": verify_count,
            }
        )
        if verified == verify_count:
            status = "success"
            warning = None
        else:
            status = "degraded"
            warning = (
                f"arXiv Atom discovery succeeded, but {evidence_failures} official evidence "
                "page request(s) did not complete."
            )
        result = SourceResult(
            name="arxiv",
            status=status,
            attempts=attempts,
            routes=tuple(routes),
            result_count=len(items),
            warning=warning,
            items=tuple(enriched),
        )
        self._cache[cache_key] = result
        return result


class SemanticScholarClient:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        requester: Requester = None,
        timeout: float = 20.0,
        min_interval: float = 1.0,
        max_attempts: int = 3,
        max_retry_after: float = 30.0,
        monotonic: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if min_interval < 1.0:
            raise ValueError("Semantic Scholar min_interval must be at least 1 second")
        if not 1 <= max_attempts <= 5:
            raise ValueError("Semantic Scholar max_attempts must be between 1 and 5")
        self.api_key = api_key.strip() if api_key and api_key.strip() else None
        self.requester = requester or _request
        self.timeout = timeout
        self.context = ssl.create_default_context(cafile=certifi.where())
        self.max_attempts = max_attempts
        self.max_retry_after = max_retry_after
        self.wall_clock = wall_clock
        self.sleep = sleep
        self.rate_limiter = RateLimiter(
            min_interval=min_interval,
            monotonic=monotonic,
            sleep=sleep,
        )
        self._cache: dict[tuple[str, int, bool], SourceResult] = {}

    def search(
        self,
        query: str,
        *,
        limit: int = 10,
        fallback_available: bool = False,
    ) -> SourceResult:
        normalized_query = _normalized_query(query)
        if not normalized_query:
            raise ValueError("Semantic Scholar query must not be empty")
        if not 1 <= limit <= 100:
            raise ValueError("Semantic Scholar limit must be between 1 and 100")
        cache_key = (normalized_query, limit, fallback_available)
        if cache_key in self._cache:
            return self._cache[cache_key]

        fields = (
            "paperId,title,authors,year,publicationDate,venue,externalIds,url,"
            "openAccessPdf,abstract"
        )
        parameters = urlencode({"query": query.strip(), "limit": limit, "fields": fields})
        headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
        authentication = "anonymous"
        if self.api_key is not None:
            headers["x-api-key"] = self.api_key
            authentication = "api_key"

        routes: list[dict[str, object]] = []
        attempts = 0
        last_status: int | None = None
        last_error: str | None = None
        for attempt in range(1, self.max_attempts + 1):
            self.rate_limiter.wait()
            attempts += 1
            try:
                response = self.requester(
                    f"{SEMANTIC_SCHOLAR_API_URL}?{parameters}",
                    headers=headers,
                    context=self.context,
                    timeout=self.timeout,
                )
                last_status = response.status
                last_error = None
            except SourceNetworkError as exc:
                response = None
                last_error = _safe_error_code(exc)

            if response is not None and response.status == 200:
                try:
                    items = _parse_semantic_scholar(response.body)
                except (json.JSONDecodeError, TypeError, ValueError):
                    routes.append(
                        {
                            "route": "graph_api",
                            "status": "failed",
                            "attempt": attempt,
                            "authentication": authentication,
                            "error": "invalid_json",
                        }
                    )
                    result = SourceResult(
                        name="semantic_scholar",
                        status="failed",
                        attempts=attempts,
                        routes=tuple(routes),
                        result_count=0,
                        warning="Semantic Scholar returned an invalid JSON response.",
                    )
                    self._cache[cache_key] = result
                    return result
                routes.append(
                    {
                        "route": "graph_api",
                        "status": "success" if items else "failed",
                        "attempt": attempt,
                        "authentication": authentication,
                        "result_count": len(items),
                    }
                )
                status = "success" if items else "failed"
                result = SourceResult(
                    name="semantic_scholar",
                    status=status,
                    attempts=attempts,
                    routes=tuple(routes),
                    result_count=len(items),
                    warning=None if items else "Semantic Scholar returned no usable evidence.",
                    items=tuple(items),
                )
                self._cache[cache_key] = result
                return result

            retryable = response is None or response.status in _TRANSIENT_STATUSES
            route: dict[str, object] = {
                "route": "graph_api",
                "status": "retrying" if retryable and attempt < self.max_attempts else "failed",
                "attempt": attempt,
                "authentication": authentication,
            }
            if response is not None:
                route["http_status"] = response.status
            if last_error is not None:
                route["error"] = last_error
            routes.append(route)
            if not retryable or attempt >= self.max_attempts:
                break

            delay = _retry_delay(
                response.headers.get("Retry-After") if response is not None else None,
                attempt=attempt,
                now=self.wall_clock(),
                maximum=self.max_retry_after,
            )
            routes[-1]["retry_delay_seconds"] = delay
            routes[-1]["retry_after_honored"] = bool(
                response is not None and response.headers.get("Retry-After")
            )
            self.sleep(delay)

        status = "degraded" if fallback_available else "failed"
        if last_status == 429:
            detail = "rate limited after bounded retries"
        elif last_status is not None:
            detail = f"ended with HTTP {last_status}"
        else:
            detail = "could not be reached after bounded retries"
        mode = "API-key" if self.api_key is not None else "anonymous"
        warning = f"Semantic Scholar {mode} access {detail}."
        if fallback_available:
            warning += " Other sources supplied usable evidence."
        result = SourceResult(
            name="semantic_scholar",
            status=status,
            attempts=attempts,
            routes=tuple(routes),
            result_count=0,
            warning=warning,
        )
        self._cache[cache_key] = result
        return result


def default_ca_diagnostic() -> dict[str, object]:
    paths = ssl.get_default_verify_paths()
    cafile_available = bool(paths.cafile and Path(paths.cafile).is_file())
    capath_available = bool(paths.capath and Path(paths.capath).is_dir())
    return {
        "route": "default_ca_environment",
        "status": "success" if cafile_available or capath_available else "failed",
        "diagnostic": True,
        "cafile_available": cafile_available,
        "capath_available": capath_available,
        "active_tls_route": "certifi",
    }


def load_agent_environment() -> None:
    load_env_file(ROOT / ".env")


def semantic_scholar_api_key(
    environ: Mapping[str, str] | None = None,
) -> str | None:
    environment = os.environ if environ is None else environ
    value = environment.get("SEMANTIC_SCHOLAR_API_KEY")
    return value.strip() if value and value.strip() else None


def _request(
    url: str,
    *,
    headers: Mapping[str, str],
    context: ssl.SSLContext,
    timeout: float,
) -> HttpResponse:
    request = Request(url, headers=dict(headers), method="GET")
    try:
        with urlopen(request, timeout=timeout, context=context) as response:
            return HttpResponse(
                status=int(response.status),
                headers={key: value for key, value in response.headers.items()},
                body=response.read(4_000_000),
            )
    except HTTPError as exc:
        return HttpResponse(
            status=int(exc.code),
            headers={key: value for key, value in exc.headers.items()},
            body=exc.read(512_000),
        )
    except (URLError, TimeoutError, OSError, ssl.SSLError) as exc:
        raise SourceNetworkError(_safe_error_code(exc)) from exc


def _parse_arxiv_atom(body: bytes) -> list[dict[str, object]]:
    root = ET.fromstring(body)
    items: list[dict[str, object]] = []
    for entry in root.findall("atom:entry", _ARXIV_NAMESPACE):
        identifier_url = _element_text(entry, "atom:id")
        title = _element_text(entry, "atom:title")
        if not identifier_url or not title:
            continue
        arxiv_id = _arxiv_id(identifier_url)
        if arxiv_id is None:
            continue
        authors = [
            _element_text(author, "atom:name")
            for author in entry.findall("atom:author", _ARXIV_NAMESPACE)
        ]
        authors = [author for author in authors if author]
        doi = _element_text(entry, "arxiv:doi")
        published = _element_text(entry, "atom:published")
        updated = _element_text(entry, "atom:updated")
        summary = " ".join((_element_text(entry, "atom:summary") or "").split())
        primary_url = f"https://arxiv.org/abs/{arxiv_id}"
        items.append(
            {
                "title": " ".join(title.split()),
                "authors": authors,
                "arxiv_id": re.sub(r"v\d+$", "", arxiv_id, flags=re.IGNORECASE),
                "arxiv_version": arxiv_id,
                "doi": doi,
                "published_at": published,
                "updated_at": updated,
                "summary": summary,
                "primary_url": primary_url,
            }
        )
    return items


def _parse_semantic_scholar(body: bytes) -> list[dict[str, object]]:
    payload = json.loads(body.decode("utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise ValueError("Semantic Scholar response must contain data")
    items: list[dict[str, object]] = []
    for raw in payload["data"]:
        if not isinstance(raw, dict):
            continue
        title = raw.get("title")
        paper_id = raw.get("paperId")
        if not isinstance(title, str) or not title.strip() or not isinstance(paper_id, str):
            continue
        authors = raw.get("authors")
        author_names = [
            item.get("name")
            for item in authors
            if isinstance(item, dict) and isinstance(item.get("name"), str)
        ] if isinstance(authors, list) else []
        external_ids = raw.get("externalIds") if isinstance(raw.get("externalIds"), dict) else {}
        open_access_pdf = raw.get("openAccessPdf") if isinstance(raw.get("openAccessPdf"), dict) else {}
        items.append(
            {
                "paper_id": paper_id,
                "title": title.strip(),
                "authors": author_names,
                "year": raw.get("year"),
                "published_at": raw.get("publicationDate"),
                "venue": raw.get("venue"),
                "doi": external_ids.get("DOI"),
                "arxiv_id": external_ids.get("ArXiv"),
                "url": raw.get("url"),
                "pdf_url": open_access_pdf.get("url"),
                "abstract": raw.get("abstract"),
            }
        )
    return items


def _retry_delay(
    retry_after: str | None,
    *,
    attempt: int,
    now: datetime,
    maximum: float,
) -> float:
    if retry_after:
        stripped = retry_after.strip()
        try:
            return min(max(float(stripped), 0.0), maximum)
        except ValueError:
            try:
                target = parsedate_to_datetime(stripped)
                if target.tzinfo is None:
                    target = target.replace(tzinfo=timezone.utc)
                return min(max((target - now).total_seconds(), 0.0), maximum)
            except (TypeError, ValueError, OverflowError):
                pass
    return min(float(2 ** (attempt - 1)), maximum)


def _normalized_query(value: str) -> str:
    return " ".join(value.casefold().split())


def _element_text(element: ET.Element, path: str) -> str | None:
    child = element.find(path, _ARXIV_NAMESPACE)
    if child is None or child.text is None or not child.text.strip():
        return None
    return child.text.strip()


def _arxiv_id(value: str) -> str | None:
    parsed = urlsplit(value)
    candidate = parsed.path.removeprefix("/abs/").strip("/")
    return candidate or None


def _safe_error_code(error: BaseException) -> str:
    text = str(error).casefold()
    if "certificate" in text or "ssl" in text:
        return "tls_error"
    if "timed out" in text or "timeout" in text:
        return "timeout"
    if "name or service" in text or "getaddrinfo" in text:
        return "dns_error"
    if isinstance(error, SourceNetworkError):
        return str(error)
    return error.__class__.__name__.casefold()


def _emit(payload: Mapping[str, object]) -> None:
    sys.stdout.buffer.write(
        json.dumps(payload, ensure_ascii=True, separators=(",", ":")).encode("ascii")
        + b"\n"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Probe Literature Radar arXiv and Semantic Scholar sources safely"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    arxiv = commands.add_parser("arxiv", help="Search arXiv Atom and verify official evidence")
    arxiv.add_argument("--query", required=True)
    arxiv.add_argument("--limit", type=int, default=3)
    arxiv.add_argument("--evidence-limit", type=int)
    semantic = commands.add_parser("semantic-scholar", help="Search Semantic Scholar Graph API")
    semantic.add_argument("--query", required=True)
    semantic.add_argument("--limit", type=int, default=10)
    semantic.add_argument("--fallback-available", action="store_true")
    probe = commands.add_parser("probe", help="Probe both sources with one query")
    probe.add_argument("--query", default="diffractive optical neural network")
    probe.add_argument("--arxiv-limit", type=int, default=1)
    probe.add_argument("--semantic-limit", type=int, default=3)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    load_agent_environment()
    api_key = semantic_scholar_api_key()
    try:
        if args.command == "arxiv":
            result = ArxivClient().search(
                args.query,
                limit=args.limit,
                evidence_limit=args.evidence_limit,
            )
            _emit(result.to_payload())
            return 0 if result.status in {"success", "degraded"} else 1
        if args.command == "semantic-scholar":
            result = SemanticScholarClient(api_key=api_key).search(
                args.query,
                limit=args.limit,
                fallback_available=args.fallback_available,
            )
            payload = result.to_payload()
            payload["api_key_configured"] = api_key is not None
            _emit(payload)
            return 0 if result.status in {"success", "degraded"} else 1

        arxiv_result = ArxivClient().search(
            args.query,
            limit=args.arxiv_limit,
            evidence_limit=args.arxiv_limit,
        )
        semantic_result = SemanticScholarClient(api_key=api_key).search(
            args.query,
            limit=args.semantic_limit,
            fallback_available=bool(arxiv_result.items),
        )
        payload = {
            "ok": arxiv_result.status == "success"
            and semantic_result.status in {"success", "degraded"},
            "api_key_configured": api_key is not None,
            "sources": [
                arxiv_result.to_payload(),
                semantic_result.to_payload(),
            ],
        }
        _emit(payload)
        return 0 if payload["ok"] else 1
    except (OSError, ValueError, SourceNetworkError) as exc:
        _emit({"ok": False, "error": _safe_error_code(exc)})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
