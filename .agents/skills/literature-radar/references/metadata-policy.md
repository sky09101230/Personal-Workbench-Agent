# Metadata and publication-date policy

Use this reference during paper identity verification, date reconciliation, recency scoring, and preprint/publication merging.

## Identity first

Merge in this order:

1. normalized DOI;
2. versionless arXiv ID;
3. canonical title plus overlapping authors;
4. canonical title + year only as a cautious fallback.

A dataset, supplementary file, repository collection, conference abstract, preprint, and journal article can describe the same work. Keep one paper identity, select the strongest verified version, and retain additional identifiers as evidence.

## Date semantics

Do not force every date into one field during verification. Track:

- **preprint_at** — first public preprint submission date;
- **online_at** — publisher online-first or version-of-record availability date;
- **issue_at** — journal issue/print publication date;
- **accepted_at** — acceptance date when authoritative and useful;
- **first_public_at** — earliest reliably verified public paper version;
- **version_published_at** — publication date of the version being recommended.

The result field `published_at` is `first_public_at` and is used for the configured lookback and recency score. `year`, venue, and publication type describe the strongest recommended version. Preserve the other dates in `date_evidence`.

## Authority and reconciliation

Prefer, in order:

1. official publisher/proceedings page or official arXiv record;
2. Crossref field with explicit semantics (`published-online`, `published-print`, `issued`);
3. authoritative repository metadata;
4. OpenAlex or Semantic Scholar as discovery/corroboration;
5. search snippets only as leads.

Crossref `created` is DOI registration time, not automatically publication time. It may corroborate an online-first date when another reliable source/index reports the same date. OpenAlex `publication_date` may represent online-first availability while Crossref `issued` represents a future issue/print month; that is an explainable date difference, not a verification conflict.

## Example of an explainable difference

For an article available online in July but assigned to a December issue:

```json
{
  "first_public_at": "2026-07-03",
  "online_at": "2026-07-03",
  "issue_at": "2026-12",
  "version_published_at": "2026-07-03",
  "selected_reason": "online-first date corroborated by DOI registration and a scholarly index; Crossref issued date is the print/issue assignment"
}
```

Do not exclude it merely because July and December differ.

## True conflict

Mark `verification_conflict` and exclude a candidate only when reliable sources cannot reconcile a difference that changes one of:

- paper identity;
- preprint versus formal publication status;
- whether the work is inside the lookback window;
- the version to recommend;
- author/title attribution.

Record the conflicting fields and sources without guessing.

## Recency and formal-version exceptions

- Recency uses `first_public_at`, not a later issue date.
- A formal publication inside the window whose preprint was older is not automatically a new discovery. It may enter only as an explicit formal-version/major-update exception.
- Routine arXiv version increments do not reset recency.
- A genuinely major new version needs primary evidence of material new results.
