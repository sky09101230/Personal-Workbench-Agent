from __future__ import annotations

import json
from pathlib import Path

import pytest

from workbench_agent.config import AgentConfig, DeviceConfig, ProjectConfig, ServerConfig
from workbench_agent.errors import AgentConfigError, ManifestValidationError
from workbench_agent.models import load_run_manifest
from workbench_agent.service import AgentService


class FakeClient:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def health(self) -> dict[str, object]:
        self.calls.append("health")
        return {"status": "ok"}

    def heartbeat_device(self, device: DeviceConfig) -> dict[str, object]:
        self.calls.append("heartbeat")
        return {"id": "device-1"}

    def observe_project_source(
        self, project: ProjectConfig, device_id: str
    ) -> dict[str, object]:
        self.calls.append(f"source:{project.key}")
        return {"source": {"id": f"source-{project.key}"}}

    def observe_run(self, source_id: str, observation: object) -> dict[str, object]:
        self.calls.append("run")
        return {"id": "run-1"}


def make_config(*paths: Path) -> AgentConfig:
    return AgentConfig(
        ServerConfig("http://server", "TOKEN"),
        DeviceConfig("lab-5090", "Lab RTX 5090"),
        tuple(
            ProjectConfig(
                f"project-{index}",
                f"id-{index}",
                str(path),
                "remote_workspace",
                f"workspace:project-{index}",
            )
            for index, path in enumerate(paths)
        ),
    )


def write_manifest(tmp_path: Path, **changes: object) -> Path:
    data: dict[str, object] = {
        "run_id": "exp_034",
        "experiment_name": "baseline",
        "status": "finished",
        "created_at": None,
        "started_at": "2026-08-27T10:00:00+08:00",
        "ended_at": "2026-08-27T13:00:00+08:00",
        "latest_metrics": {"loss": 0.132},
        "summary": {"epochs": 100},
        "config_summary": {"batch_size": 64},
        "relative_path": "runs/exp_034",
        "has_best_checkpoint": True,
    }
    data.update(changes)
    path = tmp_path / "workbench-run.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_doctor_only_calls_health_and_never_ingest(tmp_path: Path) -> None:
    client = FakeClient()
    service = AgentService(make_config(tmp_path), client)  # type: ignore[arg-type]

    report = service.doctor(token_present=True)

    assert report.healthy
    assert client.calls == ["health"]


def test_sync_calls_heartbeat_once_and_each_source(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    client = FakeClient()

    source_ids = AgentService(make_config(first, second), client).sync()  # type: ignore[arg-type]

    assert client.calls == ["heartbeat", "source:project-0", "source:project-1"]
    assert source_ids == {
        "project-0": "source-project-0",
        "project-1": "source-project-1",
    }


def test_dry_run_sends_zero_requests(tmp_path: Path) -> None:
    client = FakeClient()

    assert AgentService(make_config(tmp_path), client).sync(dry_run=True) == {}  # type: ignore[arg-type]
    assert client.calls == []


def test_sync_rejects_missing_path_before_writes(tmp_path: Path) -> None:
    client = FakeClient()

    with pytest.raises(AgentConfigError, match="does not exist"):
        AgentService(make_config(tmp_path / "missing"), client).sync()  # type: ignore[arg-type]
    assert client.calls == []


def test_observe_run_call_order(tmp_path: Path) -> None:
    client = FakeClient()
    service = AgentService(make_config(tmp_path), client)  # type: ignore[arg-type]

    service.observe_run("project-0", write_manifest(tmp_path))

    assert client.calls == ["heartbeat", "source:project-0", "run"]


def test_manifest_accepts_dicts_nulls_and_aware_datetimes(tmp_path: Path) -> None:
    observation = load_run_manifest(write_manifest(tmp_path, experiment_name=None))

    assert observation.experiment_name is None
    assert observation.created_at is None
    assert observation.started_at is not None
    assert observation.started_at.utcoffset() is not None
    assert observation.latest_metrics == {"loss": 0.132}
    assert observation.summary == {"epochs": 100}
    assert observation.config_summary == {"batch_size": 64}


def test_manifest_rejects_naive_datetime(tmp_path: Path) -> None:
    with pytest.raises(ManifestValidationError, match="timezone"):
        load_run_manifest(write_manifest(tmp_path, started_at="2026-08-27T10:00:00"))


@pytest.mark.parametrize("field", ["latest_metrics", "summary", "config_summary"])
def test_manifest_requires_object_fields(tmp_path: Path, field: str) -> None:
    with pytest.raises(ManifestValidationError, match=field):
        load_run_manifest(write_manifest(tmp_path, **{field: []}))
