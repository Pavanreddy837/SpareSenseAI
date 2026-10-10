
import math
import uuid
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

from analysis import detect_stock_shortages
from actions import recommend_action


# ==========================================
# 1. PAGE CONFIGURATION AND PATHS
# ==========================================
st.set_page_config(
    page_title="SpareSense AI",
    page_icon="📦",
    layout="wide",
)

st.title("📦 SpareSense AI")
st.subheader("Your Daily Supply-Chain Decision Assistant")
st.caption("Kaveri Spares & Hydraulics | North Karnataka")

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
HISTORY_FILE = DATA_DIR / "transfer_history.csv"

PENDING = "PENDING_APPROVAL"
APPROVED = "APPROVED"
REJECTED = "REJECTED"


def now_iso():
    return datetime.now().isoformat(timespec="seconds")


def clean_columns(df):
    df = df.copy()
    df.columns = df.columns.astype(str).str.strip().str.lower()
    return df


def load_inventory_for_transfer():
    inventory = clean_columns(
        pd.read_csv(DATA_DIR / "inventory.csv")
    )

    required = {"sku", "location", "stock"}
    missing = required - set(inventory.columns)

    if missing:
        raise ValueError(
            "inventory.csv is missing required columns: "
            + ", ".join(sorted(missing))
        )

    inventory["sku"] = inventory["sku"].astype(str).str.strip()
    inventory["location"] = (
        inventory["location"].astype(str).str.strip()
    )
    inventory["stock"] = pd.to_numeric(
        inventory["stock"], errors="coerce"
    )

    if (
        inventory["sku"].eq("").any()
        or inventory["location"].eq("").any()
    ):
        raise ValueError(
            "Inventory has blank SKU or location values."
        )

    if inventory["stock"].isna().any():
        raise ValueError(
            "Inventory has missing or non-numeric stock values."
        )

    if not inventory["stock"].map(math.isfinite).all():
        raise ValueError(
            "Inventory has non-finite stock values."
        )

    if (inventory["stock"] < 0).any():
        raise ValueError("Inventory has negative stock values.")

    # Remove exact duplicate rows only.
    inventory = inventory.drop_duplicates().copy()

    # Conflicting SKU/location records must be resolved manually.
    conflicts = inventory.duplicated(
        subset=["sku", "location"],
        keep=False,
    )

    if conflicts.any():
        examples = inventory.loc[
            conflicts, ["sku", "location"]
        ].drop_duplicates()

        pairs = ", ".join(
            f"{row.sku} at {row.location}"
            for row in examples.itertuples(index=False)
        )

        raise ValueError(
            "Conflicting duplicate SKU/location records found. "
            "Resolve them in inventory.csv first. Records: "
            + pairs
        )

    return inventory


def positive_whole_number(value):
    try:
        number = float(value)

        return (
            math.isfinite(number)
            and number > 0
            and number.is_integer()
        )

    except (TypeError, ValueError):
        return False


def validate_transfer_draft(draft, current_inventory):
    """Validate a pending transfer without changing inventory."""

    required = {
        "draft_id",
        "sku",
        "from_location",
        "to_location",
        "quantity",
        "donor_safety_buffer",
        "status",
        "donor_stock",
        "destination_stock",
    }

    missing = required - set(draft)

    if missing:
        return (
            "Draft is missing required fields: "
            + ", ".join(sorted(missing))
        )

    if draft.get("status") != PENDING:
        return "This draft is no longer pending approval."

    sku = str(draft.get("sku", "")).strip()
    source = str(draft.get("from_location", "")).strip()
    destination = str(draft.get("to_location", "")).strip()

    if not sku or not source or not destination:
        return "SKU, source, and destination must all be provided."

    if source == destination:
        return (
            "Source and destination must be different warehouses."
        )

    if not positive_whole_number(draft.get("quantity")):
        return "Transfer quantity must be a positive whole number."

    try:
        quantity = int(float(draft["quantity"]))
        buffer = float(draft["donor_safety_buffer"])
        snapshot_source = float(draft["donor_stock"])
        snapshot_destination = float(draft["destination_stock"])

    except (TypeError, ValueError):
        return (
            "Quantity, safety buffer, or stock snapshot is invalid."
        )

    numeric_values = [
        buffer,
        snapshot_source,
        snapshot_destination,
    ]

    if not all(math.isfinite(value) for value in numeric_values):
        return "Draft contains non-finite numeric values."

    if (
        buffer < 0
        or snapshot_source < 0
        or snapshot_destination < 0
    ):
        return (
            "Draft contains negative stock or safety-buffer values."
        )

    source_rows = current_inventory[
        (current_inventory["sku"] == sku)
        & (current_inventory["location"] == source)
    ]

    destination_rows = current_inventory[
        (current_inventory["sku"] == sku)
        & (current_inventory["location"] == destination)
    ]

    if len(source_rows) != 1:
        return "Source inventory record is missing or ambiguous."

    if len(destination_rows) != 1:
        return (
            "Destination inventory record is missing or ambiguous."
        )

    current_source = float(source_rows.iloc[0]["stock"])
    current_destination = float(
        destination_rows.iloc[0]["stock"]
    )

    # Block approval if stock changed after draft creation.
    if not math.isclose(
        current_source,
        snapshot_source,
        abs_tol=1e-9,
    ):
        return (
            "Source stock changed since this draft was created. "
            "Generate a new draft."
        )

    if not math.isclose(
        current_destination,
        snapshot_destination,
        abs_tol=1e-9,
    ):
        return (
            "Destination stock changed since this draft was created. "
            "Generate a new draft."
        )

    if current_source - quantity < buffer:
        return "Source stock would fall below the safety buffer."

    return None


def explain_recommendation(draft):
    """Create a plain-language explanation of the recommendation."""

    def value_for(*keys):
        for key in keys:
            value = draft.get(key)

            if value is None:
                continue

            try:
                if pd.isna(value):
                    continue
            except (TypeError, ValueError):
                pass

            if isinstance(value, str) and not value.strip():
                continue

            return value

        return None

    def number_for(*keys):
        value = value_for(*keys)

        if value is None:
            return None

        try:
            number = float(value)
            return number if math.isfinite(number) else None

        except (TypeError, ValueError):
            return None

    action = str(
        value_for("action", "action_type", "recommendation")
        or "REVIEW"
    ).upper()

    sku = value_for("sku") or "Unknown SKU"

    location = (
        value_for("location", "target_location", "to_location")
        or "Unknown location"
    )

    stock = number_for("stock", "current_stock")
    demand = number_for("daily_demand")

    days_cover = number_for(
        "days_of_stock",
        "estimated_days_of_stock",
    )

    lead_time = number_for(
        "fastest_lead_days",
        "lead_time_days",
        "supplier_lead_time",
    )

    quantity = number_for(
        "quantity",
        "transfer_qty",
        "recommended_qty",
        "order_qty",
        "qty",
    )

    open_po_qty = number_for("open_po_qty")
    overdue_po_count = number_for("overdue_po_count")

    supplier = value_for("supplier", "supplier_name")

    source = value_for(
        "from_location",
        "source_location",
        "donor_location",
    )

    reason = value_for("reason", "explanation", "message")

    if (
        days_cover is None
        and stock is not None
        and demand is not None
        and demand > 0
    ):
        days_cover = stock / demand

    action_label = {
        "TRANSFER_DRAFT": "Stock transfer",
        "PO_DRAFT": "Purchase order",
        "MONITOR": "Monitor stock",
    }.get(action, action.replace("_", " ").title())

    lines = [
        f"**Proposed decision:** {action_label}",
        f"**Item and destination:** {sku} — {location}",
    ]

    if stock is not None:
        lines.append(f"**Current stock:** {stock:g} units")

    if demand is not None and demand >= 0:
        lines.append(
            f"**Observed daily demand:** {demand:.2f} units/day"
        )

    if days_cover is not None and days_cover >= 0:
        lines.append(
            f"**Estimated stock cover:** {days_cover:.1f} days"
        )

    if lead_time is not None and lead_time >= 0:
        lines.append(
            f"**Fastest supplier lead time:** {lead_time:g} days"
        )

    if quantity is not None:
        lines.append(f"**Proposed quantity:** {quantity:g} units")

    if source:
        lines.append(f"**Proposed source warehouse:** {source}")

    if supplier:
        lines.append(f"**Proposed supplier:** {supplier}")

    if (
        days_cover is not None
        and lead_time is not None
        and days_cover < lead_time
    ):
        lines.append(
            "**Risk to check:** Estimated stock cover is shorter "
            "than the fastest supplier lead time, so a purchase "
            "may arrive after a stockout."
        )

    if action == "TRANSFER_DRAFT":
        lines.append(
            "**Why this action:** The engine proposed moving stock "
            "from another location. Confirm source stock and safety "
            "buffer before approval."
        )

    elif action == "PO_DRAFT":
        lines.append(
            "**Why this action:** The engine proposed supplier "
            "replenishment. Verify supplier, price, minimum order "
            "quantity, and delivery estimate."
        )

    elif action == "MONITOR":
        lines.append(
            "**Why this action:** The engine recommends monitoring "
            "rather than an immediate transfer or purchase."
        )

    else:
        lines.append(
            "**Why this action:** Review the proposed action and "
            "supporting data before deciding."
        )

    if open_po_qty is not None and open_po_qty > 0:
        lines.append(
            f"**Open purchase orders:** {open_po_qty:g} units are "
            "listed for this SKU. Verify status, expected delivery "
            "date, and destination."
        )

    if overdue_po_count is not None and overdue_po_count > 0:
        lines.append(
            f"**Overdue PO alert:** {overdue_po_count:g} overdue "
            "purchase-order record(s) are associated with this SKU."
        )

    if reason:
        lines.append(
            f"**Recommendation engine note:** {reason}"
        )

    lines.append(
        "**Human approval required:** This is a proposal only. "
        "Approval records a decision in this demo; it does not "
        "execute a real transfer or purchase order."
    )

    return "\n\n".join(lines)


# ==========================================
# 2. LOAD INVENTORY ANALYSIS
# ==========================================
try:
    result = detect_stock_shortages()

    if result is None or result.empty:
        st.warning("No inventory records were returned.")
        st.stop()

    result = clean_columns(result)

    required_analysis_columns = {
        "sku",
        "location",
        "stock",
        "daily_demand",
        "shortage_risk",
    }

    missing = required_analysis_columns - set(result.columns)

    if missing:
        st.error(
            "Analysis is missing required columns: "
            + ", ".join(sorted(missing))
        )
        st.stop()

except Exception as exc:
    st.error(f"Could not analyze inventory: {exc}")
    st.stop()


# ==========================================
# 3. SUMMARY METRICS
# ==========================================
critical = result[
    result["shortage_risk"].fillna(False).astype(bool)
].copy()

total_records = len(result)
shortage_count = len(critical)

locations_affected = (
    critical["location"].nunique()
    if not critical.empty
    else 0
)

overdue_count = (
    int(
        pd.to_numeric(
            result["overdue_po_count"],
            errors="coerce",
        ).fillna(0).sum()
    )
    if "overdue_po_count" in result.columns
    else 0
)

c1, c2, c3, c4 = st.columns(4)

c1.metric("📦 Inventory Records", total_records)
c2.metric("🚨 Shortage Risks", shortage_count)
c3.metric("📍 Locations Affected", locations_affected)
c4.metric("⏰ Overdue PO Records", overdue_count)

st.divider()


# ==========================================
# 3A. VISUAL INVENTORY DASHBOARD
# ==========================================
st.header("📊 Visual Inventory Dashboard")

# Work on a copy so the original analysis is not modified.
visual = result.copy()

# Convert numeric fields safely.
for column in [
    "stock",
    "daily_demand",
    "days_of_stock",
    "fastest_lead_days",
]:
    if column in visual.columns:
        visual[column] = pd.to_numeric(
            visual[column],
            errors="coerce",
        )

visual["stock"] = visual["stock"].fillna(0)


# ------------------------------------------
# A. STOCK LEVELS BY SKU AND WAREHOUSE
# ------------------------------------------
st.subheader("📦 Stock Levels by SKU and Warehouse")

if {"sku", "location", "stock"}.issubset(visual.columns):
    stock_pivot = visual.pivot_table(
        index="sku",
        columns="location",
        values="stock",
        aggfunc="sum",
        fill_value=0,
    )

    if not stock_pivot.empty:
        st.bar_chart(stock_pivot)

        st.caption(
            "Compare recorded stock for each SKU across warehouses. "
            "Values are units, not monetary value."
        )
    else:
        st.info("No stock-level data is available.")

else:
    st.warning(
        "Stock chart requires sku, location, and stock columns."
    )

st.divider()


# ------------------------------------------
# B. SHORTAGE RISK DISTRIBUTION
# ------------------------------------------
st.subheader("🚨 Shortage Risk Distribution")

if "shortage_risk" in visual.columns:
    shortage_flag = (
        visual["shortage_risk"]
        .fillna(False)
        .astype(bool)
    )

    if {
        "days_of_stock",
        "fastest_lead_days",
    }.issubset(visual.columns):
        cover = visual["days_of_stock"]
        lead = visual["fastest_lead_days"]

        at_risk = (
            (~shortage_flag)
            & cover.notna()
            & lead.notna()
            & (cover < lead)
        )

    else:
        at_risk = pd.Series(
            False,
            index=visual.index,
        )

    visual["risk_category"] = "Healthy / Monitor"
    visual.loc[at_risk, "risk_category"] = "At Risk"
    visual.loc[shortage_flag, "risk_category"] = "Critical"

    risk_order = [
        "Critical",
        "At Risk",
        "Healthy / Monitor",
    ]

    risk_counts = (
        visual["risk_category"]
        .value_counts()
        .reindex(risk_order, fill_value=0)
        .rename_axis("Risk Category")
        .reset_index(name="Inventory Records")
    )

    risk_left, risk_right = st.columns([2, 1])

    with risk_left:
        st.bar_chart(
            risk_counts.set_index("Risk Category")
        )

    with risk_right:
        st.dataframe(
            risk_counts,
            hide_index=True,
            width="stretch",
        )

    st.caption(
        "Risk categories use the current analysis rules. "
        "Healthy / Monitor does not guarantee that an item "
        "will never run out."
    )

else:
    st.warning(
        "Shortage risk chart requires shortage_risk from analysis.py."
    )

st.divider()


# ------------------------------------------
# C. WAREHOUSE COMPARISON
# ------------------------------------------
st.subheader("🏭 Warehouse Stock Comparison")

if {"location", "stock", "sku"}.issubset(visual.columns):
    warehouse_totals = (
        visual.groupby("location", as_index=False)["stock"]
        .sum()
        .sort_values("stock", ascending=False)
        .set_index("location")
    )

    warehouse_left, warehouse_right = st.columns([2, 1])

    with warehouse_left:
        st.bar_chart(warehouse_totals)

    with warehouse_right:
        st.dataframe(
            warehouse_totals.reset_index().rename(
                columns={"stock": "Total Units"}
            ),
            hide_index=True,
            width="stretch",
        )

    st.info(
        "Caution: total units across different SKUs are not directly "
        "comparable measures of warehouse health. Use the SKU-level "
        "chart and shortage risks when deciding where stock should move."
    )

else:
    st.warning(
        "Warehouse comparison requires location, stock, and sku columns."
    )

# ==========================================
# 3B. SMART TRANSFER OPPORTUNITIES
# ==========================================
st.header("🔄 Smart Transfer Opportunities")

st.write(
    "Find potential stock transfers between warehouses. "
    "These are suggestions only and require human review."
)

required_transfer_columns = {
    "sku",
    "location",
    "stock",
    "daily_demand",
}

if required_transfer_columns.issubset(visual.columns):

    transfer_view = visual.copy()

    transfer_view["stock"] = pd.to_numeric(
        transfer_view["stock"],
        errors="coerce",
    )

    transfer_view["daily_demand"] = pd.to_numeric(
        transfer_view["daily_demand"],
        errors="coerce",
    )

    if "days_of_stock" in transfer_view.columns:
        transfer_view["days_of_stock"] = pd.to_numeric(
            transfer_view["days_of_stock"],
            errors="coerce",
        )
    else:
        transfer_view["days_of_stock"] = (
            transfer_view["stock"]
            / transfer_view["daily_demand"].replace(0, float("nan"))
        )

    if "fastest_lead_days" in transfer_view.columns:
        transfer_view["fastest_lead_days"] = pd.to_numeric(
            transfer_view["fastest_lead_days"],
            errors="coerce",
        )
    else:
        transfer_view["fastest_lead_days"] = float("nan")

    # Default safety buffer for this exploratory dashboard.
    # Confirm business-specific buffers before acting.
    default_safety_buffer = 6

    opportunities = []

    for sku in transfer_view["sku"].dropna().unique():

        sku_rows = transfer_view[
            transfer_view["sku"] == sku
        ].copy()

        if len(sku_rows) < 2:
            continue

        for _, destination_row in sku_rows.iterrows():

            destination = destination_row["location"]
            destination_stock = destination_row["stock"]
            destination_demand = destination_row["daily_demand"]
            destination_cover = destination_row["days_of_stock"]
            destination_lead = destination_row["fastest_lead_days"]

            if (
                pd.isna(destination_stock)
                or pd.isna(destination_demand)
                or destination_demand <= 0
            ):
                continue

            destination_is_at_risk = (
                pd.notna(destination_cover)
                and pd.notna(destination_lead)
                and destination_cover < destination_lead
            )

            destination_is_critical = (
                bool(destination_row["shortage_risk"])
                if pd.notna(destination_row.get("shortage_risk"))
                else False
            )

            if not (
                destination_is_at_risk
                or destination_is_critical
            ):
                continue

            for _, source_row in sku_rows.iterrows():

                source = source_row["location"]

                if source == destination:
                    continue

                source_stock = source_row["stock"]
                source_demand = source_row["daily_demand"]

                if (
                    pd.isna(source_stock)
                    or pd.isna(source_demand)
                    or source_stock <= default_safety_buffer
                ):
                    continue

                transferable = max(
                    0,
                    math.floor(
                        source_stock - default_safety_buffer
                    ),
                )

                if transferable <= 0:
                    continue

                # Estimate enough stock to cover the destination's
                # lead time, using its observed daily demand.
                target_days = (
                    max(0, destination_lead)
                    if pd.notna(destination_lead)
                    else 1
                )

                target_stock = math.ceil(
                    destination_demand * target_days
                )

                recommended_qty = min(
                    transferable,
                    max(0, target_stock - destination_stock),
                )

                if recommended_qty <= 0:
                    continue

                opportunities.append({
                    "SKU": sku,
                    "Source Warehouse": source,
                    "Destination Warehouse": destination,
                    "Source Stock": source_stock,
                    "Destination Stock": destination_stock,
                    "Transfer Quantity": recommended_qty,
                    "Source Stock After Transfer": (
                        source_stock - recommended_qty
                    ),
                    "Destination Stock After Transfer": (
                        destination_stock + recommended_qty
                    ),
                    "Destination Stock Cover (days)": (
                        destination_cover
                    ),
                    "Safety Buffer": default_safety_buffer,
                    "Status": "REVIEW REQUIRED",
                })

    if opportunities:
        opportunity_df = pd.DataFrame(opportunities)

        opportunity_df = opportunity_df.sort_values(
            by=[
                "Destination Stock Cover (days)",
                "Transfer Quantity",
            ],
            ascending=[True, False],
            na_position="first",
        )

        st.success(
            f"Found {len(opportunity_df)} potential transfer "
            "opportunity/opportunities for review."
        )

        st.dataframe(
            opportunity_df,
            hide_index=True,
            width="stretch",
        )

        st.caption(
            "These are exploratory recommendations. The dashboard "
            "does not reserve stock, create a transfer transaction, "
            "or update inventory.csv. Confirm stock, demand, and "
            "safety buffers before using a recommendation."
        )

    else:
        st.info(
            "No potential transfers were found using the current "
            "stock, demand, lead-time, and safety-buffer rules."
        )

else:
    st.warning(
        "Transfer opportunity analysis requires sku, location, "
        "stock, and daily_demand columns."
    )


st.divider()


# ==========================================
# 4. TODAY'S PRIORITIES
# ==========================================
st.header("🚨 Today's Priorities")

if critical.empty:
    st.success(
        "No stock shortages detected by the current rules."
    )

else:
    st.error(
        f"{shortage_count} inventory record(s) need attention."
    )

    if "days_of_stock" in critical.columns:
        critical = critical.sort_values(
            "days_of_stock",
            ascending=True,
            na_position="first",
        )

    for _, row in critical.iterrows():
        name = row.get("name", row["sku"])

        with st.container(border=True):
            st.subheader(f"⚠️ {name} — {row['location']}")

            a, b, c, d = st.columns(4)

            a.metric(
                "Current Stock",
                f"{float(row['stock']):.0f}",
            )

            demand = pd.to_numeric(
                pd.Series([row["daily_demand"]]),
                errors="coerce",
            ).iloc[0]

            b.metric(
                "Daily Demand",
                f"{demand:.2f} units/day"
                if pd.notna(demand)
                else "Unknown",
            )

            days = row.get("days_of_stock")

            c.metric(
                "Days Remaining",
                f"{days:.1f}" if pd.notna(days) else "Unknown",
            )

            lead = row.get("fastest_lead_days")

            d.metric(
                "Fastest Lead Time",
                f"{lead:.0f} days"
                if pd.notna(lead)
                else "Unknown",
            )

            if (
                pd.notna(lead)
                and pd.notna(days)
                and days < lead
            ):
                st.warning(
                    f"Stock may run out in {days:.1f} days, "
                    f"but the fastest supplier needs {lead:.0f} days."
                )

            if "open_po_qty" in result.columns:
                open_qty = pd.to_numeric(
                    pd.Series([row.get("open_po_qty", 0)]),
                    errors="coerce",
                ).iloc[0]

                if pd.notna(open_qty) and open_qty > 0:
                    st.info(
                        f"Open PO quantity for this SKU: {open_qty:g} units. "
                        "Confirm destination and delivery status before relying on it."
                    )


# ==========================================
# 5. INVENTORY ANALYSIS
# ==========================================
st.header("📊 Inventory Analysis")

display_cols = [
    col
    for col in [
        "sku",
        "name",
        "location",
        "stock",
        "daily_demand",
        "days_of_stock",
        "fastest_lead_days",
        "open_po_qty",
        "overdue_po_count",
        "shortage_risk",
    ]
    if col in result.columns
]

inventory_view = result[display_cols].copy()

if "days_of_stock" in inventory_view.columns:
    inventory_view["days_of_stock"] = (
        inventory_view["days_of_stock"].replace(
            [float("inf"), float("-inf")],
            None,
        )
    )

st.dataframe(
    inventory_view,
    width="stretch",
    hide_index=True,
)


# ==========================================
# 6. PURCHASE ORDER ALERTS
# ==========================================
st.divider()
st.header("📋 Purchase Order Alerts")

if "overdue_po_count" in result.columns:
    overdue = result[
        pd.to_numeric(
            result["overdue_po_count"],
            errors="coerce",
        ).fillna(0) > 0
    ].copy()

    if overdue.empty:
        st.success("No overdue purchase orders detected.")

    else:
        st.error(
            f"{len(overdue)} inventory record(s) are linked "
            "to overdue purchase orders."
        )

        overdue_cols = [
            col
            for col in [
                "sku",
                "name",
                "location",
                "stock",
                "daily_demand",
                "days_of_stock",
                "open_po_qty",
                "overdue_po_count",
            ]
            if col in overdue.columns
        ]

        st.dataframe(
            overdue[overdue_cols],
            width="stretch",
            hide_index=True,
        )

else:
    st.warning(
        "Overdue PO analysis is unavailable. Check analysis.py."
    )


# ==========================================
# 7. OPEN PURCHASE ORDERS
# ==========================================
st.subheader("📦 Open Purchase Orders by SKU")

if "open_po_qty" in result.columns:
    po_cols = [
        col
        for col in [
            "sku",
            "name",
            "location",
            "open_po_qty",
        ]
        if col in result.columns
    ]

    st.dataframe(
        result[po_cols].drop_duplicates(
            subset=["sku", "location"]
        ),
        width="stretch",
        hide_index=True,
    )

else:
    st.info("Open PO quantities are not available.")


# ==========================================
# 8. GENERATE AN ACTION DRAFT
# ==========================================
st.divider()
st.header("📝 Prepare an Action Draft")

if critical.empty:
    st.info(
        "No shortage action is available under the current rules."
    )

else:
    options = [
        f"{row['sku']} — {row['location']}"
        for _, row in critical.iterrows()
    ]

    selected = st.selectbox(
        "Select a shortage to resolve",
        options,
        key="action_shortage_selection",
    )

    row = critical.iloc[options.index(selected)]

    st.write(
        f"Selected item: **{row['sku']}** at **{row['location']}**"
    )

    if st.button(
        "⚙️ Generate Recommendation",
        type="primary",
        key="generate_action",
    ):
        try:
            inventory = clean_columns(
                pd.read_csv(DATA_DIR / "inventory.csv")
            )

            sales = clean_columns(
                pd.read_csv(DATA_DIR / "sales.csv")
            )

            suppliers = clean_columns(
                pd.read_csv(DATA_DIR / "suppliers.csv")
            )

            products = clean_columns(
                pd.read_csv(DATA_DIR / "products.csv")
            )

            for df in [
                inventory,
                sales,
                suppliers,
                products,
            ]:
                if "sku" in df.columns:
                    df["sku"] = (
                        df["sku"].astype(str).str.strip()
                    )

            for df in [inventory, sales]:
                if "location" in df.columns:
                    df["location"] = (
                        df["location"].astype(str).str.strip()
                    )

            if (
                "stock" not in inventory.columns
                or "qty_sold" not in sales.columns
            ):
                raise ValueError(
                    "inventory.csv needs stock and sales.csv needs qty_sold."
                )

            inventory["stock"] = pd.to_numeric(
                inventory["stock"],
                errors="coerce",
            )

            sales["qty_sold"] = pd.to_numeric(
                sales["qty_sold"],
                errors="coerce",
            )

            if (
                inventory["stock"].isna().any()
                or sales["qty_sold"].isna().any()
            ):
                raise ValueError(
                    "Inventory stock or sales quantities contain invalid values."
                )

            action_draft = recommend_action(
                sku=str(row["sku"]).strip(),
                location=str(row["location"]).strip(),
                stock=float(row["stock"]),
                daily_demand=float(row["daily_demand"]),
                fastest_lead_days=float(
                    row["fastest_lead_days"]
                ),
                inventory=inventory,
                sales=sales,
                suppliers=suppliers,
                products=products,
            )

            action_draft = dict(action_draft)

            action_draft.setdefault(
                "sku", str(row["sku"]).strip()
            )
            action_draft.setdefault(
                "location", str(row["location"]).strip()
            )
            action_draft.setdefault(
                "stock", float(row["stock"])
            )
            action_draft.setdefault(
                "daily_demand", float(row["daily_demand"])
            )

            for col in [
                "days_of_stock",
                "fastest_lead_days",
                "open_po_qty",
                "overdue_po_count",
                "name",
            ]:
                if col in row.index:
                    key = (
                        "product_name"
                        if col == "name"
                        else col
                    )
                    action_draft.setdefault(key, row[col])

            action_draft["draft_id"] = str(uuid.uuid4())
            action_draft["created_at"] = now_iso()
            action_draft["status"] = PENDING

            st.session_state["action_draft"] = action_draft
            st.session_state["action_decision"] = PENDING

        except Exception as exc:
            st.error(f"Could not prepare action: {exc}")


# ==========================================
# 9. REVIEW ACTION DRAFT
# ==========================================
if "action_draft" in st.session_state:
    action_draft = st.session_state["action_draft"]

    st.subheader("📄 Proposed Action")

    action_type = str(
        action_draft.get("action", "REVIEW")
    ).upper()

    if action_type == "TRANSFER_DRAFT":
        st.info("Recommended action: Stock Transfer")

    elif action_type == "PO_DRAFT":
        st.info("Recommended action: Purchase Order")

    elif action_type == "MONITOR":
        st.info("Recommended action: Monitor Stock")

    else:
        st.warning("Recommended action: Manual Review")

    st.subheader("💡 Why SpareSense AI recommends this action")
    st.markdown(explain_recommendation(action_draft))

    with st.expander("View full recommendation data"):
        st.json(action_draft)

    st.caption(
        "Review the quantity, source or supplier, lead time, "
        "and estimated cost before deciding."
    )

    decision = st.session_state.get(
        "action_decision",
        action_draft.get("status", PENDING),
    )

    if decision == PENDING:
        left, right = st.columns(2)

        with left:
            if st.button(
                "✅ Approve Action Draft",
                type="primary",
                key="approve_action_draft",
            ):
                if action_draft.get("status") != PENDING:
                    st.error("This draft is no longer pending.")

                elif action_type not in {
                    "TRANSFER_DRAFT",
                    "PO_DRAFT",
                    "MONITOR",
                }:
                    st.error(
                        "Unknown action type. Cannot approve this draft."
                    )

                elif (
                    action_type in {"TRANSFER_DRAFT", "PO_DRAFT"}
                    and not positive_whole_number(
                        action_draft.get(
                            "quantity",
                            action_draft.get(
                                "qty",
                                action_draft.get("order_qty"),
                            ),
                        )
                    )
                ):
                    st.error(
                        "The proposed quantity must be a positive whole number."
                    )

                else:
                    st.session_state["action_decision"] = APPROVED
                    st.session_state["action_draft"]["status"] = APPROVED
                    st.session_state["action_draft"]["decided_at"] = (
                        now_iso()
                    )
                    st.rerun()

        with right:
            if st.button(
                "❌ Reject Action Draft",
                key="reject_action_draft",
            ):
                if action_draft.get("status") != PENDING:
                    st.error("This draft is no longer pending.")

                else:
                    st.session_state["action_decision"] = REJECTED
                    st.session_state["action_draft"]["status"] = REJECTED
                    st.session_state["action_draft"]["decided_at"] = (
                        now_iso()
                    )
                    st.rerun()

    elif decision == APPROVED:
        st.success(
            "Action draft approved for the demo. "
            "No stock transfer or purchase order was executed."
        )

    elif decision == REJECTED:
        st.warning(
            "Action draft rejected. No transaction executed."
        )

    if st.button(
        "🔄 Clear Action Draft",
        key="clear_action_draft",
    ):
        st.session_state.pop("action_draft", None)
        st.session_state.pop("action_decision", None)
        st.rerun()


# ==========================================
# 10. INVENTORY TRANSFER WORKFLOW
# ==========================================
st.divider()
st.header("🚚 Inventory Transfer Workflow")

st.write(
    "Prepare, review, and approve a proposed stock transfer "
    "between warehouse locations."
)

try:
    transfer_inventory = load_inventory_for_transfer()
    inventory_error = None

except Exception as exc:
    transfer_inventory = pd.DataFrame()
    inventory_error = str(exc)

if inventory_error:
    st.error(
        f"Transfer workflow unavailable: {inventory_error}"
    )

if not transfer_inventory.empty:
    skus = sorted(transfer_inventory["sku"].unique())

    if not skus:
        st.warning("No SKU records are available for transfers.")

    else:
        selected_sku = st.selectbox(
            "Transfer SKU",
            skus,
            key="transfer_sku",
        )

        sku_rows = transfer_inventory[
            transfer_inventory["sku"] == selected_sku
        ]

        destination_options = sorted(
            sku_rows["location"].unique()
        )

        if len(destination_options) < 2:
            st.warning(
                "This SKU must have stock records at two or more locations."
            )

        else:
            destination = st.selectbox(
                "Destination warehouse",
                destination_options,
                key="transfer_destination",
            )

            source_options = [
                loc
                for loc in destination_options
                if loc != destination
            ]

            source = st.selectbox(
                "Source warehouse",
                source_options,
                key="transfer_source",
            )

            source_row = sku_rows[
                sku_rows["location"] == source
            ].iloc[0]

            destination_row = sku_rows[
                sku_rows["location"] == destination
            ].iloc[0]

            source_stock = float(source_row["stock"])
            destination_stock = float(destination_row["stock"])

            st.subheader("Current Stock")

            col1, col2 = st.columns(2)

            col1.metric(
                f"{source} Stock",
                f"{source_stock:g} units",
            )

            col2.metric(
                f"{destination} Stock",
                f"{destination_stock:g} units",
            )

            max_source_whole = max(
                0,
                math.floor(source_stock),
            )

            safety_buffer = st.number_input(
                f"Minimum stock to retain at {source}",
                min_value=0,
                max_value=max_source_whole,
                value=min(6, max_source_whole),
                step=1,
                key="transfer_safety_buffer",
            )

            max_transfer = max(
                0,
                math.floor(source_stock - safety_buffer),
            )

            st.caption(
                f"Maximum transferable quantity: {max_transfer} units."
            )

            if max_transfer <= 0:
                st.warning(
                    "No whole units are available to transfer "
                    "without breaching the safety buffer."
                )

            else:
                transfer_qty = st.number_input(
                    "Transfer quantity",
                    min_value=1,
                    max_value=max_transfer,
                    value=min(1, max_transfer),
                    step=1,
                    key="transfer_quantity",
                )

                if st.button(
                    "📝 Generate Transfer Draft",
                    type="primary",
                    key="generate_transfer",
                ):
                    st.session_state["transfer_draft"] = {
                        "draft_id": str(uuid.uuid4()),
                        "action": "TRANSFER_DRAFT",
                        "sku": selected_sku,
                        "from_location": source,
                        "to_location": destination,
                        "quantity": int(transfer_qty),
                        "donor_stock": source_stock,
                        "destination_stock": destination_stock,
                        "donor_safety_buffer": int(safety_buffer),
                        "status": PENDING,
                        "created_at": now_iso(),
                        "reason": (
                            f"Transfer {int(transfer_qty)} units from "
                            f"{source} to {destination}. Review the "
                            "proposal before approval."
                        ),
                    }

                    st.rerun()


# ==========================================
# 11. REVIEW AND APPROVE TRANSFER
# ==========================================
transfer_draft = st.session_state.get("transfer_draft")

if transfer_draft:
    st.divider()
    st.subheader("📋 Transfer Proposal")
    st.json(transfer_draft)

    decision = transfer_draft.get("status", PENDING)

    if decision == PENDING:
        st.warning(
            "Approval only records your decision. It does not modify "
            "inventory.csv or physically move stock."
        )

        approve_col, reject_col = st.columns(2)

        with approve_col:
            if st.button(
                "✅ Approve Transfer",
                type="primary",
                key="approve_transfer",
            ):
                try:
                    # Reload current inventory at approval time.
                    fresh_inventory = load_inventory_for_transfer()

                    fresh_draft = st.session_state.get(
                        "transfer_draft", {}
                    )

                    error = validate_transfer_draft(
                        fresh_draft,
                        fresh_inventory,
                    )

                    if error:
                        st.error("Approval blocked: " + error)

                    else:
                        fresh_draft["status"] = APPROVED
                        fresh_draft["decided_at"] = now_iso()

                        st.session_state["transfer_draft"] = fresh_draft
                        st.rerun()

                except Exception as exc:
                    st.error(
                        "Approval blocked: could not validate "
                        f"current inventory: {exc}"
                    )

        with reject_col:
            if st.button(
                "❌ Reject Transfer",
                key="reject_transfer",
            ):
                fresh_draft = st.session_state.get(
                    "transfer_draft", {}
                )

                if fresh_draft.get("status") != PENDING:
                    st.error("This transfer is no longer pending.")

                else:
                    fresh_draft["status"] = REJECTED
                    fresh_draft["decided_at"] = now_iso()

                    st.session_state["transfer_draft"] = fresh_draft
                    st.rerun()

    elif decision == APPROVED:
        st.success(
            "Transfer proposal approved. Inventory has not been changed "
            "and no physical transfer was executed."
        )

    elif decision == REJECTED:
        st.info(
            "Transfer proposal rejected. No stock was moved."
        )

    else:
        st.error(
            f"Unknown transfer decision status: {decision!r}. "
            "Do not save this draft."
        )

    if transfer_draft.get("status") in {APPROVED, REJECTED}:
        st.caption(
            "Save the final decision to the local transfer history CSV."
        )

        if st.button(
            "💾 Save Decision to History",
            key="save_transfer_history",
        ):
            try:
                draft_id = str(
                    transfer_draft.get("draft_id", "")
                ).strip()

                status = transfer_draft.get("status")

                if not draft_id:
                    st.error(
                        "Draft ID is missing; decision cannot be saved."
                    )

                elif status not in {APPROVED, REJECTED}:
                    st.error(
                        "Only approved or rejected decisions can be saved."
                    )

                else:
                    DATA_DIR.mkdir(
                        parents=True,
                        exist_ok=True,
                    )

                    new_record = pd.DataFrame([transfer_draft])

                    if HISTORY_FILE.exists():
                        old_history = pd.read_csv(
                            HISTORY_FILE,
                            dtype=str,
                        )

                        # Repair older history files that lack draft_id.
                        if "draft_id" not in old_history.columns:
                            old_history.insert(
                                0,
                                "draft_id",
                                "",
                            )

                        # Preserve existing columns and add new ones.
                        all_columns = list(old_history.columns)

                        for column in new_record.columns:
                            if column not in all_columns:
                                all_columns.append(column)

                        old_history = old_history.reindex(
                            columns=all_columns
                        )

                        new_record = new_record.reindex(
                            columns=all_columns
                        )

                        # Prevent saving this draft more than once.
                        existing_ids = (
                            old_history["draft_id"]
                            .fillna("")
                            .astype(str)
                            .str.strip()
                        )

                        if existing_ids.eq(draft_id).any():
                            st.info(
                                "This transfer decision is already saved."
                            )

                        else:
                            history = pd.concat(
                                [old_history, new_record],
                                ignore_index=True,
                            )

                            history.to_csv(
                                HISTORY_FILE,
                                index=False,
                            )

                            st.success(
                                "Transfer decision saved to "
                                "data/transfer_history.csv."
                            )

                    else:
                        new_record.to_csv(
                            HISTORY_FILE,
                            index=False,
                        )

                        st.success(
                            "Transfer decision saved to "
                            "data/transfer_history.csv."
                        )

            except pd.errors.EmptyDataError:
                st.error(
                    "The history CSV is empty or invalid. "
                    "Back it up and check its contents before saving."
                )

            except Exception as exc:
                st.error(
                    f"Could not save transfer history: {exc}"
                )


# ==========================================
# 12. TRANSFER DECISION HISTORY
# ==========================================
st.divider()
st.subheader("📚 Transfer Decision History")

if HISTORY_FILE.exists():
    try:
        saved_history = pd.read_csv(HISTORY_FILE)

        if saved_history.empty:
            st.info(
                "No transfer decisions have been saved."
            )

        else:
            st.dataframe(
                saved_history,
                width="stretch",
                hide_index=True,
            )

    except Exception as exc:
        st.error(
            f"Could not read transfer history: {exc}"
        )

else:
    st.info(
        "No transfer decisions have been saved yet."
    )


# ==========================================
# 13. FOOTER
# ==========================================
st.divider()

st.caption(
    "SpareSense AI | Hackathon Demo | "
    "Rule-based recommendations • Human approval required • "
    "No real purchase orders or stock transfers are executed"
)
