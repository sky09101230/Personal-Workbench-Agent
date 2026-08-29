import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from workbench_agent.cli import build_parser, main
from workbench_agent.errors import CodexExecutionError, ResearchTaskError


def write_config(tmp_path: Path, project_path: Path) -> Path:
    config = {
        "server": {"url": "http://127.0.0.1:1", "token_env": "MISSING_TOKEN"},
        "device": {"id": "lab-5090", "name": "Lab RTX 5090"},
        "projects": [
            {
                "key": "demo",
                "project_id": "project-id",
                "path": str(project_path),
                "source_type": "remote_workspace",
                "source_key": "workspace:demo",
            }
        ],
    }
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    return path


def test_sync_dry_run_needs_no_token_or_network(tmp_path: Path, capsys: object) -> None:
    config_path = write_config(tmp_path, tmp_path)

    result = main(["--config", str(config_path), "sync", "--dry-run"])

    assert result == 0
    output = capsys.readouterr().out  # type: ignore[attr-defined]
    assert "no HTTP writes" in output
    assert "workspace:demo" in output
    assert "token" not in output.lower()


def test_normal_error_has_no_traceback(tmp_path: Path, capsys: object) -> None:
    config_path = write_config(tmp_path, tmp_path)

    result = main(["--config", str(config_path), "heartbeat"])

    assert result == 2
    error = capsys.readouterr().err  # type: ignore[attr-defined]
    assert "MISSING_TOKEN" in error
    assert "Traceback" not in error


def fake_research_result() -> SimpleNamespace:
    return SimpleNamespace(
        task_key="d2nn-recent-papers",
        run_key="d2nn-recent-papers-20260829T091500Z-a31f42",
        query_plan=("expanded query",),
        papers=(SimpleNamespace(title="Verified paper", relevance_score=0.95),),
    )


def test_parser_has_nested_research_run_command() -> None:
    args = build_parser().parse_args(
        ["research", "run", "d2nn-recent-papers", "--dry-run"]
    )

    assert args.command == "research"
    assert args.research_command == "run"
    assert args.task_key == "d2nn-recent-papers"
    assert args.dry_run is True


def test_research_dry_run_needs_no_token_and_reports_zero_writes(
    tmp_path: Path,
    capsys: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeResearchService:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        def run(self, task_key: str, *, dry_run: bool) -> tuple[object, None]:
            assert task_key == "d2nn-recent-papers"
            assert dry_run
            return fake_research_result(), None

    monkeypatch.setattr("workbench_agent.cli.ResearchService", FakeResearchService)

    result = main(
        [
            "--config",
            str(write_config(tmp_path, tmp_path)),
            "research",
            "run",
            "d2nn-recent-papers",
            "--dry-run",
        ]
    )

    assert result == 0
    output = capsys.readouterr().out  # type: ignore[attr-defined]
    assert "Research completed" in output
    assert "Recommended: 1" in output
    assert "no Workbench write" in output


def test_research_normal_success_uses_token(
    tmp_path: Path,
    capsys: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeResearchService:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        def run(self, task_key: str, *, dry_run: bool) -> tuple[object, dict[str, object]]:
            assert not dry_run
            return fake_research_result(), {"status": "accepted"}

    monkeypatch.setenv("MISSING_TOKEN", "secret")
    monkeypatch.setattr("workbench_agent.cli.ResearchService", FakeResearchService)

    result = main(
        [
            "--config",
            str(write_config(tmp_path, tmp_path)),
            "research",
            "run",
            "d2nn-recent-papers",
        ]
    )

    assert result == 0
    assert "Workbench ingest accepted" in capsys.readouterr().out  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    "error",
    [ResearchTaskError("Unknown research task"), CodexExecutionError("Codex failed")],
)
def test_research_errors_have_no_traceback(
    tmp_path: Path,
    capsys: object,
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
) -> None:
    class FailingResearchService:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        def run(self, task_key: str, *, dry_run: bool) -> object:
            raise error

    monkeypatch.setattr("workbench_agent.cli.ResearchService", FailingResearchService)

    result = main(
        [
            "--config",
            str(write_config(tmp_path, tmp_path)),
            "research",
            "run",
            "missing",
            "--dry-run",
        ]
    )

    assert result == 2
    stderr = capsys.readouterr().err  # type: ignore[attr-defined]
    assert str(error) in stderr
    assert "Traceback" not in stderr


def test_cli_loads_dotenv_next_to_selected_config(
    tmp_path: Path,
    capsys: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class FakeClient:
        def __init__(self, url: str, token: str | None) -> None:
            captured["url"] = url
            captured["token"] = token

        def __enter__(self) -> "FakeClient":
            return self

        def __exit__(self, *args: object) -> None:
            return None

    class FakeService:
        def __init__(self, config: object, client: object) -> None:
            pass

        def heartbeat(self) -> None:
            captured["heartbeat"] = True

    config_path = write_config(tmp_path, tmp_path)
    (tmp_path / ".env").write_text(
        "MISSING_TOKEN=from-dotenv\n", encoding="utf-8"
    )
    monkeypatch.delenv("MISSING_TOKEN", raising=False)
    monkeypatch.setattr("workbench_agent.cli.WorkbenchClient", FakeClient)
    monkeypatch.setattr("workbench_agent.cli.AgentService", FakeService)

    result = main(["--config", str(config_path), "heartbeat"])

    assert result == 0
    assert captured == {
        "url": "http://127.0.0.1:1",
        "token": "from-dotenv",
        "heartbeat": True,
    }
    assert "Heartbeat accepted" in capsys.readouterr().out  # type: ignore[attr-defined]
