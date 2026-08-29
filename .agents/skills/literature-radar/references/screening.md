# Screening

Screen in two passes: hard evidence gates, then comparative reading value.

## Hard gates

Exclude a candidate from Top N when any of these applies:

- the paper cannot be verified as real;
- title/authors/identity or publication-date differences cannot be reconciled under `metadata-policy.md`;
- no DOI, arXiv ID, official proceedings record, or reliable primary paper URL exists;
- its central topic is outside the profile or primarily matches an excluded direction;
- it is already in Zotero and has no evidenced formal-version or major-revision exception;
- the recommendation would require claims not supported by the abstract/full text inspected;
- it is a duplicate preprint/published representation of another candidate; normal online-first versus later issue dates are not duplicates or conflicts;
- it is an editorial, news article, presentation, patent, dataset page, or secondary commentary rather than the required real paper.

`verified_candidate_count` is the number of unique candidates that pass identity and primary-evidence gates, even if they later rank below the final shortlist.

## Relevance screening

Judge the actual problem and method, not keyword occurrence. For D2NN, a paper is strongly relevant when diffraction/free-space propagation/metasurfaces perform a central computational or neural-network function. Generic optical neural networks, integrated photonics, or metasurface papers are only relevant when the contribution materially intersects the configured free-space/diffractive scope.

## Novelty screening against Zotero

“Not in the library” is necessary but not sufficient. Look for a contribution relative to known work:

- new physical mechanism or trainable element;
- new architecture or scaling strategy;
- new experimental demonstration;
- new task or application with substantive methodological implications;
- new material/device that changes capability;
- meaningful robustness, efficiency, accuracy, or programmability advance;
- strong negative result, limitation analysis, or comparison that changes how known work should be interpreted.

## Evidence notes

For each serious candidate, keep a short note:

- problem;
- core method/physics;
- main difference from related work;
- reported result and evaluation setting;
- limitations stated or reliably inferable;
- publication status;
- evidence depth (`full_text`, `abstract`, or `metadata`);
- duplicate decision;
- why included/excluded.

Do not compare headline metrics across different tasks, datasets, optical setups, or simulation/experimental conditions without stating the mismatch.

## Final selection

- Prefer fewer strong papers over filling `max_results`.
- Preprints are allowed but must be labeled.
- Favor accessible primary evidence when otherwise comparable.
- A high-prestige venue does not rescue weak relevance.
- A recent date does not rescue an incremental or unverified paper.
