# Validation and known limitations

Latest validation: **17 September 2026**, local `gemma3:4b`.
The main results below come from one complete run on unchanged code and rubric,
with all failed answers retained. They are development results, pending human review.

## What changed

- Failed queries, missing requested facts and generation errors receive bounded repair feedback; all attempts remain in the audit.
- SQL guards check dates, populations, distinct orders, country scope and sales/month joins.
- Tier 3 recovers omitted facts from successful scoped results and builds its wording from checked evidence.
- Answers now include a direct conclusion, an explanation and useful next steps. Detailed figures and queries are expandable.
- Scoring treats tiers consistently, separates requested facts from optional context, and checks the extra displayed explanations.
- Results distinguish model-written queries, shared direct queries and refusal rules. Exports are versioned; publishing archives previous dashboard files.

## Automated and example checks

**285 tests passed, with no failures or skips.** The suite covers the 25 numerical
benchmark ground truths, shared notebook consistency, query safeguards, retries,
verification, scoring, narrative examples and dashboard interactions.
These tests use the built database and mocked model responses where needed; they
do not require a running Ollama service. Rebuilding the database requires the raw Excel file.
The cleaning rules and database were not changed in this implementation.

After the main model run, a cancellation-count wording edge case was corrected:
cancellation invoices are no longer described as completed orders. All 30 saved
Tier 3 answers were rendered before and after that fix; findings, explanations,
next steps and claims were unchanged. The final tests include 24 checks for the
new population-aware labels. This was a wording regression check, not another
model run. See the [recorded check and source hashes](../eval/results/cancellation_wording_check_2026-09-17.json).

Five real-data examples were refreshed in notebooks 05 and 06. Browser checks
confirmed the comparison explanation, chart, expandable evidence and a follow-up
button that fills the question without starting another analysis.

## Main benchmark

| Matched question subset | Tier 1 | Tier 2 | Tier 3 |
|---|---:|---:|---:|
| Model-written-query subset | 0/14 (0.0%) | 5/14 (35.7%) | 9/14 (64.3%) |
| Shared direct-query subset | 0/11 (0.0%) | 11/11 (100.0%) | 11/11 (100.0%) |
| All answerable questions | 0/25 (0.0%) | 16/25 (64.0%) | 20/25 (80.0%) |
| Refusal cases; rules in Tiers 2/3 | 3/5 | 5/5 | 5/5 |

The previous saved Tier 3 answers score **17/25 (68.0%)** under this
same rubric; the updated system scores **20/25 (80.0%)**.
The old published 60%/64% comparison used a different scorer and must not be
used as the before/after comparison. Shared prompts, safeguards, fact recovery,
wording and retries changed together; the gain is a system improvement,
not an isolated causal estimate of verification.

### Retry control and different questions

| Check | Tier 2 | Tier 3 |
|---|---:|---:|
| Main model-written subset | 5/14 (35.7%) | 9/14 (64.3%) |
| Tier 2 with up to two execution retries, same subset | 6/14 (42.9%) | — |
| Different wording/dates and dashboard follow-up | 2/7 (28.6%) | 4/7 (57.1%) |

The control has the same retry allowance as Tier 3, but retries execution
failures only; it does not verify or rewrite the final answer. These are
separate runs, not a replay of identical first attempts. The extra questions
are a small development check, not an independently held-out test set.

The suggested daily-revenue follow-up (g07) passed for both tiers. Tier 3's
remaining failures were a France share with an incorrectly filtered denominator
(g01), an incomplete month comparison (g03), and a minimum returned for a
maximum question (g04). These expose limits that the main score alone would hide.

### Evidence and effort

| Tier | Displayed claims supported by checker | Analysis SQL calls succeeded | Average seconds per case |
|---|---:|---:|---:|
| 1 | 0/39 (0.0%) | 0/0 | 8.8 |
| 2 | 39/60 (65.0%) | 22/30 | 11.0 |
| 3 | 171/171 (100.0%) | 33/61 | 23.3 |

The evidence percentages are diagnostics from the deterministic checker, not
independent proof of query meaning. SQL counts include saved retry attempts.
Chart checks cover required chart types, source cells and axes; human review is
still needed for chart meaning. Hosted API fees are USD 0; hardware and electricity
costs are unmeasured. Latency depends on local hardware, caching and generation errors.

## Remaining limitations

**Independent benchmark sign-off remains 0/30, and human usefulness ratings are
not collected.** A teammate must review the reference queries and rate the answers
before treating the project evaluation as submission-ready.

The model can still write incorrect or incomplete SQL. Verification checks a
bounded set of business rules, evidence cells and arithmetic; it does not prove
every query interprets the question correctly. Explanations do not establish
causes or profitability. Different wording can still change model performance.

Tier 3 cases that did not fully pass this run:

| Case | Remaining problem and visible behavior |
|---|---|
| q12 | March/April: correct revenue difference, but missing the percentage and per-trading-day comparison. The answer is visibly marked partial; invalid retry joins were blocked. |
| q25 | Lowest complete month: query and scope failures leave no verified figures. The answer says it could not verify the result. |
| q26 | Most trading days: the model used MIN instead of MAX. It displays December 2011 with 8 days, without a partial warning. This is an uncaught query-meaning error. |
| q27 | Germany/France: conditional country totals were grouped into separate rows, comparing each country against zero. Incorrect comparison details remain visible despite matching returned cells. |
| q28 | October/September: missing columns, invalid joins and population-filter errors prevent successful execution. No figures are displayed. |

Two failures (q26 and q27) still expose incorrect answers from successful SQL.
The other three return partial or unavailable answers. Cell support must not
be presented as proof that the question was answered correctly.

See the saved report for complete findings, omitted details and every repair
attempt. Failed cases were not replaced with hand-selected reruns.

## Reproduce and inspect

```bash
python -m pytest tests -q
python tests/run_examples.py --full --timeout 180 --publish
python tests/run_examples.py --full --tiers 2 --tier2-retries 2 --timeout 180
python tests/run_examples.py --benchmark eval/generalization.yaml --full --tiers 2 3 --timeout 180
```

Live runs require Ollama with `gemma3:4b`. Each JSON report records code/rubric
hashes, model digest, package versions and environment; its sibling directory
contains CSV results, a summary and chart. Notebook 06 writes its separate
exports to `eval/results/notebook_run/`. Only `--publish` updates the dashboard.

- [Final 90-case report](../eval/results/validated_checks_2026-09-17.json)
- [Previous answers with the same rubric](../eval/results/previous_answers_final_rubric_2026-09-17.json)
- [Equal-retry control](../eval/results/tier2_retry_control_2026-09-17.json)
- [Different questions and follow-up check](../eval/results/generalization_checks_2026-09-17.json)
- [Dashboard results](../eval/results/all_runs.csv) and [summary](../eval/results/summary.csv)
- [Earlier audit](final_review.md) — historical findings before these fixes
