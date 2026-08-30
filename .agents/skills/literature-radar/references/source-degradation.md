# Source degradation policy

Use this reference for every external source attempt. A Literature Radar run does not require every optional source to be green; it requires adequate reliable evidence for every final recommendation.

## Status vocabulary

Every requested source must finish in exactly one state:

- **success** — the source ultimately returned enough reliable discovery or verification evidence. Earlier route or environment diagnostics do not force degradation when the final verified route succeeds.
- **degraded** — the source returned limited/partial usable evidence, or the source failed but a documented fallback supplied usable evidence.
- **failed** — the source was attempted and no usable evidence or fallback was obtained.
- **not_attempted** — the source was deliberately skipped; record the reason.

Record source name, final status, attempts, route diagnostics, result/evidence count, and a safe warning. `sources_used` includes only sources that supplied usable discovery or verification evidence. Route-level `failed` diagnostics may coexist with source-level `success` when a separate verified route completed the intended source role.

## Stable source helper

Use the repository helper rather than ad-hoc Python HTTPS snippets for arXiv and Semantic Scholar:

```powershell
python .agents\skills\literature-radar\scriptscademic_sources.py probe `
  --query "diffractive optical neural network"
```

The helper emits machine-readable JSON, loads the optional Semantic Scholar key from the Agent root `.env`, and never emits request headers or secret values.

## arXiv TLS and evidence

- All Python HTTPS requests use `ssl.create_default_context(cafile=certifi.where())` as the normal verified CA path.
- Never use `verify=False`, `CERT_NONE`, disabled hostname checks, or an untrusted CA.
- Structured discovery uses the official Atom API.
- Returned candidates are checked against official `https://arxiv.org/abs/<id>` evidence pages.
- Atom success plus sufficient official-page evidence produces source-level `success`.
- A missing/broken default Anaconda/OpenSSL CA path is recorded only as a `default_ca_environment` diagnostic with `active_tls_route=certifi`; it does not degrade an otherwise successful arXiv source.
- Atom success with only partial official-page verification is `degraded`.
- No usable Atom or official evidence is `failed`.

## Semantic Scholar authentication and request control

- `SEMANTIC_SCHOLAR_API_KEY` is optional and is read from the Agent root `.env` through the existing environment loader.
- When configured, send it only in the `x-api-key` request header.
- Never write the key to stdout/stderr, logs, prompts, `result.json`, `report.md`, Workbench payloads, tests, or Git.
- Keyed and anonymous traffic are both limited to no more than approximately one request per second by default.
- Normalize and deduplicate equivalent `(query, limit, fallback mode)` requests within one helper process.
- On `429` or transient `5xx`, honor `Retry-After` when present, capped at 30 seconds.
- Without `Retry-After`, use bounded exponential backoff of 1 then 2 seconds for three total attempts.
- A later successful response is source-level `success`; earlier `429` attempts remain route diagnostics only.
- Exhausted anonymous or keyed attempts are `degraded` only when another source supplied usable fallback evidence; otherwise they are `failed`.

## Success threshold for the run

The run may succeed when:

- Zotero Library Context has adequate coverage despite isolated query failures;
- at least one broad discovery source succeeds;
- every finalist has a primary source and reconciled identity;
- metadata conflicts affecting identity, status, or the search window are resolved or the candidate is excluded;
- source degradations and their fallbacks are recorded.

A source failure cannot be hidden, but an optional source failure alone is not a Radar blocker when coverage remains adequate.

## Output shape

Use a compact structured record. Keep route/environment diagnostics inside `routes`; keep the card-level warning focused on material source limitations:

```json
{
  "name": "arxiv",
  "status": "success",
  "attempts": 2,
  "routes": [
    {
      "route": "default_ca_environment",
      "status": "failed",
      "diagnostic": true,
      "active_tls_route": "certifi"
    },
    {
      "route": "atom_api",
      "status": "success",
      "tls": "certifi",
      "result_count": 3
    },
    {
      "route": "official_evidence",
      "status": "success",
      "verified_count": 3,
      "requested_count": 3
    }
  ],
  "result_count": 3,
  "warning": null
}
```

Do not include request headers, API keys, tokens, proxy URLs, local CA paths, or raw error pages.
