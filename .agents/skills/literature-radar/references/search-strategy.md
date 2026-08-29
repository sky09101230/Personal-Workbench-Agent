# Search strategy

Also read [source-degradation.md](source-degradation.md) and [metadata-policy.md](metadata-policy.md).

Use this reference after Library Context has been collected.

## 1. Define the window

- `to` is the UTC calendar date of the run.
- `from` is `lookback_days` before `to`.
- Prefer works first made public inside the window. A journal issue date is not necessarily the first-public date when an arXiv version exists.
- Older works may enter the candidate pool only when recent results are too thin or when an important formal/major revision occurred in the window. Record the exception as a warning.

## 2. Expand the topic without losing it

Build 6–12 purposeful queries across these buckets:

1. Exact profile phrases.
2. Accepted acronyms and spelling variants.
3. Closely related architecture/physics terms.
4. Task combinations such as classification, imaging, inverse design, generation, or reconfigurability when they are relevant to the profile.
5. Vocabulary learned from highly related Zotero anchor papers.
6. Title/author follow-ups for promising candidates or suspected new versions.

For the D2NN profile, useful expansions can include `D2NN`, `D2NNs`, `diffractive deep neural network`, `diffractive optical neural network`, `free-space optical neural network`, `all-optical neural network`, `reconfigurable diffractive network`, `metasurface neural network`, and `space-domain optical computing`. These are examples, not a mandatory static query list.

Treat exclusions semantically. `on-chip photonics` and `silicon photonics` should remove papers whose central contribution is integrated/on-chip photonics, but should not hide a directly relevant free-space/diffractive paper that mentions an on-chip baseline.

## 3. Use source roles deliberately

| Source family | Best V0 role | Evidence status |
|---|---|---|
| arXiv | frontier discovery, version history, abstract/PDF | primary for preprints |
| OpenAlex | broad discovery, DOI and related-work metadata | index; corroborate claims elsewhere |
| Semantic Scholar | discovery, similar/citing work, OA pointers | index; corroborate claims elsewhere |
| DOI/Crossref | DOI metadata reconciliation | authoritative metadata, not always full evidence |
| Publisher/proceedings page | canonical publication status and article metadata | primary |

Do not force a source to appear in `sources_used` merely because it is listed in the profile. Record every requested source with `success`, `degraded`, `failed`, or `not_attempted`. Anonymous optional APIs use at most two attempts and bounded backoff as defined in `source-degradation.md`. Continue after an optional failure only when other sources provide adequate discovery and primary evidence.

## 4. Candidate bookkeeping

Keep a compact scratch table with:

- discovered title and source;
- normalized DOI;
- versionless arXiv ID;
- canonical title;
- authors and first-public date;
- publication status;
- abstract/full-text availability;
- likely profile match;
- likely Zotero duplicate;
- verification URLs.

`candidate_count` means unique external works after DOI/arXiv/title identity merging and before hard screening. Use `scripts/paper_identity.py` when candidates are materialized as JSON; merge records with a missing DOI against DOI-bearing records by canonical title, and prefer the formal non-repository record as canonical. Stop collecting at `max_candidates`; deepen verification instead of endlessly expanding.

## 5. Verification and evidence retrieval

Before final selection, apply the date semantics in `metadata-policy.md`:

1. Open an arXiv abstract page, publisher/proceedings page, or another canonical primary page.
2. Confirm title, core author list, date/year, and DOI/arXiv identifier.
3. Resolve conflicts with another authoritative metadata source.
4. Read the abstract for every verified candidate.
5. For likely finalists, inspect accessible method, results, discussion, figures/tables, and limitations sections. Use the full paper when available; otherwise constrain the summary to abstract-supported facts.

An index snippet, search snippet, blog, news item, or model memory cannot be the sole evidence for a recommendation.

## 6. Recency and version identity

- Strip arXiv version suffixes for identity while retaining the version/date in notes.
- When a DOI publication and arXiv preprint share the same work, keep one candidate with the strongest canonical URL and both identifiers.
- Record `publication_type` from the strongest verified status: journal/conference over preprint when the formal version is confirmed.
- Do not treat routine arXiv version increments as new papers. A major new result must be evidenced before granting a version exception.
