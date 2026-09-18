from pathlib import Path
import duckdb


DB_PATH = Path(__file__).resolve().parents[1] / "data" / "evidenceiq.duckdb"


con = duckdb.connect(str(DB_PATH), read_only=True)

print("\nTABLES")
print(con.execute("SHOW TABLES").fetchdf())

for table in ["sales", "dim_month", "dim_product", "dim_customer"]:
    print(f"\n{'=' * 60}")
    print(table)
    print("=" * 60)

    print(con.execute(f"DESCRIBE {table}").fetchdf())

    count = con.execute(
        f"SELECT COUNT(*) FROM {table}"
    ).fetchone()[0]

    print("Rows:", count)

    print(con.execute(
        f"SELECT * FROM {table} LIMIT 5"
    ).fetchdf())