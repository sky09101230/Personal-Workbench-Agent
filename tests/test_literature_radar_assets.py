from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / ".agents" / "skills" / "literature-radar"
PROFILE = ROOT / "research_profiles" / "d2nn.json"


def test_skill_is_project_discoverable_and_complete() -> None:
    skill_text = (SKILL / "SKILL.md").read_text(encoding="utf-8")

    assert skill_text.startswith("---\nname: literature-radar\n")
    assert "description:" in skill_text.split("---", 2)[1]
    assert 'zotero.backend = "cli"' in skill_text
    assert "zotero_cli.py preflight" in skill_text
    assert "research_tasks/" in skill_text
    assert "result.json" in skill_text
    assert "report.md" in skill_text

    for name in (
        "search-strategy.md",
        "zotero-context.md",
        "screening.md",
        "ranking.md",
    ):
        assert (SKILL / "references" / name).is_file()
    assert (SKILL / "scripts" / "zotero_cli.py").is_file()


def test_d2nn_profile_contract() -> None:
    profile = json.loads(PROFILE.read_text(encoding="utf-8"))

    assert profile["schema_version"] == 1
    assert profile["key"] == "d2nn"
    assert profile["interests"]
    assert profile["keywords"]["include"]
    assert profile["time"]["lookback_days"] == 60
    assert profile["zotero"] == {
        "enabled": True,
        "backend": "cli",
        "use_recent_library": True,
        "use_collections": True,
        "duplicate_detection": True,
        "novelty_against_library": True,
    }
    assert profile["search"]["max_results"] <= profile["search"]["max_candidates"]
    assert profile["search"]["sources"] == [
        "arxiv",
        "openalex",
        "semantic_scholar",
        "publisher_web",
    ]
    assert abs(sum(profile["ranking"].values()) - 1.0) < 1e-9
    assert profile["output"]["language"] == "zh-CN"


def test_upstream_and_ignored_outputs_are_recorded() -> None:
    upstream = (SKILL / "UPSTREAM.md").read_text(encoding="utf-8")
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()

    assert "97131ba7007f62374cc689cf7a85fa8fead8bb2b" in upstream
    assert "MIT License" in upstream
    assert "/research_outputs/" in gitignore
