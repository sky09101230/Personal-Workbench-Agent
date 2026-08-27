from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping
from urllib.parse import urlsplit

from .errors import AgentConfigError


@dataclass(frozen=True)
class ServerConfig:
    url: str
    token_env: str


@dataclass(frozen=True)
class DeviceConfig:
    id: str
    name: str


@dataclass(frozen=True)
class ProjectConfig:
    key: str
    project_id: str
    path: str
    source_type: str
    source_key: str


@dataclass(frozen=True)
class AgentConfig:
    server: ServerConfig
    device: DeviceConfig
    projects: tuple[ProjectConfig, ...]

    def project(self, key: str) -> ProjectConfig:
        for project in self.projects:
            if project.key == key:
                return project
        raise AgentConfigError(f"Unknown project key: {key}")


def default_config_path() -> Path:
    return Path.home() / ".workbench-agent" / "config.json"


def _object(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise AgentConfigError(f"{field} must be a JSON object")
    return value


def _required_string(data: Mapping[str, object], field: str) -> str:
    value = data.get(field)
    if not isinstance(value, str) or not value.strip():
        raise AgentConfigError(f"{field} must be a non-empty string")
    return value.strip()


def load_config(path: str | Path | None = None) -> AgentConfig:
    config_path = Path(path) if path is not None else default_config_path()
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise AgentConfigError(f"Cannot read config {config_path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise AgentConfigError(f"Invalid JSON in config {config_path}: {exc}") from exc

    root = _object(raw, "config")
    server_raw = _object(root.get("server"), "server")
    device_raw = _object(root.get("device"), "device")
    projects_raw = root.get("projects")
    if not isinstance(projects_raw, list):
        raise AgentConfigError("projects must be a JSON array")

    server_url = _required_string(server_raw, "url").rstrip("/")
    parsed_url = urlsplit(server_url)
    if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
        raise AgentConfigError("server.url must be an absolute http(s) URL")

    projects: list[ProjectConfig] = []
    for index, item in enumerate(projects_raw):
        project_raw = _object(item, f"projects[{index}]")
        projects.append(
            ProjectConfig(
                key=_required_string(project_raw, "key"),
                project_id=_required_string(project_raw, "project_id"),
                path=_required_string(project_raw, "path"),
                source_type=_required_string(project_raw, "source_type"),
                source_key=_required_string(project_raw, "source_key"),
            )
        )

    keys = [project.key for project in projects]
    if len(keys) != len(set(keys)):
        raise AgentConfigError("project keys must be unique")

    return AgentConfig(
        server=ServerConfig(
            url=server_url,
            token_env=_required_string(server_raw, "token_env"),
        ),
        device=DeviceConfig(
            id=_required_string(device_raw, "id"),
            name=_required_string(device_raw, "name"),
        ),
        projects=tuple(projects),
    )


def load_token(config: AgentConfig, environ: Mapping[str, str] | None = None) -> str:
    environment = os.environ if environ is None else environ
    token = environment.get(config.server.token_env)
    if not token:
        raise AgentConfigError(
            f"Token environment variable is missing: {config.server.token_env}"
        )
    return token
