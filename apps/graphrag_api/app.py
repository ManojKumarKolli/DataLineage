# apps/graphrag_api/app.py
import os, re, sqlite3
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


@app.post("/lineage-api/ask")
def lineage_ask_question(
    question: str = Body(..., description="Natural language question about data lineage", embed=True),
    model: str | None = Body(None, description="Override LLM model (optional)", embed=True)
):
    """
    Natural language question interface for data lineage investigations.
    
    Accepts any user question and intelligently extracts:
    - What entity to investigate (account, customer, transaction, etc.)
    - What metric to focus on (balance, transactions, fees, etc.)
    - Which identifiers (account IDs, customer names, etc.)
    
    Examples:
    - "What's the balance issue with account 102?"
    - "Show me all transactions for customer Asha Patel"
    - "Why is the balance different for account 105?"
    - "List all accounts with discrepancies"
    """
    from core.lineage.question_parser import QuestionParser
    
    # Parse the natural language question
    parser = QuestionParser()
    parsed = parser.parse(question)

    # Transaction/history questions are better served via SQL generation than lineage reconcile.
    is_transaction_question = (
        parsed.focus_metric.value == "transactions"
        or bool(re.search(r"\b(transactions?|txn|activity|history|recent)\b", question, re.IGNORECASE))
    )
    if is_transaction_question:
        try:
            sql_res = sql.answer(question)
            rows = sql_res.get("rows", [])
            cols = sql_res.get("columns", [])
            query_text = sql_res.get("sql", "")
            summary_text = nlg.summarize(
                question,
                cols,
                rows,
                flavor="SQL",
                source=sql_res.get("source"),
            ) if rows else "No transactions found for this question."

            return {
                "narrative": summary_text,
                "metrics": {
                    "rows_returned": len(rows),
                    "question_type": "transactions",
                },
                "path": [],
                "diffs": [],
                "queries": [{"type": "SQL", "query": query_text}] if query_text else [],
                "results": [
                    {
                        "name": "Transaction query result",
                        "columns": cols,
                        "rows": rows,
                    }
                ],
            }
        except Exception:
            # Fall through to lineage handlers if SQL generation/execution fails.
            pass
    
    # Convert to API parameters
    focus_by, identifier = parser.extract_focus_by_and_id(parsed)

    # Handle aggregate superlative questions (e.g., "which customer has the highest balances?")
    is_balance_question = (
        parsed.focus_metric.value == "balance"
        or bool(re.search(r"\bbalances?\b", question, re.IGNORECASE))
    )
    if (
        identifier == "*"
        and parsed.investigation_type.value == "customer"
        and parsed.ranking in {"highest", "lowest"}
        and is_balance_question
    ):
        order = "DESC" if parsed.ranking == "highest" else "ASC"
        with sqlite3.connect(SQLITE_PATH) as con:
            cur = con.cursor()
            cur.execute(
                f"""
                SELECT customer_id, full_name, total_balance
                FROM mart_customer_balances
                ORDER BY total_balance {order}
                LIMIT 1
                """
            )
            top = cur.fetchone()

        if not top:
            raise HTTPException(status_code=404, detail="No customer balances found. Seed demo data first.")

        customer_id, customer_name, customer_balance = top
        bal = lineage.balances_across_stages(by="customer", key=customer_id)
        diffs = lineage.diffs(by="customer", key=customer_id)

        totals = bal.get("totals", {}) if bal.get("ok") else {}
        raw_total = totals.get("raw")
        stage_total = totals.get("stage")
        mart_total = totals.get("mart")

        def _delta(a, b):
            if a is None or b is None:
                return None, None
            d = b - a
            pct = (d / a) if abs(a) > 1e-9 else None
            return d, pct

        d_stage, pct_stage = _delta(raw_total, stage_total)
        d_mart, pct_mart = _delta(stage_total if stage_total is not None else raw_total, mart_total)

        diff_rows = diffs.get("rows", []) if diffs.get("ok") else []
        discrepant_accounts = sum(1 for row in diff_rows if len(row) >= 4 and abs((row[3] or 0.0)) > 0.01)
        max_variance_percent = None
        for row in diff_rows:
            if len(row) < 4:
                continue
            base = row[1] or 0.0
            if abs(base) <= 1e-9:
                continue
            pct = abs((row[3] or 0.0) / base)
            max_variance_percent = pct if max_variance_percent is None else max(max_variance_percent, pct)

        direction = "highest" if parsed.ranking == "highest" else "lowest"
        narrative = (
            f"Customer {customer_name} (ID {customer_id}) has the {direction} total balance at "
            f"${customer_balance:,.2f} in mart.customer_balances."
        )

        return {
            "narrative": narrative,
            "metrics": {
                "raw_balance": raw_total,
                "mart_balance": mart_total,
                "gross_drift": (mart_total - raw_total) if raw_total is not None and mart_total is not None else None,
                "discrepant_accounts": discrepant_accounts,
                "max_variance_percent": max_variance_percent,
                "total_transactions": None,
                "window": "full"
            },
            "path": [
                {
                    "label": "Raw accounts (per-account balances)",
                    "stage": "raw",
                    "balance": raw_total,
                    "txn_count": None,
                    "delta_balance": None,
                    "delta_percent": None,
                },
                {
                    "label": "Staging accounts (cleansed balances)",
                    "stage": "stage",
                    "balance": stage_total,
                    "txn_count": None,
                    "delta_balance": d_stage,
                    "delta_percent": pct_stage,
                },
                {
                    "label": "Customer mart balance (sum of accounts)",
                    "stage": "mart",
                    "balance": mart_total,
                    "txn_count": None,
                    "delta_balance": d_mart,
                    "delta_percent": pct_mart,
                }
            ],
            "diffs": [
                {
                    "account_id": row[0],
                    "raw_balance": row[1],
                    "stage_balance": row[2],
                    "delta": row[3],
                }
                for row in diff_rows
            ],
            "queries": [
                {
                    "type": "SQL",
                    "query": (
                        "SELECT customer_id, full_name, total_balance "
                        "FROM mart_customer_balances "
                        f"ORDER BY total_balance {order} LIMIT 1;"
                    )
                },
                {
                    "type": "SQL",
                    "query": (
                        "SELECT account_id, COALESCE(r.balance,0) AS raw_balance, "
                        "COALESCE(s.balance,0) AS stage_balance, "
                        "(COALESCE(s.balance,0) - COALESCE(r.balance,0)) AS delta "
                        f"FROM (SELECT account_id FROM stage_accounts WHERE customer_id={customer_id} "
                        f"UNION SELECT account_id FROM raw_accounts WHERE customer_id={customer_id}) a "
                        "LEFT JOIN raw_accounts r ON r.account_id = a.account_id "
                        "LEFT JOIN stage_accounts s ON s.account_id = a.account_id "
                        "ORDER BY ABS(delta) DESC, a.account_id;"
                    )
                }
            ],
            "results": [
                {
                    "name": f"Customer with {direction} total balance",
                    "columns": ["customer_id", "full_name", "total_balance"],
                    "rows": [[customer_id, customer_name, customer_balance]],
                }
            ]
        }

    # Handle aggregate ranking questions on account counts
    is_account_count_question = (
        bool(re.search(r"\baccounts?\b", question, re.IGNORECASE))
        and (
            parsed.focus_metric.value == "count"
            or bool(re.search(r"\b(count|number|how many)\b", question, re.IGNORECASE))
        )
    )
    asks_extreme = (
        parsed.ranking in {"highest", "lowest"}
        or bool(re.search(r"\b(most|least)\b", question, re.IGNORECASE))
    )
    if identifier == "*" and is_account_count_question and asks_extreme:
        is_lowest = parsed.ranking == "lowest" or bool(re.search(r"\bleast\b", question, re.IGNORECASE))
        order = "ASC" if is_lowest else "DESC"

        with sqlite3.connect(SQLITE_PATH) as con:
            cur = con.cursor()
            cur.execute(
                f"""
                SELECT COUNT(a.account_id) AS account_count
                FROM customers c
                LEFT JOIN accounts a ON a.customer_id = c.customer_id
                GROUP BY c.customer_id
                ORDER BY account_count {order}
                LIMIT 1
                """
            )
            top = cur.fetchone()

            if not top:
                raise HTTPException(status_code=404, detail="No customers/accounts found.")

            best_count = int(top[0])

            cur.execute(
                """
                SELECT c.customer_id, c.full_name, COUNT(a.account_id) AS account_count
                FROM customers c
                LEFT JOIN accounts a ON a.customer_id = c.customer_id
                GROUP BY c.customer_id, c.full_name
                HAVING COUNT(a.account_id) = ?
                ORDER BY c.customer_id
                """,
                (best_count,),
            )
            winners = cur.fetchall()

            cur.execute(
                """
                SELECT c.customer_id, c.full_name, COUNT(a.account_id) AS account_count
                FROM customers c
                LEFT JOIN accounts a ON a.customer_id = c.customer_id
                GROUP BY c.customer_id, c.full_name
                ORDER BY account_count DESC, c.customer_id
                LIMIT 10
                """
            )
            leaderboard = cur.fetchall()

        customer_id, customer_name = winners[0][0], winners[0][1]
        account_count = best_count
        direction = "lowest" if is_lowest else "highest"
        if len(winners) > 1:
            names = ", ".join([w[1] for w in winners])
            narrative = (
                f"There is a tie for {direction} number of accounts at {account_count}: {names}."
            )
        else:
            narrative = (
                f"{customer_name} (customer_id {customer_id}) has the {direction} number of accounts "
                f"with {account_count} accounts."
            )

        return {
            "narrative": narrative,
            "metrics": {
                "customer_id": customer_id,
                "account_count": int(account_count),
                "tied_customers": len(winners),
                "leaderboard_size": len(leaderboard),
            },
            "path": [],
            "diffs": [],
            "queries": [
                {
                    "type": "SQL",
                    "query": (
                        "SELECT c.customer_id, c.full_name, COUNT(a.account_id) AS account_count "
                        "FROM customers c LEFT JOIN accounts a ON a.customer_id = c.customer_id "
                        "GROUP BY c.customer_id, c.full_name "
                        f"ORDER BY account_count {order}, c.customer_id LIMIT 1;"
                    ),
                },
                {
                    "type": "SQL",
                    "query": (
                        "SELECT c.customer_id, c.full_name, COUNT(a.account_id) AS account_count "
                        "FROM customers c LEFT JOIN accounts a ON a.customer_id = c.customer_id "
                        "GROUP BY c.customer_id, c.full_name "
                        "ORDER BY account_count DESC, c.customer_id LIMIT 10;"
                    ),
                },
            ],
            "results": [
                {
                    "name": f"Customer with {direction} account count",
                    "columns": ["customer_id", "full_name", "account_count"],
                    "rows": [[r[0], r[1], int(r[2])] for r in winners],
                },
                {
                    "name": "Top customers by account count",
                    "columns": ["customer_id", "full_name", "account_count"],
                    "rows": [[r[0], r[1], int(r[2])] for r in leaderboard],
                },
            ],
        }
    
    # Handle aggregate/general questions (no specific identifier)
    if identifier == "*":
        # Use LLM SQL generator + execution as default fallback for aggregate NL questions.
        try:
            sql_res = sql.answer(question)
            rows = sql_res.get("rows", [])
            cols = sql_res.get("columns", [])
            query_text = sql_res.get("sql", "")

            if rows:
                summary_text = nlg.summarize(
                    question,
                    cols,
                    rows,
                    flavor="SQL",
                    source=sql_res.get("source"),
                )
                return {
                    "narrative": summary_text,
                    "metrics": {
                        "rows_returned": len(rows),
                        "focus": f"{parsed.investigation_type.value}:{parsed.focus_metric.value}",
                    },
                    "path": [],
                    "diffs": [],
                    "queries": [{"type": "SQL", "query": query_text}] if query_text else [],
                    "results": [
                        {
                            "name": "LLM-generated aggregate answer",
                            "columns": cols,
                            "rows": rows,
                        }
                    ],
                }
        except Exception:
            pass

        # Last-resort fallback uses live stage summary (not hardcoded values)
        stage_summary = lineage.stage_summary().get("stages", [])
        return {
            "narrative": (
                "I could not map this aggregate question to a lineage entity safely. "
                "Showing live stage totals instead; try asking with explicit entity + metric."
            ),
            "metrics": {
                "stages_found": len(stage_summary),
            },
            "path": [],
            "diffs": [],
            "queries": [],
            "results": [
                {
                    "name": "Current stage summary",
                    "columns": ["stage_id", "label", "row_count", "total_balance", "variance_vs_prev", "issues_count"],
                    "rows": [
                        [
                            s.get("stage_id"),
                            s.get("label"),
                            s.get("row_count"),
                            s.get("total_balance"),
                            s.get("variance_vs_prev"),
                            s.get("issues_count"),
                        ]
                        for s in stage_summary
                    ],
                }
            ],
        }
    
    # Call the underlying reconcile endpoint with parsed parameters
    return lineage_reconcile_entity(
        focusBy=focus_by,
        identifier=identifier,
        issue=question,  # Use original question as issue context
        model=model
    )


@app.get("/lineage-api/reconcile")
def lineage_reconcile_entity(
    focusBy: str = Query("account", regex="^(account|customer)$"),
    identifier: str = Query(..., description="Account ID or customer key"),
    issue: str = Query("", description="Free-text description of the problem"),
    model: str | None = Query(None, description="Override LLM model for narrative (optional)")
):
    """
    Entity-level lineage investigation used by the UI.

    - focusBy: 'account' or 'customer'
    - identifier: e.g. '102' or 'Asha Patel'
    - issue: free-text, passed into narrative generator
    """

    fb = (focusBy or "account").lower()
    key = identifier

    # 1) Get balances + lineage context (raw → stage → mart)
    bal = lineage.balances_across_stages(by=fb, key=key)
    if not bal.get("ok"):
        raise HTTPException(status_code=400, detail=bal.get("error", "balances_across_stages failed"))

    # 2) Row-level diffs (raw vs stage)
    diffs = lineage.diffs(by=fb, key=key)
    if not diffs.get("ok"):
        raise HTTPException(status_code=400, detail=diffs.get("error", "diffs failed"))

    # ---------- Build metrics + path for the UI ----------
    metrics: Dict[str, Any] = {}
    path: list[Dict[str, Any]] = []

    if fb == "account":
        # balances_across_stages(by='account') returns:
        #   raw:   (account_id, customer_id, account_type, balance)
        #   stage: (account_id, customer_id, account_type, balance)
        raw_row = bal.get("raw")
        stg_row = bal.get("stage")
        mart_total = bal.get("mart_customer_total")
        fees = bal.get("fees")

        raw_bal = raw_row[3] if raw_row else None
        stg_bal = stg_row[3] if stg_row else None

        def _delta(a, b):
            if a is None or b is None:
                return None, None
            d = b - a
            pct = (d / a) if abs(a) > 1e-9 else None
            return d, pct

        d_stage, pct_stage = _delta(raw_bal, stg_bal)
        d_mart, pct_mart = _delta(stg_bal if stg_bal is not None else raw_bal, mart_total)

        metrics = {
            "raw_balance": raw_bal,
            "stage_balance": stg_bal,
            "mart_customer_total": mart_total,
            "fees_total": fees,
            "delta_stage_vs_raw": d_stage,
            "delta_stage_vs_raw_pct": pct_stage,
            "delta_mart_vs_stage_or_raw": d_mart,
            "delta_mart_vs_stage_or_raw_pct": pct_mart,
        }

        path = [
            {
                "stage": "raw",
                "label": "Raw account snapshot",
                "balance": raw_bal,
                "txn_count": None,
                "delta_balance": None,
                "delta_percent": None,
            },
            {
                "stage": "stage",
                "label": "Staging account snapshot",
                "balance": stg_bal,
                "txn_count": None,
                "delta_balance": d_stage,
                "delta_percent": pct_stage,
            },
            {
                "stage": "mart",
                "label": "Customer-level mart total",
                "balance": mart_total,
                "txn_count": None,
                "delta_balance": d_mart,
                "delta_percent": pct_mart,
            },
        ]

    elif fb == "customer":
        # balances_across_stages(by='customer') returns:
        #   totals: {raw, stage, mart, fees}
        totals = bal.get("totals", {}) or {}
        raw_total = totals.get("raw")
        stage_total = totals.get("stage")
        mart_total = totals.get("mart")
        fees_total = totals.get("fees")

        def _delta(a, b):
            if a is None or b is None:
                return None, None
            d = b - a
            pct = (d / a) if abs(a) > 1e-9 else None
            return d, pct

        d_stage, pct_stage = _delta(raw_total, stage_total)
        d_mart, pct_mart = _delta(stage_total if stage_total is not None else raw_total, mart_total)

        metrics = {
            "raw_total": raw_total,
            "stage_total": stage_total,
            "mart_total": mart_total,
            "fees_total": fees_total,
            "delta_stage_vs_raw": d_stage,
            "delta_stage_vs_raw_pct": pct_stage,
            "delta_mart_vs_stage_or_raw": d_mart,
            "delta_mart_vs_stage_or_raw_pct": pct_mart,
        }

        path = [
            {
                "stage": "raw",
                "label": "Raw accounts (per-account balances)",
                "balance": raw_total,
                "txn_count": None,
                "delta_balance": None,
                "delta_percent": None,
            },
            {
                "stage": "stage",
                "label": "Staging accounts (cleansed balances)",
                "balance": stage_total,
                "txn_count": None,
                "delta_balance": d_stage,
                "delta_percent": pct_stage,
            },
            {
                "stage": "mart",
                "label": "Customer mart balance (sum of accounts)",
                "balance": mart_total,
                "txn_count": None,
                "delta_balance": d_mart,
                "delta_percent": pct_mart,
            },
        ]

    # ---------- Build tables for the LLM (richer context) ----------
    tables: list[Dict[str, Any]] = []

    # Table 1: raw vs stage by account (from diffs())
    if diffs.get("rows"):
        tables.append({
            "title": "Raw vs stage balances by account",
            "columns": diffs.get("columns", []),
            "rows": diffs.get("rows", []),
        })

    # Table 2: customer account breakdown (for account-focused investigation)
    # balances_across_stages(by='account') now returns customer_accounts_stage etc.
    if fb == "account":
        cust_stage = bal.get("customer_accounts_stage") or []
        if cust_stage:
            tables.append({
                "title": "All accounts for this customer (stage_accounts)",
                "columns": ["account_id", "account_type", "balance"],
                "rows": cust_stage,
            })

    # Table 3: per-stage account details (for customer-focused investigations)
    if fb == "customer":
        for block in bal.get("details", []):
            stage = block.get("stage")
            rows = block.get("rows", [])
            if rows:
                tables.append({
                    "title": f"Accounts at {stage} stage",
                    "columns": ["account_id", "account_type", "balance"],
                    "rows": rows,
                })

    # Semantic hint to steer the LLM toward the *right* explanation
    semantic_hint = (
        "Important: the mart table 'mart.customer_balances' is aggregated at CUSTOMER level. "
        "It sums balances from all of a customer's accounts (e.g., checking + savings + brokerage). "
        "Raw/stage tables hold individual ACCOUNT rows."
    )

    # 3) LLM narrative (Capgemini) with question + metrics + tables
    payload_for_llm = {
        "focus_by": fb,
        "identifier": key,
        "issue": issue or "Balances are not matching across stages for this entity.",
        "metrics": metrics,
        "balances_raw_payload": bal,
        "diffs_raw_payload": diffs,
        "semantic_hint": semantic_hint,
        "tables": tables,
    }

    nar = lineage.narrative(payload_for_llm, model_name=model or os.getenv("CAPGEMINI_MODEL"))

    # 4) Final shape for UI
    diff_rows = diffs.get("rows") or diffs.get("diffs") or []

    # 5) Build queries used for investigation
    queries = []
    results = []

    # Add the diffs query
    if fb == "customer":
        cust_id = diffs.get("key")
        query_text = f"""
SELECT a.account_id,
       COALESCE(r.balance,0) AS raw_balance,
       COALESCE(s.balance,0) AS stage_balance,
       (COALESCE(s.balance,0) - COALESCE(r.balance,0)) AS delta
FROM (SELECT account_id FROM stage_accounts WHERE customer_id={cust_id}
      UNION
      SELECT account_id FROM raw_accounts WHERE customer_id={cust_id}) a
LEFT JOIN raw_accounts   r ON r.account_id = a.account_id
LEFT JOIN stage_accounts s ON s.account_id = a.account_id
ORDER BY ABS(delta) DESC, a.account_id
        """.strip()
        queries.append({"type": "SQL", "query": query_text})
        results.append({
            "name": "Raw vs Stage Balances by Account",
            "columns": diffs.get("columns", ["account_id","raw_balance","stage_balance","delta"]),
            "rows": diff_rows
        })
    elif fb == "account":
        acct = diffs.get("key")
        query_text = f"""
SELECT
  r.account_id,
  r.balance AS raw_balance,
  s.balance AS stage_balance,
  (COALESCE(s.balance,0) - COALESCE(r.balance,0)) AS delta
FROM raw_accounts r
LEFT JOIN stage_accounts s ON s.account_id = r.account_id
WHERE r.account_id={acct}
        """.strip()
        queries.append({"type": "SQL", "query": query_text})
        results.append({
            "name": "Raw vs Stage Balance for Account",
            "columns": diffs.get("columns", ["account_id","raw_balance","stage_balance","delta"]),
            "rows": diff_rows
        })

    # Add balance queries
    if fb == "account":
        acct = key
        balance_query = f"""
SELECT account_id, customer_id, account_type, balance
FROM raw_accounts
WHERE account_id={acct}
        """.strip()
        queries.append({"type": "SQL", "query": balance_query})
        
        stage_query = f"""
SELECT account_id, customer_id, account_type, balance
FROM stage_accounts
WHERE account_id={acct}
        """.strip()
        queries.append({"type": "SQL", "query": stage_query})
    elif fb == "customer":
        cust_id = key
        balance_query = f"""
SELECT customer_id, full_name,
       (SELECT SUM(balance) FROM raw_accounts WHERE customer_id={cust_id}) AS raw_sum,
       (SELECT SUM(balance) FROM stage_accounts WHERE customer_id={cust_id}) AS stage_sum
FROM raw_customers
WHERE customer_id={cust_id}
        """.strip()
        queries.append({"type": "SQL", "query": balance_query})

    return {
        "metrics": metrics,
        "path": path,
        "diffs": diff_rows,
        "narrative": nar.get("summary") if nar and nar.get("ok") else None,
        "queries": queries,
        "results": results,
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
