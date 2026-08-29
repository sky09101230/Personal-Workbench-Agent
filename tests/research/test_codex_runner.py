import json
import subprocess
from pathlib import Path

import pytest

from workbench_agent.errors import CodexExecutionError
from workbench_agent.research.codex_runner import CodexResearchRunner


SCHEMA = {"type": "object"}
RESULT = {"schema_version": "1"}


def output_path(command: list[str]) -> Path:
    return Path(command[command.index("--output-last-message") + 1])


def test_success_uses_official_schema_and_output_file(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        schema_path = Path(command[command.index("--output-schema") + 1])
        assert json.loads(schema_path.read_text(encoding="utf-8")) == SCHEMA
        assert "--search" in command
        assert "--ephemeral" in command
        assert kwargs["input"] == "instruction"
        output_path(command).write_text(json.dumps(RESULT), encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, "events", "")

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert CodexResearchRunner().run("instruction", SCHEMA) == RESULT


def test_require_mcp_uses_codex_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        assert command == ["codex", "mcp", "get", "zotero", "--json"]
        return subprocess.CompletedProcess(command, 0, '{"name":"zotero"}', "")

    monkeypatch.setattr(subprocess, "run", fake_run)

    CodexResearchRunner().require_mcp("zotero")


def test_missing_mcp_is_explicit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda command, **kwargs: subprocess.CompletedProcess(command, 1, "", "missing"),
    )

    with pytest.raises(CodexExecutionError, match="not configured: zotero"):
        CodexResearchRunner().require_mcp("zotero")


def test_executable_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    def missing(*args: object, **kwargs: object) -> object:
        raise FileNotFoundError

    monkeypatch.setattr(subprocess, "run", missing)

    with pytest.raises(CodexExecutionError, match="not found"):
        CodexResearchRunner("missing-codex").run("instruction", SCHEMA)


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
