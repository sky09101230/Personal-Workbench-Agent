from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, MutableMapping
from urllib.parse import urlsplit

from .errors import AgentConfigError


_ENV_ASSIGNMENT = re.compile(
    r"^(?:export\s+)?(?P<key>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?P<value>.*)$"
)


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


def project_root() -> Path:
    """Return the source project root, falling back to the current directory."""
    package_path = Path(__file__).resolve().parent
    for candidate in (package_path, *package_path.parents):
        if (candidate / "pyproject.toml").is_file() and (
            candidate / "src" / "workbench_agent"
        ).is_dir():
            return candidate
    return Path.cwd().resolve()


def default_config_path() -> Path:
    return project_root() / "config.json"


def default_env_path(config_path: str | Path | None = None) -> Path:
    path = (
        Path(config_path).expanduser()
        if config_path is not None
        else default_config_path()
    )
    return path.parent / ".env"


def _dotenv_value(raw: str, *, path: Path, line_number: int) -> str:
    value = raw.strip()
    if not value:
        return ""

    quote = value[0]
    if quote in {"'", '"'}:
        result: list[str] = []
        escaped = False
        for index, character in enumerate(value[1:], start=1):
            if escaped:
                if quote == '"':
                    result.append(
                        {"n": "\n", "r": "\r", "t": "\t", "\\": "\\", '"': '"'}.get(
                            character, f"\\{character}"
                        )
                    )
                else:
                    result.append(
                        character
                        if character in {"'", "\\"}
                        else f"\\{character}"
                    )
                escaped = False
                continue
            if character == "\\":
                escaped = True
                continue
            if character == quote:
                trailing = value[index + 1 :].strip()
                if trailing and not trailing.startswith("#"):
                    raise AgentConfigError(
                        f"Invalid .env assignment in {path} at line {line_number}"
                    )
                return "".join(result)
            result.append(character)
        raise AgentConfigError(
            f"Unterminated quoted value in {path} at line {line_number}"
        )

    for index, character in enumerate(value):
        if character == "#" and (index == 0 or value[index - 1].isspace()):
            return value[:index].rstrip()
    return value


def load_env_file(
    path: str | Path | None = None,
    *,
    environ: MutableMapping[str, str] | None = None,
    override: bool = False,
) -> Path | None:
    """Load a dotenv file without replacing existing environment variables."""
    env_path = Path(path).expanduser() if path is not None else default_env_path()
    if not env_path.is_file():
        return None

    environment = os.environ if environ is None else environ
    try:
        lines = env_path.read_text(encoding="utf-8-sig").splitlines()
    except OSError as exc:
        raise AgentConfigError(
            f"Cannot read environment file {env_path}: {exc}"
        ) from exc

    for line_number, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = _ENV_ASSIGNMENT.fullmatch(line)
        if match is None:
            raise AgentConfigError(
                f"Invalid .env assignment in {env_path} at line {line_number}"
            )
        key = match.group("key")
        if override or key not in environment:
            environment[key] = _dotenv_value(
                match.group("value"), path=env_path, line_number=line_number
            )
    return env_path


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
    config_path = (
        Path(path).expanduser() if path is not None else default_config_path()
    )
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
