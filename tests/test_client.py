from __future__ import annotations

import json
from datetime import datetime

import httpx
import pytest

from workbench_agent.client import WorkbenchClient
from workbench_agent.config import DeviceConfig, ProjectConfig
from workbench_agent.errors import (
    WorkbenchApiError,
    WorkbenchConnectionError,
)
from workbench_agent.models import RunObservation


DEVICE = DeviceConfig("lab-5090", "Lab RTX 5090")
PROJECT = ProjectConfig(
    "semantic-segmentation",
    "project-1",
    r"D:\D2NN\Semantic-Segmentation",
    "remote_workspace",
    "workspace:semantic-segmentation",
)
RUN = RunObservation(
    run_id="exp_034",
    experiment_name="baseline",
    status="finished",
    created_at=None,
    started_at=datetime.fromisoformat("2026-08-27T10:00:00+08:00"),
    ended_at=datetime.fromisoformat("2026-08-27T13:00:00+08:00"),
    latest_metrics={"loss": 0.132, "accuracy": 0.928},
    summary={"epochs": 100},
    config_summary={"learning_rate": 0.001},
    relative_path="runs/exp_034",
    has_best_checkpoint=True,
)


def json_body(request: httpx.Request) -> dict[str, object]:
    return json.loads(request.content)


def test_health_and_authorization_header() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/api/health"
        assert request.headers["Authorization"] == "Bearer secret"
        return httpx.Response(200, json={"status": "ok"})

    with WorkbenchClient(
        "http://workbench.example:8000", "secret", transport=httpx.MockTransport(handler)
    ) as client:
        assert client.health() == {"status": "ok"}


def test_client_does_not_inherit_system_proxy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:1")
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json={"status": "ok"})
    )

    with WorkbenchClient("http://127.0.0.1:8000", None, transport=transport) as client:
        assert client._client._trust_env is False
        assert client.health() == {"status": "ok"}


def test_heartbeat_payload() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/devices/heartbeat")
        assert json_body(request) == {
            "device_id": "lab-5090",
            "name": "Lab RTX 5090",
            "agent_version": "0.1.0",
        }
        return httpx.Response(200, json={"id": "device-1"})

    with WorkbenchClient("http://server", "token", transport=httpx.MockTransport(handler)) as client:
        client.heartbeat_device(DEVICE)


def test_source_payload() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/sources/observe")
        assert json_body(request) == {
            "project_id": "project-1",
            "source_type": "remote_workspace",
            "source_key": "workspace:semantic-segmentation",
            "device_id": "lab-5090",
            "local_path": r"D:\D2NN\Semantic-Segmentation",
        }
        return httpx.Response(200, json={"id": "source-1"})

    with WorkbenchClient("http://server", "token", transport=httpx.MockTransport(handler)) as client:
        client.observe_project_source(PROJECT, DEVICE.id)


def test_run_payload() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json_body(request)
        assert request.url.path.endswith("/runs/observe")
        assert body["source_id"] == "source-1"
        assert body["run_id"] == "exp_034"
        assert body["started_at"] == "2026-08-27T10:00:00+08:00"
        assert body["latest_metrics"] == {"loss": 0.132, "accuracy": 0.928}
        assert body["has_best_checkpoint"] is True
        return httpx.Response(200, json={"id": "run-1"})

    with WorkbenchClient("http://server", "token", transport=httpx.MockTransport(handler)) as client:
        client.observe_run("source-1", RUN)


def test_research_ingest_path_payload_and_auth() -> None:
    payload = {"schema_version": "1", "task_key": "demo", "papers": []}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/api/news/papers/research/ingest"
        assert request.headers["Authorization"] == "Bearer secret"
        assert json_body(request) == payload
        return httpx.Response(200, json={"status": "accepted"})

    with WorkbenchClient(
        "http://workbench.example", "secret", transport=httpx.MockTransport(handler)
    ) as client:
        assert client.ingest_paper_research(payload) == {"status": "accepted"}


@pytest.mark.parametrize("status", [404, 409, 422, 500])
def test_http_errors_raise_api_error(status: int) -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(status, json={"detail": "no"}))
    with WorkbenchClient("http://server", "token", transport=transport) as client:
        with pytest.raises(WorkbenchApiError, match=str(status)):
            client.health()


@pytest.mark.parametrize("error_type", [httpx.ConnectError, httpx.ReadTimeout])
def test_connection_and_timeout_raise_connection_error(error_type: type[Exception]) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise error_type("failed", request=request)

    with WorkbenchClient(
        "http://server", "token", transport=httpx.MockTransport(handler)
    ) as client:
        with pytest.raises(WorkbenchConnectionError):
            client.health()
