from __future__ import annotations

import argparse
import json
import re
import sys
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from urllib.parse import urlsplit


ALLOWED_SOURCE_STATUS = {"success", "degraded", "failed", "not_attempted"}
SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_-]{16,}"),
    re.compile(r"(?i)ZOTERO_API_KEY\s*="),
    re.compile(r"(?i)ZOTERO_LIBRARY_ID\s*="),
    re.compile(r"(?i)authorization:\s*bearer\s+\S+"),
)


class ValidationError(ValueError):
    pass


def validate(result_path: Path, report_path: Path) -> dict[str, object]:
    result = json.loads(result_path.read_text(encoding="utf-8"))
    report = report_path.read_text(encoding="utf-8")
    if not isinstance(result, dict) or result.get("schema_version") != 1:
        raise ValidationError("result must be a schema_version 1 object")

    profile_ref = result.get("profile")
    if not isinstance(profile_ref, dict) or not isinstance(profile_ref.get("path"), str):
        raise ValidationError("result.profile.path is required")
    profile_path = (result_path.parents[2] / profile_ref["path"]).resolve()
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    ranking = profile.get("ranking")
    if not isinstance(ranking, dict):
        raise ValidationError("profile ranking is required")
    weights = {
        "relevance": Decimal(str(ranking["relevance"])),
        "novelty": Decimal(str(ranking["novelty_to_zotero"])),
        "scientific_value": Decimal(str(ranking["scientific_value"])),
        "recency": Decimal(str(ranking["recency"])),
    }
    if sum(weights.values()) != Decimal("1.0"):
        raise ValidationError("ranking weights must sum to 1")

    search = result.get("search")
    if not isinstance(search, dict):
        raise ValidationError("search object is required")
    statuses = search.get("source_status")
    if not isinstance(statuses, list) or not statuses:
        raise ValidationError("search.source_status must be a non-empty array")
    useful_source = False
    for index, source in enumerate(statuses):
        if not isinstance(source, dict):
            raise ValidationError(f"source_status[{index}] must be an object")
        if source.get("status") not in ALLOWED_SOURCE_STATUS:
            raise ValidationError(f"source_status[{index}] has invalid status")
        attempts = source.get("attempts")
        if isinstance(attempts, bool) or not isinstance(attempts, int) or attempts < 0:
            raise ValidationError(f"source_status[{index}].attempts must be non-negative")
        count = source.get("result_count", 0)
        if isinstance(count, int) and count > 0 and source.get("status") in {"success", "degraded"}:
            useful_source = True
    if not useful_source:
        raise ValidationError("at least one source must provide usable results")

    screening = result.get("screening")
    if not isinstance(screening, dict) or not isinstance(
        screening.get("verified_not_selected"), list
    ):
        raise ValidationError("screening.verified_not_selected is required")

    papers = result.get("recommendations")
    max_results = profile.get("search", {}).get("max_results")
    if not isinstance(papers, list) or not isinstance(max_results, int) or len(papers) > max_results:
        raise ValidationError("recommendation count exceeds profile max_results")
    verified = search.get("verified_candidate_count")
    expected_verified = len(papers) + len(screening["verified_not_selected"])
    if verified != expected_verified:
        raise ValidationError("verified candidate count must equal selected plus verified_not_selected")

    previous = Decimal("2")
    report_position = -1
    for index, paper in enumerate(papers):
        if not isinstance(paper, dict):
            raise ValidationError(f"recommendations[{index}] must be an object")
        title = paper.get("title")
        if not isinstance(title, str) or not title.strip():
            raise ValidationError(f"recommendations[{index}].title is required")
        scores = paper.get("scores")
        if not isinstance(scores, dict):
            raise ValidationError(f"{title}: scores are required")
        calculated = sum(
            Decimal(str(scores[name])) * weight for name, weight in weights.items()
        ).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
        if calculated != Decimal(str(scores.get("overall"))):
            raise ValidationError(f"{title}: overall score mismatch")
        if calculated > previous:
            raise ValidationError("recommendations are not sorted by overall")
        previous = calculated

        date_evidence = paper.get("date_evidence")
        if not isinstance(date_evidence, dict):
            raise ValidationError(f"{title}: date_evidence is required")
        if date_evidence.get("first_public_at") != paper.get("published_at"):
            raise ValidationError(f"{title}: published_at must equal first_public_at")
        if not date_evidence.get("selected_reason"):
            raise ValidationError(f"{title}: date selection reason is required")

        evidence = paper.get("evidence")
        primary = evidence.get("primary_url") if isinstance(evidence, dict) else None
        if not isinstance(primary, str) or urlsplit(primary).scheme != "https":
            raise ValidationError(f"{title}: HTTPS primary evidence is required")
        relationship = paper.get("zotero_relationship")
        if not isinstance(relationship, dict) or relationship.get("already_in_library") is not False:
            raise ValidationError(f"{title}: invalid Zotero duplicate decision")

        position = report.find(title)
        if position <= report_position:
            raise ValidationError(f"{title}: report order/content mismatch")
        report_position = position

    combined = result_path.read_text(encoding="utf-8") + "\n" + report
    for pattern in SECRET_PATTERNS:
        if pattern.search(combined):
            raise ValidationError(f"secret-like content matched {pattern.pattern}")

    return {
        "ok": True,
        "recommendation_count": len(papers),
        "source_count": len(statuses),
        "candidate_count": search.get("candidate_count"),
        "verified_candidate_count": search.get("verified_candidate_count"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate Literature Radar result/report artifacts")
    parser.add_argument("result", type=Path)
    parser.add_argument("report", type=Path)
    args = parser.parse_args()
    try:
        payload = validate(args.result.resolve(), args.report.resolve())
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValidationError) as exc:
        payload = {"ok": False, "error": str(exc)}
        sys.stdout.buffer.write(json.dumps(payload, ensure_ascii=True).encode("ascii") + b"\n")
        return 1
    sys.stdout.buffer.write(json.dumps(payload, ensure_ascii=True).encode("ascii") + b"\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
