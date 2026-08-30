---
name: literature-radar
description: Discover and rank recent papers from a research profile by combining read-only Zotero library context with verified external academic search. Use for a one-off Literature Radar run that writes result.json and report.md; do not use for Workbench ingest, ResearchTask execution, scheduling, or Zotero writes.
---

# Literature Radar

Run a one-off, repository-local literature discovery pass from a Research Profile. The purpose is to find papers that are both new to the user's Zotero library and worth reading, not to fill a quota.

## V0.1 boundaries

- Read a JSON profile from `research_profiles/`; do not read or invoke `research_tasks/`.
- Use the profile's read-only Zotero backend for Library Context. V0 defaults to `zotero.backend = "cli"`; MCP is a future optional backend and is not required for a CLI run.
- Never create, edit, tag, move, import, merge, attach, or delete Zotero data.
- Use external academic search for discovery. Zotero is not the public search engine.
- Do not call the existing Paper Research Worker, `ResearchService`, Workbench APIs, ingest endpoints, databases, schedulers, daemons, or automations.
- Do not expose API keys, environment variables, local attachment paths, or secrets in prompts or output files.
- On a required Zotero CLI or external-search failure, report the exact blocker and stop. Never claim a dependency succeeded or fabricate recommendations.

## Run inputs

Default to `research_profiles/d2nn.json` when the user does not provide a profile. Respect a user-supplied result limit only when it is lower than or equal to `search.max_results`.

Resolve all paths from the repository root with workspace file tools. Windows-safe output directories use UTC timestamps without colons, for example `research_outputs/20260829T153045Z/`.

## Zotero CLI backend

Read [references/zotero-context.md](references/zotero-context.md) before accessing the library.

Resolve the executable with the stdlib helper:

```powershell
python .agents\skills\literature-radar\scripts\zotero_cli.py resolve
python .agents\skills\literature-radar\scripts\zotero_cli.py preflight
python .agents\skills\literature-radar\scripts\zotero_cli.py batch-search `
  --limit 10 `
  --query "diffractive neural network" `
  --query "diffractive optical computing"
```

The helper implements this exact order without `shell=True` or PowerShell aliases:

1. `shutil.which("zotero-cli")`;
2. on Windows, `shutil.which("zotero-cli.exe")`;
3. resolve `uv`, run `uv tool dir --bin`, then check `<uv-bin>\zotero-cli.exe` on Windows;
4. fail explicitly if no executable is found.

`preflight` runs machine-readable `zotero-cli --json config`, validates it, and returns only a non-sensitive readiness summary. The helper forces UTF-8 for the child process, parses raw stdout bytes as UTF-8, and emits ASCII-safe JSON escapes so Windows console code pages and PowerShell redirection cannot corrupt data. The first successful JSON search confirms actual library access.

Use the helper rather than invoking the CLI through a PowerShell alias. All machine-readable Zotero calls use `--json`, raw-byte UTF-8 decoding, strict envelope validation, and safe diagnostics. `batch-search` isolates a failed query and returns `degraded: true` when other queries succeed. Use only read operations such as `search`, `get metadata`, `get recent`, `get collections`, and optional semantic database status/search. Semantic search may enrich context but must not block V0.

## Required workflow

1. **Load and validate the profile.** Confirm `schema_version == 1`, required arrays are non-empty, `zotero.backend` is supported, `lookback_days`, candidate/result limits are positive, and ranking weights sum to 1. Map `ranking.novelty_to_zotero` to the output score named `novelty`.
2. **Preflight Zotero first.** For backend `cli`, resolve the executable and run `zotero-cli config` through the helper. Then perform a bounded JSON search to confirm the configured local/web library is readable. If either step fails, stop.
3. **Build Zotero Library Context.** Run the profile-derived searches through `batch-search`, normally with 10 results per query. Continue after an isolated query failure, mark the context degraded, and stop only when successful queries do not provide adequate duplicate/novelty coverage. Deduplicate anchors by DOI → arXiv ID → canonical title → title+year. Inspect detailed metadata only for important anchors. Do not traverse the full library or bulk-read PDFs.
4. **Plan external queries.** Read [references/search-strategy.md](references/search-strategy.md), [references/source-degradation.md](references/source-degradation.md), and [references/metadata-policy.md](references/metadata-policy.md). Expand concepts, abbreviations, neighboring terms, tasks, and anchor-paper vocabulary from the profile plus Zotero context. Keep the scope centered on the profile and honor exclusions semantically.
5. **Discover candidates.** Search the requested source families using available Codex web/search capabilities. Treat arXiv, OpenAlex, and Semantic Scholar as discovery/metadata sources; prefer arXiv abstract pages, DOI/publisher pages, and official proceedings pages as primary evidence. Keep at most `search.max_candidates` unique works after identity merging.
6. **Normalize and verify identity.** Use `scripts/paper_identity.py` or the same deterministic rules to merge versions in DOI → versionless arXiv ID → canonical title → title+year order. Verify title, authors, date/year, publication status, and at least one reliable identifier or primary URL. A preprint and its journal/conference version are one work unless they contain a materially distinct contribution.
7. **Screen against Zotero.** Read [references/screening.md](references/screening.md). Every candidate must be checked against Library Context. Papers already present are excluded by default, except a clearly important new formal version or major revision; document any exception.
8. **Read enough primary evidence.** For serious finalists, inspect the abstract and the most relevant accessible method, result, discussion, and limitation material. Prefer full text when accessible, but do not invent details when only an abstract is available. Record evidence depth and make claims no stronger than the material read.
9. **Rank.** Read [references/ranking.md](references/ranking.md). Score relevance, novelty to Zotero, scientific value, and recency on 0–1 relative scales, then calculate the configured weighted overall score. Do not use keyword presence, citation count, or venue prestige as a substitute for content judgment.
10. **Write the run artifacts.** Create `research_outputs/<timestamp>/result.json` and `report.md` only after the required dependencies and evidence gates succeed. Sort recommendations by descending `scores.overall`; output fewer than the limit when evidence is insufficient.
11. **Validate before finishing.** Run `scripts/validate_output.py <result.json> <report.md>`, then parse `result.json`, verify its recommendation count and score arithmetic, ensure every recommendation has primary evidence, confirm `report.md` matches the JSON order, and scan both files for secrets or unsupported claims.

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
    "backend": "cli",
    "executable": "...",
    "queries_used": [],
    "anchor_count": 0,
    "related_collection_count": 0,
    "summary": "...",
    "warnings": []
  },
  "search": {
    "queries": [],
    "sources_requested": [],
    "sources_used": [],
    "source_status": [{"name": "openalex", "status": "success", "attempts": 1, "routes": [], "result_count": 0, "warning": null}],
    "candidate_count": 0,
    "verified_candidate_count": 0
  },
  "screening": {"verified_not_selected": [], "exclusion_counts": {}},
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
  "date_evidence": {"first_public_at": "...", "online_at": null, "issue_at": null, "preprint_at": null, "version_published_at": "...", "selected_reason": "..."},
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

Use `null` for an unknown DOI or arXiv ID; never invent one. `related_papers` may be empty. Do not name a related Zotero paper unless a real CLI result established that it exists.

## Report contract

`report.md` is the human acceptance view. Include the strongest verified-but-not-selected papers and their exclusion reasons so Top N choices are auditable.  Its header must list profile, generation time, lookback window, Zotero backend, context status, anchor count, external source status/degradation, unique candidate count, verified candidate count, final count, and warnings. Explain material online/preprint/issue date semantics for shortlisted papers. For each paper show title; authors/date/venue/type; DOI/arXiv; Chinese AI Summary; Why Recommended; Zotero Relationship; the four component scores plus overall; evidence depth; and primary source.

Finish by returning the absolute paths to both artifacts, counts, selected titles and identifiers, Zotero executable/preflight/query details, dependency status, and warnings. Do not upload or ingest anything.
