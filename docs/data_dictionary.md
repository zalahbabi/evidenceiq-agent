# Data Dictionary

What every column means, and every rule we applied to get there.

**Source:** UCI Machine Learning Repository, Online Retail II (dataset 502).
A UK online gift wholesaler, 1 December 2009 to 9 December 2011.

**Built by:** `python src/build_db.py` (explained in `notebooks/02_build_database.ipynb`)
**Output:** `data/processed/evidenceiq.duckdb`

This file and `docs/kpi_definitions.md` together define what a correct answer
is. Every ground-truth answer in `eval/benchmark.yaml` was computed against a
database built with exactly these rules. **If you change a rule here, the
benchmark answers may become wrong.**

---

## The database at a glance

| Table | Rows | What it is |
|---|---|---|
| `sales` | 1,033,030 | one row per invoice line. The main table. |
| `dim_month` | 25 | one row per month. Use this for anything about months. |
| `dim_product` | 5,304 | one row per stock code |
| `dim_customer` | 5,942 | one row per identified customer |

| | |
|---|---|
| Date range | 2009-12-01 to 2011-12-09 |
| Invoices | 53,622 |
| Stock codes | 5,304 |
| Countries | 43 (the UK is 85% of revenue) |
| Total revenue | GBP 19,003,147.78 (cancellations included) |

---

## Table: `sales`

### Columns from the raw file

| Column | Type | Meaning | Notes |
|---|---|---|---|
| `invoice_no` | VARCHAR | Order number | A leading `C` means a cancellation |
| `stock_code` | VARCHAR | Product code | Some codes are not products — see below |
| `description` | VARCHAR | Product name | 0.41% are missing. The same code can have several different descriptions, so group by `stock_code` and use `mode(description)` for the name |
| `quantity` | BIGINT | Units on this line | Negative on returns. Range −80,995 to 80,995 |
| `invoice_ts` | TIMESTAMP | When the order was placed | |
| `unit_price` | DOUBLE | Price per unit, GBP | 0.58% are zero. Max is 38,970 |
| `customer_id` | DOUBLE | Customer number | NULL for guest checkout — 22.76% of rows |
| `country` | VARCHAR | Customer country | 43 values |

### Columns we added

| Column | Type | How it is worked out | Why |
|---|---|---|---|
| `revenue` | DOUBLE | `quantity * unit_price` | Used by nearly every question |
| `is_cancellation` | BOOLEAN | `invoice_no` starts with `C` | So nobody has to write `LIKE 'C%'` every time |
| `is_product` | BOOLEAN | `stock_code` not in the non-product list | Without it, "Manual" is the best-selling item ever |
| `is_outlier` | BOOLEAN | `invoice_no` in the four odd invoices | Two huge orders cancelled minutes later |
| `invoice_date` | DATE | date part of `invoice_ts` | |
| `invoice_month` | VARCHAR | `YYYY-MM` | Sorts correctly as text |

---

## Cleaning rules

Applied in this order by `src/build_db.py`.

### 1. Remove exact duplicate rows

The two sheets in the Excel file **overlap for the first nine days of
December 2010**. If you do not deduplicate, December 2010 reads
GBP 1,126,445 instead of the true GBP 746,724 — **51% too high**.

This is the single most important cleaning step. Anything comparing months
around that date is wrong without it.

### 2. Remove bad-debt adjustments

A handful of invoices start with `A`. They are accounting write-offs, not
sales, and they are large enough to distort totals. Deleted, not flagged.

### 3. Rename the columns

`Customer ID` becomes `customer_id`, and so on. The raw names have spaces and
capitals, which need quoting in SQL every time — the agent gets that wrong.

### 4. Flag rather than delete

Returns, non-products and the outlier orders are all **kept and flagged**. If
we deleted them, "what is our return rate?" would become unanswerable.

---

## Things that are flagged, not deleted

### Non-product stock codes (0.54% of rows)

Postage, fees, manual adjustments and test rows. `is_product` is FALSE for:

`DOT`, `POST`, `C2`, `M`, `m`, `S`, `B`, `BANK CHARGES`, `AMAZONFEE`,
`ADJUST`, `ADJUST2`, `PADS`, `CRUK`, `TEST001`, `TEST002`, `DCGSSGIRL`,
`DCGSSBOY`

The ones that actually matter by size:

| Code | Rows | Revenue | What it is |
|---|---|---|---|
| `DOT` | 1,425 | 309,844 | DOTCOM postage |
| `POST` | 2,086 | 110,430 | postage |
| `M` | 1,387 | −83,326 | manual adjustment |
| `AMAZONFEE` | 36 | −221,520 | Amazon fees |
| `BANK CHARGES` | 100 | −35,482 | bank charges |

Leave `is_product` out of a product ranking and `M` ("Manual") comes top.

### The two outlier orders

| Invoice | Stock code | Quantity | Revenue | Time |
|---|---|---|---|---|
| `541431` | 23166 | 74,215 | 77,183.60 | 2011-01-18 10:01 |
| `C541433` | 23166 | −74,215 | −77,183.60 | 2011-01-18 10:17 |
| `581483` | 23843 | 80,995 | 168,469.60 | 2011-12-09 09:15 |
| `C581484` | 23843 | −80,995 | −168,469.60 | 2011-12-09 09:27 |

Two enormous orders placed and cancelled **16 and 12 minutes later**. They net
to zero overall, but any query that removes cancellations keeps the order and
drops the cancellation, which leaves a fake 168,469 in the totals. That is why
`is_outlier` exists as a separate flag.

### Guest checkouts (22.76% of rows)

No `customer_id`. Kept, because the revenue is real. Excluded from anything
counting customers — say so when answering, because "how many customers do we
have" means "identified customers".

---

## Data quality profile

Percentages of all 1,033,030 rows.

| Measure | % |
|---|---|
| No customer ID (guest checkout) | 22.76 |
| Negative quantity | 2.18 |
| Cancellation invoice (`C` prefix) | 1.85 |
| Not a product | 0.54 |
| Zero or negative unit price | 0.58 |
| Missing description | 0.41 |

Rows by flag:

| Cancellation | Product | Outlier | Rows | Revenue |
|---|---|---|---|---|
| no | yes | no | 1,009,358 | 19,399,815.50 |
| yes | yes | no | 18,081 | −484,119.85 |
| no | no | no | 4,566 | 819,729.69 |
| yes | no | no | 1,021 | −732,277.56 |
| no | yes | yes | 2 | 245,653.20 |
| yes | yes | yes | 2 | −245,653.20 |

---

## Table: `dim_month`

One row per month. **Use this for any question about months** rather than
grouping `sales` yourself — it already carries the traps.

| Column | Meaning |
|---|---|
| `invoice_month` | `YYYY-MM` |
| `trading_days` | distinct days with at least one order |
| `last_day` | last date seen in that month |
| `net_revenue` | revenue **excluding** cancellations — matches KPI 1 |
| `gross_revenue` | revenue **including** cancellations |
| `is_complete_month` | FALSE for the final month in the data |

> **Changed 2026-09-04.** `net_revenue` used to be a plain `SUM(revenue)`, which
> included cancellations and therefore contradicted KPI 1. The agent would query
> `WHERE NOT is_cancellation` and get a different answer to our own ground truth,
> and the verifier could not tell which was right — both numbers came from real
> queries. `net_revenue` now excludes cancellations and `gross_revenue` keeps the
> old figure. Benchmark questions q09, q11, q12 and q14 were recomputed.

### Why this table exists

**December 2011 has 8 trading days, not 26.** The data stops on the 9th. It is
never a valid month-over-month comparison. `is_complete_month` is FALSE for it.

**Months have different trading-day counts.** March 2011 had 27 and April had
21. Revenue fell 25.03% between them (716,215 to 536,969), but per trading day
it fell only 3.61% (26,526 to 25,570). Both numbers are true and they support
opposite decisions, so any month comparison must state the day count.

**December trails off anyway.** The shop stops trading around the 23rd, so a
November-to-December drop is normal, not a problem.

---

## Table: `dim_product`

| Column | Meaning |
|---|---|
| `stock_code` | product code |
| `description` | `mode(description)` — the most common name for that code |
| `units_sold` | `SUM(quantity)` where quantity > 0 |
| `gross_revenue` | `SUM(revenue)` where quantity > 0 |

Grouping by description instead of stock code splits one product across
several rows, because the raw descriptions are inconsistent.

---

## Table: `dim_customer`

| Column | Meaning |
|---|---|
| `customer_id` | customer number |
| `country` | most common country for that customer |
| `first_order`, `last_order` | date range |
| `orders` | distinct non-cancelled invoices |
| `net_revenue` | total revenue |

Guest checkouts are excluded — we cannot tell those orders apart.

---

## What is NOT in this data

Questions needing any of these **cannot be answered** and the system must
refuse rather than estimate:

- cost of goods, profit, margin
- discounts, promotions, marketing spend
- customer age, gender or any demographic
- competitor prices
- website traffic, conversion rates
- stock or inventory levels
- delivery times or shipping status (beyond the postage line items)

---

## Quick sanity checks

If you rebuild the database, these must hold. `src/build_db.py` checks the
first two automatically and refuses to write the file if they fail.

| Check | Expected |
|---|---|
| Rows in `sales` | 1,033,030 |
| Total revenue (cancellations included) | 19,003,147.78 |
| Revenue excluding cancellations | 20,465,198.39 |
| November 2011 net revenue (`dim_month`) | 1,503,866.78 |
| November 2011 gross revenue (with cancellations) | 1,456,145.80 |
| December 2011 trading days | 8 |
| December 2010 gross revenue (the overlap test) | 746,723.61 |

The last one is the important one. If December 2010 comes out near 1,126,445,
the deduplication step did not run.
