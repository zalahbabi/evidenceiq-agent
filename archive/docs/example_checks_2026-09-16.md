# Live example checks — 16 September 2026

## Verdict: partly working, not ready to call fully reliable

The dashboard and regression suite work, but the live verified analyst failed
three of five answerable examples. All five known unsupported requests were
refused correctly. These selected examples are **not** the full benchmark and
must not be used as a project accuracy score.

The agent, prompts, verifier and dashboard were left unchanged during this test.
The run used local **gemma3:4b**, the normal **two verification retries**, and a
four-minute maximum per example. No example timed out. Expected SQL results were
computed separately and were never passed to the model.

## Actual results

| Example | Expected | Actual verified-tier result | Outcome |
|---|---|---|---|
| Total revenue in 2011 | £9,809,614.01, cancellations excluded | Correct amount and caveat; two retries | Pass |
| Customers who bought in 2011 | 4,220 identified customers | Correct count; one retry | Pass |
| Five highest-revenue products in 2011 | All five product/revenue pairs below | Correct SQL rows, but four revenues and a digit in a product name were redacted | Fail |
| November vs October 2011 revenue | Increase of 30.63%; 26 trading days each | “The query could not be made to run.” | Fail |
| Is December 2011 complete? | No; only 8 trading days | “I could not verify the reported figures.” | Fail |
| Profit margin | Refuse: no costs | Refused before tools | Pass |
| December vs November full-month comparison | Refuse: incomplete December | Refused with explanation | Pass |
| Next-quarter revenue forecast | Refuse: outside scope | Refused before tools | Pass |
| Cost of goods sold | Refuse: no cost data | Refused before tools | Pass |
| Promotion generating most revenue | Refuse: no promotion data | Refused before tools | Pass |

**Verified tier: 7/10 passed, comprising 2/5 answerable questions and 5/5 refusals.**

Two additional tier checks:

- **Tier 1, 2011 revenue:** refused without database access. Recorded as a baseline
  observation, not a successful factual answer.
- **Tier 2, 2011 revenue:** returned £9,809,614.01 after repairing an omitted year
  restriction. Its paragraph still included `[call 1]`, which is a presentation issue.

The five model-backed Tier 3 examples took approximately **25–94 seconds** each,
including process startup. The revenue check also included initial font-cache
setup, so these are observed test durations, not a controlled speed comparison.
Refusal cases took about half a second including process startup and needed no
model calls. Each example ran once, with the application's normal retry loop.

### Correct top-five result, read directly from the database

| Product code | Product | Revenue (GBP) |
|---|---|---:|
| 22423 | REGENCY CAKESTAND 3 TIER | 146,461.78 |
| 47566 | PARTY BUNTING | 98,237.49 |
| 85123A | WHITE HANGING HEART T-LIGHT HOLDER | 94,027.39 |
| 85099B | JUMBO BAG RED RETROSPOT | 90,140.66 |
| 23084 | RABBIT NIGHT LIGHT | 66,870.03 |

## Failure details

### 1. A correct product-list attempt was replaced by a worse retry

The second answer attempt contained all five correct revenue claims. The
number scanner treated the **3** inside the database product name
`REGENCY CAKESTAND 3 TIER` as an undeclared quantitative claim. That triggered
another retry. The final attempt bundled all five revenues into one claim with
`calc: sum` and the first product's value, which correctly failed recomputation:

```text
we get 495737.3500, not 146461.78
```

A separate generic “Revenue excludes cancellations” claim reused the first
product's revenue and passed numeric matching. The final paragraph retained that
one number but redacted the other four. Its chart request also omitted `x` and
`y`, so no chart was accepted.

Relevant functions: `number_tokens`, `undeclared_numbers`, `clean_findings`,
`tier3`, and `make_chart` in notebooks 04–06 where defined.

**Fix direction:** recognize exact labels from evidence as labels, preserve the
best checked attempt, and require chart axes when a non-empty chart is requested.
Do not restore a blanket exemption for small numbers.

### 2. Month comparison generated invalid and incorrectly scoped SQL

The final SQL used `dim_month.invoice_month` even though the joined table was
aliased as `dm`. Its repair fixed the alias but retained an invalid `ORDER BY`
on a non-grouped column. The answer could not be produced.

An intermediate attempt was also semantically wrong: it used the same combined
sum for October and November, grouped by product, limited to one product, and
computed a ratio as though it were a percentage change. These values came from
real SQL but did **not** answer the question. This illustrates why numerical
provenance alone cannot prove business correctness.

**Fix direction:** use the small `dim_month` query pattern for comparisons, then
apply the deterministic percentage-change operation to the two monthly totals.
Validate period and population meaning; merely making SQL execute is insufficient.

### 3. Boolean evidence did not fit the required numeric claim

The successful query returned only:

```sql
SELECT is_complete_month
FROM dim_month
WHERE invoice_month = '2011-12'
```

```json
{"is_complete_month": false}
```

Gemma encoded this as a claim with `value: 0`. The numeric verifier correctly
refused to treat a boolean as numeric zero, but there was no separate route to
retain the evidence-backed qualitative conclusion. The fallback warning also
introduced **8** trading days without fetching or declaring that value, so it
was redacted.

**Fix direction:** handle boolean/qualitative evidence explicitly and retrieve
`trading_days` with completeness. Never make `False` support an arbitrary numeric
zero claim.

## Other checks completed

- Fresh installation from `requirements.txt`: **45 automated tests passed**.
- All **25 numerical benchmark ground truths** reproduced from the database.
- Automated dashboard checks: year/market filters, partial-month warning, product
  table, no-sales empty state, page navigation and blank-question validation passed.
- Browser test: submitted the profit-margin question through the actual analyst
  form and confirmed an immediate refusal without numerical claims.
- Rendering check: loaded the genuine returned revenue answer into the dashboard
  session and confirmed that its findings and supported evidence rendered without
  errors. This rendering check did not make a second model call.
- Evaluation page remained empty; selected examples were not passed off as a full
  benchmark scoreboard.

The passing regression suite does not contradict the failed live examples:
its existing fixtures do not cover these complete model-output failure patterns.

## Reproduce and inspect

```bash
python -m pytest tests -q
python tests/run_examples.py --timeout 240
```

- [Complete answers, tool logs and per-call model responses](../../eval/results/example_checks_2026-09-16.json)
- [Live-example runner](../../tests/run_examples.py)

Package versions for this run: DuckDB 1.5.5, pandas 3.0.5, Streamlit 1.64.0,
sqlglot 30.18.0, Ollama Python client 0.6.2. Model: `gemma3:4b`.
