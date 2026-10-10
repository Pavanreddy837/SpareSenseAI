import pandas as pd
from pathlib import Path

data_dir = Path(__file__).resolve().parents[1] / "data"

files = [
    "products.csv",
    "inventory.csv",
    "sales.csv",
    "suppliers.csv",
    "purchase_orders.csv"
]

for filename in files:
    path = data_dir / filename

    try:
        df = pd.read_csv(path)
        print(f"\n✅ {filename}")
        print("Rows and columns:", df.shape)
        print("Columns:", df.columns.tolist())
        print(df.head(3))
    except Exception as e:
        print(f"\n❌ {filename}: {e}")