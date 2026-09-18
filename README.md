# EvidenceIQ

A local retail analyst that **checks numerical evidence before showing verified answers**.

EvidenceIQ queries real data, checks source cells and arithmetic, and builds
Tier 3's final wording from supported facts. Its business-rule and completeness
checks cover common mistakes; they do not prove every free-form query
interprets the question correctly.

**Dataset:** Online Retail II — a UK online gift wholesaler, Dec 2009 – Dec 2011,
1,033,030 transaction lines.

ZAKA Capstone 2026 · Machine Learning Track · Group 5 · Partner: SnowHeap

---

## The three tiers

We build the same analyst three times and compare them on the same questions.

| Tier | What it can do | What we expect |
|---|---|---|
| 1 | Nothing but the question — no data access | may invent numbers or refuse |
| 2 | Common KPI query patterns, otherwise model-driven SQL / calculations | real data, unchecked wording |
| 3 | Tier 2 + our checking layer | only evidence-backed claims are shown |

Tier 1 → 2 compares a data-free model with a system that adds data, tools,
query patterns and scope rules. Tier 2 → 3 adds verification, fact recovery and
repair attempts. These are system comparisons; the optional equal-retry control
helps separate extra attempts from verification. Common query patterns are shared by
Tiers 2 and 3 and labelled separately in evaluation; assess model-generated
answers separately when measuring the effect of verification.

Read [how the tiers work](docs/architecture.md) or browse the
[essential documentation](docs/README.md). For concrete comparisons, see
[example questions and results](#example-questions-and-results).

---

## Quick start

```bash
git clone <repo-url>
cd evidenceiq-agent

python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Download `online_retail_II.xlsx` from the
[UCI repository](https://archive.ics.uci.edu/dataset/502/online+retail+ii)
and put it in `data/raw/`. It is 45MB and not in git, so everyone downloads it once.

Build the database:

```bash
python src/build_db.py
```

Takes about a minute — most of it reading the Excel file. It prints the row
count and total revenue and **stops** if either has changed:

```
Rows:    1,033,030
Revenue: GBP 19,003,147.78
```

If you see different numbers, don't carry on. A cleaning rule changed, which
means every ground-truth answer in `eval/benchmark.yaml` may now be wrong.
See `docs/data_dictionary.md`.

For the agent, install Ollama and keep its app or local service running. Then
download the local model:

```bash
ollama pull gemma3:4b
```

---

## Dashboard

```bash
streamlit run app/dashboard.py
```

Open the local address printed in the terminal (normally `http://localhost:8501`).

- **Overview:** revenue, orders, average order value, customers, monthly trends,
  country revenue and top products. Year and market filters apply throughout.
  Complete months are selected by default; turn the switch off to include the
  partial December 2011 period. Monthly data can be downloaded as CSV.
- **Ask the analyst:** select one of the three tiers, ask a question and inspect
  the executed queries. Tier 3 leads with an answer, explains what the results
  mean and suggests useful next steps. Select a suggested question to fill the
  input, then choose Analyze to run it. Detailed figures and supporting queries
  are expandable, and the download contains the same checked answer and
  explanation. Custom model-driven questions require Ollama
  with `gemma3:4b`; recognised query patterns run directly against the database.
- **Evaluation:** reads `eval/results/all_runs.csv`, published by the live example
  runner with `--full --publish`. It shows recorded results and human-review status,
  or an empty state when no results exist.

The overview works without Ollama. It queries DuckDB directly and caches only
small aggregate results, invalidating the cache when the database changes.
All computation is local; the app does not require a hosted API or remote fonts.

The dashboard loads only definitions and constants from notebook 06; it does
not run notebook demos or evaluation loops. The notebooks remain self-contained,
with ordinary dictionaries and a deterministic verifier.

### Checks

```bash
python -m pytest tests -q
python tests/run_examples.py --timeout 180         # selected examples
python tests/run_examples.py --full --timeout 180 --publish  # all 90 runs + dashboard
```

The tests exercise notebook code, database ground truths and dashboard interactions.
Data-dependent checks require the local dataset. See
[validation and limitations](docs/validation.md) for recorded results, remaining
failures and links to the saved evidence. Every live report gets its own CSV,
summary and chart. `--publish` updates the dashboard after a complete run and
archives the previous results.

Additional checks:

```bash
# Different dates and wording; reported separately from the main benchmark
python tests/run_examples.py --benchmark eval/generalization.yaml --full --tiers 2 3 --timeout 180
# Tier 2 execution-retry control, without verification
python tests/run_examples.py --full --tiers 2 --tier2-retries 2 --timeout 180
# Re-evaluate saved outputs with the current scorer, without model calls
python tests/run_examples.py --rescore eval/results/validated_checks_2026-09-16.json
```

---

## The notebooks

Run them in order. Each one builds on the last.

| Notebook | What it does |
|---|---|
| `01_eda.ipynb` | explore the raw file and find the traps |
| `02_build_database.ipynb` | the cleaning, explained step by step |
| `03_baseline_llm.ipynb` | **Tier 1** — the model with no data access |
| `04_tier2_agent.ipynb` | **Tier 2** — the model with SQL and Python tools |
| `05_tier3_verification.ipynb` | **Tier 3** — the checking layer |
| `06_evaluation.ipynb` | all 3 tiers × 30 questions → the scoreboard |

`src/build_db.py` is the script version of notebook 02. The notebook explains
it, the script is what you actually run.

---

## Layout

```
app/          Streamlit retail dashboard, analyst workspace and evaluation view
data/         raw/ and processed/ - both gitignored, both rebuildable
docs/         essential guides: architecture, data, KPIs and validation
archive/      historical documents and original teammate implementation
eval/         benchmark.yaml and results/
notebooks/    01 to 06, in order
src/          build_db.py
```

**Each notebook is self-contained.** It defines every function it needs, so you
do not need to execute earlier notebooks in the same kernel. Complete the data,
package and model setup first, and use `notebooks/` as the kernel's working
directory. Notebooks 05 and 06 repeat the definitions from earlier notebooks.

The trade-off: if you fix a bug in `run_sql` or `verify`, **fix it in every
notebook that defines it**. Notebook 04 defines the tools, 05 adds the checker,
06 has everything.

---

## The database

Opened **read-only**, so a misbehaving agent cannot alter it. There are two
safety nets: we check the SQL before running it, and DuckDB itself refuses writes.

| Table | Rows | Notes |
|---|---|---|
| `sales` | 1,033,030 | one row per line item. Flags: `is_cancellation`, `is_product`, `is_outlier` |
| `dim_month` | 25 | **`trading_days` and `is_complete_month` — read these before any month comparison** |
| `dim_product` | 5,304 | description resolved by mode; the raw ones are inconsistent |
| `dim_customer` | 5,942 | excludes the 22.8% of rows with no customer ID |

Every column and every cleaning rule: **`docs/data_dictionary.md`**
Every KPI formula and its expected value: **`docs/kpi_definitions.md`**

---

## Five things about this data that will bite you

Full detail in `01_eda.ipynb`. The short version:

1. **The two raw sheets overlap by nine days.** Not deduplicating overstates
   December 2010 by 51% (£1,126,445 vs the true £746,724). Handled at build time.
2. **December 2011 is incomplete** — the data stops on the 9th, 8 trading days.
   Never a valid month-over-month comparison. Check `dim_month.is_complete_month`.
3. **Months have different numbers of trading days.** March 2011 had 27, April 21.
   Revenue fell 25%, but per trading day it fell only 3.6%. Say the day count.
4. **The UK is 85% of revenue.** "Which country earns most" is a constant, not a question.
5. **Most "returns" are not returns** — Amazon fees, manual adjustments, and two
   freak orders cancelled minutes after being placed. Naive rate 8%+, real
   product rate 2.36%.

---

## Evaluation

`eval/benchmark.yaml` holds the questions we score against. Each one has the
answer **we worked out ourselves in SQL**, plus the query that produced it.

30 questions: 10 easy, 11 medium, 4 hard, and 5 that the data
**cannot** answer. Those last five matter most — a good system refuses; a bad
one invents a profit margin.

**Before treating the scores as final, every question needs `reviewed_by` filled
in by someone who did not write it.** Re-run its `gt_sql`, confirm the result,
and record the reviewer's name.

`06_evaluation.ipynb` runs everything and writes `eval/results/notebook_run/`.
Use `python tests/run_examples.py --full --publish` to save a versioned report
and update the dashboard.

### Recorded comparison

The **17 September 2026** run used local `gemma3:4b` on all 30 questions in
each tier. A pass requires the requested facts and additional numerical claims
to satisfy the scorer's checks. These are development results: independent
benchmark review is still **0/30**, and human usefulness ratings have not been collected.

| Measure | Tier 1: no data | Tier 2: tools | Tier 3: tools + verification |
|---|---:|---:|---:|
| All answerable questions | 0/25 (0%) | 16/25 (64%) | **20/25 (80%)** |
| Same 14 questions requiring model-written queries in Tiers 2/3 | 0/14 (0%) | 5/14 (35.7%) | **9/14 (64.3%)** |
| Same 11 questions using shared direct queries in Tiers 2/3 | 0/11 (0%) | 11/11 (100%) | 11/11 (100%) |
| Correct refusals | 3/5 | 5/5 | 5/5 |
| Average time per question, including refusals | 8.8 seconds | 11.0 seconds | 23.3 seconds |

Tier 3 passed four more benchmark questions than Tier 2 in this run, at a
higher average response time. The shared direct-query results are not evidence
of better model reasoning. With the same maximum of two retries, the Tier 2
control passed **6/14** model-query cases, versus Tier 3's **9/14** in the main run.
The control retries execution failures only; Tier 3 also retries verification
and completeness failures.
On seven additional questions with different wording or dates, Tier 2 passed
**2/7** and Tier 3 passed **4/7**. These separate development runs show an
improvement, but do not isolate verification from retries or establish performance
on an independent test set.

Sources: [complete saved run](eval/results/validated_checks_2026-09-17.json),
[equal-retry control](eval/results/tier2_retry_control_2026-09-17.json), and
[additional questions](eval/results/generalization_checks_2026-09-17.json).

### Example questions and results

In **Ask the analyst**, paste a question below and run it once in each tier.
The table summarizes actual saved responses, rather than promising identical
answers on every rerun. Tiers were run separately; Tier 3 does not simply receive
and correct the saved Tier 2 answer. **Pass/Fail** refers to the benchmark scorer.

| Question to try | Tier 1 result | Tier 2 result | Tier 3 result |
|---|---|---|---|
| **q17:** How much revenue came from France in 2011? | **Fail:** says it lacks the sales data. | **Fail:** its incorrect country filter is rejected; no answer. | **Pass:** repairs the country filter and retains the supported answer: **£200,027.06**, excluding cancellations. |
| **q24:** What were the top five countries by revenue in 2011? | **Fail:** offers a speculative ranking led by the United States, explicitly without actual data. | **Fail:** retrieves correct totals but changes four of them in its written answer. | **Pass:** returns the correct full ranking and leads with the UK at **£8,244,599.81**. See the detailed comparison below. |
| **q08:** What share of our 2011 revenue came from the UK? | **Fail:** estimates approximately **75%** without supporting data. | **Pass:** reports **84.04611845311553%**. | **Pass:** reports **84.05%**, explains the concentration of revenue in the UK, and suggests follow-up questions. |
| **q11:** Did November 2011 beat October 2011 on revenue, and by what percentage? | **Fail:** cannot give a numerical answer. | **Pass:** lists both monthly totals and day counts, then reports a **30.63%** increase. | **Pass:** leads with the increase and explains that both months had the same number of trading days. |
| **q30:** Which promotion generated the most revenue? | **Fail:** claims it can identify the promotion with the highest sales volume, despite missing promotion data. | **Pass:** refuses because promotion data is unavailable. | **Pass:** gives the same refusal, explains the missing information, and suggests an answerable country-revenue question. |
| **q26:** Which month had the most trading days? | **Fail:** confuses calendar days with recorded trading days. | **Fail:** reports December 2011 with **8 days**. | **Fail:** also reports December 2011 with **8 days**; it does not catch the query's minimum/maximum mistake. |

q08, q17, q24 and q26 use model-written queries in the grounded tiers. q11 uses
a **shared direct query**, so its benefit here is a clearer explanation, not
higher numerical accuracy. q30 uses a **shared refusal rule**; it is not a
Tier 3-only safeguard.

#### Worked example: correct query, incorrect written answer

For **q24**, Tier 2's query results and structured claims contain the right
numbers, but its public answer adds incorrect digits. Tier 3 builds its wording
and detailed figures from checked evidence. Its full ranking matches the saved
benchmark reference, with cancellations excluded:

| Country | Tier 2 written answer | Tier 3 detailed figures / reference value |
|---|---:|---:|
| United Kingdom | £8,244,599.81 | £8,244,599.81 |
| Netherlands | £2,766,611.86 | **£276,661.86** |
| EIRE | £2,731,072.26 | **£273,107.26** |
| Germany | £2,134,722.66 | **£213,472.66** |
| France | £2,000,270.06 | **£200,027.06** |

This illustrates why a successful database query alone is not enough: the
final written answer also needs to agree with its evidence.

#### Worked example: explaining what the numbers mean

For **q11**, both grounded tiers are numerically correct. Tier 3 adds context:

> Yes. Revenue was higher in November 2011 than in October 2011, a change of 30.63%. Cancellations are excluded.

Its **What this means** section explains that the months had equal trading-day
counts, so the difference is not explained by reporting length; the figures do
not establish its cause. It then suggests: **“What was revenue per trading day
in October 2011 and November 2011?”** The supporting totals remain expandable.

**Where verification still fails:** q26's correct answer is **March 2010 and
March 2011, with 27 trading days each**. The model instead queried the minimum.
Tier 3 verified the returned cells but missed that the query answered the
opposite question. Country comparisons and share denominators also have known
failures. See [validation and remaining limitations](docs/validation.md) before
presenting these examples as evidence of reliability.

---

## Team

| Name | Owns |
|---|---|
| Zayed Al Ahbabi | Tier 2 — SQL generation, tools, the tool log |
| Abdelateef M. Adam | Tier 3 — the verification layer and the evaluation |
| Fatima Abdulla Alhosani | The Streamlit app and both dashboards |

Shared: benchmark questions, the report, the demo.

---

## Working agreements

- Branch off `main`, open a PR. No direct pushes to `main`.
- Never commit anything from `data/`.
- Any change to a cleaning rule or a KPI definition updates `docs/` **in the
  same PR**, and the person opening it says so in the description.
- `python src/build_db.py` must still pass before you request review.
- New benchmark questions need `reviewed_by` filled by someone else.
