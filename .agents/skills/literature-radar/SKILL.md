---
name: literature-radar
description: Discover and rank recent papers from a research profile by combining read-only Zotero library context with verified external academic search. Use for a one-off Literature Radar run that writes result.json and report.md; do not use for Workbench ingest, ResearchTask execution, scheduling, or Zotero writes.
---

# Literature Radar

Run a one-off, repository-local literature discovery pass from a Research Profile. The purpose is to find papers that are both new to the user's Zotero library and worth reading, not to fill a quota.

## V0 boundaries

- Read a JSON profile from `research_profiles/`; do not read or invoke `research_tasks/`.
- Use the MCP server named `zotero` only for read-only library context. Never create, edit, tag, move, import, or delete Zotero data.
- Use external academic search for discovery. Zotero is not the public search engine.
- Do not call the existing Paper Research Worker, `ResearchService`, Workbench APIs, ingest endpoints, databases, schedulers, daemons, or automations.
- Do not expose API keys, environment variables, local attachment paths, or secrets in prompts or output files.
- On a required Zotero or external-search failure, report the exact blocker and stop. Never claim a dependency succeeded or fabricate recommendations.

## Run inputs

Default to `research_profiles/d2nn.json` when the user does not provide a profile. Respect a user-supplied result limit only when it is lower than or equal to `search.max_results`.

Resolve all paths from the repository root with workspace file tools. Windows-safe output directories use UTC timestamps without colons, for example `research_outputs/20260829T153045Z/`.

## Required workflow

1. **Load and validate the profile.** Confirm `schema_version == 1`, required arrays are non-empty, `lookback_days`, candidate/result limits are positive, and ranking weights sum to 1. Map `ranking.novelty_to_zotero` to the output score named `novelty`.
2. **Build Zotero Library Context first.** Read [references/zotero-context.md](references/zotero-context.md). Query the MCP server `zotero` with a bounded, read-only strategy. Capture enough verified metadata for duplicate and relationship judgments, but do not traverse the full library or full text. If `zotero.enabled` is true and MCP cannot be called successfully, stop the run.
3. **Plan external queries.** Read [references/search-strategy.md](references/search-strategy.md). Expand concepts, abbreviations, neighboring terms, tasks, and anchor-paper vocabulary from the profile plus Zotero context. Keep the scope centered on the profile and honor exclusions semantically.
4. **Discover candidates.** Search the requested source families using available Codex web/search capabilities. Treat arXiv, OpenAlex, and Semantic Scholar as discovery/metadata sources; prefer arXiv abstract pages, DOI/publisher pages, and official proceedings pages as primary evidence. Keep at most `search.max_candidates` unique works after identity merging.
5. **Normalize and verify identity.** Merge versions in DOI → versionless arXiv ID → canonical title → title+year order. Verify title, authors, date/year, publication status, and at least one reliable identifier or primary URL. A preprint and its journal/conference version are one work unless they contain a materially distinct contribution.
6. **Screen against Zotero.** Read [references/screening.md](references/screening.md). Every candidate must be checked against Library Context. Papers already present are excluded by default, except a clearly important new formal version or major revision; document any exception.
7. **Read enough primary evidence.** For serious finalists, inspect the abstract and the most relevant accessible method, result, discussion, and limitation material. Prefer full text when accessible, but do not invent details when only an abstract is available. Record evidence depth and make claims no stronger than the material read.
8. **Rank.** Read [references/ranking.md](references/ranking.md). Score relevance, novelty to Zotero, scientific value, and recency on 0–1 relative scales, then calculate the configured weighted overall score. Do not use keyword presence, citation count, or venue prestige as a substitute for content judgment.
9. **Write the run artifacts.** Create `research_outputs/<timestamp>/result.json` and `report.md` only after the required dependencies and evidence gates succeed. Sort recommendations by descending `scores.overall`; output fewer than the limit when evidence is insufficient.
10. **Validate before finishing.** Parse `result.json`, verify its recommendation count and score arithmetic, ensure every recommendation has primary evidence, confirm `report.md` matches the JSON order, and scan both files for secrets or unsupported claims.

## Result contract

`result.json` must be UTF-8 JSON with this top-level shape:

```json
{
  "schema_version": 1,
  "profile": {"key": "...", "name": "...", "path": "..."},
  "generated_at": "ISO-8601 UTC",
  "search_window": {"from": "YYYY-MM-DD", "to": "YYYY-MM-DD", "lookback_days": 60},
  "zotero_context": {
    "success": true,
    "server": "zotero",
    "queries_used": 0,
    "known_paper_count": 0,
    "related_collection_count": 0,
    "summary": "...",
    "warnings": []
  },
  "search": {
    "queries": [],
    "sources_requested": [],
    "sources_used": [],
    "candidate_count": 0,
    "verified_candidate_count": 0
  },
  "warnings": [],
  "recommendations": []
}
```

Each recommendation must include at least:

```json
{
  "title": "...",
  "authors": ["..."],
  "year": 2026,
  "published_at": "...",
  "doi": null,
  "arxiv_id": null,
  "url": "...",
  "venue": "...",
  "publication_type": "preprint | journal | conference | other",
  "ai_summary": "中文：问题、方法、区别、主要结果、可靠可判断的局限",
  "recommendation_reason": "中文：为什么对该 profile 和当前 Zotero 背景值得读",
  "zotero_relationship": {
    "already_in_library": false,
    "related_papers": [{"title": "Zotero 中真实存在的标题", "relationship": "..."}],
    "relationship_summary": "..."
  },
  "scores": {
    "relevance": 0.0,
    "novelty": 0.0,
    "scientific_value": 0.0,
    "recency": 0.0,
    "overall": 0.0
  },
  "evidence": {
    "primary_url": "...",
    "additional_urls": [],
    "evidence_depth": "full_text | abstract | metadata"
  }
}
```

Use `null` for an unknown DOI or arXiv ID; never invent one. `related_papers` may be empty. Do not name a related Zotero paper unless the MCP result actually established that it exists.

## Report contract

`report.md` is the human acceptance view. Its header must list profile, generation time, search window, unique candidate count, verified candidate count, final count, sources requested/used, Zotero success, and warnings. For each paper show title; authors/year/venue/type; DOI/arXiv; Chinese AI Summary; Why Recommended; Zotero Relationship; the four component scores plus overall; evidence depth; and primary source.

Finish by returning the absolute paths to both artifacts, counts, selected titles, dependency status, and warnings. Do not upload or ingest anything.
