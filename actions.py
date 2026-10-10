import pandas as pd
from pathlib import Path
from math import ceil, isfinite


def recommend_action(
    sku,
    location,
    stock,
    daily_demand,
    fastest_lead_days,
    inventory,
    sales,
    suppliers,
    products,
    safety_days=3,
):
    """
    Generate a simulated inventory transfer or purchase draft.

    Transfer quantity targets the greater of supplier lead time
    or safety coverage, rather than adding both periods together.

    No real inventory or purchase order is changed.
    """

    sku = str(sku).strip()
    location = str(location).strip()

    try:
        stock = float(stock)
        daily_demand = float(daily_demand)
        safety_days = float(safety_days)
        lead_time = float(fastest_lead_days)
    except (TypeError, ValueError, OverflowError):
        return {
            "action": "REVIEW",
            "sku": sku,
            "location": location,
            "status": "PENDING_REVIEW",
            "reason": "Stock, demand, safety days, or lead time is invalid.",
        }

    if not all(
        isfinite(value)
        for value in [stock, daily_demand, safety_days, lead_time]
    ):
        return {
            "action": "REVIEW",
            "sku": sku,
            "location": location,
            "status": "PENDING_REVIEW",
            "reason": "Numeric inputs must be finite numbers.",
        }

    if stock < 0 or daily_demand < 0:
        return {
            "action": "REVIEW",
            "sku": sku,
            "location": location,
            "status": "PENDING_REVIEW",
            "reason": "Stock and demand cannot be negative.",
        }

    if safety_days < 0 or lead_time < 0:
        return {
            "action": "REVIEW",
            "sku": sku,
            "location": location,
            "status": "PENDING_REVIEW",
            "reason": "Safety days and lead time cannot be negative.",
        }

    if daily_demand == 0:
        return {
            "action": "REVIEW",
            "sku": sku,
            "location": location,
            "status": "PENDING_REVIEW",
            "reason": (
                "No positive demand was recorded. "
                "Verify sales data before recommending an action."
            ),
        }

    days_of_stock = stock / daily_demand

    if days_of_stock >= lead_time:
        return {
            "action": "MONITOR",
            "sku": sku,
            "location": location,
            "days_of_stock": round(days_of_stock, 2),
            "status": "NO_ACTION_REQUIRED",
            "reason": (
                "Current stock covers the fastest supplier "
                "lead time. Continue monitoring inventory."
            ),
        }

    # --------------------------------------------------
    # 1. Normalize and validate input data
    # --------------------------------------------------
    inventory = inventory.copy()
    sales = sales.copy()
    suppliers = suppliers.copy()
    products = products.copy()

    for df in [inventory, sales, suppliers, products]:
        df.columns = df.columns.str.strip().str.lower()

    required_inventory = {"sku", "location", "stock"}
    required_sales = {"sku", "location", "qty_sold", "date"}
    required_suppliers = {
        "sku", "supplier", "lead_time_days", "price", "moq"
    }

    if not required_inventory.issubset(inventory.columns):
        return {
            "action": "REVIEW",
            "sku": sku,
            "location": location,
            "status": "PENDING_REVIEW",
            "reason": "Inventory data is missing required columns.",
        }

    if not required_sales.issubset(sales.columns):
        return {
            "action": "REVIEW",
            "sku": sku,
            "location": location,
            "status": "PENDING_REVIEW",
            "reason": "Sales data is missing required columns.",
        }

    if not required_suppliers.issubset(suppliers.columns):
        return {
            "action": "REVIEW",
            "sku": sku,
            "location": location,
            "status": "PENDING_REVIEW",
            "reason": "Supplier data is missing required columns.",
        }

    for df in [inventory, sales, suppliers]:
        df["sku"] = df["sku"].astype(str).str.strip()

    for df in [inventory, sales]:
        df["location"] = df["location"].astype(str).str.strip()

    inventory["stock"] = pd.to_numeric(
        inventory["stock"], errors="coerce"
    )

    if inventory["stock"].isna().any():
        return {
            "action": "REVIEW",
            "sku": sku,
            "location": location,
            "status": "PENDING_REVIEW",
            "reason": "Inventory contains missing or invalid stock values.",
        }

    if (inventory["stock"] < 0).any():
        return {
            "action": "REVIEW",
            "sku": sku,
            "location": location,
            "status": "PENDING_REVIEW",
            "reason": "Inventory contains negative stock values.",
        }

    # Remove exact duplicate rows only.
    inventory = inventory.drop_duplicates().copy()

    # Each SKU/location must have exactly one stock record.
    duplicate_keys = inventory.duplicated(
        subset=["sku", "location"], keep=False
    )

    if duplicate_keys.any():
        return {
            "action": "REVIEW",
            "sku": sku,
            "location": location,
            "status": "PENDING_REVIEW",
            "reason": (
                "Multiple inventory records exist for the same "
                "SKU and location. Resolve them before recommending "
                "a transfer."
            ),
        }

    # Confirm the selected destination exists in inventory.
    destination_rows = inventory[
        (inventory["sku"] == sku)
        & (inventory["location"] == location)
    ]

    if destination_rows.empty:
        return {
            "action": "REVIEW",
            "sku": sku,
            "location": location,
            "status": "PENDING_REVIEW",
            "reason": (
                "The selected SKU/location was not found in inventory."
            ),
        }

    actual_destination_stock = float(
        destination_rows.iloc[0]["stock"]
    )

    # Do not calculate a draft using stale destination stock.
    if actual_destination_stock != stock:
        return {
            "action": "REVIEW",
            "sku": sku,
            "location": location,
            "status": "PENDING_REVIEW",
            "reason": (
                f"Provided stock ({stock:g}) does not match the "
                f"inventory record ({actual_destination_stock:g}). "
                "Refresh the inventory data and try again."
            ),
        }

    # --------------------------------------------------
    # 2. Prepare sales history for donor demand estimates
    # --------------------------------------------------
    sales["qty_sold"] = pd.to_numeric(
        sales["qty_sold"], errors="coerce"
    )

    sales["date"] = pd.to_datetime(
        sales["date"], errors="coerce"
    )

    if sales["qty_sold"].isna().any():
        return {
            "action": "REVIEW",
            "sku": sku,
            "location": location,
            "status": "PENDING_REVIEW",
            "reason": "Sales data contains missing or invalid quantities.",
        }

    if (sales["qty_sold"] < 0).any():
        return {
            "action": "REVIEW",
            "sku": sku,
            "location": location,
            "status": "PENDING_REVIEW",
            "reason": "Sales quantities cannot be negative.",
        }

    sales = sales.dropna(subset=["date"]).copy()

    if not sales.empty:
        latest_date = sales["date"].max().normalize()
        first_date = max(
            sales["date"].min().normalize(),
            latest_date - pd.Timedelta(days=29),
        )

        sales = sales[
            (sales["date"] >= first_date)
            & (sales["date"] < latest_date + pd.Timedelta(days=1))
        ].copy()

        observed_days = (latest_date - first_date).days + 1
    else:
        observed_days = 0

    # --------------------------------------------------
    # 3. Find a suitable donor warehouse
    # --------------------------------------------------
    donor_locations = inventory[
        (inventory["sku"] == sku)
        & (inventory["location"] != location)
    ].copy()

    donor_options = []

    # Target coverage is the greater of supplier lead time
    # and safety coverage. Do not add the two periods together.
    target_cover_days = max(lead_time, safety_days)
    target_stock = daily_demand * target_cover_days
    needed = max(0, ceil(target_stock - stock))

    for _, donor in donor_locations.iterrows():
        donor_location = str(donor["location"]).strip()
        donor_stock = float(donor["stock"])

        donor_sales = sales[
            (sales["sku"] == sku)
            & (sales["location"] == donor_location)
        ]

        if observed_days > 0 and not donor_sales.empty:
            donor_daily_demand = (
                donor_sales["qty_sold"].sum() / observed_days
            )
        else:
            donor_daily_demand = 0.0

        donor_daily_demand = max(0.0, float(donor_daily_demand))

        # Reserve stock for the donor's own demand.
        donor_buffer = donor_daily_demand * safety_days
        transferable = max(0.0, donor_stock - donor_buffer)

        # Only transfer the destination's calculated requirement,
        # subject to available stock after the donor's reserve.
        quantity = min(
            int(transferable),
            int(needed),
        )

        if quantity > 0:
            donor_options.append({
                "location": donor_location,
                "stock": donor_stock,
                "daily_demand": donor_daily_demand,
                "buffer": donor_buffer,
                "transferable": transferable,
                "quantity": quantity,
            })

    if donor_options:
        # Prefer the donor that covers the most need, then
        # the donor with the greatest transferable stock.
        donor_options.sort(
            key=lambda item: (
                item["quantity"],
                item["transferable"],
            ),
            reverse=True,
        )

        donor = donor_options[0]

        return {
            "action": "TRANSFER_DRAFT",
            "sku": sku,
            "product_name": "Oil Filter",
            "from_location": donor["location"],
            "to_location": location,
            "quantity": donor["quantity"],
            "donor_stock": donor["stock"],
            "donor_daily_demand": round(
                donor["daily_demand"], 2
            ),
            "donor_safety_buffer": round(
                donor["buffer"], 2
            ),
            "transferable_quantity": int(donor["transferable"]),
            "target_cover_days": target_cover_days,
            "target_stock": ceil(target_stock),
            "days_of_stock": round(days_of_stock, 2),
            "status": "PENDING_APPROVAL",
            "reason": (
                f"{location} has {days_of_stock:.1f} days of stock. "
                f"The target is {ceil(target_stock)} units, based on "
                f"{target_cover_days:g} days of coverage. "
                f"{donor['location']} has {donor['stock']:.0f} units, "
                f"with an estimated transferable quantity of "
                f"{int(donor['transferable'])} units after its "
                f"safety reserve. Proposed transfer: "
                f"{donor['quantity']} units. Review before approval."
            ),
        }

    # --------------------------------------------------
    # 4. No suitable transfer: compare suppliers
    # --------------------------------------------------
    sku_suppliers = suppliers[
        suppliers["sku"] == sku
    ].copy()

    if sku_suppliers.empty:
        return {
            "action": "REVIEW",
            "sku": sku,
            "location": location,
            "status": "PENDING_REVIEW",
            "reason": "No supplier is listed for this product.",
        }

    for column in ["lead_time_days", "price", "moq"]:
        sku_suppliers[column] = pd.to_numeric(
            sku_suppliers[column], errors="coerce"
        )

    sku_suppliers = sku_suppliers.dropna(
        subset=["lead_time_days", "price", "moq"]
    )

    sku_suppliers = sku_suppliers[
        (sku_suppliers["lead_time_days"] >= 0)
        & (sku_suppliers["price"] >= 0)
        & (sku_suppliers["moq"] >= 1)
    ].copy()

    if sku_suppliers.empty:
        return {
            "action": "REVIEW",
            "sku": sku,
            "location": location,
            "status": "PENDING_REVIEW",
            "reason": (
                "No supplier has valid lead time, price and MOQ data."
            ),
        }

    # Calculate supplier quantities based on the greater of
    # lead time or safety coverage, not their sum.
    sku_suppliers["quantity_needed"] = sku_suppliers[
        "lead_time_days"
    ].apply(
        lambda supplier_lead: max(
            1,
            ceil(
                daily_demand
                * max(float(supplier_lead), safety_days)
                - stock
            ),
        )
    )

    sku_suppliers["order_quantity"] = sku_suppliers.apply(
        lambda row: max(
            int(row["quantity_needed"]),
            ceil(float(row["moq"])),
        ),
        axis=1,
    )

    sku_suppliers["estimated_total"] = (
        sku_suppliers["order_quantity"]
        * sku_suppliers["price"]
    )

    sku_suppliers["can_arrive_before_stockout"] = (
        sku_suppliers["lead_time_days"] < days_of_stock
    )

    feasible = sku_suppliers[
        sku_suppliers["can_arrive_before_stockout"]
    ]

    if not feasible.empty:
        supplier = feasible.sort_values(
            ["estimated_total", "lead_time_days"]
        ).iloc[0]
    else:
        supplier = sku_suppliers.sort_values(
            ["lead_time_days", "estimated_total"]
        ).iloc[0]

    quantity = int(supplier["order_quantity"])

    return {
        "action": "PO_DRAFT",
        "sku": sku,
        "location": location,
        "supplier": str(supplier["supplier"]),
        "quantity": quantity,
        "unit_price": float(supplier["price"]),
        "estimated_total": round(
            quantity * float(supplier["price"]), 2
        ),
        "lead_time_days": float(supplier["lead_time_days"]),
        "stock_cover_days": round(days_of_stock, 2),
        "can_arrive_before_stockout": bool(
            supplier["can_arrive_before_stockout"]
        ),
        "status": "PENDING_APPROVAL",
        "reason": (
            "No suitable transfer was found. Supplier options "
            "were compared using lead time, estimated cost and MOQ. "
            "Review the purchase draft before approval."
        ),
    }


if __name__ == "__main__":
    BASE_DIR = Path(__file__).resolve().parent
    DATA_DIR = BASE_DIR / "data"

    inventory = pd.read_csv(DATA_DIR / "inventory.csv")
    sales = pd.read_csv(DATA_DIR / "sales.csv")
    suppliers = pd.read_csv(DATA_DIR / "suppliers.csv")
    products = pd.read_csv(DATA_DIR / "products.csv")

    for df in [inventory, sales, suppliers, products]:
        df.columns = df.columns.str.strip().str.lower()

    result = recommend_action(
        sku="F101",
        location="Gokak",
        stock=8,
        daily_demand=4,
        fastest_lead_days=3,
        inventory=inventory,
        sales=sales,
        suppliers=suppliers,
        products=products,
    )

    print("\n=== SPARESENSE AI: ACTION DRAFT ===")
    for key, value in result.items():
        print(f"{key}: {value}")
