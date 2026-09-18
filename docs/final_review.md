# Final submission review — 17 September 2026

> Historical audit, recorded before the subsequent implementation changes.
> See [current validation](validation.md) for fixes and newly measured results.

## Verdict

**The application is a useful prototype, but the current evidence does not
establish that verification improved answer accuracy.** Present it as an
exploratory comparison of three systems, with a demonstrated evidence-filtering
mechanism and substantial limitations. Do not present 60% → 64% as a verified
accuracy improvement or claim that the system proves every number's meaning.

This review read the implementation and saved answers, installed the declared
dependencies in a temporary environment, reran tests and reference SQL, and
replayed scoring and verification probes. No implementation, benchmark, database
or existing result file was changed. No new live-model benchmark was run.
File locations below use physical line numbers in the repository files,
including the JSON representation of notebooks.

## 1. Routing and the comparison

`question_contract()` in `notebooks/06_evaluation.ipynb:664` matches the whole
normalised question with regular expressions. It extracts dates and ranking
limits, then constructs prewritten SQL. Recognised questions include annual
KPIs, product rankings, the leading country outside the UK, month completeness
and one month-comparison wording.

`tier2()` checks missing-data rules first, then calls the pattern route before
any model planning (`notebooks/06_evaluation.ipynb:924`). `patterned_answer()`
builds the answer, claims and chart deterministically from live results. Tier 3
calls Tier 2 and verifies the result. Neither tier needs Gemma on this route.
I replaced the model function with one that raises an error and successfully
ran all 11 recognised questions through both tiers: **11/11 each, zero model calls**.

The pattern IDs are q01–q07, q10, q11, q20 and q21. They are reusable templates,
not hardcoded result values, but their success does not test model-written SQL.

Tier 1 has no router (`notebooks/06_evaluation.ipynb:1060`). That is reasonable
for a data-free baseline, but Tier 1 → Tier 2 changes data access, prompts,
tool orchestration, query guards, templates and refusal rules together. It is
not an isolated measurement of grounding. Tier 2 → Tier 3 holds the router
constant, but includes verification, sanitisation and extra attempts together.
An equal-retry control would be needed to isolate verification from extra effort.

All five Tier 2/3 refusal cases also use deterministic rules and make **zero
model calls**. They are incorrectly recorded as `model_tools` by the fallback
route label. Tier 1 itself explicitly returns `model_tools` despite having no
tools (`notebooks/06_evaluation.ipynb:1073`). Report these as separate rule-based
refusals and a no-data baseline, respectively.

### Table for the report

These are the existing saved scores, not corrected estimates of model quality.
The baseline subsets use the same question IDs as the grounded-tier routes.

| Question subset | N per tier | Tier 1 | Tier 2 | Tier 3 |
|---|---:|---:|---:|---:|
| Model-written-query subset in Tiers 2/3 | 14 | 0/14 (0%) | 4/14 (28.6%) | 5/14 (35.7%) |
| Direct-query subset in Tiers 2/3 | 11 | 0/11 (0%) | 11/11 (100%) | 11/11 (100%) |
| All answerable, combined system score | 25 | 0/25 (0%) | 15/25 (60%) | 16/25 (64%) |
| Refusal cases; rules in Tiers 2/3 | 5 | 3/5 | 5/5 | 5/5 |

Put the model-written subset first and state the scoring defect beside this
table. The combined score is an application-level result. Eleven templates
provide 73% of Tier 2's passes and 69% of Tier 3's passes. The benchmark was
used during development and targeted fixes, so it is a development benchmark,
not an independent held-out generalisation test.

## 2. The one-question accuracy gain is a scoring artifact

On **q25**, both tiers' findings correctly say February 2011 and GBP 522,545.56.
Both use the same correct SQL. Tier 2's amount claim contains only `522545.56`
as its text, while the month appears in another claim and the findings.

The verifier attaches `row` and `column` coordinates to the Tier 3 amount claim
(`notebooks/06_evaluation.ipynb:1165`). The scorer accepts those coordinates as
label evidence (`notebooks/06_evaluation.ipynb:1523`). Tier 2 is scored with its
unmodified claims: the verified copy used for metrics is discarded
(`tests/run_examples.py:147`; also `notebooks/06_evaluation.ipynb:1613`).
Thus the same correct business answer fails for Tier 2 and passes for Tier 3.

I replayed the saved answers without calling Gemma. Applying the same source
binding to both tiers, while retaining all Tier 2 claims, changes **only q25**:

| Scoring sensitivity on saved answers | Tier 2 | Tier 3 |
|---|---:|---:|
| Existing scorer | 15/25 | 16/25 |
| Consistent source binding | 16/25 | 16/25 |
| Corresponding model-query subset | 5/14 | 5/14 |

This is a diagnostic sensitivity check, not a replacement official score. A
corrected scorer should assess the displayed answer consistently without giving
Tier 2 access to Tier 3's output filtering. Review the rubric before rescoring.

**q09** returns the correct November 2011 / GBP 1,503,866.78 in both tiers.
It fails because reference SQL also selects 26 trading days, although the
question asks only for the highest-revenue month and amount
(`eval/benchmark.yaml:174`). Its query also omits the complete-month restriction;
that is a query-quality issue even though it returns the correct winner here.
Score the requested fact separately from contextual completeness and query rules.
If the rubric accepted the requested facts on q09 as well as fixing q25, the
saved-answer sensitivity would be **17/25 (68%) for both**, or **6/14 (42.9%)**
on the model-query subset. Do not quietly substitute those numbers for the
recorded results.

### Every failing grounded-tier case

| ID | Tiers failing | What the saved answer actually does | Classification |
|---|---|---|---|
| q08 | 2, 3 | Uses product exclusions and `country = 'UK'`; no valid share result | Genuine query failure |
| q09 | 2, 3 | Correct month and revenue; no trading-day fact or complete-month guard | Correct requested facts; stricter context requirement |
| q12 | 2, 3 | Repeats disallowed product filters; no total/per-day comparison | Genuine query failure |
| q22 | 2, 3 | Groups by country instead of customer and uses wrong filters/join form | Genuine query failure |
| q23 | 2, 3 | Wrong population filters; repair counts lines instead of distinct orders | Genuine query failure |
| q24 | 2, 3 | Wrong product filters and aliases; customer join would also omit guests | Genuine query failure |
| q25 | 2 only | Correct month, amount and SQL; source-binding mismatch in scoring | Scoring false negative |
| q26 | 2, 3 | Tier 2 invents 26 days and misses the tie; Tier 3 withholds the answer | Wrong/incomplete, then safely withheld |
| q27 | 2, 3 | Product filters incorrectly narrow country revenue | Genuine query failure |
| q28 | 2, 3 | Product filters retained after attempted year repair | Genuine query failure |

Seven failed IDs have no useful query result. q26 is also a real failure. These
are not mostly formatting failures. Do not globally loosen numerical tolerance
or accept a partial top-five list to improve the score.

The scorer has false positives too (`notebooks/06_evaluation.ipynb:1491`): a
probe swapping Germany/France labels in q27 still passes because column names
such as `germany` and `france` are not checked as labels. A correct revenue plus
an invented extra profit claim also passes. It measures coverage of expected
facts, not correctness of every statement. New result-row scoring also ignores
the benchmark's `also_accept` alternatives. Define required facts, optional
context, alternatives and extra-claim errors explicitly.

## 3. What the evidence metrics actually demonstrate

| Metric on 14 model-query questions | Tier 2 | Tier 3 |
|---|---:|---:|
| Mean per-answer evidence coverage, including empty answers as zero | 25.0% | 39.3% |
| Supported / all claims in retained answer | 4/9 (44.4%) | 6/8 (75.0%) |
| Unsupported claims in retained answer | 5/9 | 2/8 |
| Mean per-answer unsupported rate, empty answers zero | 25.0% | 10.7% |
| Unsupported / displayed claims, rechecked | 5/9 (55.6%) | 0/6 (0%) |
| Undeclared numeric occurrences | 1 | 0 |
| Average recorded seconds | 13.91 | 19.98 |

Across all 30 cases, displayed unsupported claims are **5/33 → 0/30**.
Tier 3 withholds two retained claims, on q25 and q26. No final saved answer
contains a literal `[unverified]` marker; q26 becomes a no-verified-answer
message. Redaction counts across earlier attempts are not retained.

These support a narrow claim: **the filter suppresses claims that its own
evidence checker rejects**. They do not establish a lower independently judged
hallucination rate. The five Tier 2 rejections include a correct number with the
wrong unit field (q09), a correct number with invalid calculation inputs (q19),
a date encoded as a number (q25), and two unsupported claims on q26. The sole
undeclared occurrence on q18 is a leaked `call 1` annotation, not a new business
measurement. All `flagged` arithmetic counts in the final CSV are zero.

The headline 48.3% → 55.0% evidence coverage averages 30 per-answer fractions,
assigning zero to empty answers and correct refusals. It is not the percentage
of all claims supported. The claim-weighted retained fractions are
28/33 (84.8%) and 30/32 (93.8%). The dashboard averages coverage over the 25
answerable questions instead, giving 58% and 66% (`app/dashboard.py:343`).
Choose and label one denominator for each metric.

### A demonstrated limit of verification

Using real SQL for France's 2011 revenue, I gave the verifier a correct claim
`France revenue was £200,027.06` but findings saying
`Germany revenue was £200,027.06`.

Actual output:

```text
Wrong-country prose probe: status= supported undeclared= [] public= Germany revenue was £200,027.06.
```

`clean_findings()` checks the number against supported values, not the country
relationship in each sentence (`notebooks/06_evaluation.ipynb:1391`). A supported
claim does not prove the surrounding prose. Until fixed, prefer text generated
from checked facts and describe the guarantee as numerical provenance and
arithmetic checks, with limited scope checks.

## 4. Tests and database checks actually run

The temporary Python 3.14 environment was installed from `requirements.txt`.
The initial restricted-network installation failed; retrying with approved
network access succeeded. The test command was:

```bash
MPLCONFIGDIR=/tmp/evidenceiq-review-mpl /tmp/evidenceiq-review-env/bin/python -m pytest tests -q -ra
```

Actual output:

```text
........................................................................ [ 88%]
.........                                                                [100%]
81 passed in 35.30s
```

**No failures or skips.** The pytest suite does not require a running Ollama
server or the raw Excel file. It imports the Ollama client, stubs model calls
where needed, and exercises direct patterns. Several tests require the built
database. Some explicitly skip when it is absent; dashboard/direct-query tests
also assume it is present. The failed-build test uses a synthetic DataFrame,
not the raw Excel workbook (`tests/test_notebooks.py:187`).

`tests/run_examples.py` requires Ollama for model-driven cases. A real rebuild
through notebook 02 or `src/build_db.py` requires the raw Excel file. Neither
full rebuilding nor a new live-model evaluation was part of this review.

All **26 nonempty `gt_sql` statements** were rerun read-only: 25 numerical
questions plus q14's contextual query. All 25 scalar `gt_value` entries match
within 0.011; the complete query rows, including both q26 tied months, were
also inspected. The scalar test alone is not independent review of every row
label or business definition (`tests/test_notebooks.py:139`).

```text
Ground truth: 25 / 25 match; SQL statements executed: 26 / 26
sales rows 1033030 PASS
Revenue including cancellations 19003147.78 PASS
2011 revenue excluding cancellations 9809614.01 PASS
November 2011 net revenue 1503866.78 PASS
December 2011 trading days 8 PASS
December 2010 gross revenue 746723.61 PASS
All 25 dim_month totals match sales excluding cancellations: True []
Independent reviewed_by: 0 / 30
```

No evidence of stale numerical ground truth was found. This does not satisfy
the team's second-person sign-off rule (`eval/benchmark.yaml:19`). Leave those
fields unset until an actual teammate reviews them.

## 5. Required metrics: status

| Required metric | Status and correction needed |
|---|---|
| Numerical accuracy | Produced, but q25 bias and inconsistent fact requirements must be fixed. Separate factual correctness from complete-context success. |
| Query execution success | `queries_ok` counts all logged tools, not just SQL, and Tier 3 retains only its selected attempt's log. It is not an all-attempt SQL rate. Retained SQL success on the model subset is 7/23 for Tier 2 and 8/25 for Tier 3; do not interpret this as an all-attempt comparison. |
| Tool selection | Produced, but checks successful tools, so correct tool choice with failed SQL is marked wrong. q14 is a correct deterministic refusal yet expected `run_sql`, producing another mismatch. |
| Claims supported | Produced; distinguish mean per-answer coverage from claim-weighted support and final displayed output. |
| Unsupported-claim rate | Produced for retained internal claims, including Tier 3 claims hidden from users. Add final-output exposure and separately count undeclared prose. |
| Chart correctness | Structural/type checks only. Both tiers score 22/30 (73.3%) largely because 18 cases expect no chart; only 4/12 required charts pass. Human correctness/readability is unmeasured. |
| Response usefulness | No 1–5 rating field, rubric, completed review sheet or aggregate found. |
| Latency | Produced; model-query means are 13.91/19.98 seconds, versus mixed-route means 6.78/9.60. Runner timing includes child startup; notebook timing differs. No repeated controlled timing experiment. |
| Estimated cost | Input/output tokens tracked. No paid API charge for local Ollama. Notebook 03 sets `cost_usd = 0.0`; no consolidated all-tier currency metric or hardware/electricity estimate. Label this zero API fees, not zero total compute cost. |
| Improvement over baseline | Can be calculated from tables, but not a clean causal grounding/verification effect. No reliable accuracy gain remains after the q25 diagnostic correction. |

Metric implementations: `notebooks/06_evaluation.ipynb:1402` and `:1579`.
The full example runner updates `all_runs.csv` but does not regenerate
`summary.csv` or `comparison.png` (`tests/run_examples.py:158`). Notebook 06 does,
using a different summary schema. The current merged results are traceable to
their source reports, but the merging/reaggregation command is not checked in.
Make one documented evaluation/export procedure authoritative.

Notebook 03 also retains its older 1% scalar accuracy scorer and counts refusal
flags without checking fabricated figures (`notebooks/03_baseline_llm.ipynb:291`
and `:320`). Those results must not be mixed with the stricter notebook 06
scoreboard. The shared-copy regression test covers notebooks 04–06, not 03.

## 6. Ranked issues

| Rank | Priority | Issue | Primary location |
|---|---|---|---|
| 1 | P1 | The entire claimed accuracy gain is q25's asymmetric source-binding score | `tests/run_examples.py:147`; `notebooks/06_evaluation.ipynb:1523` |
| 2 | P1 | Router and rule-based refusals confound the claimed grounding ablation | `notebooks/06_evaluation.ipynb:924`; `README.md:26` |
| 3 | P1 | Numeric matching permits incorrect prose; the proof claim is too broad | `notebooks/06_evaluation.ipynb:1391`; `README.md:3` |
| 4 | P1 | Independent benchmark review remains 0/30 | `eval/benchmark.yaml:19` |
| 5 | P1 | Scorer mixes unasked context with required facts, misses some label swaps and extra false claims | `eval/benchmark.yaml:174`; `notebooks/06_evaluation.ipynb:1491` |
| 6 | P2 | Mixed-version, targeted-rerun results are development evidence, without a frozen final run or held-out questions | `docs/validation.md:31`; `eval/results/validated_checks_2026-09-16.json:2` |
| 7 | P2 | Evidence/query/tool/chart labels and denominators overstate what is measured; retry history is lost | `notebooks/06_evaluation.ipynb:1342`, `:1402`, `:1579`; `app/dashboard.py:343` |
| 8 | P2 | SQL failures generate no claims, so the verification retry loop sees no feedback and stops; the one SQL-repair attempt is all they receive | `notebooks/06_evaluation.ipynb:1320`, `:1343` |
| 9 | P2 | Evaluation entry points diverge; the live runner leaves summary/chart exports stale | `notebooks/03_baseline_llm.ipynb:291`; `tests/run_examples.py:158` |
| 10 | P2 | Usefulness ratings and final written/demo deliverables are incomplete or unverified | `notebooks/06_evaluation.ipynb:1764`; `docs/validation.md:78` |

## 7. Deliverable inventory

The original brief's **13-item list is not present in the supplied request or
repository**. Its location was requested during review. The following is a
repository inventory, not an invented mapping to 13 requirements.

| Item | Evidence/status |
|---|---|
| Dataset exploration | Notebook 01 exists with outputs and findings. |
| Cleaned database and reproducible builder | Present; current database passes all checks. |
| Data dictionary and KPI definitions | Present. |
| Three tier implementations | Present, with routing and comparison caveats above. |
| Deterministic verification and tool logs | Present; semantic limitations and incomplete retry-history capture remain. |
| Dashboard | Present; automated interaction tests pass. |
| Benchmark and results | Present; 0/30 independently signed off; scorer needs correction. |
| Technical report | No completed submission report found. Documentation and notebook placeholders are not a technical report. |
| Business recommendations | EDA findings exist; no completed recommendations linking business action, supporting SQL and limitations found. |
| Usefulness evaluation | Missing human rubric, ratings and results. |
| Live demonstration | Example code exists; no demo script, recording, rehearsal record or fallback plan found. Rehearsal outside the repo cannot be assessed. |
| Final presentation | No submission slide deck found. Whether required cannot be confirmed without the brief. |
| Reproducibility package | Setup guide exists; no frozen dependency lock/model digest/hardware manifest or reproducible final merged-score command found. |

## 8. Best use of the remaining time

### Fix before submission

1. Agree a human-reviewed rubric. Fix q25's asymmetry; separate requested facts
   from context; test swapped labels, extra wrong claims and alternative answers.
   Rescore all saved outputs consistently and preserve the old scores.
2. Label routes correctly, publish the model-query table first, and report
   refusals as rules. Replace the causal accuracy-improvement claim with the
   observed evidence-filtering result.
3. Make verified business prose derive from checked facts, or visibly narrow
   the guarantee. Add the wrong-country prose probe as a regression test.
4. Have a teammate review all 30 questions and rate anonymised Tier 2/3 outputs
   for usefulness on a defined 1–5 scale. This review cannot sign for them.
5. Freeze code, prompts, rubric and model identity. Run one complete final
   benchmark; export all summaries from that run. If time allows, add a small
   held-out paraphrase set and use the same initial Tier 2 answers to assess
   verification before retries. Report the retry contribution separately.
6. Finish the technical report, a few evidence-backed business recommendations,
   and a short rehearsed demo with saved-output fallback. Use current results,
   not the notebook's unfilled conclusion template.

### Report as limitations

The small model's SQL failures; narrow English pattern coverage; no general
semantic or causal proof; the small development benchmark; no statistical
evidence of an accuracy gain; timing sensitive to startup/cache/hardware;
unmeasured hardware/electricity cost; and human review of chart meaning.
Do not spend the remaining time adding more benchmark-specific routes merely
to raise the headline score.

### Defensible conclusion

On this development benchmark, deterministic verification reduced the display
of internally unsupported claims, at additional latency. It did not demonstrate
an improvement in business-answer accuracy after accounting for a scoring
asymmetry. Direct query templates were reliable on their recognised questions;
free-form model-written queries remained the main failure point. Independent
human review and a frozen evaluation are still required.
