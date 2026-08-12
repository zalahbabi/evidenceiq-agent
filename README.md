# EvidenceIQ

An AI data analyst that answers business questions **and proves how it got the answer**.

Standard LLMs will produce a confident, well-written number that nobody calculated.
EvidenceIQ executes a real query, generates a chart, and then checks every figure in
its own written answer against the query result. If a claim isn't backed by evidence,
it doesn't ship.

**Dataset:** Online Retail II — a UK online gift wholesaler, Dec 2009 – Dec 2011,
~1.07M transaction lines.

---

## Quick start

```bash
git clone <repo-url>
cd evidenceiq

python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Download `online_retail_II.xlsx` and put it in `data/raw/`.
(It is not in git — it's 45MB. Source: UCI Machine Learning Repository, "Online Retail II".)

Then build the database:

```bash
python src/data/build_db.py
```

Takes about 50 seconds — most of that is reading the Excel file, which happens once.
It prints the row count and total revenue, and **fails loudly**
if either doesn't match the agreed baseline:

```
rows     1,033,030
revenue  GBP 19,003,147.78
```

If you see different numbers, stop — a cleaning rule has changed and everyone's
answers are now inconsistent. Check `docs/data_dictionary.md`.

---

## Layout

```
app/          Streamlit UI and the evidence panel
data/         raw/ (gitignored) and processed/ (gitignored, rebuildable)
docs/         data dictionary, KPI definitions, decisions log
eval/         benchmark.yaml, gold answers, scoring harness, results
notebooks/    01_eda.ipynb, 02_gold_answers.ipynb
src/          data/ agent/ verify/ viz/ baseline/
```

## Querying

The database is opened **read-only**. Writes are rejected by DuckDB itself, so a
misbehaving agent cannot alter the data.

```python
import duckdb
con = duckdb.connect("data/processed/evidenceiq.duckdb", read_only=True)
con.execute("SELECT SUM(revenue) FROM sales WHERE invoice_month = '2011-11'").fetchone()
```

| Table | Rows | Notes |
|---|---|---|
| `sales` | 1,033,030 | One row per line item. Flags: `is_cancellation`, `is_product`, `is_outlier` |
| `dim_month` | 25 | **`is_complete_month` and `trading_days` — read before any month comparison** |
| `dim_product` | 5,304 | Description resolved by mode; they are inconsistent in the raw data |
| `dim_customer` | 5,942 | Excludes the 22.8% of rows with no customer ID |
| `product_sales` | view | Completed sales of real products only |

---

## Five things about this data that will bite you

Full detail in `notebooks/01_eda.ipynb`. The short version:

1. **The two raw sheets overlap by nine days.** Not deduplicating overstates
   December 2010 by 51% (£1,126,445 vs the true £746,724). Handled at build time.
2. **December 2011 is incomplete** — the data stops on the 9th, 8 trading days.
   It is never a valid month-over-month comparison. Check `dim_month.is_complete_month`.
3. **Months have different numbers of trading days.** March 2011 had 27, April 21.
   Revenue "fell 28%", but per trading day it fell 7%. Say the day count.
4. **The UK is 83.5% of revenue.** "Which country earns most" is a constant, not a question.
5. **Most "returns" are not returns** — Amazon fees, manual adjustments, and two freak
   orders cancelled minutes after being placed. Naive rate 8%+, real product rate 2.36%.

---

## Team

| Role | Owner |
|---|---|
| Data & KPI definitions | _tbd_ |
| Agent & tooling | _tbd_ |
| Verification layer | _tbd_ |
| Eval & benchmark | _tbd_ |
| UI & integration | _tbd_ |

Weekly integrator (rotates): _tbd_

## Working agreements

- Branch off `main`, open a PR. No direct pushes to `main`.
- Never commit anything from `data/`.
- Any change to a cleaning rule or KPI definition updates `docs/` **in the same PR**,
  and the person opening it says so in the description.
- `python src/data/build_db.py` must pass before you request review.
