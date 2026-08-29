from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Callable

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / ".agents" / "skills" / "literature-radar" / "scripts" / "validate_output.py"
SPEC = importlib.util.spec_from_file_location("literature_radar_validate_output", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
validator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(validator)


def write_artifacts(tmp_path: Path, *, change: Callable[[dict[str, object]], None] | None = None) -> tuple[Path, Path]:
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
    result = {
        "schema_version": 1,
        "profile": {"path": "research_profiles/d2nn.json"},
        "search": {
            "candidate_count": 4,
            "verified_candidate_count": 1,
            "source_status": [
                {
                    "name": "openalex",
                    "status": "success",
                    "attempts": 1,
                    "routes": [],
                    "result_count": 4,
                    "warning": None,
                }
            ],
        },
        "screening": {"verified_not_selected": [], "exclusion_counts": {}},
        "recommendations": [
            {
                "title": "Verified Paper",
                "published_at": "2026-08-20",
                "date_evidence": {
                    "first_public_at": "2026-08-20",
                    "online_at": "2026-08-20",
                    "issue_at": None,
                    "preprint_at": None,
                    "version_published_at": "2026-08-20",
                    "selected_reason": "publisher online date",
                },
                "scores": {
                    "relevance": 0.9,
                    "novelty": 0.8,
                    "scientific_value": 0.7,
                    "recency": 0.85,
                    "overall": 0.823,
                },
                "evidence": {"primary_url": "https://example.org/paper"},
                "zotero_relationship": {"already_in_library": False},
            }
        ],
    }
    if change is not None:
        change(result)
    result_path = run_dir / "result.json"
    report_path = run_dir / "report.md"
    result_path.write_text(json.dumps(result), encoding="utf-8")
    report_path.write_text("# Report\n\nVerified Paper\n", encoding="utf-8")
    return result_path, report_path


def test_valid_artifacts_pass(tmp_path: Path) -> None:
    result, report = write_artifacts(tmp_path)

    assert validator.validate(result, report) == {
        "ok": True,
        "recommendation_count": 1,
        "source_count": 1,
        "candidate_count": 4,
        "verified_candidate_count": 1,
    }


def test_source_status_is_required(tmp_path: Path) -> None:
    result, report = write_artifacts(
        tmp_path, change=lambda value: value["search"].pop("source_status")
    )

    with pytest.raises(validator.ValidationError, match="source_status"):
        validator.validate(result, report)


def test_score_mismatch_is_rejected(tmp_path: Path) -> None:
    def change(value: dict[str, object]) -> None:
        value["recommendations"][0]["scores"]["overall"] = 0.9  # type: ignore[index]

    result, report = write_artifacts(tmp_path, change=change)

    with pytest.raises(validator.ValidationError, match="score mismatch"):
        validator.validate(result, report)


def test_first_public_date_drives_published_at(tmp_path: Path) -> None:
    def change(value: dict[str, object]) -> None:
        value["recommendations"][0]["date_evidence"]["first_public_at"] = "2026-08-19"  # type: ignore[index]

    result, report = write_artifacts(tmp_path, change=change)

    with pytest.raises(validator.ValidationError, match="first_public_at"):
        validator.validate(result, report)


def test_secret_like_output_is_rejected(tmp_path: Path) -> None:
    result, report = write_artifacts(tmp_path)
    label = "ZOTERO_API_" + "KEY"
    report.write_text(f"Verified Paper\n{label}=not-allowed", encoding="utf-8")

    with pytest.raises(validator.ValidationError, match="secret-like"):
        validator.validate(result, report)
