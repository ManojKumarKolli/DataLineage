#!/usr/bin/env python3
# core/graphrag/graphrag_router.py
from __future__ import annotations
import os, re, json, logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from neo4j import GraphDatabase
from dotenv import load_dotenv

# Your Capgemini LLM client (already in your repo)
from core.common.llm_client import capgemini_llm

logger = logging.getLogger("graphrag")
load_dotenv()

# --------------------------------------------------------------------
# Schema model
# --------------------------------------------------------------------
@dataclass
class GraphSchema:
    node_props: Dict[str, List[str]]   # label -> [properties]
    rel_types: List[str]               # relationship type names

def _extract_schema(raw: Any) -> GraphSchema:
    """
    Normalize APOC meta.schema() across versions.

    Shapes seen:
    1) {"nodes": {Label: {"properties": {...}}}, "rels": {...}}  (classic)
    2) {"nodes": {...}, "relationships": {...}}                  (alt key)
    3) {Label: {"type":"node","properties":{...}},               (flat map)
       "OWNS":{"type":"relationship",...}, ...}
    """
    if not isinstance(raw, dict):
        raise ValueError(f"Unexpected schema type: {type(raw)}")

    # Shape 1/2
    if "nodes" in raw:
        nodes_obj = raw.get("nodes") or {}
        rels_obj = raw.get("rels") or raw.get("relationships") or {}
        node_props: Dict[str, List[str]] = {}
        for label, meta in nodes_obj.items():
            props = meta.get("properties", {}) if isinstance(meta, dict) else {}
            node_props[label] = sorted(list(props.keys()))
        if isinstance(rels_obj, dict):
            rel_types = sorted(list(rels_obj.keys()))
        elif isinstance(rels_obj, list):
            rel_types = sorted([str(x) for x in rels_obj])
        else:
            rel_types = []
        return GraphSchema(node_props=node_props, rel_types=rel_types)

    # Shape 3: flat map
    node_props: Dict[str, List[str]] = {}
    rel_types: List[str] = []
    for key, meta in raw.items():
        if not isinstance(meta, dict):
            continue
        t = meta.get("type")
        if t == "node":
            props = meta.get("properties", {}) or {}
            node_props[key] = sorted(list(props.keys()))
        elif t == "relationship":
            rel_types.append(key)

    if not node_props and not rel_types:
        raise KeyError(f"Unrecognized APOC schema keys: {list(raw.keys())}")

    return GraphSchema(node_props=node_props, rel_types=sorted(rel_types))

# --------------------------------------------------------------------
# Cypher repair & temporal sanitization
# --------------------------------------------------------------------
# Common LLM mistakes for this dataset
_POSTED_REVERSE = re.compile(r'(?is)\(t\s*:\s*Transaction\)\s*-\s*\[:\s*POSTED\s*\]\s*->\s*\(a\s*:\s*Account\)')
_POSTED_RIGHT   = "(a:Account)-[:POSTED]->(t:Transaction)"
_WHERE_STR_EQ_NUM = re.compile(r'(?is)\b(a\.\s*account_id)\s*=\s*["\'](\d+)["\']')
_COUNTERPARTY_CUSTOMER = re.compile(r'(?is)\(c1\s*:\s*Customer\)\s*-\s*\[:\s*COUNTERPARTY\s*\]\s*->\s*\(c2\s*:\s*Customer\)')


_TEMPORAL_FIXES = [
    # date("YYYY-MM-DD HH:MM:SS")  -> date(datetime(replace("..."," ","T")))
    (re.compile(r'(?is)\bdate\s*\(\s*"[^"]+\s+\d{2}:\d{2}:\d{2}"\s*\)'),
     lambda m: "date(datetime(replace(" + m.group(0)[5:-1] + ", ' ', 'T')))" ),

    # date(t.txn_time) -> date(datetime(replace(t.txn_time,' ','T')))
    (re.compile(r'(?is)\bdate\s*\(\s*t\.txn_time\s*\)'),
     lambda m: "date(datetime(replace(t.txn_time, ' ', 'T')))"),

    # datetime("YYYY-MM-DD HH:MM:SS") -> datetime(replace("..."," ","T"))
    (re.compile(r'(?is)\bdatetime\s*\(\s*"[^"]+\s+\d{2}:\d{2}:\d{2}"\s*\)'),
     lambda m: "datetime(replace(" + m.group(0)[9:-1] + ", ' ', 'T'))"),

    # datetime(t.txn_time) -> datetime(replace(t.txn_time,' ','T'))
    (re.compile(r'(?is)\bdatetime\s*\(\s*t\.txn_time\s*\)'),
     lambda m: "datetime(replace(t.txn_time, ' ', 'T'))"),
]

_ORDER_BY_DT = re.compile(r'(?is)\border\s+by\s+datetime\s*\(\s*t\.txn_time\s*\)\s*(asc|desc)?')

def _normalize_time_ops(cy: str) -> str:
    def _sub(m):
        direction = m.group(1) or "DESC"
        return f"ORDER BY t.txn_time {direction}"
    return _ORDER_BY_DT.sub(_sub, cy)

def _sanitize_temporal(cy: str) -> str:
    fixed = _normalize_time_ops(cy)
    for patt, repl in _TEMPORAL_FIXES:
        fixed = patt.sub(repl, fixed)
    return fixed

def _repair_cypher_shape(cy: str) -> str:
    fixed = cy
    fixed = _POSTED_REVERSE.sub(_POSTED_RIGHT, fixed)
    fixed = _WHERE_STR_EQ_NUM.sub(lambda m: f"{m.group(1)} = {m.group(2)}", fixed)
    if _COUNTERPARTY_CUSTOMER.search(fixed):
        fixed = _COUNTERPARTY_CUSTOMER.sub(
            "(a:Account)-[:POSTED]->(t:Transaction)-[:COUNTERPARTY]->(cp:Account)", fixed
        )
        if re.search(r'(?is)\breturn\b', fixed) is None:
            fixed += "\nRETURN a.account_id AS from_acct, t.txn_id AS txn_id, t.amount AS amount, cp.account_id AS to_acct"
    return fixed

def _ensure_limit(cy: str, default_limit: int = 100) -> str:
    # Add LIMIT if no limit present; avoid adding inside subqueries
    if re.search(r'(?is)\blimit\s+\d+', cy):
        return cy
    return f"{cy.strip()}\nLIMIT {default_limit}"

# Useful fallbacks (domain-aware)
def _fallback_txns_for_account(acct_id: int) -> str:
    return f"""
    MATCH (a:Account {{account_id:{acct_id}}})-[:POSTED]->(t:Transaction)
    RETURN t.txn_id AS txn_id, t.txn_type AS txn_type, t.amount AS amount,
           t.currency AS currency, t.description AS description, t.txn_time AS txn_time
    ORDER BY datetime(t.txn_time) DESC
    LIMIT 100
    """

def _fallback_counterparty() -> str:
    return """
    MATCH (a:Account)-[:POSTED]->(t:Transaction)-[:COUNTERPARTY]->(cp:Account)
    RETURN a.account_id AS from_acct, t.txn_id AS txn_id, t.amount AS amount, cp.account_id AS to_acct
    ORDER BY txn_id
    LIMIT 100
    """

# --------------------------------------------------------------------
# LLM prompt & extraction helpers
# --------------------------------------------------------------------
_CYPHER_FENCE = re.compile(r"```.*?```", re.S)

def _extract_first_cypher(text: str) -> str:
    """Return text starting at first MATCH; strip code fences."""
    if not text:
        return ""
    s = _CYPHER_FENCE.sub("", text).strip()
    m = re.search(r"(?is)\bMATCH\b", s)
    if not m:
        return s.strip()
    return s[m.start():].strip()

_CYPHER_TEMPLATE = """You are a senior Neo4j Cypher engineer. Generate ONE READ-ONLY Cypher query that runs on Neo4j 5.x.

Hard rules (must follow):
- Use ONLY these labels: Customer, Account, Transaction, SecurityPosition, TimeDeposit.
- Use ONLY these relationship types (with directions):
  Customer -[:OWNS]-> Account
  Account  -[:POSTED]-> Transaction
  Transaction -[:COUNTERPARTY]-> Account
  Account -[:HAS_POSITION]-> SecurityPosition
  Account -[:HAS_DEPOSIT]-> TimeDeposit
- Property types:
  Account.account_id is INTEGER
  Transaction.txn_time is STRING in "YYYY-MM-DD HH:MM:SS"
- When ordering by time, use: ORDER BY datetime(t.txn_time) DESC
- When grouping by month from a string date, use: substring(t.txn_time, 0, 7) AS month
- Do NOT invent labels, relationship types, or properties.
- Do NOT use APOC procedures.
- Return small, useful columns with clear aliases.
- Default LIMIT 100 unless user asked otherwise.

Schema summary:
{SCHEMA_BULLETS}

Checklist before you output:
1) Relationship directions match the list above.
2) account_id compared as INTEGER (e.g., a.account_id = 102), not string.
3) If you need a month key, use substring(t.txn_time, 0, 7).
4) Use datetime(t.txn_time) if you sort by time.
5) No updates; only MATCH/WHERE/RETURN/ORDER BY/LIMIT.

You must output Cypher ONLY. No prose. No code fences.

Examples (follow strictly):

-- Example A: “Show all transactions for account 102.”
MATCH (a:Account {account_id: 102})-[:POSTED]->(t:Transaction)
RETURN t.txn_id    AS txn_id,
       t.txn_type  AS txn_type,
       t.amount    AS amount,
       t.currency  AS currency,
       t.description AS description,
       t.txn_time  AS txn_time
ORDER BY datetime(t.txn_time) DESC
LIMIT 100

-- Example B: “Give me the counterparty relationship.”
MATCH (a:Account)-[:POSTED]->(t:Transaction)-[:COUNTERPARTY]->(cp:Account)
RETURN a.account_id  AS from_acct,
       t.txn_id      AS txn_id,
       t.amount      AS amount,
       cp.account_id AS to_acct
ORDER BY txn_id
LIMIT 100

-- Example C: “Which accounts does Asha Patel own?”
MATCH (c:Customer {full_name: "Asha Patel"})-[:OWNS]->(a:Account)
RETURN a.account_id AS account_id, a.account_type AS type, a.status AS status, a.balance AS balance
ORDER BY a.balance DESC
LIMIT 100

-- Example D: “Monthly net flows for checking accounts.”
MATCH (a:Account {account_type: "CHECKING"})-[:POSTED]->(t:Transaction)
WITH substring(t.txn_time, 0, 7) AS month, t.amount AS amt
RETURN month, sum(amt) AS net_flows
ORDER BY month
LIMIT 100

-- Example E: “Positions for symbol AAPL and their owners.”
MATCH (a:Account)-[:HAS_POSITION]->(p:SecurityPosition {symbol: "AAPL"})
OPTIONAL MATCH (c:Customer)-[:OWNS]->(a)
RETURN p.symbol AS symbol,
       sum(p.quantity) AS total_qty,
       sum(p.quantity * coalesce(p.last_price, p.avg_price)) AS market_value,
       collect(DISTINCT c.full_name) AS owners
LIMIT 100

User question:
{QUESTION}
"""

def _schema_bullets(schema: GraphSchema) -> str:
    lines = []
    for label in sorted(schema.node_props.keys()):
        props = ", ".join(schema.node_props[label])
        lines.append(f"- {label}({props})")
    lines.append("\nRelationships (directed):")
    lines.append("  Customer -[:OWNS]-> Account")
    lines.append("  Account  -[:POSTED]-> Transaction")
    lines.append("  Transaction -[:COUNTERPARTY]-> Account")
    lines.append("  Account -[:HAS_POSITION]-> SecurityPosition")
    lines.append("  Account -[:HAS_DEPOSIT]-> TimeDeposit")
    return "\n".join(lines)

# --------------------------------------------------------------------
# GraphRAG engine
# --------------------------------------------------------------------
class GraphRAG:
    """
    LLM-first GraphRAG router for Neo4j with schema-aware prompting,
    automatic Cypher repairs, and safe fallbacks.
    """
    def __init__(
        self,
        uri: Optional[str] = None,
        user: Optional[str] = None,
        password: Optional[str] = None,
        database: Optional[str] = None,
        model_name: Optional[str] = None,
    ):
        load_dotenv()
        self.uri = uri or os.getenv("NEO4J_URI")
        self.user = user or os.getenv("NEO4J_USER")
        self.password = password or os.getenv("NEO4J_PASS")
        self.database = database or os.getenv("NEO4J_DB") or "neo4j"
        self.model_name = (model_name or os.getenv("CAPGEMINI_MODEL") 
                           or "anthropic.claude-3-5-sonnet-20241022-v2:0").strip()

        if not (self.uri and self.user and self.password):
            raise RuntimeError("Set NEO4J_URI, NEO4J_USER, NEO4J_PASS (.env)")

        self._driver = GraphDatabase.driver(self.uri, auth=(self.user, self.password))
        self.schema: Optional[GraphSchema] = None
        self.last_source: str = "llm"  # 'llm' | 'retry' | 'fallback'

    # --- lifecycle ---
    def close(self):
        self._driver.close()

    def set_model(self, model_name: str):
        self.model_name = (model_name or self.model_name).strip()

    def _session(self):
        return self._driver.session(database=self.database)

    # --- schema ---
    def load_schema(self) -> GraphSchema:
        with self._session() as s:
            recs = s.run("CALL apoc.meta.schema() YIELD value RETURN value").data()
            if recs and "value" in recs[0]:
                raw = recs[0]["value"]
                self.schema = _extract_schema(raw)
                return self.schema

            # fallback: apoc.meta.graph()
            recs = s.run("""
                CALL apoc.meta.graph() YIELD nodes, relationships
                RETURN {nodes:nodes, relationships:relationships} AS value
            """).data()
            if recs:
                self.schema = _extract_schema(recs[0]["value"])
                return self.schema

            # last resort: synthesize labels seen
            synth = s.run("""
                CALL {
                  MATCH (n) WITH labels(n) AS L LIMIT 200
                  UNWIND L AS label RETURN DISTINCT label
                } WITH collect(label) AS labels
                RETURN {nodes: apoc.map.fromPairs([l IN labels | [l, {properties:{}}]]), relationships:{}} AS value
            """).single()
            if synth and "value" in synth:
                self.schema = _extract_schema(synth["value"])
                return self.schema

            raise RuntimeError("Could not read schema via APOC. Is the APOC plugin enabled for THIS database?")

    # --- execution with temporal retry ---
    def run_cypher(self, cypher: str, params: Dict[str, Any] | None = None) -> Tuple[List[str], List[tuple]]:
        params = params or {}
        with self._session() as s:
            try:
                res = s.run(cypher, **params)
                keys = res.keys()
                rows = [tuple(r[k] for k in keys) for r in res]
                return list(keys), rows
            except Exception as e:
                msg = str(e)
                needs_retry = ("expected a map but was String" in msg.lower()
                               or "type mismatch: expected a map but was string" in msg.lower()
                               or "22n01" in msg.lower() or "22g03" in msg.lower())
                if needs_retry:
                    safe = _sanitize_temporal(cypher)
                    if safe != cypher:
                        logger.warning("[GraphRAG] Temporal sanitize retry.\nOriginal:\n%s\n---\nFixed:\n%s", cypher, safe)
                        res = s.run(safe, **params)
                        keys = res.keys()
                        rows = [tuple(r[k] for k in keys) for r in res]
                        self.last_source = "retry"
                        return list(keys), rows
                raise

    # --- public API ---
    def answer(self, question: str) -> Dict[str, Any]:
        """
        LLM → Cypher (schema-aware) → repair → execute → summary.
        """
        if self.schema is None:
            self.load_schema()

        # Build prompt
        bullets = _schema_bullets(self.schema)
        prompt = _CYPHER_TEMPLATE.replace("{SCHEMA_BULLETS}", bullets).replace("{QUESTION}", question)

        # Invoke LLM
        raw = capgemini_llm(
            prompt=prompt,
            system_prompt="Only Cypher. No prose.",
            model_name=self.model_name,
        ) or ""

        cypher = _extract_first_cypher(raw)
        cypher = _repair_cypher_shape(_sanitize_temporal(_ensure_limit(cypher)))
        params: Dict[str, Any] = {}

        # Intent inference for better summaries/viz later
        intent, params = self._infer_intent(question, cypher, params)

        # Execute
        keys, rows = self.run_cypher(cypher, params)
        self.last_source = "llm"

        # If empty, apply intent-aware fallbacks
        if not rows:
            ql = question.strip().lower()
            # transactions for account X
            m = re.search(r"(?:account|acct)\s+(\d+)", ql)
            if ("transaction" in ql or "transactions" in ql) and m:
                acct = int(m.group(1))
                cy2 = _fallback_txns_for_account(acct)
                keys, rows = self.run_cypher(cy2, {})
                if rows:
                    cypher = cy2
                    intent = "txns_for_account"
                    params = {"account": acct}
                    self.last_source = "fallback"

            # generic counterparty map
            elif "counterparty" in ql:
                cy2 = _fallback_counterparty()
                keys, rows = self.run_cypher(cy2, {})
                if rows:
                    cypher = cy2
                    intent = "counterparty_edges"
                    params = {}
                    self.last_source = "fallback"

        summary = self._summarize(intent, keys, rows, params)
        return {
            "intent": intent,
            "cypher": cypher,
            "params": params,
            "columns": keys,
            "rows": rows,
            "summary": summary
        }

    # --- heuristics ---
    def _infer_intent(self, question: str, cypher: str, params: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
        q = question.strip().lower()

        # accounts by customer
        m = re.search(r"(?:which\s+)?accounts?.*(?:does|do)\s+(.+?)\s+(?:own|have)", q) \
            or re.search(r"accounts?\s+for\s+(.+)", q) \
            or re.search(r"(?:for|of)\s+(.+?)\s+accounts?", q)
        if m:
            name = m.group(1).title().strip()
            return "accounts_by_customer", {"name": name}

        # transactions for account N
        m = re.search(r"(?:account|acct)\s+(\d+)", q)
        if ("transaction" in q or "transactions" in q) and m:
            return "txns_for_account", {"account": int(m.group(1))}

        if "counterparty" in q:
            return "counterparty_edges", {}

        if "portfolio" in q or "positions" in q or "holdings" in q:
            return "positions_or_portfolio", {}

        return "generic_graph", params

    # --- summaries ---
    def _summarize(self, intent: str, cols: List[str], rows: List[tuple], params: Dict[str, Any]) -> str:
        if not rows:
            return "No data found for that question."

        if intent == "accounts_by_customer":
            name = params.get("name", "Customer")
            parts = []
            for r in rows:
                # expect: account_id, type, status, balance
                if len(r) >= 4:
                    parts.append(f"{r[1]} #{r[0]} ({r[2]}), balance {float(r[3]):,.2f}")
            return f"{name} owns {len(rows)} account(s): " + "; ".join(parts) if parts else f"No accounts found for {name}."

        if intent == "txns_for_account":
            acct = params.get("account")
            return f"Found {len(rows)} transaction(s) for account {acct}."

        if intent == "counterparty_edges":
            return f"Found {len(rows)} counterparty edge(s)."

        if intent == "positions_or_portfolio":
            return f"Returned {len(rows)} row(s) for positions/portfolio."

        return f"Returned {len(rows)} row(s)."

    # --- visualization helper for UI ---
    def viz_cypher_for(self, intent: str, params: Dict[str, Any]) -> Optional[str]:
        if intent == "accounts_by_customer" and "name" in params:
            return """
            MATCH (c:Customer {full_name:$name})-[r:OWNS]->(a:Account)
            RETURN c,r,a
            LIMIT 200
            """
        if intent == "txns_for_account" and "account" in params:
            return """
            MATCH (a:Account {account_id:$account})-[r:POSTED]->(t:Transaction)
            OPTIONAL MATCH (t)-[cp:COUNTERPARTY]->(b:Account)
            RETURN a,r,t,cp,b
            LIMIT 300
            """
        if intent == "counterparty_edges":
            return """
            MATCH (a:Account)-[p:POSTED]->(t:Transaction)-[cp:COUNTERPARTY]->(b:Account)
            RETURN a,p,t,cp,b
            LIMIT 400
            """
        # generic graph
        return """
        MATCH (c:Customer)-[r:OWNS]->(a:Account)
        RETURN c,r,a
        LIMIT 150
        """
