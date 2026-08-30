from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Callable

import pytest

from workbench_agent.errors import LiteratureRadarValidationError
from workbench_agent.literature import (
    LiteratureIngestService,
    literature_ingest_payload,
    validate_literature_output,
)


class RecordingClient:
    def __init__(self) -> None:
        self.payloads: list[dict[str, object]] = []

    def ingest_paper_research(self, payload: dict[str, object]) -> dict[str, object]:
        self.payloads.append(payload)
        return {
            "status": "succeeded",
            "run_id": "research-run:test",
            "created_run": True,
            "created_papers": 2,
            "created_recommendations": 2,
        }


def test_validated_output_maps_complete_radar_contract(tmp_path: Path) -> None:
    result_path, report_path, raw = write_artifacts(tmp_path)

    validation = validate_literature_output(result_path, report_path)
    payload = literature_ingest_payload(raw)

    assert validation == {
        "ok": True,
        "recommendation_count": 1,
        "source_count": 2,
        "candidate_count": 7,
        "verified_candidate_count": 2,
    }
    assert payload["schema_version"] == "2"
    assert payload["run_kind"] == "literature_radar"
    assert payload["task_key"] == "literature-radar:d2nn"
    assert payload["run_key"].startswith("radar-d2nn-20260829T174702Z-")
    assert payload["ingest_identity"].startswith("sha256:")
    assert len(payload["ingest_identity"]) == 71
    assert payload["candidate_count"] == 7
    assert payload["verified_candidate_count"] == 2
    assert payload["recommended_count"] == 1
    assert [paper["selection_kind"] for paper in payload["papers"]] == [
        "recommended",
        "verified_not_selected",
    ]
    assert payload["papers"][0]["zotero_relationship"]["already_in_library"] is False
    assert payload["papers"][1]["recommendation_reason"] == "Strong but lower evidence depth."
    assert "executable" not in payload["zotero_context"]
    assert payload["diagnostics"]["screening"]["exclusion_counts"]["already_in_zotero"] == 1


def test_mapping_identity_is_stable_for_equivalent_json_key_order(tmp_path: Path) -> None:
    _, _, raw = write_artifacts(tmp_path)
    reordered = {key: raw[key] for key in reversed(list(raw))}

    first = literature_ingest_payload(raw)
    second = literature_ingest_payload(reordered)

    assert second["ingest_identity"] == first["ingest_identity"]
    assert second["run_key"] == first["run_key"]


def test_service_dry_run_validates_without_upload(tmp_path: Path) -> None:
    result, report, _ = write_artifacts(tmp_path)
    client = RecordingClient()

    payload, response, validation = LiteratureIngestService(client).ingest(
        result,
        report_path=report,
        dry_run=True,
    )

    assert response is None
    assert validation["ok"] is True
    assert payload["recommended_count"] == 1
    assert client.payloads == []


def test_service_uploads_only_after_validator_passes(tmp_path: Path) -> None:
    result, report, _ = write_artifacts(tmp_path)
    client = RecordingClient()

    payload, response, _ = LiteratureIngestService(client).ingest(
        result,
        report_path=report,
    )

    assert response is not None
    assert response["run_id"] == "research-run:test"
    assert client.payloads == [payload]


def test_validator_failure_blocks_upload(tmp_path: Path) -> None:
    def mutate(result: dict[str, object]) -> None:
        result["recommendations"][0]["scores"]["overall"] = 0.001  # type: ignore[index]

    result, report, _ = write_artifacts(tmp_path, mutate=mutate)
    client = RecordingClient()

    with pytest.raises(LiteratureRadarValidationError, match="validation failed"):
        LiteratureIngestService(client).ingest(result, report_path=report)

    assert client.payloads == []


def test_mapper_rejects_malformed_verified_count(tmp_path: Path) -> None:
    _, _, raw = write_artifacts(tmp_path)
    malformed = copy.deepcopy(raw)
    malformed["search"]["verified_candidate_count"] = 3

    with pytest.raises(LiteratureRadarValidationError, match="does not match"):
        literature_ingest_payload(malformed)


def write_artifacts(
    tmp_path: Path,
    *,
    mutate: Callable[[dict[str, object]], None] | None = None,
) -> tuple[Path, Path, dict[str, object]]:
    profile_dir = tmp_path / "research_profiles"
    profile_dir.mkdir()
    profile = {
        "ranking": {
            "relevance": 0.35,
            "novelty_to_zotero": 0.30,
            "scientific_value": 0.20,
            "recency": 0.15,
        },
        "search": {"max_results": 5},
    }
    (profile_dir / "d2nn.json").write_text(json.dumps(profile), encoding="utf-8")
    run_dir = tmp_path / "research_outputs" / "run"
    run_dir.mkdir(parents=True)
    result: dict[str, object] = {
        "schema_version": 1,
        "profile": {
            "key": "d2nn",
            "name": "D2NN Literature Radar",
            "path": "research_profiles/d2nn.json",
        },
        "generated_at": "2026-08-29T17:47:02Z",
        "search_window": {
            "from": "2026-06-30",
            "to": "2026-08-29",
            "lookback_days": 60,
        },
        "zotero_context": {
            "success": True,
            "status": "success",
            "backend": "cli",
            "executable": "C:/Users/example/zotero-cli.exe",
            "utf8": True,
            "queries_used": ["diffractive neural network"],
            "successful_queries": 1,
            "failed_queries": 0,
            "query_limit": 10,
            "anchor_count": 22,
            "related_collection_count": 3,
            "summary": "Read-only library context was available.",
            "warnings": [],
        },
        "search": {
            "queries": ["diffractive neural network"],
            "sources_requested": ["openalex", "arxiv"],
            "sources_used": ["openalex", "arxiv"],
            "source_status": [
                {
                    "name": "openalex",
                    "status": "success",
                    "attempts": 1,
                    "routes": [{"route": "works_search", "status": "success"}],
                    "result_count": 7,
                    "warning": None,
                },
                {
                    "name": "arxiv",
                    "status": "degraded",
                    "attempts": 1,
                    "routes": [{"route": "atom", "status": "failed"}],
                    "result_count": 1,
                    "warning": "TLS fallback used.",
                },
            ],
            "candidate_count": 7,
            "verified_candidate_count": 2,
        },
        "screening": {
            "verified_not_selected": [
                {
                    "title": "Verified Alternative",
                    "doi": None,
                    "arxiv_id": "2608.00002",
                    "publication_type": "preprint",
                    "venue": "arXiv",
                    "date_evidence": {
                        "first_public_at": "2026-08-22",
                        "online_at": None,
                        "issue_at": None,
                        "preprint_at": "2026-08-22",
                        "accepted_at": None,
                        "version_published_at": "2026-08-22",
                        "selected_reason": "Official arXiv v1 date.",
                    },
                    "scores": {
                        "relevance": 0.75,
                        "novelty": 0.8,
                        "scientific_value": 0.7,
                        "recency": 1.0,
                        "overall": 0.796,
                    },
                    "primary_url": "https://arxiv.org/abs/2608.00002",
                    "reason": "Strong but lower evidence depth.",
                }
            ],
            "exclusion_counts": {
                "already_in_zotero": 1,
                "topic_or_exclusion_mismatch": 2,
            },
        },
        "stability": {"arxiv_atom_tls": {"status": "verified"}},
        "warnings": ["arXiv source degraded."],
        "recommendations": [
            {
                "title": "Verified Paper",
                "authors": ["Example Author"],
                "year": 2026,
                "published_at": "2026-08-20",
                "doi": "10.1234/example.1",
                "arxiv_id": None,
                "url": "https://doi.org/10.1234/example.1",
                "venue": "Example Journal",
                "publication_type": "journal",
                "ai_summary": "A verified summary.",
                "recommendation_reason": "Directly matches the profile.",
                "zotero_relationship": {
                    "already_in_library": False,
                    "related_papers": [],
                    "relationship_summary": "Related but not duplicated.",
                },
                "scores": {
                    "relevance": 0.9,
                    "novelty": 0.8,
                    "scientific_value": 0.7,
                    "recency": 0.85,
                    "overall": 0.823,
                },
                "evidence": {
                    "primary_url": "https://doi.org/10.1234/example.1",
                    "additional_urls": ["https://example.org/paper"],
                    "evidence_depth": "abstract",
                },
                "date_evidence": {
                    "first_public_at": "2026-08-20",
                    "online_at": "2026-08-20",
                    "issue_at": "2026-09",
                    "preprint_at": None,
                    "accepted_at": None,
                    "version_published_at": "2026-08-20",
                    "selected_reason": "Publisher online date.",
                },
            }
        ],
    }
    if mutate is not None:
        mutate(result)
    result_path = run_dir / "result.json"
    report_path = run_dir / "report.md"
    result_path.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    report_path.write_text("# Report\n\nVerified Paper\n", encoding="utf-8")
    return result_path, report_path, result
