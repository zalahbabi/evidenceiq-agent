# Reliability fixes — 16 September 2026

## What changed

The three previously failing selected examples now return useful answers:

- The top-five product answer keeps all five product/revenue pairs and produces a bar chart. Digits inside exact product names are treated as labels, while unrelated counts still require evidence.
- The October/November comparison fetches both monthly totals, completeness flags and trading-day counts from `dim_month`, then uses the logged percentage-change operation.
- Month completeness is a boolean fact linked to its exact database cell. `False` never serves as evidence for the numerical value zero. The trading-day count is retrieved separately.

These questions use reusable, parameterised query patterns shared by Tiers 2 and 3. Dates and ranking limits come from the whole question; figures come from the live database. Additional unrecognised filters never get silently dropped. Different years, top-three rankings, declining revenue and absent periods are included in regression tests. The excluded-UK ranking also uses an explicit `United Kingdom` exclusion. Cancellation rate uses cancellation invoices divided by completed orders in the same period, with its limitation explained in plain language.

## Verification

- Claims can identify a source call, row and column. A legacy claim without coordinates must have an unambiguous matching cell.
- Copied claims check the associated product/country label and known units, not just the number. Calculation inputs can cite specific cells as well.
- Order-count queries must count distinct completed invoices, not invoice lines. Explicit customer/stock identifiers in successful query filters are treated as labels only when introduced as identifiers in the prose.
- Recognised questions require their checked KPI query. Free-form SQL has narrower date and revenue-population checks; this is **not a universal proof of SQL meaning**. The dashboard makes this limitation visible.
- Internal `[call N]` markers are removed from business prose without exempting unrelated measurements.
- Rounding tolerance is 0.011 absolute or one part per million relative. The former 1% comparison could accept materially wrong revenue amounts.
- Retries retain the strongest verified attempt together with its own evidence log. Token usage includes all attempts.
- A chart must use real columns and a numeric measurement. Missing axes are inferred only when unambiguous. Tier 3 withholds charts containing values that did not survive verification.

## Dashboard

Common analyses identify themselves as direct database analyses. Free-form answers disclose the limits of query interpretation checking. Boolean facts show “Yes”/“No”; supporting queries sit behind expandable evidence panels. Ranked products use horizontal bars with readable labels.

The evaluation page includes answer accuracy, evidence coverage, refusal performance, tool selection, chart structure and token counts when available. It separates direct-query and model-driven runs. An unfinished experiment is labelled with its recorded/expected run count.

## Evaluation changes

Full-result scoring checks every expected measurement and boolean fact with its row labels. A correct first product cannot pass an incomplete five-product answer. Failed calls and timed-out questions remain in the denominator. A refusal flag alone is insufficient: invented public figures make a refusal fail, while genuinely verified context is allowed.

The reference query for the maximum trading-day question now returns only months tied for that maximum. Previously it returned all months, which was unsuitable for complete-result scoring; the ground-truth maximum remains 27.

The notebook and example runner use the same scoring functions. Reference SQL is executed only by evaluation code, after/beside inference; the analyst never loads benchmark questions or answers.

```bash
python -m pytest tests -q
python tests/run_examples.py --timeout 180
python tests/run_examples.py --full --timeout 180
```

The full runner checkpoints `eval/results/all_runs.csv` and saves detailed model replies, tool logs and answers to a timestamped JSON report (or the explicit `--output` path). These are actual calls; no expected results are passed to Gemma.

## Interpreting the results

Direct-query improvements are application improvements, not evidence that Gemma learned to write better SQL. Both grounded tiers share that route. The model-driven subset is the appropriate place to inspect the effect of verification on generated answers. Strict checking can reduce answer completion while blocking unsupported output.

Human usefulness and business interpretation are still review tasks. All benchmark `reviewed_by` values remain unset until another team member checks them. Local Ollama has no API charge; electricity/hardware costs are not estimated from token counts.

## Completed validation
- **81 automated tests passed**, including all 25 numerical ground truths and dashboard interaction checks.
- **All 10 original Tier 3 examples pass**: five answerable cases and five known refusals.
- Completed **90 benchmark cases plus 18 targeted reruns** with local Gemma. The table below uses the latest result for each case; original runs are preserved.
- Browser inspection confirmed the five correct product values, the working chart and the collapsible evidence panels.
- Updated notebook definition/example cells were executed and their genuine outputs saved. The complete experiment was run through the bounded example runner using the actual notebook functions.

| Tier | Complete expected facts | Correct refusals |
|---|---:|---:|
| 1 | 0/25 (0%) | 3/5 |
| 2 | 15/25 (60%) | 5/5 |
| 3 | 16/25 (64%) | 5/5 |

These figures score the expected result cells and labels, not human usefulness. The numerical baseline is deliberately given no database access.

### Routes within the verified tier

| Route | Answerable cases passing |
|---|---:|
| Model-written queries | 5/14 |
| Direct database patterns | 11/11 |

### Remaining model limitations

The identified implementation bugs are fixed, but the small model still does not answer every free-form question reliably. Incorrect or unrepaired SQL is rejected; missing requested facts fail complete-result scoring. These failures have not been hidden from the scoreboard.

| Question | Remaining issue |
|---|---|
| q08 | The model did not produce an acceptable UK-share query. |
| q09 | It returned the correct peak month and revenue but omitted the required trading-day context. |
| q12 | It did not produce the required monthly/per-day comparison queries. |
| q22 | It did not produce an acceptable customer-revenue ranking query. |
| q23 | The order-population guard rejects the model’s incorrect filters/counts; its repair remains invalid. |
| q24 | It did not produce an acceptable country-ranking query. |
| q26 | It did not provide supported facts covering both tied months. |
| q27 | It did not produce an acceptable country-comparison query. |
| q28 | This alternate free-form month-comparison wording did not produce an acceptable query. |

### Saved results

- [Latest result for all 90 cases](../../eval/results/validated_checks_2026-09-16.json)
- [Original complete run](../../eval/results/full_checks_2026-09-16.json)
- [First focused reruns](../../eval/results/final_regression_checks_2026-09-16.json)
- [Final order-population reruns](../../eval/results/order_population_checks_2026-09-16.json)
- [Dashboard data](../../eval/results/all_runs.csv) and [summary](../../eval/results/summary.csv)
