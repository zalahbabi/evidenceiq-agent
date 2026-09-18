# Database schema — paste this into another assistant

DuckDB file: `data/processed/evidenceiq.duckdb`, opened **read-only**.
UCI Online Retail II — a UK online gift wholesaler, 1 Dec 2009 to 9 Dec 2011.

---

```sql
-- ============================================================
-- sales : 1,033,030 rows. One row per invoice line. Main table.
-- ============================================================
CREATE TABLE sales (
  invoice_no       VARCHAR,   -- order number; a leading 'C' means a cancellation
  stock_code       VARCHAR,   -- product code; some codes are not products (see below)
  description      VARCHAR,   -- product name; 0.41% null, inconsistent for the same code
  quantity         BIGINT,    -- units; negative on returns. Range -80,995 to 80,995
  invoice_ts       TIMESTAMP, -- when the order was placed
  unit_price       DOUBLE,    -- price per unit in GBP; 0.58% are zero. Max 38,970
  customer_id      DOUBLE,    -- NULL for guest checkout — 22.76% of rows
  country          VARCHAR,   -- 43 values; United Kingdom is 85% of revenue
  revenue          DOUBLE,    -- DERIVED: quantity * unit_price
  is_cancellation  BOOLEAN,   -- DERIVED: invoice_no starts with 'C'  (1.85% of rows)
  is_product       BOOLEAN,   -- DERIVED: false for postage/fees/adjustments (0.54%)
  is_outlier       BOOLEAN,   -- DERIVED: 4 rows, two freak orders cancelled minutes later
  invoice_date     DATE,      -- DERIVED: date part of invoice_ts
  invoice_month    VARCHAR    -- DERIVED: 'YYYY-MM', sorts correctly as text
);

-- ============================================================
-- dim_month : 25 rows. USE THIS for anything about months.
-- ============================================================
CREATE TABLE dim_month (
  invoice_month      VARCHAR,  -- 'YYYY-MM'
  trading_days       BIGINT,   -- distinct days with at least one order
  last_day           DATE,
  net_revenue        DOUBLE,   -- EXCLUDES cancellations  <- use this one
  gross_revenue      DOUBLE,   -- INCLUDES cancellations
  is_complete_month  BOOLEAN   -- false for 2011-12, the final partial month
);

-- ============================================================
-- dim_product : 5,304 rows. One row per stock code.
-- ============================================================
CREATE TABLE dim_product (
  stock_code     VARCHAR,
  description    VARCHAR,  -- mode(description), because the raw ones are inconsistent
  units_sold     HUGEINT,  -- SUM(quantity) where quantity > 0
  gross_revenue  DOUBLE    -- SUM(revenue) where quantity > 0
);

-- ============================================================
-- dim_customer : 5,942 rows. Guest checkouts excluded.
-- ============================================================
CREATE TABLE dim_customer (
  customer_id  DOUBLE,
  country      VARCHAR,  -- mode(country) for that customer
  first_order  DATE,
  last_order   DATE,
  orders       BIGINT,   -- distinct non-cancelled invoices
  net_revenue  DOUBLE
);
```

## Sample rows

```
sales
invoice_no stock_code description                         quantity  unit_price customer_id country        revenue
489434     85048      15CM CHRISTMAS GLASS BALL 20 LIGHTS 12        6.95       13085       United Kingdom 83.40
489434     79323P     PINK CHERRY LIGHTS                  12        6.75       13085       United Kingdom 81.00

dim_month
invoice_month trading_days last_day   net_revenue gross_revenue is_complete_month
2009-12       21           2009-12-23 822,483.95  796,648.50    true
2011-11       26           2011-11-30 1,503,866.78 1,456,145.80 true
2011-12       8            2011-12-09 637,808.33  432,719.06    false
```

## Query rules — answers are wrong without these

```sql
-- revenue always excludes cancellations
WHERE NOT is_cancellation

-- product questions also need this, or "Manual" is the best seller of all time
AND is_product AND NOT is_outlier

-- group products by code, not description; the same code has several names
GROUP BY stock_code    -- and mode(description) AS description

-- units sold needs this too, or damages and write-offs are subtracted
AND quantity > 0

-- anything about months: use dim_month, it already has trading_days
```

## Five traps in this data

1. **The two raw Excel sheets overlap by nine days.** Handled at build time. If
   December 2010 ever reads about 1,126,445 instead of 746,724, deduplication
   did not run.
2. **December 2011 has 8 trading days, not 26** — the data stops on the 9th.
   Never compare it as a full month. Check `is_complete_month`.
3. **Months have different trading-day counts.** March 2011 had 27, April 21.
   Revenue fell 25% between them but only 3.6% per trading day. Both are true
   and they support opposite decisions, so always state the day count.
4. **The UK is 85% of revenue.** "Which country earns most" is a constant, not
   a question — ask for the top country *excluding* the UK.
5. **Most "returns" are not returns.** Amazon fees, manual adjustments and two
   freak orders cancelled minutes after being placed. Naive rate is 8%+, the
   real product return rate is 2.36%.

Non-product `stock_code` values (`is_product = false`):
`DOT`, `POST`, `C2`, `M`, `m`, `S`, `B`, `BANK CHARGES`, `AMAZONFEE`, `ADJUST`,
`ADJUST2`, `PADS`, `CRUK`, `TEST001`, `TEST002`, `DCGSSGIRL`, `DCGSSBOY`

The four `is_outlier` rows: invoices `541431` / `C541433` (74,215 units, cancelled
16 minutes later) and `581483` / `C581484` (80,995 units, cancelled 12 minutes
later). They net to zero, but any query that removes cancellations keeps the
order and drops the cancellation, leaving a fake 168,469 in the totals.

## Not in this data

Cost, profit, margin, discounts, promotions, marketing spend, customer
demographics, competitor prices, web traffic, stock levels, delivery times.
**Questions needing these must be refused, not estimated.**

## Known-good numbers to check any query against

| | |
|---|---|
| Rows in `sales` | 1,033,030 |
| Total revenue, cancellations included | 19,003,147.78 |
| Total revenue, cancellations excluded | 20,465,198.39 |
| Revenue 2011, cancellations excluded | 9,809,614.01 |
| Orders 2011 | 20,362 |
| Average order value 2011 | 481.76 |
| November 2011 net revenue | 1,503,866.78 |
| December 2011 trading days | 8 |
| December 2010 gross revenue (overlap test) | 746,723.61 |
| Top product 2011 | REGENCY CAKESTAND 3 TIER, 146,461.78 |
| Top country 2011 excluding UK | Netherlands, 276,661.86 |
