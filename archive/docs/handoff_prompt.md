# Handoff prompt

Paste everything below the line into another assistant, along with access to
the repo, to get it to review or improve the project.

---

## Who you are

You are helping a 3-student team on an 8-week university capstone (ZAKA, ML
track, industry partner SnowHeap). We have about 5–7 hours each per week. I own
the verification layer. Be blunt about mistakes — I would rather hear a problem
now than at the demo.

## What the project is

**EvidenceIQ** — an AI data analyst that answers business questions over a real
retail database and **proves every number it states**.

A normal LLM answers "what was our revenue in 2011?" with a confident, invented
figure. We make the agent run a real SQL query, then a separate layer checks
every number in the written answer against what that query actually returned.
Anything untraceable is blocked before the user sees it.

The project is **one experiment run three times**:

| Tier | What it can do | Purpose |
|---|---|---|
| 1 | LLM only, no data access | baseline — it fabricates |
| 2 | writes and runs real SQL/Python, draws charts | real numbers, unchecked prose |
| 3 | Tier 2 + our verification layer + retry | only evidence-backed claims shown |

Tier 1→2 measures the value of **grounding**. Tier 2→3 measures the value of
**verification**. That ablation is the contribution. Do not collapse the tiers.

## Hard constraints — do not "improve" these away

- **Notebooks only.** Each notebook is self-contained and defines every function
  it needs. Notebooks 05 and 06 deliberately repeat code from 04. We chose this
  over a shared module on purpose. Do not refactor into a package.
- **Plain dicts, not Pydantic.** No type hints everywhere, no dataclasses.
  Simple code a student would write.
- **The verifier contains no AI.** It is a search over a log plus arithmetic. A
  model checking another model's arithmetic repeats the same mistakes.
- **Local model**: `gemma3:4b` through Ollama. Free, offline, weak. Design for
  a weak model.
- Core agent and verifier logic stays in the notebooks. The authorised Streamlit dashboard lives in `app/`, regression and example runners in `tests/`, and the database builder in `src/build_db.py`.

## Repo layout

```
data/            raw/ (45MB xlsx, gitignored) and processed/evidenceiq.duckdb
docs/            data_dictionary.md · kpi_definitions.md · tiers_explained.pdf
                 reference/  (a teammate's original Tier 2, not imported)
eval/            benchmark.yaml (30 questions) · results/
notebooks/       01_eda · 02_build_database · 03_baseline_llm (tier 1)
                 04_tier2_agent · 05_tier3_verification · 06_evaluation
src/             build_db.py
```

## The dataset, and the traps in it

UCI Online Retail II — UK online gift wholesaler, Dec 2009 to 9 Dec 2011,
**1,033,030 rows** after cleaning, total revenue **GBP 19,003,147.78**
(cancellations included). `src/build_db.py` refuses to write the file if either
number changes.

Five things that have already caused wrong answers:

1. **The two raw sheets overlap by nine days.** Without deduplication December
   2010 reads 1,126,445 instead of the true 746,724 — 51% too high.
2. **December 2011 has 8 trading days, not 26** — the data stops on the 9th. It
   is never a valid month-over-month comparison. `dim_month.is_complete_month`.
3. **Months have different trading-day counts.** March 2011 had 27, April 21.
   Revenue "fell 25%" but only 3.6% per trading day. Both true, opposite
   decisions.
4. **The UK is 85% of revenue.** "Which country earns most" is a constant.
5. **Most "returns" are not returns** — Amazon fees, manual adjustments and two
   freak orders cancelled minutes after being placed. Naive rate 8%+, real
   product rate 2.36%.

Business rules every query must respect (in `docs/kpi_definitions.md`):

```
revenue           WHERE NOT is_cancellation
product questions AND is_product AND NOT is_outlier
products          GROUP BY stock_code, mode(description) for the name
months            use dim_month, it already has trading_days
units sold        AND quantity > 0
```

**Not in the data**: cost, profit, margin, discounts, promotions, marketing
spend, demographics, competitors, web traffic. Questions needing these must be
refused, not estimated.

## How Tier 2 works

Two model calls per step, never one:

1. **Plan** — model lists steps, each using one tool (`run_sql`, `run_python`,
   `make_chart`)
2. **Execute** — for each step we ask for just that one thing and run it; one
   SQL repair attempt with the error fed back
3. **Answer** — model writes the findings *while looking at the real rows*

Deliberate design choices:

- **The model never writes Python.** It picks an operation (`pct_change`,
  `difference`, `ratio`, `share`, `sum`, `mean`) and gives us the numbers; we do
  the arithmetic.
- **SQL is parsed with `sqlglot`**, not keyword-matched. A column called
  `updated_at` contains "update".
- **`fields_used` and `filters_used` are read off the executed SQL**, not asked
  for. The model invents them otherwise.
- **JSON schema passed to Ollama** so the reply shape is enforced.
- If the model returns no claims, we **build them from the tool log**, so no
  answer ever reaches Tier 3 unchecked.

## How Tier 3 works

Every number the model states must be declared as a claim. Then four checks, all
plain Python:

1. **Support** — does the value match its source cell, unit and row label? Numerical tolerance is 0.011 absolute or one part per million relative; boolean facts require exact boolean cells.
2. **Recompute** — re-derive calculated values from their inputs and compare
3. **2b** — if a number isn't in the log but every *input* is and our own
   recalculation agrees, accept it. Without this, a **correct** answer gets
   hidden just because the model skipped a tool call.
4. **Reconcile** — parts must sum to stated totals, shares to ~100%
5. **Undeclared** — scan the findings text for numbers never declared as claims.
   This is the hole the first three cannot see.

Fail → critique sent back, up to 2 retries. Still failing → claim withheld, the
number replaced with `[unverified]` in the prose, user told something was
removed.

## The contract between tiers — do not rename these

```python
log entry  {"n", "tool", "code", "ok", "rows", "error"}
claim      {"text", "value", "unit", "from_call", "calc", "inputs",
            "status", "evidence", "problem"}       # last three set by verifier only
answer     {"question", "findings", "claims", "kpis", "fields_used",
            "filters_used", "chart", "limitations", "insufficient_data",
            "log", "retries", "plan", "seconds", "tier"}
```

`calc` is one of: `none, pct_change, share, sum, diff, difference, ratio, mean`.

## Bugs already found and fixed — please do not reintroduce

- **`dim_month.net_revenue` included cancellations** while the KPI doc excluded
  them. The agent was right and our ground truth was wrong. Rebuilt with
  `FILTER (WHERE NOT is_cancellation)`; `gross_revenue` keeps the old figure.
  Four benchmark answers were recomputed.
- **The verifier crashed** when the model put a list of dicts in `inputs`.
  `as_numbers()` now copes with dicts, strings and junk. The verifier must never
  crash on bad model output — bad output is why it exists.
- **Fabricated numbers stayed in the paragraph** even when the claim was hidden.
  `clean_findings()` redacts them.
- **`gemma3:4b` sets `sufficient_data: false` while still listing steps**, so
  Tier 2 refused every question. We now trust the steps over the flag and refuse
  only when it says no *and* gives no steps. A 12B model does not do this — the
  bug is specific to small models.
- **Ambiguous questions cannot be auto-scored.** "By how much?" can be answered
  in pounds or percent. Questions now ask for a specific number, and
  `also_accept` holds legitimate alternatives.

## The benchmark

`eval/benchmark.yaml` — 30 questions: 10 easy, 11 medium, 4 hard, **5 that the
data cannot answer**. Every answerable question has a `gt_value` we computed
ourselves and a `gt_sql` that reproduces it. All 25 numeric ground truths are
verified against the database.

**Rule: if you change a cleaning rule, re-run every `gt_sql` and update the
values.** Ground truth going stale silently is the worst failure mode here.

`reviewed_by` is null on all 30 — a second person still has to confirm each one.

## Where we are

- The Streamlit dashboard is implemented in `app/dashboard.py` and authorised by the user.
- Read `docs/reliability_fixes_2026-09-16.md` and `eval/results/` for current validation and scoreboard status. Common query patterns are explicitly separated from model-driven runs.
- Historical metric wishlist (see the latest report for what is now implemented): tool-selection accuracy, chart correctness,
  response usefulness, token cost.

## What I want from you

Read the repo, then:

1. Tell me what is **wrong or fragile**, worst first. Be specific and show me
   the code.
2. Point out anywhere our **ground truth could be wrong** — that invalidates
   everything downstream.
3. Suggest improvements that fit a **weak local model** and our remaining time.
   Do not propose fine-tuning, multi-agent frameworks or a bigger model.
4. Before changing anything, say what you are going to change and why.

When you do change code:

- keep the plain-dict notebook style, and update **every** notebook that has a
  copy of the function
- re-run the affected cells and show me the real output, not what you expect
- if you touch the database or a cleaning rule, re-verify all 25 ground truths
