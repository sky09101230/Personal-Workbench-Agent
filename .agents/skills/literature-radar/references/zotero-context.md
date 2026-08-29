# Zotero Library Context

Zotero answers “what does the user already know?” It is not the public discovery engine.

## Backends

The profile selects the backend through `zotero.backend`.

- `cli` is the required/default V0 backend.
- `mcp` may be documented or implemented later, but an MCP handshake is not required when the selected backend is `cli`.

## CLI resolution and preflight

Use `scripts/zotero_cli.py` from the skill directory. It resolves in this order:

1. `shutil.which("zotero-cli")`;
2. Windows `shutil.which("zotero-cli.exe")`;
3. `uv tool dir --bin`, followed by `<uv-bin>\zotero-cli.exe` on Windows;
4. explicit failure.

The helper never uses a PowerShell alias or `shell=True`.

Before the first library read, run the helper's `preflight` command. It executes and validates `zotero-cli --json config`, but emits only readiness fields and never the settings payload. Then run `batch-search`. Library access is successful only when at least one query returns a valid `ok: true` envelope and the successful queries provide adequate context.

All subsequent machine-readable calls go through the helper. It sets `PYTHONUTF8=1` and `PYTHONIOENCODING=utf-8`, captures raw bytes, decodes UTF-8 strictly, validates exit/envelope agreement, and emits ASCII-safe JSON escapes. Treat invalid UTF-8, malformed JSON, a nonzero exit, or `ok != true` as a per-command failure. Do not parse human-oriented Markdown/prose.

## Read-only command boundary

Allowed V0 operations include:

- `--json search <query> --limit <n>`;
- `--json get metadata <KEY>` for selected anchors;
- `--json get recent --limit <n>` when enabled;
- `--json get collections` when enabled;
- semantic database status/search only when already available.

Never use `add`, `edit`, `delete`, `attach`, write-oriented `tags`, duplicate merge, note creation, batch update, or any other mutation command.

## Bounded context plan

Use the smallest query budget that establishes duplicates and nearby interests. A normal D2NN V0.1 run uses the strongest five profile-derived searches in one `batch-search`, normally with `--limit 10`:

- diffractive neural network;
- diffractive optical computing;
- optical neural network;
- free-space optical computing;
- metasurface optical computing.

These are derived from the profile, not hardcoded paper records. Deduplicate returned anchors across queries. One failed query makes the context `degraded`, not automatically failed; continue when the other queries still cover the core interests and exact finalist duplicate checks remain available. Stop when all queries fail or coverage is materially insufficient. Do not permanently lower the limit to avoid encoding problems. Do not traverse the full library.

Optionally inspect recent relevant items and collections. Semantic search may enrich context if its database is ready; its absence must not block V0. Retrieve detailed metadata only for the most important anchors or an ambiguous duplicate. Do not bulk-read PDFs.

## Capture internally

For relevant known papers, keep only what is needed:

- Zotero item key for follow-up reads;
- exact title;
- DOI normalized to lowercase without a `https://doi.org/` prefix;
- arXiv ID without the version suffix;
- authors and year/date;
- publication/venue and URL;
- collection names when useful;
- topic/method cues that support a relationship judgment.

Build four conceptual sets:

- **Known Papers** — identity records for duplicate matching.
- **Known Topics** — repeated topics or methods in related items.
- **Recent Interests** — directions visible in recently added related items.
- **Potential Duplicates** — ambiguous titles, preprint/formal versions, and candidate exact matches.

Do not write a raw library dump to `result.json` or `report.md`. Persist the real queries, anchor count, concise context summary, and only those individual anchor titles used in recommendation relationships.

## Duplicate order

For every external candidate, check:

1. normalized DOI;
2. versionless arXiv ID;
3. canonicalized title;
4. title + year.

Canonical title comparison should lowercase, normalize Unicode and whitespace, remove surrounding punctuation, and ignore only harmless punctuation differences. It must not merge substantively different works merely because they share keywords.

Profile exclusions are semantic, not literal blacklists. A Zotero anchor or external paper that substantively covers free-space diffractive computing is not discarded merely because its title also mentions on-chip computing. Pure integrated/silicon-photonic work remains outside scope.

## Relationship vocabulary

Use evidence-backed relationships such as:

- extension;
- alternative;
- complementary approach;
- new task;
- new architecture;
- new physical mechanism;
- experimental advance;
- broader review relationship;
- formal publication or major revision.

If no specific known paper is established, return an empty `related_papers` array and describe only a cautious topic-level relationship. Never invent a Zotero title.

## Failure behavior

If the profile requires Zotero CLI and resolution, `config`, or the first JSON library read fails:

1. record the exact observed error without config values or secrets;
2. stop before external recommendations;
3. do not create a successful `result.json`.
