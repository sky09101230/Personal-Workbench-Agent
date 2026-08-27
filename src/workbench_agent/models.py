from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Mapping

from .errors import ManifestValidationError


@dataclass(frozen=True)
class RunObservation:
    run_id: str
    experiment_name: str | None
    status: str
    created_at: datetime | None
    started_at: datetime | None
    ended_at: datetime | None
    latest_metrics: dict[str, object] | None
    summary: dict[str, object] | None
    config_summary: dict[str, object] | None
    relative_path: str | None
    has_best_checkpoint: bool

    def to_payload(self, source_id: str) -> dict[str, object]:
        return {
            "source_id": source_id,
            "run_id": self.run_id,
            "experiment_name": self.experiment_name,
            "status": self.status,
            "created_at": _isoformat(self.created_at),
            "started_at": _isoformat(self.started_at),
            "ended_at": _isoformat(self.ended_at),
            "latest_metrics": self.latest_metrics,
            "summary": self.summary,
            "config_summary": self.config_summary,
            "relative_path": self.relative_path,
            "has_best_checkpoint": self.has_best_checkpoint,
        }


def _isoformat(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _required_string(data: Mapping[str, object], field: str) -> str:
    value = data.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ManifestValidationError(f"{field} must be a non-empty string")
    return value.strip()


def _optional_string(data: Mapping[str, object], field: str) -> str | None:
    value = data.get(field)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ManifestValidationError(f"{field} must be a string or null")
    return value


def _optional_object(data: Mapping[str, object], field: str) -> dict[str, object] | None:
    value = data.get(field)
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ManifestValidationError(f"{field} must be an object or null")
    return value


def _optional_datetime(data: Mapping[str, object], field: str) -> datetime | None:
    value = data.get(field)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ManifestValidationError(f"{field} must be an ISO 8601 string or null")
    normalized = f"{value[:-1]}+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ManifestValidationError(f"{field} must be a valid ISO 8601 datetime") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ManifestValidationError(f"{field} must include a timezone offset")
    return parsed


def load_run_manifest(path: str | Path) -> RunObservation:
    manifest_path = Path(path)
    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ManifestValidationError(f"Cannot read manifest {manifest_path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ManifestValidationError(f"Invalid JSON in manifest {manifest_path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ManifestValidationError("manifest must be a JSON object")
    has_best_checkpoint = raw.get("has_best_checkpoint")
    if not isinstance(has_best_checkpoint, bool):
        raise ManifestValidationError("has_best_checkpoint must be a boolean")
    return RunObservation(
        run_id=_required_string(raw, "run_id"),
        experiment_name=_optional_string(raw, "experiment_name"),
        status=_required_string(raw, "status"),
        created_at=_optional_datetime(raw, "created_at"),
        started_at=_optional_datetime(raw, "started_at"),
        ended_at=_optional_datetime(raw, "ended_at"),
        latest_metrics=_optional_object(raw, "latest_metrics"),
        summary=_optional_object(raw, "summary"),
        config_summary=_optional_object(raw, "config_summary"),
        relative_path=_optional_string(raw, "relative_path"),
        has_best_checkpoint=has_best_checkpoint,
    )
