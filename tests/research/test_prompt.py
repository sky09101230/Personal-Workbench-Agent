from workbench_agent.research.prompt import PromptBuilder
from workbench_agent.research.task import ResearchTask


def test_prompt_contains_task_and_research_requirements() -> None:
    task = ResearchTask(
        key="d2nn-recent-papers",
        name="D2NN Recent Papers",
        topics=("diffractive neural networks",),
        keywords=("optical neural network",),
        exclude=("on-chip photonics",),
        lookback_days=30,
        max_candidates=30,
        max_results=5,
        zotero_enabled=True,
        require_real_papers=True,
        require_primary_sources=True,
    )

    prompt = PromptBuilder().build(
        task,
        run_key="d2nn-recent-papers-20260829T091500Z-a31f42",
        generated_at="2026-08-29T09:15:00Z",
    )

    for expected in (
        "diffractive neural networks",
        "optical neural network",
        "on-chip photonics",
        "last 30 days",
        "fewer than 5",
        "Zotero MCP first",
        "authoritative source",
        "strict structured JSON",
        "paper_research_v1",
    ):
        assert expected in prompt
