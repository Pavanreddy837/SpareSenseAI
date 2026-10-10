
import pandas as pd
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

inventory = pd.read_csv(DATA_DIR / "inventory.csv")
sales = pd.read_csv(DATA_DIR / "sales.csv")

for df in [inventory, sales]:
    df.columns = df.columns.str.strip().str.lower()
    df["sku"] = df["sku"].astype(str).str.strip()

inventory["stock"] = pd.to_numeric(
    inventory["stock"], errors="coerce"
).fillna(0)

sales["qty_sold"] = pd.to_numeric(
    sales["qty_sold"], errors="coerce"
).fillna(0)

sales["date"] = pd.to_datetime(
    sales["date"], errors="coerce"
)

# Show stock at each location for F101
print("\n=== F101 INVENTORY ===")
print(
    inventory[inventory["sku"] == "F101"][
        ["sku", "location", "stock"]
    ].to_string(index=False)
)

# Show sales over the latest 30 calendar days
valid_sales = sales.dropna(subset=["date"])

if not valid_sales.empty:
    latest_date = valid_sales["date"].max().normalize()
    start_date = latest_date - pd.Timedelta(days=29)

    recent = valid_sales[
        (valid_sales["sku"] == "F101")
        & (valid_sales["date"] >= start_date)
        & (
            valid_sales["date"]
            < latest_date + pd.Timedelta(days=1)
        )
    ]

    print("\n=== F101 SALES BY LOCATION ===")
    print(
        recent.groupby("location")["qty_sold"]
        .agg(["sum", "count"])
        .to_string()
    )
else:
    print("No valid sales dates found.")

print("\n=== F101 SALES DATE CHECK ===")

f101_sales = sales[
    (sales["sku"] == "F101")
    & sales["date"].notna()
]

if not f101_sales.empty:
    print("First sale:", f101_sales["date"].min())
    print("Last sale:", f101_sales["date"].max())
    print("Number of records:", len(f101_sales))
    print("Total units sold:", f101_sales["qty_sold"].sum())
else:
    print("No valid F101 sales records found.")

print("\n=== DUPLICATE INVENTORY CHECK ===")
print("Total inventory rows:", len(inventory))
print("Rows after removing exact duplicates:",
      len(inventory.drop_duplicates()))