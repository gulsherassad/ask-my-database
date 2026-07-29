# Experiment Log — Natural Language to SQL

Measuring and improving execution accuracy on the BIRD Mini-Dev benchmark.
All numbers are **Execution Accuracy (EX)** — the official BIRD metric: a generated
query is correct only if it runs, finishes within the timeout, and returns the same
result set as the human-written gold query. Scored with BIRD's official
`evaluation_ex.py`, not a custom comparison.

Evaluation sample: first **50** questions of Mini-Dev
(25 simple / 19 moderate / 6 challenging).
Model: `claude-sonnet-5`. One API call per question at generation time.

## Results at a glance

| Stage | Change | Total EX | Simple | Moderate | Challenging |
|-------|--------|:--------:|:------:|:--------:|:-----------:|
| 0 | Baseline (schema + question + evidence) | **64.00** | 76.00 | 52.63 | 50.00 |
| 1 | Prompt: resolve FKs to names, match exact values; fix markdown-fence bug | **76.00** | 92.00 | 57.89 | 66.67 |
| 2 | Inject 3 sample rows per table into schema context | **74.00** | 84.00 | 68.42 | 50.00 |

Stage 2 regressed overall and was **reverted**. Current system is Stage 1 (76%).

> Caveat carried throughout: the challenging bucket is only 6 questions, so its
> per-stage numbers are noise, not signal. Conclusions are drawn from the simple
> (25) and moderate (19) buckets.

## Stage 0 — Baseline and failure analysis

Baseline of 64% established the starting point. Rather than immediately adding the
"obvious" next feature (self-correction / retry-on-error), I built a failure
inspector to categorize *why* the 18 wrong answers failed:

- **1** query threw an execution error — and that one was a leftover markdown-fence
  formatting bug, not a real SQL problem.
- **17** queries ran successfully but returned the wrong rows (semantic errors).

This was the pivotal finding. **~94% of failures were semantic, not execution
errors**, which meant self-correction (feeding SQL errors back to the model) would
have addressed at most one case. Building it would have been effort spent on a
problem the data showed I didn't have. The failure analysis redirected the whole
plan away from the textbook next step.

Reading the 17 semantic failures individually surfaced two dominant, addressable
patterns:
1. **Foreign keys returned as raw IDs** — e.g. returning `link_to_major` (an integer)
   when the question asked for the major's *name*, which lives in a joined table.
2. **Literal value mismatches** — e.g. filtering `county = 'Orange'` when the stored
   value is `'Orange County'`; or date-format guesses that didn't match stored form.

## Stage 1 — Targeted prompt fixes (64% → 76%)

Two low-cost changes, motivated directly by the failure patterns above:
- Fixed the markdown-fence stripping so fenced output can't break execution
  (guaranteed +1 question).
- Added prompt instructions to (a) resolve foreign keys to human-readable names when
  the question asks for a name/label, and (b) match the full/exact value form as
  stored rather than reformatting values from the question text.

Result: **+12 points overall**, with the gain concentrated in the **simple** bucket
(76 → 92) — exactly where the FK/value failures were concentrated. This directional
match (the bucket predicted to move is the one that moved) is the evidence the
intervention worked *for the reason hypothesized*, not by luck.

Honest note: the change was net positive but **not clean** — re-running the inspector
showed 2 previously-correct questions regressed (aggregation-style questions where the
"match exactly / be literal" steer pushed the model toward a per-row instead of
aggregate reading). Net: ~8 fixed, 2 broken. Prompt steering has side effects.

## Stage 2 — Sample rows in schema context (76% → 74%, reverted)

Hypothesis from the remaining Stage 1 failures: several were caused by the model not
knowing the *actual format/location* of stored data — dates stored as `'201306'` in
one table vs `'2019-08-20 00:00:00'` in another; the meaningful date for some
questions living in a different table than the obvious one. These are information
failures, not reasoning failures, so I injected 3 sample rows per table into the
schema shown to the model.

Result: **overall EX dropped 2 points.** But the per-bucket breakdown told a more
useful story:
- **Moderate improved** 57.89 → 68.42 — the format information helped where format was
  genuinely the bottleneck.
- **Simple regressed** 92 → 84 — on easy questions the extra rows were noise that
  distracted the model.
- Net churn in both directions: some format cases fixed, others broke (in one case the
  model saw a timestamp sample and matched an over-specific literal instead of the
  correct `LIKE` prefix).

**Finding: additional context is not free.** It helps where information is the
bottleneck and hurts where the model was already sufficient and the extra tokens are
distraction. Because the net was negative and the win was already understood, I
reverted rather than keep a more complex, slightly-worse system.

## Current state and remaining failures

System stands at **76% EX** (Stage 1). The remaining ~12 failures fall into:
- **Genuine multi-step logic** — nested aggregations, subtle GROUP BY / DISTINCT
  choices. The hard core; not cheaply fixable by prompt or context.
- **Arguable gold queries** — a few questions are under-specified and the gold made one
  interpretive choice; matching it exactly is partly luck. This sets a practical
  ceiling below 100% on this sample.

## What this log demonstrates (and honest limitations)

The point of this project is not the 76% number — it's the process: establish a
measured baseline, diagnose failures before choosing a fix, intervene, re-measure,
detect regressions per-bucket, and roll back a change that looked promising but
measured worse.

Limitations I'd flag before over-claiming:
- **50-question sample.** Numbers have real margin of error, especially per-bucket.
  A full 500-question run is needed before quoting a headline figure. (Two gold rows
  in the full set have a delimiter typo in the source data; the eval wrapper repairs
  the delimiter in a temp copy without altering query content.)
- **Set-based comparison.** The official evaluator I use compares result sets with set
  equality — it ignores row order and silently de-duplicates, so it can't catch
  duplicate-row bugs. Worth stating when reporting the metric.

## Possible next steps
- Run the full 500 for a headline number with tighter confidence.
- **Targeted** value sampling (distinct values of date/text columns only) instead of
  full sample rows — the Stage 2 moderate gain suggests the format *signal* helps; the
  noise from full rows is what hurt. Untested hypothesis.
- Few-shot retrieval: inject the most similar solved question→SQL pairs as examples
  (retrieval-augmented generation over the training questions).
