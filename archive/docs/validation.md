# Current validation

See [the reliability-fix report](reliability_fixes_2026-09-16.md) for the latest changes and results. The entries below are a historical record and include limitations that have since been fixed.

# Dashboard and reliability update

## What changed

The three tiers remain separate. The agent and deterministic verifier still live
in self-contained notebooks, use plain dictionaries and use local `gemma3:4b`.
The Streamlit app is a presentation layer over those notebook definitions.

### Highest-impact defects fixed

1. **Failed claims could still be shown.** `claims_to_show()` previously removed
   only `unsupported`, leaving `flagged` calculations visible. It now admits only
   `supported`. Tier 3 sanitizes its returned findings, claim text and limitations;
   the app exports only the same supported claims it displays. Free-form model
   KPI fields are excluded because they carry no provenance.

   ```python
   return [c for c in answer.get("claims", [])
           if c.get("status") == "supported"]
   ```

2. **The calculator could turn invented inputs into “evidence.”** Inputs now
   need to match earlier successful SQL or validated calculation results. The
   log reader independently checks recorded calculations. Decimal SQL values are
   kept numeric; chart metadata and failed queries cannot substantiate a claim.
   Malformed values, booleans and non-finite numbers fail without crashing.

3. **Undeclared small numbers escaped checking.** The blanket exception for
   integers below 100 is gone. Percentage/count claims, scaled values such as
   `1.2m`, and signed numbers are checked. Redaction uses whole token spans, so
   replacing `12` cannot corrupt `120`. Undeclared prose now triggers retries.
   Explicit calendar context is exempt; number words remain a limitation.

4. **A 2011 query could silently return the all-time total.** A real Gemma run
   omitted the year restriction. Queries against sales/month tables now check for
   a reporting-year filter when the question names a year. The normal SQL repair
   attempt receives a specific error. This catches that case; it is not a general
   semantic SQL validator.

5. **Evaluation was broken and could overstate accuracy.** Notebook 06 called
   undefined baseline helpers with the wrong model-call signature. Notebooks 03
   and 06 now use the same baseline model/schema. Evaluation keeps failed runs
   as errors, counts them as wrong for answerable questions, checkpoints after
   each run, and scores only displayed Tier 3 values. Other tiers are checked on
   a copy to measure evidence without altering their experimental output.

6. **Rebuilding could restore an old KPI bug or destroy a working database.**
   Notebook 02's monthly table now excludes cancellations just like the script.
   Both builders write a replacement and validate it before replacing the old
   file. Product return-rate examples now filter both numerator and denominator
   consistently. No row-cleaning rules, benchmark values or current database
   contents were changed in this update.

### Usability and performance

- Cached database aggregates, year/market filters, complete-month protection,
  monthly/per-trading-day views, country revenue and top products.
- Analyst examples, explicit tier labels, readable failure states, query evidence
  and downloads. Malformed Tier 3 paragraphs fall back to supported claim text.
- An evaluation page that shows no invented scores and displays review status.
- Shorter planning instructions; no unnecessary chart/calculation request for a
  simple total. Known data gaps are refused before contacting the model.
- Read-only SQL, disabled external-file access, a query interrupt timer, guaranteed
  connection cleanup and explicit failure rather than silent row truncation.
- Required numerical claim fields in Ollama's response schema, missing Ollama and
  chart dependencies added, explanatory comments around safeguards.

## Checks actually run

### Automated checks

```text
python -m pytest tests -q
45 passed
```

Covers verifier failure cases, input provenance, citation errors, arithmetic
aliases, prose fallback, year omissions, early refusals, notebook-copy consistency,
failed-rebuild preservation, the evaluation loop and checkpoint output, dashboard
filter/navigation/empty states, and all 25 numerical benchmark SQL results.

### Database builds

The script and the complete database-building notebook were each run against the
original Excel file in isolated temporary destinations. Both produced:

```text
Rows loaded: 1,067,371
Duplicates removed: 34,335
Clean rows: 1,033,030
Revenue including cancellations: GBP 19,003,147.78
November 2011 revenue excluding cancellations: GBP 1,503,866.78
December 2011 trading days: 8
All 25 numerical ground truths: PASS
```

The product-return diagnostic was separately rerun after its denominator fix:

```text
2011 all-item returned-value ratio: 8.35%
2011 product-only returned-value ratio: 2.36%
```

Notebook 02's execution outputs are saved. Setup/tool/checker cells in notebooks
03–06 were rerun and their real outputs saved. The 90-run evaluation loop was
exercised with explicit test fixtures in a temporary directory; these fixtures
were not written to the project's results directory or presented as model scores.

### Local-model checks

Actual Ollama smoke results are saved in `eval/results/smoke_test.json`.
These are operational checks, not the full benchmark or a latency comparison.
Recorded durations were affected by long pauses in this local session and should
not be used as performance results.

| Question | Tier 1 | Tier 2 | Tier 3 |
|---|---|---|---|
| Total revenue in 2011 | Refused without data | GBP 9,809,614.01 after SQL repair | GBP 9,809,614.01; supported |
| Profit margin in 2011 | Refused | Refused before tools | Refused before tools |

The final Tier 3 findings were:

> The total revenue in 2011, excluding cancellations, was 9,809,614.01.

The repaired query was:

```sql
SELECT ROUND(SUM(revenue),2) AS revenue
FROM sales
WHERE NOT is_cancellation AND year(invoice_date) = 2011
```

The overview was visually inspected in the local browser with real charts and
product rows. UI tests checked these displayed revenues:

- 2011, complete months only: **GBP 9,171,806** (rounded display).
- 2011, including partial December: **GBP 9,809,614** (rounded display).
- France, 2011 including partial December: **GBP 200,027** (rounded display).

## Remaining limits and experiment work

- **All 30 `reviewed_by` fields remain pending.** Reproducing a number is not
  independent confirmation that the question, formula and interpretation agree.
- **The full 30-question × three-tier experiment has not been run here.** The
  evaluation dashboard deliberately shows an empty scoreboard until notebook 06
  generates `all_runs.csv`.
- The verifier checks numerical provenance and arithmetic within the agreed 1%
  tolerance. It does not prove that the SQL uses the right population, unit or
  business definition, nor that the prose is a correct causal interpretation.
  It can match a coincidentally equal number. Review query meaning independently.
- Numerical accuracy still means that *one* displayed value matches a target.
  For top-five/list questions this does not establish complete list correctness.
  q14 also permits a contextual explanation with raw totals, while the automated
  refusal metric only recognizes `insufficient_data`; human review remains needed.
- The scope refusal rules are deliberately small and English-language. Unusual
  paraphrases and mixed supported/unsupported requests need further evaluation.
- Arbitrary shares are not assumed to form an exhaustive 100% partition. Explicit
  sum inputs and individual share calculations are checked; complete partition
  reconciliation would need an explicit group/completeness contract.
- `dim_product` and `dim_customer` summary columns have legacy definitions that
  do not universally match KPI revenue/product exclusions. The dashboard queries
  `sales` with explicit filters. Model-generated uses of those summaries still
  need scrutiny.
- Number words, unit/context alignment, full chart correctness, tool-selection
  accuracy, response usefulness and token cost are not fully evaluated.

## Follow-up: broader live examples, 16 September 2026

The [new example checks](example_checks_2026-09-16.md) found three failures that
the original smoke test did not cover: product-list redaction/retry degradation,
month-comparison SQL generation, and boolean month-completeness claims. Of ten
selected Tier 3 examples, seven passed, but only two of five answerable examples
passed. All five known refusal cases passed. The 45 regression tests still pass.
These are selected examples, not a complete benchmark result.
