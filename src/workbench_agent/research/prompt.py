from __future__ import annotations

import json

from .task import ResearchTask


class PromptBuilder:
    version = "paper_research_v1"

    def build(self, task: ResearchTask, *, run_key: str, generated_at: str) -> str:
        task_context = {
            "key": task.key,
            "name": task.name,
            "topics": list(task.topics),
            "keywords": list(task.keywords),
            "exclude": list(task.exclude),
            "lookback_days": task.lookback_days,
            "max_candidates": task.max_candidates,
            "max_results": task.max_results,
            "zotero": {"enabled": task.zotero_enabled},
            "research": {
                "require_real_papers": task.require_real_papers,
                "require_primary_sources": task.require_primary_sources,
            },
        }
        return f"""You are executing a Personal Workbench paper research task.

Execution metadata:
- schema_version: 1
- task_key: {task.key}
- run_key: {run_key}
- generated_at: {generated_at}
- prompt_version: {self.version}

Task JSON:
{json.dumps(task_context, ensure_ascii=False, indent=2)}

Required workflow:
1. Use the configured Zotero MCP first. Inspect only the minimum relevant library context: related papers, recent saves, DOI identifiers, research directions, collections, and likely duplicates. Do not dump the library. If Zotero MCP is unavailable, do not claim it was used; stop with an explicit failure instead of silently degrading.
2. Build and execute an expanded search plan from the topics, keywords, exclusions, and verified Zotero context. Do not merely repeat the provided keywords. Put the real external queries in query_plan.
3. Search external authoritative sources using available web/search tools. OpenAlex, arXiv, Crossref, Semantic Scholar, publisher pages, and official publication pages are acceptable. Treat on-chip photonics as a topical exclusion, not a literal blacklist.
4. Prefer papers from the last {task.lookback_days} days. Expand farther back only when recent high-quality results are insufficient; never trade relevance or truth for filling the quota.
5. Verify every recommended paper against at least one authoritative source. Output fewer than {task.max_results} papers if necessary. Never invent a paper, identifier, author, venue, date, result, or Zotero relationship.
6. ai_summary must cover the research problem, core method, main innovation, reported key results, and limitations/cautions. It must not be an abstract translation.
7. recommendation_reason must explain why this user should read the paper, grounded in the task, paper, and verified Zotero context. Set relationship_to_library to null when no specific relationship is evidenced.

Return only the strict structured JSON accepted by the supplied output schema. Use null for unknown optional values. Set agent.type to codex, agent.model to the actual model identifier if available (otherwise configured), and agent.prompt_version to {self.version}. Preserve the execution metadata exactly.
"""
