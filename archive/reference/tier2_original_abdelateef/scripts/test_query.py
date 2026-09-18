import duckdb
from pathlib import Path

DB_PATH = Path("data/evidenceiq.duckdb")

con = duckdb.connect(str(DB_PATH), read_only=True)

sql = """
SELECT
    invoice_month,
    net_revenue,
    trading_days
FROM dim_month
WHERE invoice_month IN ('2011-10', '2011-11')
ORDER BY invoice_month;
"""

result = con.execute(sql).fetchdf()

print(result)

con.close()