from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .client import WorkbenchClient
from .config import AgentConfig, ProjectConfig
from .errors import AgentConfigError, AgentError, WorkbenchApiError
from .models import RunObservation, load_run_manifest


@dataclass(frozen=True)
class ProjectPathCheck:
    project: ProjectConfig
    exists: bool
    is_directory: bool

    @property
    def ok(self) -> bool:
        return self.exists and self.is_directory


@dataclass(frozen=True)
class DoctorReport:
    token_present: bool
    server_reachable: bool
    server_error: str | None
    projects: tuple[ProjectPathCheck, ...]

    @property
    def healthy(self) -> bool:
        return (
            self.token_present
            and self.server_reachable
            and all(project.ok for project in self.projects)
        )


class AgentService:
    def __init__(self, config: AgentConfig, client: WorkbenchClient) -> None:
        self.config = config
        self.client = client

    def doctor(self, *, token_present: bool) -> DoctorReport:
        server_reachable = True
        server_error = None
        try:
            self.client.health()
        except AgentError as exc:
            server_reachable = False
            server_error = str(exc)
        return DoctorReport(
            token_present=token_present,
            server_reachable=server_reachable,
            server_error=server_error,
            projects=tuple(self._check_path(project) for project in self.config.projects),
        )

    def heartbeat(self) -> dict[str, object]:
        return self.client.heartbeat_device(self.config.device)

    def sync(self, *, dry_run: bool = False) -> dict[str, str]:
        for project in self.config.projects:
            self._require_project_path(project)
        if dry_run:
            return {}
        self.heartbeat()
        source_ids: dict[str, str] = {}
        for project in self.config.projects:
            response = self.client.observe_project_source(project, self.config.device.id)
            source_ids[project.key] = self._source_id(response)
        return source_ids

    def observe_run(
        self, project_key: str, manifest_path: str | Path
    ) -> dict[str, object]:
        project = self.config.project(project_key)
        self._require_project_path(project)
        observation = load_run_manifest(manifest_path)
        self.heartbeat()
        source = self.client.observe_project_source(project, self.config.device.id)
        return self.client.observe_run(self._source_id(source), observation)

    @staticmethod
    def _check_path(project: ProjectConfig) -> ProjectPathCheck:
        path = Path(project.path)
        return ProjectPathCheck(project, path.exists(), path.is_dir())

    @classmethod
    def _require_project_path(cls, project: ProjectConfig) -> None:
        check = cls._check_path(project)
        if not check.exists:
            raise AgentConfigError(
                f"Project path does not exist for {project.key}: {project.path}"
            )
        if not check.is_directory:
            raise AgentConfigError(
                f"Project path is not a directory for {project.key}: {project.path}"
            )

    @staticmethod
    def _source_id(response: dict[str, object]) -> str:
        candidates = [response.get("id"), response.get("source_id")]
        source = response.get("source")
        if isinstance(source, dict):
            candidates.append(source.get("id"))
        for candidate in candidates:
            if isinstance(candidate, str) and candidate:
                return candidate
        raise WorkbenchApiError("Source observe response did not contain a source id")
