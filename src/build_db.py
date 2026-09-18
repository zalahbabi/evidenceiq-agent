"""
Build the database from the raw Excel file.

    python src/build_db.py

This is the same thing notebooks/02_build_database.ipynb does, but as a script
so anyone can rebuild from a clean clone with one command. The notebook is the
explanation; this file is the source of truth.

It fails loudly if the row count or the total revenue changes. If that happens,
someone edited a cleaning rule and everybody's answers just moved. Do not
"fix" it by changing the numbers below - work out what changed first, and
update docs/kpi_definitions.md in the same commit.

Takes about a minute. Most of that is reading the Excel file.
"""

import os

import duckdb
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(HERE, "..", "data", "raw", "online_retail_II.xlsx")
DB = os.path.join(HERE, "..", "data", "processed", "evidenceiq.duckdb")

# Agreed baseline. Every ground-truth answer in eval/benchmark.yaml was
# computed against a database with exactly these numbers.
EXPECTED_ROWS = 1_033_030
EXPECTED_REVENUE = 19_003_147.78

# Stock codes that are not products: postage, fees, manual adjustments, tests.
# Leaving them in makes "Manual" the best-selling item of all time.
NOT_PRODUCTS = ["DOT", "POST", "C2", "M", "m", "S", "B", "BANK CHARGES",
                "AMAZONFEE", "ADJUST", "ADJUST2", "PADS", "CRUK",
                "TEST001", "TEST002", "DCGSSGIRL", "DCGSSBOY"]

# Two orders placed and cancelled within minutes. Real rows, but so large they
# distort any returns figure, so we flag them rather than delete them.
ODD_INVOICES = ["541431", "C541433", "581483", "C581484"]


def load_raw():
    """Both sheets, one per year."""
    if not os.path.exists(RAW):
        raise SystemExit(
            "Cannot find " + RAW + "\n"
            "Download Online Retail II from the UCI repository and save it as\n"
            "data/raw/online_retail_II.xlsx")

    print("Reading the Excel file (this is the slow part)...")
    sheet1 = pd.read_excel(RAW, sheet_name="Year 2009-2010")
    sheet2 = pd.read_excel(RAW, sheet_name="Year 2010-2011")
    df = pd.concat([sheet1, sheet2], ignore_index=True)
    print("Rows loaded:", len(df))
    return df


def clean(df):
    """Remove the duplicates and bad-debt rows, then add our helper columns."""
    # The two sheets overlap for the first nine days of December 2010. Without
    # this, December 2010 reads 51% too high.
    before = len(df)
    df = df.drop_duplicates()
    print("Removed", before - len(df), "duplicate rows")

    df["Invoice"] = df["Invoice"].astype(str)
    df["StockCode"] = df["StockCode"].astype(str)

    # Invoices starting with A are bad-debt accounting entries, not sales.
    df = df[~df["Invoice"].str.startswith("A")]

    df = df.rename(columns={
        "Invoice": "invoice_no",
        "StockCode": "stock_code",
        "Description": "description",
        "Quantity": "quantity",
        "InvoiceDate": "invoice_ts",
        "Price": "unit_price",
        "Customer ID": "customer_id",
        "Country": "country",
    })

    # Work these out once here, instead of asking the AI to get them right
    # every single time.
    df["revenue"] = df["quantity"] * df["unit_price"]
    df["is_cancellation"] = df["invoice_no"].str.startswith("C")
    df["is_product"] = ~df["stock_code"].isin(NOT_PRODUCTS)
    df["is_outlier"] = df["invoice_no"].isin(ODD_INVOICES)
    df["invoice_date"] = df["invoice_ts"].dt.date
    df["invoice_month"] = df["invoice_ts"].dt.to_period("M").astype(str)

    return df


def check(df):
    """Stop everything if the numbers moved."""
    rows = len(df)
    revenue = round(df["revenue"].sum(), 2)

    print("Rows:    {:,}".format(rows))
    print("Revenue: GBP {:,.2f}".format(revenue))

    if rows != EXPECTED_ROWS or revenue != EXPECTED_REVENUE:
        raise SystemExit(
            "\nSTOP. The numbers do not match the agreed baseline.\n"
            "  expected {:,} rows and GBP {:,.2f}\n"
            "  got      {:,} rows and GBP {:,.2f}\n\n"
            "A cleaning rule has changed, which means every ground-truth answer\n"
            "in eval/benchmark.yaml may now be wrong. Find out what changed\n"
            "before rebuilding.".format(
                EXPECTED_ROWS, EXPECTED_REVENUE, rows, revenue))

    print("Checks passed.")


def build_tables(df):
    """One main table plus three summary tables."""
    os.makedirs(os.path.dirname(DB), exist_ok=True)
    if os.path.exists(DB):
        os.remove(DB)                      # always rebuild from scratch

    con = duckdb.connect(DB)
    con.execute("CREATE TABLE sales AS SELECT * FROM df")

    # dim_month carries the December warning, so the AI does not have to
    # remember it. trading_days lets us compare months fairly.
    #
    # net_revenue EXCLUDES cancellations, to match KPI 1 in
    # docs/kpi_definitions.md. It used to be a plain SUM(revenue), which
    # quietly disagreed with the KPI doc: the agent would query
    # "WHERE NOT is_cancellation" and get a different number to our own
    # ground truth. gross_revenue keeps the with-cancellations figure so
    # nothing is lost.
    con.execute("""
        CREATE TABLE dim_month AS
        SELECT
            invoice_month,
            COUNT(DISTINCT invoice_date) AS trading_days,
            MAX(invoice_date)            AS last_day,
            SUM(revenue) FILTER (WHERE NOT is_cancellation) AS net_revenue,
            SUM(revenue)                 AS gross_revenue,
            invoice_month <> (SELECT MAX(invoice_month) FROM sales)
                                         AS is_complete_month
        FROM sales
        GROUP BY invoice_month
        ORDER BY invoice_month
    """)

    # mode(description) because the same stock_code appears with several
    # different descriptions in the raw data.
    con.execute("""
        CREATE TABLE dim_product AS
        SELECT
            stock_code,
            mode(description)                          AS description,
            SUM(quantity) FILTER (WHERE quantity > 0)  AS units_sold,
            SUM(revenue)  FILTER (WHERE quantity > 0)  AS gross_revenue
        FROM sales
        GROUP BY stock_code
    """)

    # Customers with no ID are excluded (22.8% of rows). Unavoidable - we
    # cannot tell those orders apart.
    con.execute("""
        CREATE TABLE dim_customer AS
        SELECT
            customer_id,
            mode(country)     AS country,
            MIN(invoice_date) AS first_order,
            MAX(invoice_date) AS last_order,
            COUNT(DISTINCT invoice_no) FILTER (WHERE NOT is_cancellation) AS orders,
            SUM(revenue)      AS net_revenue
        FROM sales
        WHERE customer_id IS NOT NULL
        GROUP BY customer_id
    """)

    for table in ["sales", "dim_month", "dim_product", "dim_customer"]:
        n = con.execute("SELECT COUNT(*) FROM " + table).fetchone()[0]
        print("{:<15} {:>10,} rows".format(table, n))

    con.close()


def smoke_test():
    """Reopen read-only and check two answers we already know."""
    con = duckdb.connect(DB, read_only=True)

    november = con.execute("""
        SELECT ROUND(net_revenue, 2) FROM dim_month WHERE invoice_month = '2011-11'
    """).fetchone()[0]
    print("November 2011 net revenue: GBP {:,.2f}  (expected 1,503,866.78)"
          .format(november))

    # the agent's own query must agree with dim_month, or our ground truth
    # and its answers will disagree on every month question
    same = con.execute("""
        SELECT ROUND(SUM(revenue), 2) FROM sales
        WHERE NOT is_cancellation AND invoice_month = '2011-11'
    """).fetchone()[0]
    print("agrees with WHERE NOT is_cancellation:", same == november)

    december_days = con.execute("""
        SELECT trading_days FROM dim_month WHERE invoice_month = '2011-12'
    """).fetchone()[0]
    print("December 2011 trading days:", december_days, " (expected 8)")

    # The database itself refuses writes, not just our Python guard.
    try:
        con.execute("DELETE FROM sales")
        print("WARNING: the delete worked, the database is not read-only!")
    except Exception:
        print("Read-only check: writes are blocked, as expected.")

    con.close()


def main():
    df = clean(load_raw())
    check(df)
    build_tables(df)
    smoke_test()
    print("\nDatabase written to", os.path.normpath(DB))


if __name__ == "__main__":
    main()
