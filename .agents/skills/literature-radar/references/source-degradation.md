# Source degradation policy

Use this reference for every external source attempt. A Literature Radar run does not require every optional source to be green; it requires adequate primary evidence for every final recommendation.

## Status vocabulary

Every requested source must finish in exactly one state:

- **success** — the intended route returned usable results and no material fallback was needed.
- **degraded** — the source or one route failed, but a bounded fallback produced useful evidence or other sources provide adequate coverage.
- **failed** — attempted, but no usable evidence was obtained.
- **not_attempted** — deliberately skipped; state the reason.

Record source name, status, attempts, successful route(s), result/evidence count, and a safe warning. `sources_used` includes only sources that provided usable discovery or verification evidence.

## Optional-source retry budget

For an anonymous optional HTTP API such as Semantic Scholar:

1. Submit one minimal, deduplicated request with only required fields.
2. On `429` or a transient `5xx`, honor `Retry-After` when present, capped at 30 seconds.
3. Without `Retry-After`, wait 2 seconds.
4. Retry at most once. Stop after two total attempts.
5. Never assume an API key exists and never loop until success.

Two `429` responses produce `degraded` when other sources cover discovery/verification, otherwise `failed`. Do not repeat equivalent queries merely to satisfy a source name.

## arXiv routes

- Prefer the official Atom API for structured discovery when TLS succeeds.
- Never use `verify=False`, disable certificate verification, or install an untrusted CA.
- Diagnose Python/OpenSSL CA paths, `certifi`, proxy variables, and the Windows trust route. If the installed `certifi` bundle validates the chain, using `ssl.create_default_context(cafile=certifi.where())` is an acceptable verified fallback; record that route.
- If Atom safely fails but official arXiv abstract/HTML/PDF pages work, record arXiv as `degraded`, with `atom_api=failed` and `official_web=success`.
- Official arXiv pages remain primary evidence for preprints.

## Success threshold for the run

The run may succeed when:

- Zotero Library Context has adequate coverage despite isolated query failures;
- at least one broad discovery source succeeds;
- every finalist has a primary source and reconciled identity;
- metadata conflicts affecting identity, status, or the search window are resolved or the candidate is excluded;
- source degradations and their fallbacks are recorded.

A source failure cannot be hidden, but an optional source failure alone is not a Radar blocker.

## Output shape

Use a compact structured record:

```json
{
  "name": "semantic_scholar",
  "status": "degraded",
  "attempts": 2,
  "routes": [
    {"route": "graph_api", "status": "failed", "http_status": 429}
  ],
  "result_count": 0,
  "warning": "Anonymous API returned 429 twice; OpenAlex and primary pages provided coverage."
}
```

Do not include request headers, API keys, tokens, proxy URLs, or raw error pages.
