import json
import re
from pathlib import Path

import pytest

from workbench_agent.errors import CodexExecutionError, ResearchResultValidationError
from workbench_agent.research.service import ResearchService


def write_task(tmp_path: Path) -> None:
    data = {
        "key": "demo",
        "name": "Demo",
        "topics": ["diffractive neural networks"],
        "keywords": [],
        "exclude": [],
        "lookback_days": 30,
        "max_candidates": 5,
        "max_results": 1,
        "zotero": {"enabled": True},
        "research": {
            "require_real_papers": True,
            "require_primary_sources": True,
        },
    }
    (tmp_path / "demo.json").write_text(json.dumps(data), encoding="utf-8")


def result_from_instruction(instruction: str) -> dict[str, object]:
    run_key = re.search(r"^- run_key: (.+)$", instruction, re.MULTILINE)
    generated_at = re.search(r"^- generated_at: (.+)$", instruction, re.MULTILINE)
    assert run_key and generated_at
    return {
        "schema_version": "1",
        "task_key": "demo",
        "run_key": run_key.group(1),
        "generated_at": generated_at.group(1),
        "agent": {
            "type": "codex",
            "model": "configured",
            "prompt_version": "paper_research_v1",
        },
        "query_plan": ["expanded query"],
        "papers": [],
    }


class FakeRunner:
    def __init__(self, failure: Exception | None = None) -> None:
        self.failure = failure
        self.calls = 0
        self.required_mcp: list[str] = []

    def require_mcp(self, name: str) -> None:
        self.required_mcp.append(name)

    def run(self, instruction: str, schema: object) -> dict[str, object]:
        self.calls += 1
        if self.failure:
            raise self.failure
        return result_from_instruction(instruction)


class FakeClient:
    def __init__(self) -> None:
        self.payloads: list[dict[str, object]] = []

    def ingest_paper_research(self, payload: dict[str, object]) -> dict[str, object]:
        self.payloads.append(payload)
        return {"status": "accepted"}


def test_dry_run_never_ingests(tmp_path: Path) -> None:
    write_task(tmp_path)
    client = FakeClient()
    runner = FakeRunner()

    result, response = ResearchService(  # type: ignore[arg-type]
        client, runner, task_dir=tmp_path
    ).run("demo", dry_run=True)

    assert result.task_key == "demo"
    assert response is None
    assert client.payloads == []
    assert runner.required_mcp == ["zotero"]


def test_normal_run_ingests_once(tmp_path: Path) -> None:
    write_task(tmp_path)
    client = FakeClient()

    result, response = ResearchService(  # type: ignore[arg-type]
        client, FakeRunner(), task_dir=tmp_path
    ).run("demo")

    assert response == {"status": "accepted"}
    assert client.payloads == [result.to_payload()]


def test_codex_failure_never_ingests(tmp_path: Path) -> None:
    write_task(tmp_path)
    client = FakeClient()
    runner = FakeRunner(CodexExecutionError("failed"))

    with pytest.raises(CodexExecutionError):
        ResearchService(client, runner, task_dir=tmp_path).run("demo")  # type: ignore[arg-type]
    assert client.payloads == []


def test_validation_failure_never_ingests(tmp_path: Path) -> None:
    write_task(tmp_path)
    client = FakeClient()
    runner = FakeRunner()

    def invalid(instruction: str, schema: object) -> dict[str, object]:
        data = result_from_instruction(instruction)
        data["schema_version"] = "2"
        return data

    runner.run = invalid  # type: ignore[method-assign]

    with pytest.raises(ResearchResultValidationError):
        ResearchService(client, runner, task_dir=tmp_path).run("demo")  # type: ignore[arg-type]
    assert client.payloads == []
