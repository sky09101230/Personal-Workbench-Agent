from __future__ import annotations

from typing import Mapping

import httpx

from . import __version__
from .config import DeviceConfig, ProjectConfig
from .errors import (
    WorkbenchApiError,
    WorkbenchAuthenticationError,
    WorkbenchConnectionError,
)
from .models import RunObservation


class WorkbenchClient:
    def __init__(
        self,
        base_url: str,
        token: str | None,
        *,
        timeout: float = 10.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        headers = {"User-Agent": f"workbench-agent/{__version__}"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self._client = httpx.Client(
            base_url=f"{base_url.rstrip('/')}/",
            headers=headers,
            timeout=timeout,
            transport=transport,
        )

    def __enter__(self) -> WorkbenchClient:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def health(self) -> dict[str, object]:
        return self._request("GET", "api/health")

    def heartbeat_device(self, device: DeviceConfig) -> dict[str, object]:
        return self._request(
            "POST",
            "api/project-activity/devices/heartbeat",
            json={
                "device_id": device.id,
                "name": device.name,
                "agent_version": __version__,
            },
        )

    def observe_project_source(
        self, project: ProjectConfig, device_id: str
    ) -> dict[str, object]:
        return self._request(
            "POST",
            "api/project-activity/sources/observe",
            json={
                "project_id": project.project_id,
                "source_type": project.source_type,
                "source_key": project.source_key,
                "device_id": device_id,
                "local_path": project.path,
            },
        )

    def observe_run(
        self, source_id: str, observation: RunObservation
    ) -> dict[str, object]:
        return self._request(
            "POST",
            "api/project-activity/runs/observe",
            json=observation.to_payload(source_id),
        )

    def record_event(self, payload: Mapping[str, object]) -> dict[str, object]:
        return self._request(
            "POST", "api/project-activity/events", json=dict(payload)
        )

    def ingest_paper_research(
        self, payload: Mapping[str, object]
    ) -> dict[str, object]:
        return self._request(
            "POST", "api/news/papers/research/ingest", json=dict(payload)
        )

    def _request(
        self,
        method: str,
        path: str,
        *,
        json: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        try:
            response = self._client.request(method, path, json=json)
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise WorkbenchConnectionError(
                f"Cannot reach Workbench at {self._client.base_url}"
            ) from exc
        if response.status_code in {401, 403}:
            raise WorkbenchAuthenticationError(
                f"Workbench authentication failed ({response.status_code})"
            )
        if not response.is_success:
            raise WorkbenchApiError(
                f"Workbench API returned {response.status_code} for {method} /{path}"
            )
        try:
            data = response.json()
        except ValueError as exc:
            raise WorkbenchApiError("Workbench API returned invalid JSON") from exc
        if not isinstance(data, dict):
            raise WorkbenchApiError("Workbench API response must be a JSON object")
        return data
