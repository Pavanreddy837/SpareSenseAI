from __future__ import annotations
import math, uuid, sys
from datetime import datetime
from pathlib import Path
from typing import Any
import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
HISTORY = DATA / "transfer_history.csv"
sys.path.insert(0, str(ROOT))

try:
    from analysis import detect_stock_shortages
except Exception as exc:
    detect_stock_shortages = None
    ANALYSIS_IMPORT_ERROR = str(exc)
else:
    ANALYSIS_IMPORT_ERROR = None

try:
    from actions import recommend_action
except Exception as exc:
    recommend_action = None
    ACTION_IMPORT_ERROR = str(exc)
else:
    ACTION_IMPORT_ERROR = None

app = FastAPI(title="SpareSense AI API", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=False,
                   allow_methods=["*"], allow_headers=["*"])

def now_iso(): return datetime.now().isoformat(timespec="seconds")
def clean(df): 
    df = df.copy()
    df.columns = df.columns.astype(str).str.strip().str.lower()
    return df

def safe_value(v):
    if v is None: return None
    try:
        if pd.isna(v): return None
    except (TypeError, ValueError): pass
    if hasattr(v, "item"):
        try: v = v.item()
        except Exception: pass
    if isinstance(v, (pd.Timestamp, datetime)): return v.isoformat()
    if isinstance(v, float) and not math.isfinite(v): return None
    return v

def records(df):
    return [{str(k): safe_value(v) for k,v in row.items()} for row in df.to_dict(orient="records")]

def load_csv(name, required=False):
    path = DATA / name
    if not path.exists():
        if required: raise HTTPException(400, f"Required file not found: data/{name}")
        return pd.DataFrame()
    try: return clean(pd.read_csv(path))
    except Exception as e: raise HTTPException(400, f"Could not read data/{name}: {e}")

def load_inventory():
    df = load_csv("inventory.csv", True)
    needed = {"sku", "location", "stock"}
    if not needed.issubset(df.columns):
        raise HTTPException(400, "inventory.csv must contain sku, location, stock")
    df["sku"] = df["sku"].astype(str).str.strip()
    df["location"] = df["location"].astype(str).str.strip()
    df["stock"] = pd.to_numeric(df["stock"], errors="coerce")
    if df[["sku","location","stock"]].isna().any().any() or (df["stock"] < 0).any():
        raise HTTPException(400, "Inventory has missing, nonnumeric, or negative values.")
    df = df.drop_duplicates().copy()
    conflict = df.duplicated(["sku","location"], keep=False)
    if conflict.any():
        raise HTTPException(400, "Conflicting duplicate SKU/location rows in inventory.csv; resolve them before approving transfers.")
    return df

class ActionRequest(BaseModel):
    sku: str
    location: str

class TransferRequest(BaseModel):
    sku: str
    from_location: str
    to_location: str
    quantity: int = Field(gt=0)
    donor_safety_buffer: int = Field(ge=0, default=6)

class DecisionRequest(BaseModel):
    draft_id: str
    decision: str

@app.get("/api/health")
def health():
    return {"ok": True, "project_root": str(ROOT), "analysis_available": detect_stock_shortages is not None,
            "analysis_error": ANALYSIS_IMPORT_ERROR, "action_available": recommend_action is not None,
            "action_error": ACTION_IMPORT_ERROR, "data_dir_exists": DATA.exists()}

@app.get("/api/dashboard")
def dashboard():
    if detect_stock_shortages is None:
        raise HTTPException(500, "Could not import detect_stock_shortages from analysis.py: " + str(ANALYSIS_IMPORT_ERROR))
    try:
        result = detect_stock_shortages()
        if result is None: result = pd.DataFrame()
        result = clean(result)
        inv = load_csv("inventory.csv")
        sales = load_csv("sales.csv")
        suppliers = load_csv("suppliers.csv")
        products = load_csv("products.csv")
        pos = load_csv("purchase_orders.csv")
        if result.empty:
            return {"rows": [], "inventory": records(inv), "sales": records(sales), "suppliers": records(suppliers),
                    "products": records(products), "purchase_orders": records(pos), "metrics": {"records":0,"shortages":0,"locations":0,"overdue":0}}
        shortage_col = result["shortage_risk"].fillna(False).astype(bool) if "shortage_risk" in result else pd.Series(False, index=result.index)
        overdue = pd.to_numeric(result["overdue_po_count"], errors="coerce").fillna(0).sum() if "overdue_po_count" in result else 0
        return {"rows": records(result), "inventory": records(inv), "sales": records(sales), "suppliers": records(suppliers),
                "products": records(products), "purchase_orders": records(pos),
                "metrics": {"records": int(len(result)), "shortages": int(shortage_col.sum()),
                            "locations": int(result.loc[shortage_col,"location"].nunique()) if "location" in result else 0,
                            "overdue": int(overdue)}}
    except HTTPException: raise
    except Exception as e: raise HTTPException(500, f"Inventory analysis failed: {e}")

@app.post("/api/actions/draft")
def create_action(req: ActionRequest):
    if recommend_action is None:
        raise HTTPException(500, "Could not import recommend_action from actions.py: " + str(ACTION_IMPORT_ERROR))
    try:
        dash = dashboard()
        rows = pd.DataFrame(dash["rows"])
        hit = rows[(rows.get("sku", pd.Series(dtype=str)).astype(str) == req.sku) &
                   (rows.get("location", pd.Series(dtype=str)).astype(str) == req.location)]
        if hit.empty: raise HTTPException(404, "That SKU/location was not found in the current analysis.")
        row = hit.iloc[0]
        inv, sales, suppliers, products = [load_csv(n, True) for n in ("inventory.csv","sales.csv","suppliers.csv","products.csv")]
        for df in (inv,sales,suppliers,products):
            if "sku" in df: df["sku"] = df["sku"].astype(str).str.strip()
        for df in (inv,sales):
            if "location" in df: df["location"] = df["location"].astype(str).str.strip()
        draft = dict(recommend_action(sku=req.sku, location=req.location,
            stock=float(row.get("stock",0)), daily_demand=float(row.get("daily_demand",0) or 0),
            fastest_lead_days=float(row.get("fastest_lead_days",0) or 0),
            inventory=inv, sales=sales, suppliers=suppliers, products=products))
        draft.setdefault("sku", req.sku); draft.setdefault("location", req.location)
        for col in ("stock","daily_demand","days_of_stock","fastest_lead_days","open_po_qty","overdue_po_count","name"):
            if col in row and col not in draft: draft["product_name" if col=="name" else col] = safe_value(row[col])
        draft.update({"draft_id": str(uuid.uuid4()), "created_at": now_iso(), "status":"PENDING_APPROVAL"})
        return {"draft": {k:safe_value(v) for k,v in draft.items()},
                "note":"Proposal only. Approval records a decision; no purchase order or stock movement is executed."}
    except HTTPException: raise
    except Exception as e: raise HTTPException(500, f"Could not prepare action draft: {e}")

@app.post("/api/transfers/draft")
def create_transfer(req: TransferRequest):
    inv = load_inventory()
    if req.from_location == req.to_location: raise HTTPException(400, "Source and destination must differ.")
    src = inv[(inv.sku==req.sku)&(inv.location==req.from_location)]
    dst = inv[(inv.sku==req.sku)&(inv.location==req.to_location)]
    if len(src)!=1 or len(dst)!=1: raise HTTPException(400, "Source and destination inventory rows must each exist exactly once.")
    ss, ds = float(src.iloc[0].stock), float(dst.iloc[0].stock)
    if ss - req.quantity < req.donor_safety_buffer: raise HTTPException(400, "Transfer would reduce source stock below the safety buffer.")
    return {"draft":{"draft_id":str(uuid.uuid4()),"action":"TRANSFER_DRAFT","sku":req.sku,
        "from_location":req.from_location,"to_location":req.to_location,"quantity":req.quantity,
        "donor_stock":ss,"destination_stock":ds,"donor_safety_buffer":req.donor_safety_buffer,
        "status":"PENDING_APPROVAL","created_at":now_iso(),
        "reason":f"Proposed transfer of {req.quantity} units from {req.from_location} to {req.to_location}.",
        "estimated_source_after":ss-req.quantity,"estimated_destination_after":ds+req.quantity},
        "note":"Draft only. No inventory file is modified."}

@app.post("/api/decisions")
def decide(req: DecisionRequest):
    if req.decision not in ("APPROVED","REJECTED"): raise HTTPException(400, "Decision must be APPROVED or REJECTED.")
    # Decisions are deliberately kept in a local decision ledger. They do not trigger real-world actions.
    ledger = DATA / "action_decisions.csv"
    DATA.mkdir(parents=True, exist_ok=True)
    old = pd.read_csv(ledger) if ledger.exists() else pd.DataFrame()
    if "draft_id" in old and old["draft_id"].astype(str).eq(req.draft_id).any():
        raise HTTPException(409, "A decision for this draft has already been saved.")
    row = {"draft_id":req.draft_id,"status":req.decision,"decided_at":now_iso(),
           "execution_status":"NOT_EXECUTED"}
    pd.concat([old,pd.DataFrame([row])],ignore_index=True,sort=False).to_csv(ledger,index=False)
    return {"saved":True,"decision":row,"note":"Decision saved only; no real purchase order or transfer was executed."}

@app.post("/api/transfers/decision")
def transfer_decision(req: DecisionRequest):
    if req.decision not in ("APPROVED","REJECTED"): raise HTTPException(400, "Decision must be APPROVED or REJECTED.")
    # The frontend posts the full draft to /api/transfers/history after a decision.
    return {"draft_id":req.draft_id,"status":req.decision,"decided_at":now_iso(),
            "note":"Decision recorded in the interface; stock was not moved. Save the decision to history to persist it."}

@app.post("/api/transfers/history")
def save_transfer_history(draft: dict[str, Any]):
    if draft.get("status") not in ("APPROVED","REJECTED"): raise HTTPException(400, "Only approved/rejected transfer decisions can be saved.")
    if not str(draft.get("draft_id","")).strip(): raise HTTPException(400, "draft_id is required.")
    DATA.mkdir(parents=True,exist_ok=True)
    old = pd.read_csv(HISTORY) if HISTORY.exists() else pd.DataFrame()
    if "draft_id" not in old: old.insert(0,"draft_id","")
    if old["draft_id"].fillna("").astype(str).str.strip().eq(str(draft["draft_id"])).any():
        return {"saved":False,"message":"This decision is already in history."}
    pd.concat([old,pd.DataFrame([draft])],ignore_index=True,sort=False).to_csv(HISTORY,index=False)
    return {"saved":True,"message":"Transfer decision saved to data/transfer_history.csv. No stock was changed."}

@app.get("/api/transfers/history")
def transfer_history():
    return records(load_csv("transfer_history.csv"))

@app.get("/api/files/{filename}")
def get_file(filename: str):
    allowed={"inventory.csv","sales.csv","suppliers.csv","products.csv","purchase_orders.csv"}
    if filename not in allowed: raise HTTPException(404,"Unknown data file.")
    return {"filename":filename,"rows":records(load_csv(filename))}

app.mount("/", StaticFiles(directory=ROOT/"frontend", html=True), name="frontend")
