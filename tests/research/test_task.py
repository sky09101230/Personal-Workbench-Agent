import json
from pathlib import Path

import pytest

from workbench_agent.config import project_root
from workbench_agent.errors import ResearchTaskError
from workbench_agent.research.task import default_research_task_dir, load_research_task


def task_data() -> dict[str, object]:
    return {
        "key": "d2nn-recent-papers",
        "name": "D2NN Recent Papers",
        "topics": ["diffractive neural networks"],
        "keywords": [],
        "exclude": ["on-chip photonics"],
        "lookback_days": 30,
        "max_candidates": 30,
        "max_results": 5,
        "zotero": {"enabled": True},
        "research": {
            "require_real_papers": True,
            "require_primary_sources": True,
        },
    }


def write_task(tmp_path: Path, data: object) -> None:
    (tmp_path / "d2nn-recent-papers.json").write_text(
        json.dumps(data), encoding="utf-8"
    )


def test_load_valid_task_and_remove_duplicate_strings(tmp_path: Path) -> None:
    data = task_data()
    data["topics"] = ["diffractive neural networks", " diffractive neural networks "]
    write_task(tmp_path, data)

    task = load_research_task("d2nn-recent-papers", tmp_path)

    assert task.topics == ("diffractive neural networks",)
    assert task.max_results == 5
    assert task.zotero_enabled


def test_missing_key_is_rejected(tmp_path: Path) -> None:
    data = task_data()
    del data["key"]
    write_task(tmp_path, data)

    with pytest.raises(ResearchTaskError, match="key"):
        load_research_task("d2nn-recent-papers", tmp_path)


def test_unknown_field_is_rejected(tmp_path: Path) -> None:
    data = task_data()
    data["surprise"] = True
    write_task(tmp_path, data)

    with pytest.raises(ResearchTaskError, match="Unknown.*surprise"):
        load_research_task("d2nn-recent-papers", tmp_path)


def test_invalid_lookback_days_is_rejected(tmp_path: Path) -> None:
    data = task_data()
    data["lookback_days"] = 0
    write_task(tmp_path, data)

    with pytest.raises(ResearchTaskError, match="lookback_days"):
        load_research_task("d2nn-recent-papers", tmp_path)


def test_max_results_must_not_exceed_candidates(tmp_path: Path) -> None:
    data = task_data()
    data["max_results"] = 31
    write_task(tmp_path, data)

    with pytest.raises(ResearchTaskError, match="max_results"):
        load_research_task("d2nn-recent-papers", tmp_path)


@pytest.mark.parametrize("field,value", [("topics", "topic"), ("keywords", None)])
def test_array_fields_are_strict(tmp_path: Path, field: str, value: object) -> None:
    data = task_data()
    data[field] = value
    write_task(tmp_path, data)

    with pytest.raises(ResearchTaskError, match=field):
        load_research_task("d2nn-recent-papers", tmp_path)


def test_default_research_task_dir_is_in_project_root() -> None:
    assert default_research_task_dir() == project_root() / "research_tasks"
