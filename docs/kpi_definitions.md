# KPI Definitions

These are the 10 KPIs for EvidenceIQ.

All formulas run against the sales table in data/processed/evidenceiq.duckdb,
which is built by notebooks/02_build_database.ipynb.

If a number anywhere disagrees with this file, this file is right.

## Column names

The column names changed when we built the database, so use these:

| Spreadsheet | Database |
|---|---|
| InvoiceNo | invoice_no |
| StockCode | stock_code |
| Quantity | quantity |
| UnitPrice | unit_price |
| CustomerID | customer_id |
| Country | country |

There is also a column called is_cancellation. It is true for invoices starting
with C. Use it instead of writing LIKE 'C%' every time.

## The 10 KPIs

| # | KPI | Definition | Formula |
|---|---|---|---|
| 1 | Revenue | Sales value after removing cancellations | SUM(revenue) WHERE NOT is_cancellation |
| 2 | Units Sold | Total item quantity sold | SUM(quantity) WHERE NOT is_cancellation AND quantity > 0 |
| 3 | Orders | Count of distinct completed transactions | COUNT(DISTINCT invoice_no) WHERE NOT is_cancellation |
| 4 | Average Order Value | Average revenue per order | Revenue / Orders |
| 5 | Cancellation Rate | Cancellations compared to completed orders | COUNT(DISTINCT invoice_no) WHERE is_cancellation, divided by Orders |
| 6 | Active Customers | Customers with at least 1 completed order | COUNT(DISTINCT customer_id) WHERE NOT is_cancellation AND customer_id IS NOT NULL |
| 7 | Revenue by Country | Revenue broken down geographically | SUM(revenue) WHERE NOT is_cancellation GROUP BY country |
| 8 | Revenue by Product | Revenue broken down by item | SUM(revenue) WHERE NOT is_cancellation AND is_product AND NOT is_outlier GROUP BY stock_code |
| 9 | Units per Order (optional) | Average basket size | Units Sold / Orders |
| 10 | Repeat Customer Rate (optional) | Share of customers with more than 1 order | customers with more than 1 order / Active Customers |

## Numbers to check against

If you run these over the whole dataset you should get:

| KPI | Answer |
|---|---|
| Revenue | 20,465,198.39 |
| Units Sold | 11,455,906 |
| Orders | 45,330 |
| Average Order Value | 451.47 |
| Cancellation Rate | 18.29% |
| Active Customers | 5,881 |
| Units per Order | 252.7 |
| Repeat Customer Rate | 72.4% |

If you get something different, your query is wrong somewhere.

## Three fixes we had to make

We tested the first version of these formulas against the database. Three of them
gave the wrong answer, so they were changed. Everything else is the same.

### KPI 2, Units Sold: we added quantity > 0

There are 3,393 rows with a negative quantity that are not cancellations. They are
damages and write-offs. Their price is 0 so they do not change revenue, but adding
up quantity subtracts them by mistake.

Without the fix, Units Sold comes out as 10,886,592 instead of 11,455,906.

### KPI 5, Cancellation Rate: we changed what we divide by

The first version divided by every invoice number in the table. That includes the
cancellation records themselves, which are not orders. It gave 15.46%.

Dividing by completed orders gives 18.29%.

One thing to know: a cancellation is its own invoice with its own number, so we
cannot tell which order it cancelled. So this is cancellations compared to orders
in the same period, not the share of orders that were later cancelled. Any answer
using this KPI should say that.

### KPI 8, Revenue by Product: we added two filters

Without is_product, the best selling item in the whole dataset is the code M,
which is "Manual", at 339,226. DOTCOM POSTAGE is third at 309,854. Those are not
products.

Without NOT is_outlier, the top product of 2011 is PAPER CRAFT LITTLE BIRDIE at
168,470. That is one order of 80,995 items that was cancelled 12 minutes later.
Because this KPI removes cancellations, it keeps the big order and drops the
cancellation, so we need the outlier flag to remove both.

Also group by stock_code only, not by description as well. The same code shows up
with different descriptions, so grouping by description splits one product into
several. Use mode(description) to pick the most common name.

## Note on Revenue

KPI 1 takes cancellations out, so it answers "how much did we sell".

If you leave cancellations in, the answer is 19,003,147.78. That is 7.7% lower.

We use KPI 1 as the main number, but EvidenceIQ should say that cancellations are
excluded whenever it gives a revenue figure. Otherwise the 1.46 million of
cancellations is invisible.

## Rules about time

These are not KPIs but they affect every comparison between months.

The data stops on 9 December 2011, so that month only has 8 trading days instead
of the usual 26. Never compare it as a full month. There is a column
dim_month.is_complete_month to check.

Months have different numbers of trading days. March 2011 had 27 and April had 21.
Revenue fell 25% in total but only about 7% per trading day. Always say the day
count.

December is the busiest month but the shop stops trading around the 23rd, so the
drop from November to December is normal, not a problem.

## What we do not do

We do not say what caused anything. There is no data about promotions, campaigns,
pricing or competitors. We can say what contributed to a change, not what caused it.

We do not forecast. Two years of one shop's sales is not enough to predict the
future, so EvidenceIQ should refuse instead of guessing.
