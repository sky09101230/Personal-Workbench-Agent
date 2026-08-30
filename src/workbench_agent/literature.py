from __future__ import annotations

import hashlib
import importlib.util
import json
import re
from pathlib import Path
from types import ModuleType
from typing import Mapping

from .client import WorkbenchClient
from .config import project_root
from .errors import LiteratureRadarValidationError


class LiteratureIngestService:
    def __init__(self, client: WorkbenchClient) -> None:
        self.client = client

    def ingest(
        self,
        result_path: str | Path,
        *,
        report_path: str | Path | None = None,
        dry_run: bool = False,
    ) -> tuple[dict[str, object], dict[str, object] | None, dict[str, object]]:
        result = Path(result_path).expanduser().resolve()
        report = (
            Path(report_path).expanduser().resolve()
            if report_path is not None
            else result.with_name("report.md")
        )
        validation = validate_literature_output(result, report)
        try:
            raw = json.loads(result.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise LiteratureRadarValidationError(
                f"Cannot read Literature Radar result {result}: {exc}"
            ) from exc
        payload = literature_ingest_payload(raw)
        response = None if dry_run else self.client.ingest_paper_research(payload)
        return payload, response, validation


def validate_literature_output(
    result_path: Path,
    report_path: Path,
) -> dict[str, object]:
    validator_path = (
        project_root()
        / ".agents"
        / "skills"
        / "literature-radar"
        / "scripts"
        / "validate_output.py"
    )
    try:
        validator = _load_validator(validator_path)
        result = validator.validate(result_path, report_path)
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise LiteratureRadarValidationError(
            f"Literature Radar output validation failed: {exc}"
        ) from exc
    if not isinstance(result, dict) or result.get("ok") is not True:
        raise LiteratureRadarValidationError(
            "Literature Radar output validator did not return success"
        )
    return result


def literature_ingest_payload(raw: object) -> dict[str, object]:
    result = _object(raw, "result")
    if result.get("schema_version") != 1:
        raise LiteratureRadarValidationError("result.schema_version must be 1")
    profile = _object(result.get("profile"), "result.profile")
    profile_key = _string(profile, "key", "result.profile")
    generated_at = _string(result, "generated_at", "result")
    search_window = _object(result.get("search_window"), "result.search_window")
    search = _object(result.get("search"), "result.search")
    screening = _object(result.get("screening"), "result.screening")
    recommendations = _object_list(
        result.get("recommendations"),
        "result.recommendations",
    )
    alternatives = _object_list(
        screening.get("verified_not_selected"),
        "result.screening.verified_not_selected",
    )
    digest = _canonical_digest(result)
    generated_key = re.sub(r"[^0-9A-Za-z]", "", generated_at)
    safe_profile_key = re.sub(r"[^A-Za-z0-9._:-]", "-", profile_key).strip("-")
    if not safe_profile_key:
        raise LiteratureRadarValidationError("result.profile.key is not usable as an identity")

    papers = [
        _recommended_paper(paper, rank)
        for rank, paper in enumerate(recommendations, start=1)
    ]
    papers.extend(
        _alternative_paper(paper, rank)
        for rank, paper in enumerate(alternatives, start=1)
    )
    verified_count = _integer(search, "verified_candidate_count", "result.search")
    if verified_count != len(papers):
        raise LiteratureRadarValidationError(
            "verified_candidate_count does not match mapped papers"
        )

    zotero = _object(result.get("zotero_context"), "result.zotero_context")
    safe_zotero = {
        key: zotero[key]
        for key in (
            "success",
            "status",
            "backend",
            "utf8",
            "queries_used",
            "successful_queries",
            "failed_queries",
            "query_limit",
            "anchor_count",
            "related_collection_count",
            "summary",
            "warnings",
        )
        if key in zotero
    }
    diagnostics = {
        "sources_requested": search.get("sources_requested", []),
        "sources_used": search.get("sources_used", []),
        "screening": {
            "exclusion_counts": screening.get("exclusion_counts", {}),
        },
        "stability": result.get("stability", {}),
    }
    return {
        "schema_version": "2",
        "task_key": f"literature-radar:{safe_profile_key}",
        "run_key": f"radar-{safe_profile_key}-{generated_key}-{digest[:16]}",
        "generated_at": generated_at,
        "agent": {
            "type": "literature-radar",
            "model": "not-recorded",
            "prompt_version": "v0.1",
        },
        "query_plan": _string_list(search.get("queries"), "result.search.queries"),
        "papers": papers,
        "run_kind": "literature_radar",
        "ingest_identity": f"sha256:{digest}",
        "profile": {
            "key": profile_key,
            "name": _string(profile, "name", "result.profile"),
            "path": _string(profile, "path", "result.profile"),
        },
        "search_window": {
            "from": _string(search_window, "from", "result.search_window"),
            "to": _string(search_window, "to", "result.search_window"),
            "lookback_days": _integer(
                search_window,
                "lookback_days",
                "result.search_window",
            ),
        },
        "candidate_count": _integer(search, "candidate_count", "result.search"),
        "verified_candidate_count": verified_count,
        "recommended_count": len(recommendations),
        "warnings": _string_list(result.get("warnings", []), "result.warnings"),
        "source_status": _object_list(
            search.get("source_status"),
            "result.search.source_status",
        ),
        "zotero_context": safe_zotero,
        "diagnostics": diagnostics,
    }


def _recommended_paper(paper: Mapping[str, object], rank: int) -> dict[str, object]:
    context = f"result.recommendations[{rank - 1}]"
    scores = _object(paper.get("scores"), f"{context}.scores")
    evidence = _object(paper.get("evidence"), f"{context}.evidence")
    date_evidence = _object(
        paper.get("date_evidence"),
        f"{context}.date_evidence",
    )
    relationship = _object(
        paper.get("zotero_relationship"),
        f"{context}.zotero_relationship",
    )
    primary_url = _string(evidence, "primary_url", f"{context}.evidence")
    return {
        "title": _string(paper, "title", context),
        "authors": _string_list(paper.get("authors", []), f"{context}.authors"),
        "doi": _optional_string(paper.get("doi"), f"{context}.doi"),
        "arxiv_id": _optional_string(paper.get("arxiv_id"), f"{context}.arxiv_id"),
        "openalex_id": None,
        "published_at": _string(paper, "published_at", context),
        "venue": _optional_string(paper.get("venue"), f"{context}.venue"),
        "publication_type": _optional_string(
            paper.get("publication_type"),
            f"{context}.publication_type",
        ),
        "url": _optional_string(paper.get("url"), f"{context}.url") or primary_url,
        "pdf_url": None,
        "abstract": None,
        "topics": [],
        "matched_topics": [],
        "ai_summary": _string(paper, "ai_summary", context),
        "recommendation_reason": _string(
            paper,
            "recommendation_reason",
            context,
        ),
        "relevance_score": _score(scores, "relevance", f"{context}.scores"),
        "novelty_score": _score(scores, "novelty", f"{context}.scores"),
        "scientific_value_score": _score(
            scores,
            "scientific_value",
            f"{context}.scores",
        ),
        "recency_score": _score(scores, "recency", f"{context}.scores"),
        "overall_score": _score(scores, "overall", f"{context}.scores"),
        "relationship_to_library": _optional_string(
            relationship.get("relationship_summary"),
            f"{context}.zotero_relationship.relationship_summary",
        ),
        "source": {"provider": "literature_radar", "source_id": primary_url},
        "selection_kind": "recommended",
        "selection_rank": rank,
        "date_evidence": date_evidence,
        "zotero_relationship": relationship,
        "evidence": evidence,
    }


def _alternative_paper(paper: Mapping[str, object], rank: int) -> dict[str, object]:
    context = f"result.screening.verified_not_selected[{rank - 1}]"
    scores = _object(paper.get("scores"), f"{context}.scores")
    date_evidence = _object(
        paper.get("date_evidence"),
        f"{context}.date_evidence",
    )
    primary_url = _string(paper, "primary_url", context)
    return {
        "title": _string(paper, "title", context),
        "authors": [],
        "doi": _optional_string(paper.get("doi"), f"{context}.doi"),
        "arxiv_id": _optional_string(paper.get("arxiv_id"), f"{context}.arxiv_id"),
        "openalex_id": None,
        "published_at": _string(date_evidence, "first_public_at", f"{context}.date_evidence"),
        "venue": _optional_string(paper.get("venue"), f"{context}.venue"),
        "publication_type": _optional_string(
            paper.get("publication_type"),
            f"{context}.publication_type",
        ),
        "url": primary_url,
        "pdf_url": None,
        "abstract": None,
        "topics": [],
        "matched_topics": [],
        "ai_summary": "",
        "recommendation_reason": _string(paper, "reason", context),
        "relevance_score": _score(scores, "relevance", f"{context}.scores"),
        "novelty_score": _score(scores, "novelty", f"{context}.scores"),
        "scientific_value_score": _score(
            scores,
            "scientific_value",
            f"{context}.scores",
        ),
        "recency_score": _score(scores, "recency", f"{context}.scores"),
        "overall_score": _score(scores, "overall", f"{context}.scores"),
        "relationship_to_library": None,
        "source": {"provider": "literature_radar", "source_id": primary_url},
        "selection_kind": "verified_not_selected",
        "selection_rank": rank,
        "date_evidence": date_evidence,
        "zotero_relationship": {},
        "evidence": {
            "primary_url": primary_url,
            "additional_urls": [],
            "evidence_depth": None,
        },
    }


def _load_validator(path: Path) -> ModuleType:
    if not path.is_file():
        raise LiteratureRadarValidationError(
            f"Literature Radar output validator is missing: {path}"
        )
    spec = importlib.util.spec_from_file_location(
        "workbench_agent_literature_radar_validator",
        path,
    )
    if spec is None or spec.loader is None:
        raise LiteratureRadarValidationError(
            f"Cannot load Literature Radar output validator: {path}"
        )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _canonical_digest(result: Mapping[str, object]) -> str:
    canonical = json.dumps(
        result,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _object(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise LiteratureRadarValidationError(f"{field} must be a JSON object")
    return value


def _object_list(value: object, field: str) -> list[dict[str, object]]:
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise LiteratureRadarValidationError(f"{field} must be an array of objects")
    return value


def _string(data: Mapping[str, object], key: str, field: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise LiteratureRadarValidationError(f"{field}.{key} must be a non-empty string")
    return value.strip()


def _optional_string(value: object, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise LiteratureRadarValidationError(f"{field} must be a string or null")
    return value.strip() or None


def _string_list(value: object, field: str) -> list[str]:
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item.strip() for item in value
    ):
        raise LiteratureRadarValidationError(
            f"{field} must be an array of non-empty strings"
        )
    return [item.strip() for item in value]


def _integer(data: Mapping[str, object], key: str, field: str) -> int:
    value = data.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise LiteratureRadarValidationError(f"{field}.{key} must be non-negative")
    return value


def _score(data: Mapping[str, object], key: str, field: str) -> float:
    value = data.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise LiteratureRadarValidationError(f"{field}.{key} must be numeric")
    score = float(value)
    if not 0 <= score <= 1:
        raise LiteratureRadarValidationError(f"{field}.{key} must be between 0 and 1")
    return score
