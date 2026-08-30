from __future__ import annotations

import importlib.util
import json
import os
import re
import socket
import subprocess
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from types import ModuleType
from typing import Callable, Mapping, Protocol

from .client import WorkbenchClient
from .config import AgentConfig, load_config, load_env_file, load_token, project_root
from .errors import (
    AgentError,
    CodexExecutionError,
    LiteratureRadarLockError,
    LiteratureRadarPreflightError,
    LiteratureRadarRunError,
    LiteratureRadarValidationError,
    WorkbenchApiError,
    WorkbenchAuthenticationError,
    WorkbenchConnectionError,
)
from .literature import literature_ingest_payload, validate_literature_output
from .research.codex_runner import _resolve_executable, _safe_diagnostic


UTC = timezone.utc
DEFAULT_LOCK_STALE_AFTER = timedelta(hours=24)
SENSITIVE_NAMES = ("WORKBENCH_AGENT_TOKEN", "SEMANTIC_SCHOLAR_API_KEY")


class LiteratureCodexRunner(Protocol):
    executable: str

    def check_authentication(self) -> None: ...

    def run(self, instruction: str, *, workdir: Path) -> int: ...


class CodexLiteratureExecutionError(CodexExecutionError):
    def __init__(self, message: str, *, returncode: int | None = None) -> None:
        super().__init__(message)
        self.returncode = returncode


class CodexLiteratureRunner:
    """Run the repository Literature Radar skill in one reserved output directory."""

    def __init__(self, executable: str = "codex", *, timeout: float = 3600.0) -> None:
        self.executable = _resolve_executable(executable)
        self.timeout = timeout

    def check_authentication(self) -> None:
        completed = self._run_process(
            [self.executable, "login", "status"],
            timeout=min(self.timeout, 30.0),
        )
        if completed.returncode == 0:
            return
        doctor = self._run_process(
            [self.executable, "doctor", "--json"],
            timeout=min(self.timeout, 30.0),
        )
        try:
            report = json.loads(doctor.stdout)
        except json.JSONDecodeError:
            report = None
        checks = report.get("checks") if isinstance(report, dict) else None
        auth = checks.get("auth.credentials") if isinstance(checks, dict) else None
        if isinstance(auth, dict) and auth.get("status") == "ok":
            return
        raise CodexLiteratureExecutionError(
            "Codex authentication is unavailable for the active model provider; "
            "run `codex login` or repair the configured provider before the automation",
            returncode=completed.returncode,
        )

    def run(self, instruction: str, *, workdir: Path) -> int:
        diagnostic_path = workdir / "codex-last-message.txt"
        command = [
            self.executable,
            "--search",
            "--sandbox",
            "workspace-write",
            "--ask-for-approval",
            "never",
            "--cd",
            str(workdir),
            "exec",
            "--ephemeral",
            "--skip-git-repo-check",
            "--color",
            "never",
            "--output-last-message",
            str(diagnostic_path),
            "-",
        ]
        completed = self._run_process(command, input_text=instruction, timeout=self.timeout)
        self._sanitize_diagnostic(diagnostic_path)
        if completed.returncode != 0:
            detail = _safe_diagnostic(completed.stderr or completed.stdout)
            suffix = f": {detail}" if detail else ""
            raise CodexLiteratureExecutionError(
                f"Codex exited with status {completed.returncode}{suffix}",
                returncode=completed.returncode,
            )
        return completed.returncode

    @staticmethod
    def _sanitize_diagnostic(path: Path) -> None:
        if not path.is_file():
            return
        try:
            value = path.read_text(encoding="utf-8")
        except OSError:
            return
        secrets = tuple(
            secret
            for secret in (
                os.environ.get("WORKBENCH_AGENT_TOKEN", ""),
                os.environ.get("SEMANTIC_SCHOLAR_API_KEY", ""),
            )
            if secret
        )
        path.write_text(
            _redact_text(value, secrets=secrets).strip() + "\n",
            encoding="utf-8",
        )

    @staticmethod
    def _run_process(
        command: list[str],
        *,
        timeout: float,
        input_text: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(
                command,
                input=input_text,
                text=True,
                encoding="utf-8",
                capture_output=True,
                timeout=timeout,
                check=False,
            )
        except FileNotFoundError as exc:
            raise CodexLiteratureExecutionError(
                f"Codex executable was not found: {command[0]}"
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise CodexLiteratureExecutionError(
                f"Codex command timed out after {timeout:g} seconds"
            ) from exc
        except KeyboardInterrupt as exc:
            raise CodexLiteratureExecutionError("Codex research was interrupted") from exc
        except OSError as exc:
            raise CodexLiteratureExecutionError(f"Cannot start Codex: {exc}") from exc


@dataclass(frozen=True)
class LiteratureProfile:
    key: str
    name: str
    path: Path
    relative_path: str
    max_results: int
    zotero_queries: tuple[str, ...]
    raw: dict[str, object]


@dataclass(frozen=True)
class LiteraturePreflight:
    profile: LiteratureProfile
    runner: LiteratureCodexRunner
    checks: dict[str, str]
    zotero_context: dict[str, object]


@dataclass(frozen=True)
class LiteratureRunResult:
    profile_key: str
    output_directory: Path
    result_path: Path
    report_path: Path
    log_path: Path
    candidate_count: int
    verified_count: int
    recommended_count: int
    source_status: tuple[dict[str, object], ...]
    ingest_response: dict[str, object] | None


def load_literature_profile(
    profile_key: str,
    *,
    root: Path | None = None,
) -> LiteratureProfile:
    repository = (root or project_root()).resolve()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", profile_key):
        raise LiteratureRadarPreflightError(
            f"Invalid Literature Radar profile key: {profile_key}"
        )
    profiles = (repository / "research_profiles").resolve()
    path = (profiles / f"{profile_key}.json").resolve()
    try:
        path.relative_to(profiles)
    except ValueError as exc:
        raise LiteratureRadarPreflightError(
            f"Literature Radar profile escapes research_profiles: {profile_key}"
        ) from exc
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise LiteratureRadarPreflightError(
            f"Cannot read Literature Radar profile {path}: {exc}"
        ) from exc
    except json.JSONDecodeError as exc:
        raise LiteratureRadarPreflightError(
            f"Invalid JSON in Literature Radar profile {path}: {exc}"
        ) from exc
    if not isinstance(raw, dict):
        raise LiteratureRadarPreflightError("Literature Radar profile must be a JSON object")
    if raw.get("schema_version") != 1:
        raise LiteratureRadarPreflightError("Literature Radar profile schema_version must be 1")
    key = _required_string(raw, "key", "profile")
    if key != profile_key:
        raise LiteratureRadarPreflightError(
            f"Literature Radar profile key mismatch: expected {profile_key}, got {key}"
        )
    name = _required_string(raw, "name", "profile")
    _nonempty_string_list(raw.get("interests"), "profile.interests")
    keywords = _object(raw.get("keywords"), "profile.keywords")
    include = _nonempty_string_list(keywords.get("include"), "profile.keywords.include")
    _string_list(keywords.get("exclude"), "profile.keywords.exclude")
    time_config = _object(raw.get("time"), "profile.time")
    _positive_integer(time_config.get("lookback_days"), "profile.time.lookback_days")
    zotero = _object(raw.get("zotero"), "profile.zotero")
    if zotero.get("enabled") is not True or zotero.get("backend") != "cli":
        raise LiteratureRadarPreflightError(
            "Literature Radar automation requires zotero.enabled=true and backend=cli"
        )
    search = _object(raw.get("search"), "profile.search")
    max_candidates = _positive_integer(
        search.get("max_candidates"), "profile.search.max_candidates"
    )
    max_results = _positive_integer(
        search.get("max_results"), "profile.search.max_results"
    )
    if max_results > max_candidates:
        raise LiteratureRadarPreflightError(
            "profile.search.max_results cannot exceed max_candidates"
        )
    _nonempty_string_list(search.get("sources"), "profile.search.sources")
    ranking = _object(raw.get("ranking"), "profile.ranking")
    weights = []
    for field in ("relevance", "novelty_to_zotero", "scientific_value", "recency"):
        value = ranking.get(field)
        try:
            weight = Decimal(str(value))
        except (InvalidOperation, ValueError) as exc:
            raise LiteratureRadarPreflightError(
                f"profile.ranking.{field} must be numeric"
            ) from exc
        if not Decimal("0") <= weight <= Decimal("1"):
            raise LiteratureRadarPreflightError(
                f"profile.ranking.{field} must be between 0 and 1"
            )
        weights.append(weight)
    if sum(weights, Decimal("0")) != Decimal("1"):
        raise LiteratureRadarPreflightError("profile.ranking weights must sum to 1")
    return LiteratureProfile(
        key=key,
        name=name,
        path=path,
        relative_path=path.relative_to(repository).as_posix(),
        max_results=max_results,
        zotero_queries=tuple(dict.fromkeys(include)),
        raw=raw,
    )


class LiteratureRunLock:
    def __init__(
        self,
        path: Path,
        *,
        stale_after: timedelta = DEFAULT_LOCK_STALE_AFTER,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.path = path
        self.stale_after = stale_after
        self._now = now or (lambda: datetime.now(UTC))
        self.lock_id = uuid.uuid4().hex
        self.recovered_stale = False
        self._acquired = False

    def __enter__(self) -> LiteratureRunLock:
        self.acquire()
        return self

    def __exit__(self, *args: object) -> None:
        self.release()

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": 1,
            "lock_id": self.lock_id,
            "pid": os.getpid(),
            "host": socket.gethostname(),
            "started_at": _iso_utc(self._now()),
        }
        encoded = json.dumps(payload, sort_keys=True).encode("utf-8")
        for _ in range(2):
            try:
                descriptor = os.open(
                    self.path,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                )
            except FileExistsError:
                if not self._existing_lock_is_stale():
                    raise LiteratureRadarLockError(
                        "Another Literature Radar research run is active. "
                        f"Lock: {self.path}. Locks older than "
                        f"{self.stale_after.total_seconds() / 3600:g} hours "
                        "are recovered automatically."
                    )
                try:
                    self.path.unlink()
                except FileNotFoundError:
                    pass
                self.recovered_stale = True
                continue
            try:
                os.write(descriptor, encoded)
            finally:
                os.close(descriptor)
            self._acquired = True
            return
        raise LiteratureRadarLockError(
            f"Could not acquire Literature Radar run lock: {self.path}"
        )

    def release(self) -> None:
        if not self._acquired:
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            raw = None
        if isinstance(raw, dict) and raw.get("lock_id") == self.lock_id:
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass
        self._acquired = False

    def _existing_lock_is_stale(self) -> bool:
        now = self._now()
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            raw = None
        started_at = raw.get("started_at") if isinstance(raw, dict) else None
        if isinstance(started_at, str):
            try:
                started = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
            except ValueError:
                started = None
            if started is not None:
                return now - started.astimezone(UTC) >= self.stale_after
        try:
            modified = datetime.fromtimestamp(self.path.stat().st_mtime, tz=UTC)
        except OSError:
            return False
        return now - modified >= self.stale_after


class _RunLog:
    def __init__(
        self,
        path: Path,
        *,
        profile_key: str,
        started_at: datetime,
        secrets: tuple[str, ...],
    ) -> None:
        self.path = path
        self.secrets = secrets
        self.data: dict[str, object] = {
            "schema_version": 1,
            "started_at": _iso_utc(started_at),
            "completed_at": None,
            "profile": profile_key,
            "output_directory": None,
            "preflight_status": {},
            "lock_recovered_stale": False,
            "codex_exit_status": None,
            "validator_result": None,
            "candidate_count": None,
            "verified_count": None,
            "recommended_count": None,
            "final_source_status": [],
            "ingest_run_id": None,
            "ingest_created_or_existing": None,
            "final_result": "running",
            "failure_stage": None,
            "error": None,
        }
        self.write()

    def update(self, **values: object) -> None:
        self.data.update(values)
        self.write()

    def write(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        safe = _safe_log_value(self.data, secrets=self.secrets)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(safe, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.path)


class LiteratureRunService:
    def __init__(
        self,
        config: AgentConfig,
        client: WorkbenchClient,
        *,
        config_path: Path,
        env_path: Path,
        root: Path | None = None,
        runner: LiteratureCodexRunner | None = None,
        zotero_loader: Callable[[Path], ModuleType] | None = None,
        now: Callable[[], datetime] | None = None,
        lock_stale_after: timedelta = DEFAULT_LOCK_STALE_AFTER,
    ) -> None:
        self.config = config
        self.client = client
        self.config_path = config_path.expanduser().resolve()
        self.env_path = env_path.expanduser().resolve()
        self.root = (root or project_root()).resolve()
        self._runner = runner
        self._zotero_loader = zotero_loader or _load_zotero_module
        self._now = now or (lambda: datetime.now(UTC))
        self.lock_stale_after = lock_stale_after

    def run(self, profile_key: str, *, ingest: bool) -> LiteratureRunResult:
        started_at = self._now()
        token = os.environ.get(self.config.server.token_env, "")
        semantic_key = os.environ.get("SEMANTIC_SCHOLAR_API_KEY", "")
        secrets = tuple(value for value in (token, semantic_key) if value)
        log_path = self._new_log_path(profile_key, started_at)
        run_log = _RunLog(
            log_path,
            profile_key=profile_key,
            started_at=started_at,
            secrets=secrets,
        )
        lock = LiteratureRunLock(
            self.root / "logs" / "literature-radar" / "run.lock",
            stale_after=self.lock_stale_after,
            now=self._now,
        )
        stage = "lock"
        output_directory: Path | None = None
        try:
            with lock:
                run_log.update(lock_recovered_stale=lock.recovered_stale)
                stage = "preflight"
                preflight = self._preflight(profile_key, ingest=ingest, run_log=run_log)
                stage = "reserve_output"
                output_directory = self._reserve_output_directory()
                result_path = output_directory / "result.json"
                report_path = output_directory / "report.md"
                context_path = output_directory / "zotero-context.json"
                context_path.write_text(
                    json.dumps(
                        preflight.zotero_context,
                        ensure_ascii=False,
                        indent=2,
                        sort_keys=True,
                    )
                    + "\n",
                    encoding="utf-8",
                )
                run_log.update(output_directory=str(output_directory))
                instruction = build_literature_instruction(
                    preflight.profile,
                    repository_root=self.root,
                    output_directory=output_directory,
                )
                stage = "codex"
                try:
                    returncode = preflight.runner.run(
                        instruction,
                        workdir=output_directory,
                    )
                except CodexExecutionError as exc:
                    run_log.update(
                        codex_exit_status=getattr(exc, "returncode", None),
                    )
                    safe_error = _redact_text(str(exc), secrets=secrets)
                    raise LiteratureRadarRunError(
                        "Literature Radar research failed; ingest was not attempted. "
                        f"Artifacts and diagnostics were preserved in {output_directory}: "
                        f"{safe_error}"
                    ) from exc
                run_log.update(codex_exit_status=returncode)
                stage = "artifacts"
                _require_artifacts(output_directory, result_path, report_path)
                stage = "validator"
                try:
                    validation = validate_literature_output(result_path, report_path)
                    raw = json.loads(result_path.read_text(encoding="utf-8"))
                    payload = literature_ingest_payload(raw)
                    counts = _payload_counts(payload)
                except (LiteratureRadarValidationError, OSError, json.JSONDecodeError) as exc:
                    run_log.update(validator_result={"status": "failed"})
                    raise LiteratureRadarRunError(
                        "Literature Radar validation failed; ingest was not attempted. "
                        f"Artifacts were preserved in {output_directory}: {exc}"
                    ) from exc
                source_status = _source_status(raw)
                run_log.update(
                    validator_result={"status": "passed", "details": validation},
                    candidate_count=counts[0],
                    verified_count=counts[1],
                    recommended_count=counts[2],
                    final_source_status=source_status,
                )
                response: dict[str, object] | None = None
                if ingest:
                    stage = "ingest"
                    try:
                        response = self.client.ingest_paper_research(payload)
                    except (
                        WorkbenchConnectionError,
                        WorkbenchAuthenticationError,
                        WorkbenchApiError,
                    ) as exc:
                        recovery = _recovery_command(result_path)
                        raise LiteratureRadarRunError(
                            "Literature Radar succeeded but Workbench ingest failed. "
                            f"Artifacts were preserved in {output_directory}. "
                            f"Recover without rerunning research: {recovery}. Error: {exc}"
                        ) from exc
                    run_log.update(
                        ingest_run_id=_optional_log_string(response.get("run_id")),
                        ingest_created_or_existing=(
                            "created" if response.get("created_run") is True else "existing"
                        ),
                    )
                else:
                    run_log.update(ingest_created_or_existing="skipped")
                run_log.update(
                    completed_at=_iso_utc(self._now()),
                    final_result="success",
                )
                return LiteratureRunResult(
                    profile_key=profile_key,
                    output_directory=output_directory,
                    result_path=result_path,
                    report_path=report_path,
                    log_path=log_path,
                    candidate_count=counts[0],
                    verified_count=counts[1],
                    recommended_count=counts[2],
                    source_status=tuple(source_status),
                    ingest_response=response,
                )
        except LiteratureRadarRunError as exc:
            run_log.update(
                completed_at=_iso_utc(self._now()),
                final_result="failed",
                failure_stage=stage,
                error=str(exc),
            )
            raise
        except AgentError as exc:
            run_log.update(
                completed_at=_iso_utc(self._now()),
                final_result="failed",
                failure_stage=stage,
                error=str(exc),
            )
            raise LiteratureRadarRunError(str(exc)) from exc
        except Exception as exc:
            run_log.update(
                completed_at=_iso_utc(self._now()),
                final_result="failed",
                failure_stage=stage,
                error=f"{type(exc).__name__}: {exc}",
            )
            location = f" Output directory: {output_directory}." if output_directory else ""
            raise LiteratureRadarRunError(
                f"Literature Radar run failed during {stage}.{location}"
            ) from exc

    def _preflight(
        self,
        profile_key: str,
        *,
        ingest: bool,
        run_log: _RunLog,
    ) -> LiteraturePreflight:
        checks: dict[str, str] = {}

        def check(name: str, operation: Callable[[], object]) -> object:
            try:
                value = operation()
            except Exception as exc:
                checks[name] = "failed"
                run_log.update(preflight_status=checks.copy())
                if isinstance(exc, LiteratureRadarPreflightError):
                    raise
                raise LiteratureRadarPreflightError(
                    f"Preflight failed ({name}): {exc}"
                ) from exc
            checks[name] = "ok"
            run_log.update(preflight_status=checks.copy())
            return value

        check("config", lambda: load_config(self.config_path))

        def load_required_env() -> Path:
            if not self.env_path.is_file():
                raise LiteratureRadarPreflightError(
                    f"Required Agent environment file is missing: {self.env_path}"
                )
            loaded = load_env_file(self.env_path)
            if loaded is None:
                raise LiteratureRadarPreflightError(
                    f"Required Agent environment file is missing: {self.env_path}"
                )
            return loaded

        check("env", load_required_env)
        if ingest:
            check("workbench_token", lambda: load_token(self.config))
            check("workbench_health", self.client.health)
        else:
            checks["workbench_token"] = "skipped"
            checks["workbench_health"] = "skipped"
            run_log.update(preflight_status=checks.copy())
        profile = check(
            "profile",
            lambda: load_literature_profile(profile_key, root=self.root),
        )
        assert isinstance(profile, LiteratureProfile)

        def resolve_runner() -> LiteratureCodexRunner:
            if self._runner is None:
                self._runner = CodexLiteratureRunner()
            return self._runner

        runner = check("codex_executable", resolve_runner)
        assert hasattr(runner, "check_authentication")
        check("codex_authentication", runner.check_authentication)

        def load_zotero() -> tuple[ModuleType, str]:
            module = self._zotero_loader(self.root)
            if not isinstance(module, ModuleType) and not hasattr(module, "preflight"):
                raise LiteratureRadarPreflightError(
                    "Zotero helper loader returned an invalid module"
                )
            executable_value = module.resolve_zotero_cli()
            if not isinstance(executable_value, str) or not executable_value:
                raise LiteratureRadarPreflightError(
                    "Zotero executable resolver returned an invalid path"
                )
            return module, executable_value

        zotero_value = check("zotero_executable", load_zotero)
        assert isinstance(zotero_value, tuple)
        zotero, executable = zotero_value
        try:
            zotero.preflight(executable)
            batch = zotero.batch_search(
                profile.zotero_queries,
                limit=10,
                detail="summary",
                executable=executable,
            )
            zotero_context = _safe_zotero_context(
                batch,
                profile=profile,
                generated_at=self._now(),
            )
        except Exception as exc:
            checks["zotero_read_only"] = "failed"
            run_log.update(preflight_status=checks.copy())
            raise LiteratureRadarPreflightError(
                f"Preflight failed (zotero_read_only): {exc}"
            ) from exc
        checks["zotero_read_only"] = "ok"
        run_log.update(preflight_status=checks.copy())
        return LiteraturePreflight(
            profile=profile,
            runner=runner,
            checks=checks,
            zotero_context=zotero_context,
        )

    def _reserve_output_directory(self) -> Path:
        parent = self.root / "research_outputs"
        parent.mkdir(parents=True, exist_ok=True)
        stem = self._now().astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
        suffixes = [""] + [f"-{index:02d}" for index in range(1, 100)]
        for suffix in suffixes:
            candidate = parent / f"{stem}{suffix}"
            try:
                candidate.mkdir()
            except FileExistsError:
                continue
            return candidate.resolve()
        raise LiteratureRadarRunError("Could not reserve a unique research output directory")

    def _new_log_path(self, profile_key: str, started_at: datetime) -> Path:
        timestamp = started_at.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
        run_id = uuid.uuid4().hex[:8]
        safe_profile = re.sub(r"[^A-Za-z0-9._-]", "-", profile_key)
        return (
            self.root
            / "logs"
            / "literature-radar"
            / f"{timestamp}-{safe_profile}-{run_id}.json"
        )


def build_literature_instruction(
    profile: LiteratureProfile,
    *,
    repository_root: Path,
    output_directory: Path,
) -> str:
    result_path = output_directory / "result.json"
    report_path = output_directory / "report.md"
    zotero_context_path = output_directory / "zotero-context.json"
    return f"""Use the repository's `$literature-radar` skill to run one D2NN Literature Radar research pass.

Repository root: {repository_root}
Research profile: {profile.path}
Reserved output directory: {output_directory}
Orchestrator-provided Zotero context: {zotero_context_path}

The Agent orchestrator generated `zotero-context.json` immediately before this run by using the repository's existing read-only `zotero_cli.py` helper for all profile queries. Validate and use that snapshot as Zotero Library Context for duplicate and novelty screening. Do not rerun zotero-cli from this nested Codex subprocess. If the snapshot is missing, malformed, or materially inadequate, stop without external discovery or artifacts.

Write the artifacts to these exact paths; do not choose or infer another run directory:
- result.json: {result_path}
- report.md: {report_path}

Required constraints:
- Use the repository literature-radar skill and `{profile.relative_path}`.
- Treat Zotero as read-only and use only the orchestrator-provided snapshot for library context.
- Recommend at most {profile.max_results} papers, and fewer when evidence is insufficient.
- Follow the existing academic source policy and evidence gates without redesigning them.
- Run the repository's existing Literature Radar output validator before finishing.
- Do not call Workbench or any ingest endpoint.
- Do not modify Zotero, the research profile, repository code, or Git.
- Do not commit or push anything.
- Preserve truthful degraded/failed source status and never fabricate evidence.

Codex is responsible only for the research artifacts. The Agent orchestrator will validate again and perform transport after this command exits.
"""


def _load_zotero_module(root: Path) -> ModuleType:
    path = (
        root
        / ".agents"
        / "skills"
        / "literature-radar"
        / "scripts"
        / "zotero_cli.py"
    )
    if not path.is_file():
        raise LiteratureRadarPreflightError(
            f"Literature Radar Zotero helper is missing: {path}"
        )
    spec = importlib.util.spec_from_file_location(
        "workbench_agent_literature_radar_zotero_cli",
        path,
    )
    if spec is None or spec.loader is None:
        raise LiteratureRadarPreflightError(
            f"Cannot load Literature Radar Zotero helper: {path}"
        )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _safe_zotero_context(
    raw: object,
    *,
    profile: LiteratureProfile,
    generated_at: datetime,
) -> dict[str, object]:
    if not isinstance(raw, dict) or raw.get("ok") is not True:
        raise LiteratureRadarPreflightError(
            "Zotero batch search did not return a successful envelope"
        )
    data = raw.get("data")
    if not isinstance(data, dict):
        raise LiteratureRadarPreflightError(
            "Zotero batch search did not return a data object"
        )
    queries = data.get("queries")
    if not isinstance(queries, list):
        raise LiteratureRadarPreflightError(
            "Zotero batch search did not return query results"
        )
    allowed_queries = set(profile.zotero_queries)
    safe_queries: list[dict[str, object]] = []
    successful = 0
    failed = 0
    identities: set[str] = set()
    for value in queries:
        if not isinstance(value, dict):
            continue
        query = value.get("query")
        status = value.get("status")
        if not isinstance(query, str) or query not in allowed_queries:
            continue
        if status == "success":
            successful += 1
            items = value.get("items")
            item_values = items if isinstance(items, list) else []
            safe_items = [
                _safe_zotero_item(item)
                for item in item_values
                if isinstance(item, dict)
            ]
            safe_items = [item for item in safe_items if item]
            for item in safe_items:
                identity = str(
                    item.get("key")
                    or item.get("doi")
                    or item.get("title")
                    or uuid.uuid4().hex
                )
                identities.add(identity.casefold())
            safe_queries.append(
                {
                    "query": query,
                    "status": "success",
                    "count": len(safe_items),
                    "items": safe_items,
                }
            )
        elif status == "failed":
            failed += 1
            error = value.get("error")
            safe_error: dict[str, object] = {}
            if isinstance(error, dict):
                code = error.get("code")
                message = error.get("message")
                if isinstance(code, str):
                    safe_error["code"] = code
                if isinstance(message, str):
                    safe_error["message"] = _redact_text(message, secrets=())
            safe_queries.append(
                {"query": query, "status": "failed", "error": safe_error}
            )
    required_successes = max(1, (len(profile.zotero_queries) + 1) // 2)
    if successful < required_successes or not identities:
        raise LiteratureRadarPreflightError(
            "Zotero library context coverage is insufficient for duplicate and novelty screening"
        )
    return {
        "schema_version": 1,
        "generated_at": _iso_utc(generated_at),
        "profile": profile.key,
        "backend": "cli",
        "status": "degraded" if failed else "success",
        "queries_used": list(profile.zotero_queries),
        "successful_queries": successful,
        "failed_queries": failed,
        "anchor_count": len(identities),
        "limit_per_query": 10,
        "detail": "summary",
        "queries": safe_queries,
    }


def _safe_zotero_item(item: Mapping[str, object]) -> dict[str, object]:
    safe: dict[str, object] = {}
    for key in ("key", "itemType", "title", "date", "doi", "publication"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            safe[key] = value.strip()
    url = item.get("url")
    if isinstance(url, str) and url.startswith(("https://", "http://")):
        safe["url"] = url
    creators = item.get("creators")
    if isinstance(creators, list):
        safe["creators"] = [
            {
                key: value
                for key in ("type", "first", "last", "name")
                if isinstance((value := creator.get(key)), str) and value.strip()
            }
            for creator in creators
            if isinstance(creator, dict)
        ]
    for key in ("tags", "collections"):
        value = item.get(key)
        if isinstance(value, list):
            safe[key] = [entry for entry in value if isinstance(entry, str)]
    return safe

def _require_artifacts(output_directory: Path, result_path: Path, report_path: Path) -> None:
    missing = [str(path) for path in (result_path, report_path) if not path.is_file()]
    if missing:
        raise LiteratureRadarRunError(
            "Codex completed without the required Literature Radar artifacts; "
            f"ingest was not attempted. Output directory preserved: {output_directory}. "
            f"Missing: {', '.join(missing)}. "
            f"Codex diagnostic: {output_directory / 'codex-last-message.txt'}"
        )
    resolved_output = output_directory.resolve()
    for path in (result_path, report_path):
        if path.resolve().parent != resolved_output:
            raise LiteratureRadarRunError(
                f"Literature Radar artifact escaped the reserved output directory: {path}"
            )


def _payload_counts(payload: Mapping[str, object]) -> tuple[int, int, int]:
    candidate = payload.get("candidate_count")
    verified = payload.get("verified_candidate_count")
    recommended = payload.get("recommended_count")
    values = (candidate, verified, recommended)
    if any(isinstance(value, bool) or not isinstance(value, int) for value in values):
        raise LiteratureRadarValidationError(
            "Literature Radar ingest mapping returned invalid count fields"
        )
    assert isinstance(candidate, int)
    assert isinstance(verified, int)
    assert isinstance(recommended, int)
    return candidate, verified, recommended


def _source_status(raw: object) -> list[dict[str, object]]:
    if not isinstance(raw, dict):
        return []
    search = raw.get("search")
    if not isinstance(search, dict):
        return []
    statuses = search.get("source_status")
    if not isinstance(statuses, list):
        return []
    safe: list[dict[str, object]] = []
    for value in statuses:
        if not isinstance(value, dict):
            continue
        safe.append(
            {
                key: value.get(key)
                for key in (
                    "name",
                    "status",
                    "attempts",
                    "routes",
                    "result_count",
                    "warning",
                )
            }
        )
    return safe


def _recovery_command(result_path: Path) -> str:
    return f'workbench-agent literature ingest "{result_path}"'


def _iso_utc(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _safe_log_value(value: object, *, secrets: tuple[str, ...]) -> object:
    if isinstance(value, str):
        return _redact_text(value, secrets=secrets)
    if isinstance(value, list):
        return [_safe_log_value(item, secrets=secrets) for item in value]
    if isinstance(value, tuple):
        return [_safe_log_value(item, secrets=secrets) for item in value]
    if isinstance(value, dict):
        return {
            str(key): _safe_log_value(item, secrets=secrets)
            for key, item in value.items()
            if str(key).lower() not in {"authorization", "headers", "request_headers"}
        }
    return value


def _redact_text(value: str, *, secrets: tuple[str, ...]) -> str:
    text = value
    for secret in secrets:
        if secret:
            text = text.replace(secret, "[REDACTED]")
    for name in SENSITIVE_NAMES:
        text = re.sub(re.escape(name), "[REDACTED_ENV]", text, flags=re.IGNORECASE)
    text = re.sub(
        r"(?i)authorization\s*[:=]\s*bearer\s+\S+",
        "[REDACTED_HEADER]",
        text,
    )
    text = re.sub(
        r"(?i)([A-Z0-9_]*(?:TOKEN|KEY|SECRET|PASSWORD)[A-Z0-9_]*\s*[:=]\s*)\S+",
        "[REDACTED_ENV]=[REDACTED]",
        text,
    )
    text = re.sub(
        r"(?i)(?:[A-Za-z]:\\|/)[^\r\n\"']*"
        r"(?:Zotero[\\/](?:storage|attachments?)|attachments?)[^\s\"']*",
        "[REDACTED_ZOTERO_PATH]",
        text,
    )
    return text


def _optional_log_string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _object(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise LiteratureRadarPreflightError(f"{field} must be a JSON object")
    return value


def _required_string(data: Mapping[str, object], key: str, field: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise LiteratureRadarPreflightError(f"{field}.{key} must be a non-empty string")
    return value.strip()


def _string_list(value: object, field: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise LiteratureRadarPreflightError(f"{field} must be an array of strings")
    return [item.strip() for item in value if item.strip()]


def _nonempty_string_list(value: object, field: str) -> list[str]:
    result = _string_list(value, field)
    if not result:
        raise LiteratureRadarPreflightError(f"{field} must not be empty")
    return result


def _positive_integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise LiteratureRadarPreflightError(f"{field} must be a positive integer")
    return value
