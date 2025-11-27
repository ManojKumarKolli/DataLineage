# apps/graphrag_api/app.py
import os, sqlite3
from fastapi import FastAPI, Query, Body, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.responses import RedirectResponse
from pydantic import BaseModel
from typing import Dict, Any, List, Optional
from neo4j import GraphDatabase

from core.graphrag.graphrag_router import GraphRAG
from core.cortex.sql_router import CortexSQLRouter
from core.common.llm_summarizer import NLMSummarizer
from core.config.settings import (
    NEO4J_URI, NEO4J_USER, NEO4J_PASS, NEO4J_DB, CORS_ALLOW_ORIGINS, SQLITE_PATH
)

from core.lineage.lineage_router import LineageService, LINEAGE_DB_PATH


RUNTIME_MODEL = os.getenv("CAPGEMINI_MODEL", "anthropic.claude-3-5-sonnet-20241022-v2:0").strip()

app = FastAPI(title="GraphRAG + Cortex API (LLM-only)", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ALLOW_ORIGINS if CORS_ALLOW_ORIGINS != ["*"] else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if os.path.isdir("ui"):
    app.mount("/ui", StaticFiles(directory="ui", html=True), name="ui")

# --- add near the existing UI mounts ---
if os.path.isdir("ui/presentation"):
    # Correct spelling
    app.mount("/presentation", StaticFiles(directory="ui/presentation", html=True), name="presentation")

# instantiate service (after other engines)
lineage = LineageService()

# mount the new UI (next to /ui and /presentation)
if os.path.isdir("ui/lineage"):
    app.mount("/lineage", StaticFiles(directory="ui/lineage", html=True), name="lineage")

@app.get("/", include_in_schema=False)
def root_redirect():
    return RedirectResponse(url="/ui")

# Engines (LLM-only)
rag = GraphRAG(uri=NEO4J_URI, user=NEO4J_USER, password=NEO4J_PASS, database=NEO4J_DB, model_name=RUNTIME_MODEL)
sql = CortexSQLRouter(yaml_path="core/cortex/semantic.yaml", sqlite_path=SQLITE_PATH, model_name=RUNTIME_MODEL)
from core.common.llm_summarizer import NLMSummarizer

nlg = NLMSummarizer()  # uses Kimi HF model under the hood

class AskGraphResponse(BaseModel):
    intent: str
    cypher: str
    params: dict
    columns: list
    rows: list
    summary: str
    answer: str
    graph: dict | None = None
    source: str | None = None

class AskSQLResponse(BaseModel):
    sql: str
    columns: list
    rows: list
    summary: str
    answer: str
    source: str | None = None

@app.get("/config")
def config():
    return {"llm_model": RUNTIME_MODEL, "sqlite_path": SQLITE_PATH, "neo4j_db": NEO4J_DB}

@app.post("/config/model")
def set_model(model: str = Body(..., embed=True)):
    """Switch LLM model at runtime (single-mode LLM)."""
    global RUNTIME_MODEL
    model = (model or "").strip()
    if not model:
        raise HTTPException(status_code=400, detail="Model cannot be empty")
    RUNTIME_MODEL = model
    rag.set_model(model); sql.set_model(model); nlg.model_name = model
    return {"ok": True, "llm_model": RUNTIME_MODEL}

@app.get("/health")
def health():
    return {"status": "ok", "db": NEO4J_DB, "sqlite": SQLITE_PATH, "model": RUNTIME_MODEL}

@app.get("/tables/preview")
def tables_preview(limit: int = Query(5, ge=1, le=100)):
    if not os.path.exists(SQLITE_PATH):
        raise HTTPException(status_code=404, detail=f"SQLite DB not found at {SQLITE_PATH}")
    con = sqlite3.connect(SQLITE_PATH)
    cur = con.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;")
    tbls = [r[0] for r in cur.fetchall()]
    out = []
    for t in tbls:
        if t.startswith("sqlite_"):
            continue
        cur.execute(f"PRAGMA table_info({t});")
        cols = [r[1] for r in cur.fetchall()]
        cur.execute(f"SELECT * FROM {t} LIMIT {limit};")
        rows = cur.fetchall()
        out.append({"table": t, "columns": cols, "rows": rows})
    con.close()
    return out

@app.get("/ask")
def ask(q: str = Query(...), include_graph: bool = Query(True)):
    """
    GraphRAG ask: returns Cypher + rows + graph (optional).
    We intentionally omit 'answer' so UI mirrors SQL behavior (query + results).
    """
    result = rag.answer(q)
    if not result["rows"]:
        raise HTTPException(status_code=404, detail="No data found for that graph question.")

    graph_payload = None
    if include_graph:
        viz_cypher = rag.viz_cypher_for(result["intent"], result["params"])
        if viz_cypher:
            graph_payload = _run_viz_cypher(viz_cypher, result["params"])

    # Return only what UI needs for parity with SQL
    return {
        "cypher": result["cypher"],
        "columns": result["columns"],
        "rows": result["rows"],
        "graph": graph_payload,   # nodes/links for viz
        "source": rag.last_source
    }


@app.get("/ask-sql")
def ask_sql(q: str = Query(...)):
    res = sql.answer(q)
    if not res["rows"]:
        raise HTTPException(status_code=404, detail="No data found for that SQL question.")

    # Generate natural-language summary with NLMSummarizer
    explanation = nlg.summarize(
        q,
        res["columns"],
        res["rows"],
        flavor="SQL",
        source=res.get("source"),
    )

    # Use it both as 'answer' (chat bubble) and 'summary' (Result panel)
    res["answer"] = explanation
    res["summary"] = explanation

    return res




@app.post("/viz")
def viz(cypher: str = Body(None), params: dict = Body(default={})):
    if not cypher:
        cypher = "MATCH (c:Customer)-[r:OWNS]->(a:Account) RETURN c,r,a LIMIT 200"
    return _run_viz_cypher(cypher, params)

def _run_viz_cypher(cypher: str, params: Dict[str, Any]) -> Dict[str, Any]:
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASS))
    out = {"nodes": [], "links": []}
    node_index = {}
    from neo4j.graph import Node, Relationship, Path
    try:
        with driver.session(database=NEO4J_DB) as s:
            res = s.run(cypher, **params)
            for record in res:
                for v in record.values():
                    if isinstance(v, Node):
                        _add_node(v, out, node_index)
                    elif isinstance(v, Relationship):
                        _add_rel(v, out, node_index)
                    elif isinstance(v, Path):
                        for n in v.nodes:
                            _add_node(n, out, node_index)
                        for r in v.relationships:
                            _add_rel(r, out, node_index)
    finally:
        driver.close()
    return out

def _add_node(n, out, node_index):
    nid = str(n.id)
    if nid in node_index: 
        return
    label = next(iter(n.labels)) if n.labels else "Node"
    out["nodes"].append({"id": nid, "label": label, "props": dict(n)})
    node_index[nid] = True

def _add_rel(r, out, node_index):
    sid, tid = str(r.start_node.id), str(r.end_node.id)
    if sid not in node_index:
        _add_node(r.start_node, out, node_index)
    if tid not in node_index:
        _add_node(r.end_node, out, node_index)
    out["links"].append({"source": sid, "target": tid, "type": r.type, "props": dict(r)})


# ---- Lineage API ----
@app.post("/lineage-api/seed")
def lineage_seed():
    return lineage.seed_demo_balances()

@app.get("/lineage-api/catalog")
def lineage_catalog():
    return lineage.catalog()

@app.get("/lineage-api/graph")
def lineage_graph():
    return lineage.lineage_graph()

@app.get("/lineage-api/trace")
def lineage_trace(start: str = Query(...), end: str = Query(...)):
    return lineage.trace(start, end)


@app.get("/lineage-api/reconcile")
def lineage_reconcile_entity(
    focusBy: str = Query("account", regex="^(account|customer)$"),
    identifier: str = Query(..., description="Account ID or customer key"),
    issue: str = Query("", description="Free-text description of the problem"),
    model: str | None = Query(None, description="Override LLM model for narrative (optional)")
):
    """
    Entity-level reconcile used by the UI.

    - focusBy: 'account' or 'customer'
    - identifier: e.g. '102' or 'Asha Patel'
    - issue: free-text, passed into narrative generator
    """

    # 1) balances across stages
    bal = lineage.balances_across_stages(by=focusBy, key=identifier)
    if not bal.get("ok"):
        raise HTTPException(status_code=400, detail=bal.get("error", "balances_across_stages failed"))

    # 2) row-level diffs
    diffs = lineage.diffs(by=focusBy, key=identifier)
    if not diffs.get("ok"):
        raise HTTPException(status_code=400, detail=diffs.get("error", "diffs failed"))

    # ---------- Build metrics + raw→stage→mart path ----------
    metrics: Dict[str, Any] = {}
    path: List[Dict[str, Any]] = []

    def _delta(prev: Optional[float], curr: Optional[float]) -> tuple[Optional[float], Optional[float]]:
        if prev is None or curr is None:
            return (None, None)
        d = curr - prev
        pct = None if prev == 0 else d / prev
        return (d, pct)

    if bal.get("by") == "account":
        raw_row = bal.get("raw")
        stage_row = bal.get("stage")
        mart_total = bal.get("mart_customer_total")
        fees = bal.get("fees")

        raw_bal = raw_row[3] if raw_row else None  # (account_id, customer_id, account_type, balance)
        stage_bal = stage_row[3] if stage_row else None
        mart_bal = mart_total

        # raw node
        if raw_bal is not None:
            path.append({
                "stage": "raw",
                "label": "Raw accounts",
                "balance": raw_bal,
                "delta_balance": None,
                "delta_percent": None,
                "txn_count": None,
            })

        # stage node
        if stage_bal is not None:
            d, pct = _delta(raw_bal, stage_bal) if raw_bal is not None else (None, None)
            path.append({
                "stage": "stage",
                "label": "Stage accounts",
                "balance": stage_bal,
                "delta_balance": d,
                "delta_percent": pct,
                "txn_count": None,
            })

        # mart node (customer rollup)
        if mart_bal is not None:
            base = stage_bal if stage_bal is not None else raw_bal
            d, pct = _delta(base, mart_bal) if base is not None else (None, None)
            path.append({
                "stage": "mart",
                "label": "Customer balance mart",
                "balance": mart_bal,
                "delta_balance": d,
                "delta_percent": pct,
                "txn_count": None,
            })

        metrics = {
            "raw_balance": raw_bal,
            "stage_balance": stage_bal,
            "mart_balance": mart_bal,
            "gross_drift": (mart_bal - raw_bal) if raw_bal is not None and mart_bal is not None else None,
            "fees_for_account": fees,
        }

    elif bal.get("by") == "customer":
        totals = bal.get("totals", {})
        raw_bal = totals.get("raw")
        stage_bal = totals.get("stage")
        mart_bal = totals.get("mart")
        fees = totals.get("fees")

        # raw node
        if raw_bal is not None:
            path.append({
                "stage": "raw",
                "label": "Raw accounts",
                "balance": raw_bal,
                "delta_balance": None,
                "delta_percent": None,
                "txn_count": None,
            })

        # stage node
        if stage_bal is not None:
            d, pct = _delta(raw_bal, stage_bal) if raw_bal is not None else (None, None)
            path.append({
                "stage": "stage",
                "label": "Stage accounts",
                "balance": stage_bal,
                "delta_balance": d,
                "delta_percent": pct,
                "txn_count": None,
            })

        # mart node
        if mart_bal is not None:
            base = stage_bal if stage_bal is not None else raw_bal
            d, pct = _delta(base, mart_bal) if base is not None else (None, None)
            path.append({
                "stage": "mart",
                "label": "Customer balance mart",
                "balance": mart_bal,
                "delta_balance": d,
                "delta_percent": pct,
                "txn_count": None,
            })

        metrics = {
            "raw_balance": raw_bal,
            "stage_balance": stage_bal,
            "mart_balance": mart_bal,
            "gross_drift": (mart_bal - raw_bal) if raw_bal is not None and mart_bal is not None else None,
            "fees_total": fees,
        }

    # ---------- Convert diffs(rows+columns) into list-of-objects ----------
    cols_raw = diffs.get("columns") or []
    rows_raw = diffs.get("rows") or []

    diff_objects: List[Dict[str, Any]] = []
    for r in rows_raw:
        if isinstance(r, (list, tuple)):
            obj = {}
            for i, col in enumerate(cols_raw):
                obj[col] = r[i] if i < len(r) else None
            diff_objects.append(obj)
        elif isinstance(r, dict):
            diff_objects.append(r)
        else:
            # fallback: wrap as a single-column row
            diff_objects.append({"value": r})

    # ---------- Metrics from diffs (discrepancies) ----------
    discrepant_accounts = 0
    max_var_pct: Optional[float] = None
    for r in rows_raw:
        if isinstance(r, (list, tuple)) and len(r) >= 4:
            delta_val = r[3]
            raw_val = r[1]
            if delta_val is not None and abs(delta_val) > 0.01:
                discrepant_accounts += 1
                if raw_val not in (None, 0):
                    pct = abs(delta_val) / abs(raw_val)
                    if max_var_pct is None or pct > max_var_pct:
                        max_var_pct = pct

    metrics["discrepant_accounts"] = discrepant_accounts
    metrics["max_variance_percent"] = max_var_pct

    # ---------- LLM narrative ----------
    nar_payload = {
        "focus_by": focusBy,
        "identifier": identifier,
        "issue": issue,
        "balances": bal,
        "diffs": diffs,
    }
    nar = lineage.narrative(nar_payload, model_name=model or os.getenv("CAPGEMINI_MODEL"))

    return {
        "metrics": metrics,
        "path": path,
        "diffs": diff_objects,
        "narrative": nar.get("summary") if nar and nar.get("ok") else None,
    }


@app.get("/lineage-api/audit/balances")
def lineage_audit_balances(by: str = Query(..., pattern="^(customer|account)$"), key: str = Query(...), model: str = Query(None)):
    res = lineage.balances_across_stages(by, key)
    if not res.get("ok"):
        raise HTTPException(status_code=400, detail=res.get("error","invalid request"))
    # attach optional LLM narrative
    nar = lineage.narrative(res, model_name=model or os.getenv("CAPGEMINI_MODEL"))
    if nar.get("ok"):
        res["narrative"] = nar["summary"]
    return res

@app.get("/lineage-api/audit/diff")
def lineage_audit_diff(by: str = Query(..., pattern="^(customer|account)$"), key: str = Query(...), model: str = Query(None)):
    res = lineage.diffs(by, key)
    if not res.get("ok"):
        raise HTTPException(status_code=400, detail=res.get("error","invalid request"))
    # attach optional LLM narrative
    nar = lineage.narrative(res, model_name=model or os.getenv("CAPGEMINI_MODEL"))
    if nar.get("ok"):
        res["narrative"] = nar["summary"]
    return res

@app.post("/lineage-api/alerts/run")
def lineage_alerts_run():
    return lineage.run_alerts()

@app.get("/lineage-api/alerts")
def lineage_alerts(only_open: int = Query(1)):
    return lineage.list_alerts(only_open=bool(only_open))

@app.get("/lineage-api/tables/preview")
def lineage_tables_preview(limit: int = Query(5, ge=1, le=100)):
    return lineage.preview_tables(limit=limit)

@app.get("/lineage-api/preview")
def lineage_preview(limit: int = Query(5, ge=1, le=100)):
    """
    UI-friendly alias to preview lineage tables.
    Shape expected: { "tables": [ {name, stage, columns, rows}, ... ] }
    """
    res = lineage.preview_tables(limit=limit)

    # If preview_tables already returns {"tables": [...]}, just return.
    if isinstance(res, dict) and "tables" in res:
        return res

    # Otherwise, wrap bare list into {"tables": list}
    if isinstance(res, list):
        return {"tables": res}

    # Fallback: just return whatever we got.
    return {"tables": [res]}


@app.get("/lineage-api/health")
def lineage_health():
    """
    Simple health check for the lineage subsystem.
    The UI just wants to know 'is lineage alive?'.
    """
    try:
        # If your lineage engine has its own health / ping, call it here.
        info = {}
        if hasattr(lineage, "health"):
            info = lineage.health()
        return {"status": "ok", **info}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Lineage health failed: {e}")

@app.get("/lineage-api/summary")
def lineage_summary():
    """
    Stage-level summary used by the UI for the Stage Overview cards.
    We adapt lineage.catalog() into { "stages": [...] }.
    """
    cat = lineage.catalog()  # whatever your lineage engine returns

    # If catalog already returns {"stages": [...]}, just pass it through.
    if isinstance(cat, dict) and "stages" in cat:
        return cat

    # Otherwise, assume catalog is a list of stage entries or a dict of stage_id -> info.
    stages_raw = []
    if isinstance(cat, list):
        stages_raw = cat
    elif isinstance(cat, dict):
        # e.g. {"raw": {...}, "stage": {...}, "mart": {...}}
        for sid, meta in cat.items():
            if isinstance(meta, dict):
                m = meta.copy()
                m.setdefault("stage_id", sid)
                stages_raw.append(m)

    # Normalize minimal fields for the UI, with safe defaults.
    stages = []
    for s in stages_raw:
        stages.append({
            "stage_id": s.get("stage_id") or s.get("name") or s.get("id"),
            "label": s.get("label") or s.get("stage_id") or s.get("name"),
            "role": s.get("role") or s.get("description", ""),
            "row_count": s.get("row_count", 0),
            "total_balance": s.get("total_balance", 0.0),
            "variance_vs_prev": s.get("variance_vs_prev"),
            "issues_count": s.get("issues_count", 0),
        })

    return {"stages": stages}

@app.get("/lineage-api/summary")
def lineage_summary():
    """
    Stage-level summary used by the UI for the Stage Overview cards.
    """
    return lineage.stage_summary()

