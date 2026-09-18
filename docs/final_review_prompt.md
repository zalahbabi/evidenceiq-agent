# Final review prompt

Paste everything below the line into another assistant, with access to the repo.
Pair it with `docs/architecture.md`, `docs/data_dictionary.md` and
`docs/validation.md`.

---

You are doing a **final review** of a university capstone before submission.
Three students, 8 weeks, ~5–7 hours each per week, local `gemma3:4b` via Ollama.
Be blunt. I would rather hear a problem now than at the demo.

## What the project claims

**EvidenceIQ** answers business questions over a retail DuckDB database and
proves every number. It is one experiment run three times:

- **Tier 1** — LLM only, no data access (baseline, fabricates)
- **Tier 2** — writes and runs real SQL/Python (real numbers, unchecked prose)
- **Tier 3** — Tier 2 plus a deterministic verification layer and retry

Tier 1→2 is meant to measure grounding. Tier 2→3 is meant to measure
verification. That ablation is the whole contribution.

## What the results currently say

From `eval/results/summary.csv`, 30 benchmark questions, `gemma3:4b`:

| Tier | Accuracy (25 answerable) | Correct refusals (5) | Evidence coverage | Avg seconds |
|---|---|---|---|---|
| 1 | 0% | 3/5 | 0% | 11.0 |
| 2 | 60% | 5/5 | 48% | 6.8 |
| 3 | 64% | 5/5 | 55% | 9.6 |

---

# Priority 1 — things that could invalidate the project

## 1.1 The routing layer may be doing the work, not the agent

`all_runs.csv` has a `route` column with two values. Split by it:

| Tier | route | n | accuracy |
|---|---|---|---|
| 2 | `query_pattern` | 11 | **100%** |
| 2 | `model_tools` | 14 | **29%** |
| 3 | `query_pattern` | 11 | **100%** |
| 3 | `model_tools` | 14 | **36%** |

**Find out exactly what `query_pattern` does.** If it matches a question to a
pre-written SQL template and skips the model, then 11 of 25 answerable questions
never test the agent at all, and the headline 60%/64% is mostly measuring the
router.

Tell me:

- where the routing decision is made, and what triggers a `query_pattern` route
- whether the model is involved at all on that path
- whether the same routing applies to Tier 1 (the table says no — is that fair?)
- **is the comparison still honest?** If Tier 1 has no router and Tiers 2 and 3
  do, then part of the Tier 1→2 gap is the router, not grounding
- how the report should present this. My instinct is that every results table
  must be split by route, and the model-written path is the real headline

This is the first thing to look at. Everything else is secondary.

## 1.2 Tier 2 and Tier 3 differ on exactly one question

Across 25 answerable questions, Tier 2 and Tier 3 disagree only on **q25**.
Accuracy 60% → 64% is a single question.

The project's claim is that verification helps. Check whether it is being
measured with the right metric:

- accuracy barely moves, because verification does not make a wrong query right
- **evidence coverage** (48% → 55%) and **unsupported-claim rate** are where
  verification should show up, plus claims withheld and numbers redacted

Look at `all_runs.csv` columns `unsupported`, `undeclared`, `unsupported_rate`
and `supported`, and tell me which comparison actually demonstrates the thesis.
If the honest answer is "verification barely changed the outcome on this
benchmark", say so — a real negative result reported clearly is worth more than
a number that looks good and does not hold up.

## 1.3 Ground truth is unreviewed

All 30 `reviewed_by` fields in `eval/benchmark.yaml` are null. The team's own
rule is that a question does not count until a second person re-runs its
`gt_sql` and confirms.

Re-run every `gt_sql` against the database and tell me whether all 25 numeric
ground truths still match. If any cleaning rule changed after they were
computed, they are stale and every downstream number is wrong.

---

# Priority 2 — correctness and completeness

## 2.1 Verify the claims made in docs/validation.md

It states 81 automated tests pass and all 25 ground truths hold. Run
`python -m pytest tests -q` and confirm. Report anything that fails or is
skipped, and say which tests need Ollama or the raw Excel file.

## 2.2 Check the scoring is not unfairly harsh

`validation.md` says scoring "checks every expected result cell and its labels"
and that incomplete lists count as failures. Look at the failing
`model_tools` cases in `eval/results/*checks*.json`. For each, decide: was the
answer **wrong**, or **right but formatted differently**?

There is a known example — q09 was marked FAIL with the note "the visible answer
does not contain every expected measurement with its correct label", while the
answer itself said November 2011, 1,503,866.78, which is correct.

If a meaningful share of failures are formatting, the accuracy figures understate
the system and the scorer needs loosening — or the harshness needs stating
plainly in the report.

## 2.3 Metrics the brief requires

Required: numerical accuracy, query execution success, tool selection, % claims
supported by evidence, unsupported-claim rate, chart correctness, **response
usefulness**, latency, estimated cost, improvement over baseline.

Check which are actually produced. `response usefulness` is a human 1–5 rating
and I do not think it exists. Cost is tracked as tokens — confirm it is
converted to money somewhere, or say it is free because the model is local.

## 2.4 The data traps

Confirm these still hold in the built database:

| Check | Expected |
|---|---|
| `sales` rows | 1,033,030 |
| Total revenue incl. cancellations | 19,003,147.78 |
| Revenue 2011 excl. cancellations | 9,809,614.01 |
| November 2011 `net_revenue` | 1,503,866.78 |
| December 2011 trading days | 8 |
| December 2010 gross revenue | 746,723.61 |

The last one is the deduplication test — the two raw sheets overlap by nine
days, and without dedup December 2010 reads about 1,126,445.

Also confirm `dim_month.net_revenue` excludes cancellations and matches
`WHERE NOT is_cancellation`. These disagreed once and it made our own ground
truth wrong while the agent was right.

---

# Priority 3 — what is left to deliver

Against the brief's 13 required deliverables, check what exists and what does
not. I believe still missing or unfinished:

- **Technical report** — not written
- **Business recommendations** — real findings from the retail data, evidence-backed
- **Live demonstration** — not rehearsed
- **Benchmark sign-off** — 0 of 30 reviewed

Tell me what else is missing that I have not listed.

---

# How to work

- Read before changing. Say what you intend to change and why, first.
- The notebooks are **deliberately self-contained** — each defines its own
  functions and 05/06 repeat code from 04. Do not refactor into a shared module.
  If you fix a function, fix **every** copy.
- Plain dicts, not Pydantic. Simple code.
- **The verifier contains no AI** — it is a search over a log plus arithmetic.
  Keep it that way.
- If you touch a cleaning rule or the database, re-run all 25 `gt_sql` and
  report the results.
- Show me real command output, not what you expect to happen.
- Design for a weak local model. Do not propose fine-tuning, a bigger model, or
  a multi-agent framework.

## What I want back

1. A verdict on 1.1 — is the tier comparison honest as presented?
2. The results table you think belongs in the report, split however the data
   demands.
3. A ranked list of everything wrong, worst first, with file and line.
4. What to fix in the time left, and what to write up as a limitation instead.
