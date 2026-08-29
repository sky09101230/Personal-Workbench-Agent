from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from ..errors import ResearchTaskError


@dataclass(frozen=True)
class ResearchTask:
    key: str
    name: str
    topics: tuple[str, ...]
    keywords: tuple[str, ...]
    exclude: tuple[str, ...]
    lookback_days: int
    max_candidates: int
    max_results: int
    zotero_enabled: bool
    require_real_papers: bool
    require_primary_sources: bool


def default_research_task_dir() -> Path:
    return Path.home() / ".workbench-agent" / "research_tasks"


def _object(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ResearchTaskError(f"{field} must be a JSON object")
    return value


def _known_fields(data: Mapping[str, object], fields: set[str], label: str) -> None:
    unknown = sorted(set(data) - fields)
    if unknown:
        raise ResearchTaskError(f"Unknown {label} field(s): {', '.join(unknown)}")


def _string(data: Mapping[str, object], field: str) -> str:
    value = data.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ResearchTaskError(f"{field} must be a non-empty string")
    return value.strip()


def _strings(
    data: Mapping[str, object], field: str, *, required: bool = False
) -> tuple[str, ...]:
    value = data.get(field)
    if not isinstance(value, list):
        raise ResearchTaskError(f"{field} must be a JSON array")
    cleaned: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            raise ResearchTaskError(f"{field}[{index}] must be a non-empty string")
        text = item.strip()
        if text not in cleaned:
            cleaned.append(text)
    if required and not cleaned:
        raise ResearchTaskError(f"{field} must not be empty")
    return tuple(cleaned)


def _positive_int(data: Mapping[str, object], field: str) -> int:
    value = data.get(field)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ResearchTaskError(f"{field} must be a positive integer")
    return value


def _boolean(data: Mapping[str, object], field: str) -> bool:
    value = data.get(field)
    if not isinstance(value, bool):
        raise ResearchTaskError(f"{field} must be a boolean")
    return value


def load_research_task(
    key: str, task_dir: str | Path | None = None
) -> ResearchTask:
    directory = Path(task_dir) if task_dir is not None else default_research_task_dir()
    path = directory / f"{key}.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ResearchTaskError(f"Cannot read research task {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ResearchTaskError(f"Invalid JSON in research task {path}: {exc}") from exc

    root = _object(raw, "research task")
    _known_fields(
        root,
        {
            "key",
            "name",
            "topics",
            "keywords",
            "exclude",
            "lookback_days",
            "max_candidates",
            "max_results",
            "zotero",
            "research",
        },
        "research task",
    )
    zotero = _object(root.get("zotero"), "zotero")
    research = _object(root.get("research"), "research")
    _known_fields(zotero, {"enabled"}, "zotero")
    _known_fields(
        research,
        {"require_real_papers", "require_primary_sources"},
        "research",
    )

    task = ResearchTask(
        key=_string(root, "key"),
        name=_string(root, "name"),
        topics=_strings(root, "topics", required=True),
        keywords=_strings(root, "keywords"),
        exclude=_strings(root, "exclude"),
        lookback_days=_positive_int(root, "lookback_days"),
        max_candidates=_positive_int(root, "max_candidates"),
        max_results=_positive_int(root, "max_results"),
        zotero_enabled=_boolean(zotero, "enabled"),
        require_real_papers=_boolean(research, "require_real_papers"),
        require_primary_sources=_boolean(research, "require_primary_sources"),
    )
    if task.key != key:
        raise ResearchTaskError(
            f"Research task key {task.key!r} does not match requested key {key!r}"
        )
    if task.max_results > task.max_candidates:
        raise ResearchTaskError("max_results must not exceed max_candidates")
    return task
