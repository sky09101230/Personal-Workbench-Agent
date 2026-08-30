from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path
from typing import Mapping, Sequence


_ARXIV_RE = re.compile(r"(?:arxiv:|arxiv\.org/(?:abs|pdf|html)/)?([a-z.-]+/\d{7}|\d{4}\.\d{4,5})(?:v\d+)?", re.I)


def normalize_doi(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if text.startswith(prefix):
            text = text[len(prefix) :]
            break
    return text.rstrip(".,); ") if text.startswith("10.") else None


def normalize_arxiv(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    match = _ARXIV_RE.search(value.strip())
    return match.group(1).lower() if match else None


def canonical_title(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = unicodedata.normalize("NFKC", value).casefold()
    text = " ".join("".join(char if char.isalnum() else " " for char in text).split())
    return text or None


def identity_keys(record: Mapping[str, object]) -> set[str]:
    keys: set[str] = set()
    doi = normalize_doi(record.get("doi"))
    arxiv = normalize_arxiv(record.get("arxiv_id") or record.get("doi") or record.get("url"))
    title = canonical_title(record.get("title"))
    year = record.get("year")
    if doi:
        keys.add(f"doi:{doi}")
    if arxiv:
        keys.add(f"arxiv:{arxiv}")
    if title:
        keys.add(f"title:{title}")
        if isinstance(year, int):
            keys.add(f"title-year:{title}:{year}")
    return keys


def _quality(record: Mapping[str, object]) -> tuple[int, int, int]:
    doi = normalize_doi(record.get("doi")) or ""
    repository = any(name in doi for name in ("figshare", "zenodo"))
    stable_doi = int(bool(doi) and not repository and not doi.startswith("10.48550/arxiv."))
    has_primary = int(bool(record.get("primary_url") or record.get("landing") or record.get("url")))
    populated = sum(value not in (None, "", [], {}) for value in record.values())
    return stable_doi, has_primary, populated


def merge_records(records: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    groups: list[dict[str, object]] = []
    group_keys: list[set[str]] = []
    versions: list[list[dict[str, object]]] = []

    for raw in records:
        record = dict(raw)
        keys = identity_keys(record)
        matches = [index for index, known in enumerate(group_keys) if keys & known]
        if not matches:
            groups.append(record)
            group_keys.append(set(keys))
            versions.append([record])
            continue

        target = matches[0]
        versions[target].append(record)
        group_keys[target].update(keys)
        if _quality(record) > _quality(groups[target]):
            groups[target] = record
        for source in reversed(matches[1:]):
            versions[target].extend(versions[source])
            group_keys[target].update(group_keys[source])
            if _quality(groups[source]) > _quality(groups[target]):
                groups[target] = groups[source]
            del groups[source]
            del group_keys[source]
            del versions[source]

    output: list[dict[str, object]] = []
    for canonical, aliases in zip(groups, versions, strict=True):
        merged = dict(canonical)
        merged["identity"] = {
            "doi": normalize_doi(canonical.get("doi")),
            "arxiv_id": normalize_arxiv(
                canonical.get("arxiv_id") or canonical.get("doi") or canonical.get("url")
            ),
            "canonical_title": canonical_title(canonical.get("title")),
            "merged_record_count": len(aliases),
        }
        output.append(merged)
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description="Merge literature candidates by DOI, arXiv ID, and canonical title")
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    try:
        value = json.loads(args.input.read_text(encoding="utf-8"))
        if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
            raise ValueError("input must be a JSON array of objects")
        merged = merge_records(value)
        args.output.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
        payload = {"ok": True, "input_count": len(value), "output_count": len(merged)}
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        payload = {"ok": False, "error": str(exc)}
        sys.stdout.buffer.write(json.dumps(payload, ensure_ascii=True).encode("ascii") + b"\n")
        return 1
    sys.stdout.buffer.write(json.dumps(payload, ensure_ascii=True).encode("ascii") + b"\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
