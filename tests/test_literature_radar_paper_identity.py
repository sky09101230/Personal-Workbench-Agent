from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / ".agents" / "skills" / "literature-radar" / "scripts" / "paper_identity.py"
SPEC = importlib.util.spec_from_file_location("literature_radar_paper_identity", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
identity = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(identity)


def test_normalizes_doi_urls_and_arxiv_versions() -> None:
    assert identity.normalize_doi("https://doi.org/10.1002/ABC.123") == "10.1002/abc.123"
    assert identity.normalize_arxiv("https://arxiv.org/abs/2608.12300v2") == "2608.12300"
    assert identity.normalize_arxiv("10.48550/arXiv.2608.12300") == "2608.12300"


def test_canonical_title_handles_unicode_punctuation() -> None:
    assert identity.canonical_title("Phase‐Multiplexed: Optical Computing") == "phase multiplexed optical computing"


def test_merges_preprint_and_formal_version_by_title() -> None:
    records = [
        {
            "title": "A Diffractive Optical Processor",
            "doi": "10.48550/arXiv.2608.00001",
            "arxiv_id": "2608.00001v2",
            "url": "https://arxiv.org/abs/2608.00001",
            "year": 2026,
        },
        {
            "title": "A Diffractive Optical Processor",
            "doi": "10.1002/example.1",
            "url": "https://doi.org/10.1002/example.1",
            "year": 2026,
            "venue": "Journal",
        },
    ]

    merged = identity.merge_records(records)

    assert len(merged) == 1
    assert merged[0]["doi"] == "10.1002/example.1"
    assert merged[0]["identity"]["merged_record_count"] == 2


def test_merges_missing_doi_record_with_doi_record_by_title() -> None:
    records = [
        {"title": "Universal Function Approximation via Diffractive Optical Processors", "doi": None},
        {"title": "Universal Function Approximation via Diffractive Optical Processors", "doi": "https://doi.org/10.48550/arXiv.2608.04582"},
    ]

    merged = identity.merge_records(records)

    assert len(merged) == 1
    assert merged[0]["identity"]["doi"] == "10.48550/arxiv.2608.04582"


def test_does_not_merge_different_titles_from_shared_keywords() -> None:
    records = [
        {"title": "Diffractive Neural Networks for Imaging", "year": 2026},
        {"title": "Diffractive Neural Networks for Classification", "year": 2026},
    ]

    assert len(identity.merge_records(records)) == 2
