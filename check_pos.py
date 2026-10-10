
import pandas as pd
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"

po = pd.read_csv(DATA_DIR / "purchase_orders.csv")

po.columns = po.columns.str.strip().str.lower()

print("\n=== PURCHASE ORDERS ===")
print("Columns:", po.columns.tolist())
print(po.to_string(index=False))