from __future__ import annotations

import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import ModuleType

import pytest

from workbench_agent.config import AgentConfig, load_config
from workbench_agent.errors import (
    LiteratureRadarLockError,
    LiteratureRadarPreflightError,
    LiteratureRadarRunError,
    LiteratureRadarValidationError,
    WorkbenchConnectionError,
)
from workbench_agent import literature_run
from workbench_agent.literature_run import (
    CodexLiteratureExecutionError,
    CodexLiteratureRunner,
    LiteratureRunLock,
    LiteratureRunService,
    load_literature_profile,
)


FIXED_NOW = datetime(2026, 8, 30, 0, 15, tzinfo=timezone.utc)


def write_project(tmp_path: Path) -> tuple[AgentConfig, Path, Path]:
    profile_dir = tmp_path / "research_profiles"
    profile_dir.mkdir()
    profile = {
        "schema_version": 1,
        "key": "d2nn",
        "name": "D2NN Literature Radar",
        "interests": ["diffractive neural networks"],
        "keywords": {"include": ["diffractive neural network"], "exclude": []},
        "time": {"lookback_days": 60, "prefer_recent": True},
        "zotero": {"enabled": True, "backend": "cli"},
        "search": {
            "max_candidates": 40,
            "max_results": 5,
            "sources": ["arxiv", "openalex"],
        },
        "ranking": {
            "relevance": 0.35,
            "novelty_to_zotero": 0.30,
            "scientific_value": 0.20,
            "recency": 0.15,
        },
        "output": {"language": "zh-CN"},
    }
    (profile_dir / "d2nn.json").write_text(json.dumps(profile), encoding="utf-8")
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "server": {
                    "url": "http://127.0.0.1:8000",
                    "token_env": "TEST_WORKBENCH_TOKEN",
                },
                "device": {"id": "test-device", "name": "Test Device"},
                "projects": [],
            }
        ),
        encoding="utf-8",
    )
    env_path = tmp_path / ".env"
    env_path.write_text("TEST_WORKBENCH_TOKEN=test-secret\n", encoding="utf-8")
    return load_config(config_path), config_path, env_path


class FakeRunner:
    executable = "resolved-codex"

    def __init__(self, *, write_artifacts: bool = True) -> None:
        self.write_artifacts = write_artifacts
        self.auth_calls = 0
        self.run_calls = 0
        self.instruction = ""
        self.workdir: Path | None = None

    def check_authentication(self) -> None:
        self.auth_calls += 1

    def run(self, instruction: str, *, workdir: Path) -> int:
        self.run_calls += 1
        self.instruction = instruction
        self.workdir = workdir
        if self.write_artifacts:
            (workdir / "result.json").write_text(
                json.dumps(
                    {
                        "search": {
                            "source_status": [
                                {
                                    "name": "openalex",
                                    "status": "success",
                                    "attempts": 1,
                                    "routes": [],
                                    "result_count": 4,
                                    "warning": None,
                                }
                            ]
                        }
                    }
                ),
                encoding="utf-8",
            )
            (workdir / "report.md").write_text("# Radar\n", encoding="utf-8")
        return 0


class FakeClient:
    def __init__(self) -> None:
        self.health_calls = 0
        self.ingest_calls: list[dict[str, object]] = []

    def health(self) -> dict[str, object]:
        self.health_calls += 1
        return {"status": "ok"}

    def ingest_paper_research(self, payload: dict[str, object]) -> dict[str, object]:
        self.ingest_calls.append(payload)
        return {
            "run_id": "research-run:automation",
            "created_run": True,
            "created_papers": 2,
            "created_recommendations": 1,
        }


class FakeZotero(ModuleType):
    def __init__(self) -> None:
        super().__init__("fake_zotero")
        self.searches: list[tuple[str, int, str, str]] = []

    def resolve_zotero_cli(self) -> str:
        return "resolved-zotero-cli"

    def preflight(self, executable: str | None = None) -> dict[str, object]:
        assert executable == "resolved-zotero-cli"
        return {"ok": True, "executable": executable}

    def batch_search(
        self,
        queries: tuple[str, ...],
        *,
        limit: int,
        detail: str,
        executable: str,
    ) -> dict[str, object]:
        self.searches.extend(
            (query, limit, detail, executable) for query in queries
        )
        return {
            "ok": True,
            "data": {
                "successful_queries": len(queries),
                "failed_queries": 0,
                "degraded": False,
                "queries": [
                    {
                        "query": query,
                        "status": "success",
                        "count": 1,
                        "items": [
                            {
                                "key": f"KEY{index}",
                                "title": f"Anchor {index}",
                                "date": "2026",
                                "doi": f"10.1000/{index}",
                                "url": f"https://example.test/{index}",
                                "creators": [],
                                "tags": [],
                                "collections": [],
                            }
                        ],
                    }
                    for index, query in enumerate(queries, 1)
                ],
            },
        }


def patch_valid_output(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        literature_run,
        "validate_literature_output",
        lambda result, report: {
            "ok": True,
            "candidate_count": 4,
            "verified_candidate_count": 2,
            "recommendation_count": 1,
            "source_count": 1,
        },
    )
    monkeypatch.setattr(
        literature_run,
        "literature_ingest_payload",
        lambda raw: {
            "candidate_count": 4,
            "verified_candidate_count": 2,
            "recommended_count": 1,
            "papers": [{}, {}],
            "ingest_identity": "sha256:test",
        },
    )


def make_service(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    runner: FakeRunner | None = None,
    client: FakeClient | None = None,
) -> tuple[LiteratureRunService, FakeRunner, FakeClient, FakeZotero]:
    config, config_path, env_path = write_project(tmp_path)
    monkeypatch.setenv("TEST_WORKBENCH_TOKEN", "test-secret")
    actual_runner = runner or FakeRunner()
    actual_client = client or FakeClient()
    zotero = FakeZotero()
    service = LiteratureRunService(
        config,
        actual_client,  # type: ignore[arg-type]
        config_path=config_path,
        env_path=env_path,
        root=tmp_path,
        runner=actual_runner,
        zotero_loader=lambda root: zotero,
        now=lambda: FIXED_NOW,
    )
    return service, actual_runner, actual_client, zotero


def test_profile_resolution_validates_contract_and_limit(tmp_path: Path) -> None:
    write_project(tmp_path)

    profile = load_literature_profile("d2nn", root=tmp_path)

    assert profile.key == "d2nn"
    assert profile.relative_path == "research_profiles/d2nn.json"
    assert profile.max_results == 5
    assert profile.zotero_queries == ("diffractive neural network",)


def test_profile_resolution_rejects_traversal_and_bad_weights(tmp_path: Path) -> None:
    write_project(tmp_path)

    with pytest.raises(LiteratureRadarPreflightError, match="Invalid.*profile key"):
        load_literature_profile("../d2nn", root=tmp_path)

    path = tmp_path / "research_profiles" / "d2nn.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["ranking"]["recency"] = 0.25
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(LiteratureRadarPreflightError, match="weights must sum to 1"):
        load_literature_profile("d2nn", root=tmp_path)


def test_codex_runner_checks_auth_and_uses_reserved_workdir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands: list[tuple[list[str], dict[str, object]]] = []
    monkeypatch.setattr(literature_run, "_resolve_executable", lambda value: "codex.cmd")

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        commands.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    runner = CodexLiteratureRunner(timeout=50)

    runner.check_authentication()
    assert runner.run("use skill", workdir=tmp_path) == 0

    assert commands[0][0] == ["codex.cmd", "login", "status"]
    run_command, run_kwargs = commands[1]
    assert run_command[0] == "codex.cmd"
    assert run_command[run_command.index("--cd") + 1] == str(tmp_path)
    assert "workspace-write" in run_command
    assert "--search" in run_command
    assert "--ephemeral" in run_command
    assert run_kwargs["input"] == "use skill"
    assert "shell" not in run_kwargs


def test_orchestration_runs_preflight_codex_validator_and_ingest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_valid_output(monkeypatch)
    service, runner, client, zotero = make_service(tmp_path, monkeypatch)

    result = service.run("d2nn", ingest=True)

    assert runner.auth_calls == 1
    assert runner.run_calls == 1
    assert runner.workdir == result.output_directory
    assert "$literature-radar" in runner.instruction
    assert str(result.result_path) in runner.instruction
    assert str(result.report_path) in runner.instruction
    assert "at most 5 papers" in runner.instruction
    assert "Do not call Workbench" in runner.instruction
    assert zotero.searches == [
        ("diffractive neural network", 10, "summary", "resolved-zotero-cli")
    ]
    context_path = result.output_directory / "zotero-context.json"
    context = json.loads(context_path.read_text(encoding="utf-8"))
    assert context["status"] == "success"
    assert context["anchor_count"] == 1
    assert "executable" not in context
    assert str(context_path) in runner.instruction
    assert "Do not rerun zotero-cli" in runner.instruction
    assert client.health_calls == 1
    assert len(client.ingest_calls) == 1
    assert result.candidate_count == 4
    assert result.verified_count == 2
    assert result.recommended_count == 1
    assert result.ingest_response is not None
    assert result.ingest_response["run_id"] == "research-run:automation"
    log = json.loads(result.log_path.read_text(encoding="utf-8"))
    assert log["preflight_status"] == {
        "config": "ok",
        "env": "ok",
        "workbench_token": "ok",
        "workbench_health": "ok",
        "profile": "ok",
        "codex_executable": "ok",
        "codex_authentication": "ok",
        "zotero_executable": "ok",
        "zotero_read_only": "ok",
    }
    assert log["codex_exit_status"] == 0
    assert log["validator_result"]["status"] == "passed"
    assert log["candidate_count"] == 4
    assert log["verified_count"] == 2
    assert log["recommended_count"] == 1
    assert log["final_source_status"][0]["name"] == "openalex"
    assert log["ingest_run_id"] == "research-run:automation"
    assert log["ingest_created_or_existing"] == "created"
    assert log["final_result"] == "success"
    assert not (tmp_path / "logs" / "literature-radar" / "run.lock").exists()


def test_workbench_preflight_failure_stops_before_research(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class UnreachableClient(FakeClient):
        def health(self) -> dict[str, object]:
            self.health_calls += 1
            raise WorkbenchConnectionError("Workbench is unavailable")

    runner = FakeRunner()
    service, _, client, _ = make_service(
        tmp_path,
        monkeypatch,
        runner=runner,
        client=UnreachableClient(),
    )

    with pytest.raises(LiteratureRadarRunError, match="workbench_health"):
        service.run("d2nn", ingest=True)

    assert runner.run_calls == 0
    assert client.ingest_calls == []
    assert not (tmp_path / "research_outputs").exists()
    logs = list((tmp_path / "logs" / "literature-radar").glob("*.json"))
    assert len(logs) == 1
    log = json.loads(logs[0].read_text(encoding="utf-8"))
    assert log["preflight_status"]["workbench_health"] == "failed"
    assert log["final_result"] == "failed"


def test_missing_env_stops_before_research(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, runner, client, _ = make_service(tmp_path, monkeypatch)
    (tmp_path / ".env").unlink()

    with pytest.raises(LiteratureRadarRunError, match="environment file is missing"):
        service.run("d2nn", ingest=True)

    assert runner.run_calls == 0
    assert client.health_calls == 0
    assert client.ingest_calls == []


def test_missing_artifact_blocks_validator_and_ingest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_valid_output(monkeypatch)
    service, runner, client, _ = make_service(
        tmp_path,
        monkeypatch,
        runner=FakeRunner(write_artifacts=False),
    )

    with pytest.raises(LiteratureRadarRunError, match="without the required"):
        service.run("d2nn", ingest=True)

    assert runner.run_calls == 1
    assert client.ingest_calls == []
    assert len(list((tmp_path / "research_outputs").glob("*/"))) == 1


def test_validator_failure_blocks_ingest_and_preserves_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        literature_run,
        "validate_literature_output",
        lambda result, report: (_ for _ in ()).throw(
            LiteratureRadarValidationError("evidence gate rejected result")
        ),
    )
    service, runner, client, _ = make_service(tmp_path, monkeypatch)

    with pytest.raises(LiteratureRadarRunError, match="validation failed"):
        service.run("d2nn", ingest=True)

    assert runner.workdir is not None
    assert (runner.workdir / "result.json").is_file()
    assert (runner.workdir / "report.md").is_file()
    assert client.ingest_calls == []
    log_path = next((tmp_path / "logs" / "literature-radar").glob("*.json"))
    log = json.loads(log_path.read_text(encoding="utf-8"))
    assert log["validator_result"] == {"status": "failed"}
    assert log["failure_stage"] == "validator"


def test_ingest_failure_preserves_artifacts_and_reports_recovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingIngestClient(FakeClient):
        def ingest_paper_research(self, payload: dict[str, object]) -> dict[str, object]:
            self.ingest_calls.append(payload)
            raise WorkbenchConnectionError("network dropped")

    patch_valid_output(monkeypatch)
    client = FailingIngestClient()
    service, runner, _, _ = make_service(tmp_path, monkeypatch, client=client)

    with pytest.raises(LiteratureRadarRunError, match="Recover without rerunning") as error:
        service.run("d2nn", ingest=True)

    assert runner.workdir is not None
    result_path = runner.workdir / "result.json"
    assert result_path.is_file()
    assert (runner.workdir / "report.md").is_file()
    assert str(result_path) in str(error.value)
    assert "workbench-agent literature ingest" in str(error.value)
    assert len(client.ingest_calls) == 1
    log_path = next((tmp_path / "logs" / "literature-radar").glob("*.json"))
    log = json.loads(log_path.read_text(encoding="utf-8"))
    assert log["validator_result"]["status"] == "passed"
    assert log["failure_stage"] == "ingest"
    assert log["final_result"] == "failed"


def test_research_only_run_skips_workbench_checks_and_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_valid_output(monkeypatch)
    service, _, client, _ = make_service(tmp_path, monkeypatch)

    result = service.run("d2nn", ingest=False)

    assert client.health_calls == 0
    assert client.ingest_calls == []
    assert result.ingest_response is None
    log = json.loads(result.log_path.read_text(encoding="utf-8"))
    assert log["preflight_status"]["workbench_token"] == "skipped"
    assert log["preflight_status"]["workbench_health"] == "skipped"
    assert log["ingest_created_or_existing"] == "skipped"


def test_concurrent_run_lock_is_rejected_and_released(tmp_path: Path) -> None:
    path = tmp_path / "logs" / "literature-radar" / "run.lock"
    first = LiteratureRunLock(path, now=lambda: FIXED_NOW)
    second = LiteratureRunLock(path, now=lambda: FIXED_NOW)

    first.acquire()
    try:
        with pytest.raises(LiteratureRadarLockError, match="Another Literature Radar"):
            second.acquire()
    finally:
        first.release()

    assert not path.exists()


def test_stale_lock_is_recovered_safely(tmp_path: Path) -> None:
    path = tmp_path / "logs" / "literature-radar" / "run.lock"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "lock_id": "abandoned",
                "started_at": "2026-08-28T00:00:00Z",
            }
        ),
        encoding="utf-8",
    )
    lock = LiteratureRunLock(
        path,
        stale_after=timedelta(hours=24),
        now=lambda: FIXED_NOW,
    )

    lock.acquire()
    try:
        assert lock.recovered_stale is True
        current = json.loads(path.read_text(encoding="utf-8"))
        assert current["lock_id"] == lock.lock_id
    finally:
        lock.release()

    assert not path.exists()


def test_codex_failure_log_redacts_secrets_headers_and_zotero_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingRunner(FakeRunner):
        def run(self, instruction: str, *, workdir: Path) -> int:
            self.run_calls += 1
            self.workdir = workdir
            raise CodexLiteratureExecutionError(
                "WORKBENCH_AGENT_TOKEN=test-secret "
                "SEMANTIC_SCHOLAR_API_KEY=semantic-secret "
                "Authorization: Bearer bearer-secret "
                r"C:\Users\tester\Zotero\storage\ABC\paper.pdf",
                returncode=7,
            )

    monkeypatch.setenv("SEMANTIC_SCHOLAR_API_KEY", "semantic-secret")
    service, _, client, _ = make_service(
        tmp_path,
        monkeypatch,
        runner=FailingRunner(),
    )

    with pytest.raises(LiteratureRadarRunError) as error:
        service.run("d2nn", ingest=True)

    message = str(error.value)
    assert "test-secret" not in message
    assert "semantic-secret" not in message
    assert "bearer-secret" not in message
    assert client.ingest_calls == []
    log_path = next((tmp_path / "logs" / "literature-radar").glob("*.json"))
    text = log_path.read_text(encoding="utf-8")
    for forbidden in (
        "WORKBENCH_AGENT_TOKEN",
        "SEMANTIC_SCHOLAR_API_KEY",
        "test-secret",
        "semantic-secret",
        "bearer-secret",
        "Authorization",
        r"Zotero\\storage",
    ):
        assert forbidden not in text
    log = json.loads(text)
    assert log["codex_exit_status"] == 7
    assert log["failure_stage"] == "codex"
    assert log["final_result"] == "failed"


def test_codex_auth_failure_is_explicit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(literature_run, "_resolve_executable", lambda value: "codex.cmd")
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda command, **kwargs: subprocess.CompletedProcess(
            command, 1, "", "Not logged in"
        ),
    )

    with pytest.raises(CodexLiteratureExecutionError, match="codex login"):
        CodexLiteratureRunner().check_authentication()


def test_codex_auth_accepts_healthy_non_openai_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(literature_run, "_resolve_executable", lambda value: "codex.cmd")
    calls = 0

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        nonlocal calls
        calls += 1
        if command[1:3] == ["login", "status"]:
            return subprocess.CompletedProcess(command, 1, "", "Not logged in")
        return subprocess.CompletedProcess(
            command,
            1,
            json.dumps(
                {
                    "checks": {
                        "auth.credentials": {
                            "status": "ok",
                            "summary": "auth is not required for the active provider",
                        }
                    }
                }
            ),
            "",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    CodexLiteratureRunner().check_authentication()

    assert calls == 2
