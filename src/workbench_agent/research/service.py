from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from ..client import WorkbenchClient
from ..errors import ResearchResultValidationError
from .codex_runner import CodexResearchRunner
from .models import ResearchResult, research_result_schema
from .prompt import PromptBuilder
from .task import load_research_task


class ResearchService:
    def __init__(
        self,
        client: WorkbenchClient,
        runner: CodexResearchRunner,
        *,
        task_dir: str | Path | None = None,
    ) -> None:
        self.client = client
        self.runner = runner
        self.task_dir = task_dir

    def run(
        self, task_key: str, *, dry_run: bool = False
    ) -> tuple[ResearchResult, dict[str, object] | None]:
        task = load_research_task(task_key, self.task_dir)
        if task.zotero_enabled:
            self.runner.require_mcp("zotero")
        now = datetime.now(timezone.utc)
        generated_at = now.isoformat().replace("+00:00", "Z")
        run_key = (
            f"{task.key}-{now.strftime('%Y%m%dT%H%M%SZ')}-{uuid4().hex[:6]}"
        )
        instruction = PromptBuilder().build(
            task, run_key=run_key, generated_at=generated_at
        )
        raw = self.runner.run(instruction, research_result_schema(task.max_results))
        result = ResearchResult.from_payload(
            raw, task_key=task.key, max_results=task.max_results
        )
        if result.run_key != run_key:
            raise ResearchResultValidationError(
                "run_key does not match the current research execution"
            )
        if result.generated_at != generated_at:
            raise ResearchResultValidationError(
                "generated_at does not match the current research execution"
            )
        if dry_run:
            return result, None
        return result, self.client.ingest_paper_research(result.to_payload())
