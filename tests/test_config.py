import json
from pathlib import Path

import pytest

from workbench_agent.config import load_config, load_token
from workbench_agent.errors import AgentConfigError


def config_data(path: str) -> dict[str, object]:
    return {
        "server": {
            "url": "http://workbench.example:8000/",
            "token_env": "WORKBENCH_AGENT_TOKEN",
        },
        "device": {"id": "lab-5090", "name": "Lab RTX 5090"},
        "projects": [
            {
                "key": "semantic-segmentation",
                "project_id": "project-1",
                "path": path,
                "source_type": "remote_workspace",
                "source_key": "workspace:semantic-segmentation",
            }
        ],
    }


def write_config(tmp_path: Path, data: object) -> Path:
    path = tmp_path / "config.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_load_valid_config_and_windows_path(tmp_path: Path) -> None:
    config = load_config(write_config(tmp_path, config_data(r"D:\D2NN\Semantic-Segmentation")))

    assert config.server.url == "http://workbench.example:8000"
    assert config.projects[0].path == r"D:\D2NN\Semantic-Segmentation"
    assert config.project("semantic-segmentation") == config.projects[0]


def test_missing_required_field_is_rejected(tmp_path: Path) -> None:
    data = config_data(str(tmp_path))
    del data["device"]["name"]  # type: ignore[index]

    with pytest.raises(AgentConfigError, match="name"):
        load_config(write_config(tmp_path, data))


def test_duplicate_project_key_is_rejected(tmp_path: Path) -> None:
    data = config_data(str(tmp_path))
    data["projects"].append(dict(data["projects"][0]))  # type: ignore[union-attr,index]

    with pytest.raises(AgentConfigError, match="unique"):
        load_config(write_config(tmp_path, data))


def test_missing_token_environment_is_rejected(tmp_path: Path) -> None:
    config = load_config(write_config(tmp_path, config_data(str(tmp_path))))

    with pytest.raises(AgentConfigError, match="WORKBENCH_AGENT_TOKEN"):
        load_token(config, {})


def test_invalid_server_url_is_rejected(tmp_path: Path) -> None:
    data = config_data(str(tmp_path))
    data["server"]["url"] = "WORKBENCH_HOST:8000"  # type: ignore[index]

    with pytest.raises(AgentConfigError, match="absolute"):
        load_config(write_config(tmp_path, data))
