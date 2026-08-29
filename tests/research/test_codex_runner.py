import json
import subprocess
from pathlib import Path

import pytest

from workbench_agent.errors import CodexExecutionError
from workbench_agent.research import codex_runner
from workbench_agent.research.codex_runner import CodexResearchRunner


SCHEMA = {"type": "object"}
RESULT = {"schema_version": "1"}
RESOLVED_CODEX = "resolved-codex"


@pytest.fixture(autouse=True)
def resolve_default_codex(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        codex_runner.shutil,
        "which",
        lambda executable: RESOLVED_CODEX if executable == "codex" else None,
    )


def output_path(command: list[str]) -> Path:
    return Path(command[command.index("--output-last-message") + 1])


def test_success_uses_official_schema_and_output_file(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        schema_path = Path(command[command.index("--output-schema") + 1])
        assert command[0] == RESOLVED_CODEX
        assert json.loads(schema_path.read_text(encoding="utf-8")) == SCHEMA
        assert "--search" in command
        assert "--ephemeral" in command
        assert kwargs["input"] == "instruction"
        assert "shell" not in kwargs
        output_path(command).write_text(json.dumps(RESULT), encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, "events", "")

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert CodexResearchRunner().run("instruction", SCHEMA) == RESULT


def test_require_mcp_uses_resolved_codex_executable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        assert command == [RESOLVED_CODEX, "mcp", "get", "zotero", "--json"]
        assert "shell" not in kwargs
        return subprocess.CompletedProcess(command, 0, '{"name":"zotero"}', "")

    monkeypatch.setattr(subprocess, "run", fake_run)

    CodexResearchRunner().require_mcp("zotero")


def test_windows_npm_shim_resolves_codex_to_codex_cmd(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolved = r"C:\Users\tester\AppData\Roaming\npm\codex.cmd"
    lookups: list[str] = []

    def fake_which(executable: str) -> str | None:
        lookups.append(executable)
        return resolved if executable == "codex.cmd" else None

    monkeypatch.setattr(codex_runner, "_is_windows", lambda: True)
    monkeypatch.setattr(codex_runner.shutil, "which", fake_which)

    runner = CodexResearchRunner()

    assert runner.executable == resolved
    assert lookups == ["codex", "codex.cmd"]


def test_executable_missing_is_reported_during_initialization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lookups: list[str] = []

    def missing(executable: str) -> None:
        lookups.append(executable)
        return None

    monkeypatch.setattr(codex_runner, "_is_windows", lambda: True)
    monkeypatch.setattr(codex_runner.shutil, "which", missing)

    with pytest.raises(CodexExecutionError, match="not found: missing-codex"):
        CodexResearchRunner("missing-codex")

    assert lookups == ["missing-codex", "missing-codex.cmd", "missing-codex.exe"]


def test_explicit_executable_path_is_supported(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executable = tmp_path / "codex.cmd"
    executable.write_text("@echo off\n", encoding="utf-8")
    lookups: list[str] = []

    def missing(candidate: str) -> None:
        lookups.append(candidate)
        return None

    monkeypatch.setattr(codex_runner, "_is_windows", lambda: True)
    monkeypatch.setattr(codex_runner.shutil, "which", missing)

    runner = CodexResearchRunner(str(executable))

    assert runner.executable == str(executable)
    assert lookups == [str(executable)]


def test_non_windows_does_not_probe_windows_extensions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lookups: list[str] = []

    def missing(executable: str) -> None:
        lookups.append(executable)
        return None

    monkeypatch.setattr(codex_runner, "_is_windows", lambda: False)
    monkeypatch.setattr(codex_runner.shutil, "which", missing)

    with pytest.raises(CodexExecutionError, match="not found: codex"):
        CodexResearchRunner()

    assert lookups == ["codex"]


def test_missing_mcp_is_explicit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda command, **kwargs: subprocess.CompletedProcess(command, 1, "", "missing"),
    )

    with pytest.raises(CodexExecutionError, match="not configured: zotero"):
        CodexResearchRunner().require_mcp("zotero")


def test_runtime_executable_disappearance_is_explicit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def missing(*args: object, **kwargs: object) -> object:
        raise FileNotFoundError

    monkeypatch.setattr(subprocess, "run", missing)

    with pytest.raises(CodexExecutionError, match="not found"):
        CodexResearchRunner().run("instruction", SCHEMA)


def test_non_zero_exit_redacts_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda command, **kwargs: subprocess.CompletedProcess(
            command, 7, "", "WORKBENCH_AGENT_TOKEN=super-secret failed"
        ),
    )

    with pytest.raises(CodexExecutionError, match="status 7") as error:
        CodexResearchRunner().run("instruction", SCHEMA)
    assert "super-secret" not in str(error.value)


def test_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    def timeout(*args: object, **kwargs: object) -> object:
        raise subprocess.TimeoutExpired("codex", 3)

    monkeypatch.setattr(subprocess, "run", timeout)

    with pytest.raises(CodexExecutionError, match="timed out"):
        CodexResearchRunner(timeout=3).run("instruction", SCHEMA)


@pytest.mark.parametrize("contents,match", [("", "empty"), ("{", "malformed")])
def test_invalid_output(
    monkeypatch: pytest.MonkeyPatch, contents: str, match: str
) -> None:
    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        output_path(command).write_text(contents, encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(CodexExecutionError, match=match):
        CodexResearchRunner().run("instruction", SCHEMA)
