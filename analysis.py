
import pandas as pd
from pathlib import Path

# Locate the data folder
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"


def load_data():
    """Load all five datasets."""
    products = pd.read_csv(DATA_DIR / "products.csv")
    inventory = pd.read_csv(DATA_DIR / "inventory.csv")
    sales = pd.read_csv(DATA_DIR / "sales.csv")
    suppliers = pd.read_csv(DATA_DIR / "suppliers.csv")
    purchase_orders = pd.read_csv(DATA_DIR / "purchase_orders.csv")

    return products, inventory, sales, suppliers, purchase_orders


def detect_stock_shortages():
    products, inventory, sales, suppliers, purchase_orders = load_data()

    # Normalize column names
    for df in [products, inventory, sales, suppliers, purchase_orders]:
        df.columns = df.columns.str.strip().str.lower()

    # Normalize SKU and location values
    for df in [products, inventory, sales, suppliers, purchase_orders]:
        if "sku" in df.columns:
            df["sku"] = df["sku"].astype(str).str.strip()

    for df in [inventory, sales]:
        if "location" in df.columns:
            df["location"] = df["location"].astype(str).str.strip()

    # Clean inventory quantities
    inventory["stock"] = pd.to_numeric(
        inventory["stock"], errors="coerce"
    ).fillna(0)

    # Remove completely identical inventory records
    inventory = inventory.drop_duplicates().copy()

    # Detect conflicting stock records for the same SKU/location
    duplicate_keys = inventory.duplicated(
        subset=["sku", "location"], keep=False
    )

    if duplicate_keys.any():
        conflicting = inventory.loc[
            duplicate_keys, ["sku", "location", "stock"]
        ].drop_duplicates()

        conflicting_keys = conflicting.duplicated(
            subset=["sku", "location"], keep=False
        )

        if conflicting_keys.any():
            raise ValueError(
                "Conflicting inventory records found for the same "
                "SKU and location. Please check data/inventory.csv."
            )

        inventory = inventory.drop_duplicates(
            subset=["sku", "location"]
        ).copy()

    # Clean sales data
    sales["qty_sold"] = pd.to_numeric(
        sales["qty_sold"], errors="coerce"
    ).fillna(0)

    sales["date"] = pd.to_datetime(
        sales["date"], errors="coerce"
    )

    sales = sales.dropna(subset=["date"])

    if sales.empty:
        raise ValueError("Sales data has no valid dates.")

    # Use the latest 30 calendar days available in the dataset
    latest_date = sales["date"].max().normalize()
    first_date = sales["date"].min().normalize()

    window_start = max(
        first_date,
        latest_date - pd.Timedelta(days=29)
    )

    recent_sales = sales[
        (sales["date"] >= window_start)
        & (sales["date"] < latest_date + pd.Timedelta(days=1))
    ].copy()

    observation_days = (latest_date - window_start).days + 1

    print(f"\nDemand observation window: {observation_days} days")

    # Calculate demand by SKU and location
    demand = (
        recent_sales.groupby(["sku", "location"])["qty_sold"]
        .sum()
        .reset_index()
    )

    demand["daily_demand"] = (
        demand["qty_sold"] / observation_days
    )

    # Attach demand to inventory
    result = inventory.merge(
        demand[["sku", "location", "daily_demand"]],
        on=["sku", "location"],
        how="left",
        validate="one_to_one"
    )

    result["daily_demand"] = result["daily_demand"].fillna(0)

    # Calculate days of stock remaining
    result["days_of_stock"] = float("inf")

    has_demand = result["daily_demand"] > 0

    result.loc[has_demand, "days_of_stock"] = (
        result.loc[has_demand, "stock"]
        / result.loc[has_demand, "daily_demand"]
    )

    # Calculate fastest valid supplier lead time per SKU
    suppliers["lead_time_days"] = pd.to_numeric(
        suppliers["lead_time_days"], errors="coerce"
    )

    valid_suppliers = suppliers[
        suppliers["lead_time_days"].notna()
        & (suppliers["lead_time_days"] >= 0)
    ]

    supplier_lead = (
        valid_suppliers.groupby("sku")["lead_time_days"]
        .min()
        .rename("fastest_lead_days")
        .reset_index()
    )

    result = result.merge(
        supplier_lead,
        on="sku",
        how="left",
        validate="many_to_one"
    )

    # ------------------------------------------
    # PURCHASE ORDER ANALYSIS
    # ------------------------------------------
    required_columns = {
        "po", "sku", "qty", "expected_date", "status"
    }

    today = pd.Timestamp.now().normalize()

    if required_columns.issubset(purchase_orders.columns):

        purchase_orders["qty"] = pd.to_numeric(
            purchase_orders["qty"], errors="coerce"
        ).fillna(0)

        purchase_orders["expected_date"] = pd.to_datetime(
            purchase_orders["expected_date"], errors="coerce"
        )

        purchase_orders["status_clean"] = (
            purchase_orders["status"]
            .astype(str)
            .str.strip()
            .str.lower()
        )

        # Orders that are no longer open
        closed_statuses = {
            "delivered",
            "received",
            "completed",
            "cancelled",
            "canceled",
            "closed"
        }

        open_orders = purchase_orders[
            ~purchase_orders["status_clean"].isin(closed_statuses)
        ].copy()

        # Mark orders whose expected date has passed
        open_orders["overdue"] = (
            open_orders["expected_date"].notna()
            & (open_orders["expected_date"] < today)
        )

        # Total open quantity per SKU
        incoming = (
            open_orders.groupby("sku")["qty"]
            .sum()
            .rename("open_po_qty")
            .reset_index()
        )

        result = result.merge(
            incoming,
            on="sku",
            how="left",
            validate="many_to_one"
        )

        result["open_po_qty"] = result["open_po_qty"].fillna(0)

        # Number of overdue purchase orders per SKU
        overdue_counts = (
            open_orders[open_orders["overdue"]]
            .groupby("sku")["po"]
            .nunique()
            .rename("overdue_po_count")
            .reset_index()
        )

        result = result.merge(
            overdue_counts,
            on="sku",
            how="left",
            validate="many_to_one"
        )

        result["overdue_po_count"] = (
            result["overdue_po_count"].fillna(0).astype(int)
        )

        # Display detailed overdue-order information
        overdue_orders = open_orders[open_orders["overdue"]]

        print("\n=== OVERDUE PURCHASE ORDERS ===")

        if overdue_orders.empty:
            print("No overdue open purchase orders detected.")
        else:
            po_columns = [
                col for col in [
                    "po",
                    "supplier",
                    "sku",
                    "qty",
                    "expected_date",
                    "status"
                ]
                if col in overdue_orders.columns
            ]

            print(
                overdue_orders[po_columns].to_string(index=False)
            )

    else:
        result["open_po_qty"] = 0
        result["overdue_po_count"] = 0

        print(
            "\nWarning: Purchase-order CSV is missing required columns."
        )

    # ------------------------------------------
    # SHORTAGE RISK ANALYSIS
    # ------------------------------------------
    # Open POs are shown separately.
    # They are not automatically assumed to arrive in time.
    result["shortage_risk"] = (
        result["daily_demand"].gt(0)
        & result["fastest_lead_days"].notna()
        & (
            result["days_of_stock"]
            < result["fastest_lead_days"]
        )
    )

    # Add product names
    if "name" in products.columns:
        product_names = products[
            ["sku", "name"]
        ].drop_duplicates("sku")

        result = result.merge(
            product_names,
            on="sku",
            how="left",
            validate="many_to_one"
        )

    # Return highest-risk items first
    return result.sort_values(
        ["shortage_risk", "days_of_stock"],
        ascending=[False, True]
    )


if __name__ == "__main__":
    result = detect_stock_shortages()

    print("\n=== SPARESENSE AI: STOCK ANALYSIS ===\n")

    columns = [
        col for col in [
            "sku",
            "name",
            "location",
            "stock",
            "daily_demand",
            "days_of_stock",
            "fastest_lead_days",
            "open_po_qty",
            "overdue_po_count",
            "shortage_risk"
        ]
        if col in result.columns
    ]

    print(result[columns].to_string(index=False))