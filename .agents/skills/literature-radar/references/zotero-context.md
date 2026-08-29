# Zotero Library Context

Zotero answers “what does the user already know?” It is not the public discovery engine.

## Required access mode

- Use the configured MCP server named `zotero`.
- Use read-only search, inventory, collection, and item metadata operations only.
- Do not import, save, update, tag, move, select a write target, or modify attachments.
- Do not silently replace a required MCP call with direct local API access. Direct/local diagnostics may explain a failure, but `zotero_context.success` is true only after a real MCP read succeeds.

## Bounded context plan

Use the smallest query budget that establishes duplicates and nearby interests. A normal V0 run should need roughly 6–15 Zotero reads, not a full-library traversal.

1. Search 3–5 strongest profile phrases and acronyms.
2. Inspect the metadata of the most related results.
3. List or search clearly related collections when collection access is enabled.
4. Inspect a bounded set of recently added relevant items when recent-library context is enabled.
5. Run exact DOI, arXiv ID, or title searches for candidates that reach serious screening.

Do not read every attachment or full text. For Library Context, metadata and a small number of abstracts/notes are enough unless a specific relationship cannot otherwise be established.

## Capture internally

For relevant known papers, keep only what is needed:

- exact title;
- DOI normalized to lowercase without a `https://doi.org/` prefix;
- arXiv ID without the version suffix;
- authors and year;
- collection names when useful;
- date added/recentness when available;
- topic/method cues that can support a relationship judgment.

Build four conceptual sets:

- **Known Papers** — identity records for duplicate matching.
- **Known Topics** — repeated topics or methods in related items.
- **Recent Interests** — directions visible in recently added related items.
- **Potential Duplicates** — ambiguous titles, preprint/formal versions, and candidate exact matches.

Do not write a raw library dump to `result.json` or `report.md`. Persist counts and a concise context summary; disclose individual Zotero titles only when they are used in a recommendation relationship.

## Duplicate order

For every candidate, check:

1. normalized DOI;
2. versionless arXiv ID;
3. canonicalized title;
4. title + year.

Canonical title comparison should lowercase, normalize Unicode and whitespace, remove surrounding punctuation, and ignore only harmless punctuation differences. It must not merge two substantively different titles merely because they share keywords.

## Relationship vocabulary

Use evidence-backed relationships such as:

- extends the architecture of;
- applies the method to a new task;
- replaces or adds a physical mechanism;
- reports experimental validation for a previously simulated idea;
- provides a formal publication or major revision of;
- challenges or improves a stated limitation of;
- is adjacent but uses a materially different optical platform.

If no specific known paper is established, return an empty `related_papers` array and describe only a cautious topic-level relationship. Never invent a Zotero title.

## Failure behavior

If the profile requires Zotero and the MCP server cannot start, authenticate, expose a readable interface, or return a successful read:

1. record the exact observed error;
2. state that the local API being alive does not prove MCP success;
3. stop before external recommendations and do not create a successful `result.json`.
