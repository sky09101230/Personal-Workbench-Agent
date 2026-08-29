# Ranking

Scores are structured relative judgments, not measured ground truth. Use the full 0–1 range consistently across the current candidate set and retain enough notes to explain each score.

## Relevance

- `0.90–1.00`: directly advances the profile's central method/physics/problem.
- `0.70–0.89`: strong direct connection with one meaningful scope difference.
- `0.45–0.69`: adjacent and useful, but not central.
- `<0.45`: weak fit; normally screen out.

Base this on the paper's actual method and results, not title keywords.

## Novelty to Zotero

- `0.90–1.00`: distinctly new mechanism, architecture, task, or experimental capability relative to known papers.
- `0.70–0.89`: meaningful extension that changes what can be done or understood.
- `0.45–0.69`: useful incremental extension or new application with limited conceptual distance.
- `0.10–0.44`: close repetition of known work.
- `0.00`: already in the library without a justified version exception.

State the evidence-backed relationship that supports the judgment. Library absence alone cannot justify a high score.

## Scientific value

Combine:

- substantive methodological/physical contribution;
- adequacy of experiments, simulations, baselines, ablations, or theory;
- clarity of evidence for the main claim;
- likely usefulness for the user's research decisions;
- evidence depth available during this run.

Do not reduce this to venue prestige or changing citation counts. Abstract-only evidence should normally cap confidence and score unless the abstract reports unusually clear, verifiable results.

## Recency

Use the first reliable public date relative to the configured search window:

- 0–7 days: `1.00`
- 8–21 days: `0.85`
- 22–45 days: `0.70`
- 46–60 days: `0.55`
- older than the requested window: at most `0.25`, and only with an explicit exception

If the profile has another lookback, scale the bands proportionally while preserving the same ordering.

## Overall

For the V0 profile:

```text
overall =
  relevance * ranking.relevance +
  novelty * ranking.novelty_to_zotero +
  scientific_value * ranking.scientific_value +
  recency * ranking.recency
```

Round component scores and overall to three decimals. Recalculate after rounding and allow only a `0.001` arithmetic tolerance. Sort descending by overall, breaking near-ties by relevance, then novelty, then stronger evidence depth.

The final report should show all component scores so the user can disagree with the judgment rather than mistaking the number for objective truth.
