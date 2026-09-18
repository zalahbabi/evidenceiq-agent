# EvidenceIQ

An AI data analyst that answers business questions **and proves how it got the answer**.

Standard LLMs produce a confident, well-written number that nobody calculated.
EvidenceIQ runs a real query, then checks every figure in its own written answer
against what that query returned. If a claim isn't backed by evidence, it doesn't ship.

**Dataset:** Online Retail II — a UK online gift wholesaler, Dec 2009 – Dec 2011,
1,033,030 transaction lines.

ZAKA Capstone 2026 · Machine Learning Track · Group 5 · Partner: SnowHeap

---

## The three tiers

We build the same analyst three times and compare them on the same questions.

| Tier | What it can do | What we expect |
|---|---|---|
| 1 | Nothing but the question — no data access | invents numbers |
| 2 | Writes and runs real SQL / Python | real numbers, unchecked wording |
| 3 | Tier 2 + our checking layer | only evidence-backed claims are shown |

Tier 1 → 2 measures what **using real data** is worth.
Tier 2 → 3 measures what **checking** is worth.
That comparison is the point of the project.

Full explanation: **`docs/tiers_explained.pdf`**

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

For the agent, you also need a local model:

```bash
ollama pull gemma3:4b
pip install ollama
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
| `06_evaluation.ipynb` | all 3 tiers × 15 questions → the scoreboard |

`src/build_db.py` is the script version of notebook 02. The notebook explains
it, the script is what you actually run.

---

## Layout

```
app/          the Streamlit app (week 6)
data/         raw/ and processed/ - both gitignored, both rebuildable
docs/         data dictionary, KPI definitions, the tier explainer
eval/         benchmark.yaml and results/
notebooks/    01 to 06, in order
src/          build_db.py
```

**Each notebook is self-contained.** It defines every function it needs, so you
can open any one of them and run it top to bottom without setting anything up
first. Notebooks 05 and 06 start with a setup cell that repeats the code from
the notebooks before them.

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

15 questions so far, target 30: 5 easy, 5 medium, 2 hard, 3 that the data
**cannot** answer. Those last three matter most — a good system refuses; a bad
one invents a profit margin.

**A question does not count until `reviewed_by` is filled in by someone who
did not write it.** Re-run the `gt_sql`, confirm the number, put your name in.

`06_evaluation.ipynb` runs everything and writes `eval/results/`.

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
