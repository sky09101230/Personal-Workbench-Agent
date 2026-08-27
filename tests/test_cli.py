import json
from pathlib import Path

from workbench_agent.cli import main


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
