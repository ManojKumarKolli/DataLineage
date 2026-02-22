# core/lineage/lineage_router.py
from __future__ import annotations
import os, sqlite3, time, json
from dataclasses import dataclass
from typing import Dict, Any, List, Optional, Tuple

from core.config.settings import SQLITE_PATH

LINEAGE_DB_PATH = os.getenv("LINEAGE_SQLITE_PATH", "data/lineage.db")

try:
    from core.common.llm_client import capgemini_llm
except Exception:
    capgemini_llm = None

def _ensure_dir(p: str):
    d = os.path.dirname(p)
    if d and not os.path.exists(d):
        os.makedirs(d, exist_ok=True)

@dataclass
class Dataset:
    id: int
    name: str
    stage: str
    physical_table: str
    primary_key: str | None = None

SCHEMA_SQL = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS datasets (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT UNIQUE NOT NULL,
  stage TEXT NOT NULL,                -- raw | stage | mart
  physical_table TEXT NOT NULL,       -- table/view in main db
  primary_key TEXT
);

CREATE TABLE IF NOT EXISTS columns (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  dataset_id INTEGER NOT NULL,
  name TEXT NOT NULL,
  dtype TEXT,
  FOREIGN KEY(dataset_id) REFERENCES datasets(id)
);

CREATE TABLE IF NOT EXISTS edges (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source_id INTEGER NOT NULL,
  target_id INTEGER NOT NULL,
  op TEXT,
  expr TEXT,
  FOREIGN KEY(source_id) REFERENCES datasets(id),
  FOREIGN KEY(target_id) REFERENCES datasets(id)
);

CREATE TABLE IF NOT EXISTS checks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  left_dataset_id INTEGER NOT NULL,
  right_dataset_id INTEGER NOT NULL,
  metric TEXT NOT NULL,
  left_value REAL,
  right_value REAL,
  delta REAL,
  status TEXT,
  run_at TEXT,
  notes TEXT,
  FOREIGN KEY(left_dataset_id) REFERENCES datasets(id),
  FOREIGN KEY(right_dataset_id) REFERENCES datasets(id)
);

CREATE TABLE IF NOT EXISTS alerts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT NOT NULL,          -- RECONCILE|DIFF|QUALITY
  title TEXT NOT NULL,
  detail TEXT,
  severity TEXT,               -- INFO|WARN|ERROR
  created_at TEXT,
  is_open INTEGER DEFAULT 1
);
"""

# Logical lineage edges for demo
DEMO_EDGES = [
    ("raw.customers_raw",     "stage.customers_stg",     "CLEAN", "trim names, normalize email/phone"),
    ("raw.accounts_raw",      "stage.accounts_stg",      "CLEAN", "cast types, uppercase account_type (+discrepancy)"),
    ("raw.transactions_raw",  "stage.transactions_stg",  "CLEAN", "parse datetime, coalesce amount"),
    ("raw.fees_raw",          "stage.fees_stg",          "CLEAN", "cast fee amounts"),
    ("raw.fx_raw",            "stage.fx_stg",            "CLEAN", "normalize currency codes"),
    ("stage.accounts_stg",    "mart.customer_balances",  "AGG",   "sum(balance) by customer"),
    ("stage.transactions_stg","mart.txn_monthly",        "AGG",   "sum(amount) by month"),
    ("stage.fees_stg",        "mart.fees_by_customer",   "AGG",   "sum(fee_amount) by customer"),
]

class LineageService:
    def __init__(self, lineage_db: str = LINEAGE_DB_PATH, main_db: str = SQLITE_PATH):
        self.lineage_db = lineage_db
        self.main_db = main_db
        _ensure_dir(self.lineage_db)
        self._init_schema()

    # ---------- connections ----------
    def _connect_lineage(self):
        return sqlite3.connect(self.lineage_db)

    def _connect_main(self):
        return sqlite3.connect(self.main_db)

    def _init_schema(self):
        con = self._connect_lineage()
        try:
            con.executescript(SCHEMA_SQL)
            con.commit()
        finally:
            con.close()

    # ============================================================
    # SEED: materialize RAW/STAGE/MART with extra sample data
    # ============================================================
    def seed_demo_balances(self) -> Dict[str, Any]:
        """
        Builds raw_* , stage_* , and mart_* tables in the MAIN DB and populates
        them from your canonical demo tables, injecting small discrepancies.
        Registers datasets + edges in lineage DB.
        Also seeds fees & FX to widen metrics space.
        """
        with self._connect_main() as con:
            cur = con.cursor()

            # --- RAW tables (copy) ---
            cur.execute("DROP TABLE IF EXISTS raw_customers")
            cur.execute("CREATE TABLE raw_customers AS SELECT * FROM customers")

            cur.execute("DROP TABLE IF EXISTS raw_accounts")
            cur.execute("CREATE TABLE raw_accounts AS SELECT * FROM accounts")

            cur.execute("DROP TABLE IF EXISTS raw_transactions")
            cur.execute("CREATE TABLE raw_transactions AS SELECT * FROM transactions")

            # Additional RAW: fees & fx
            cur.execute("DROP TABLE IF EXISTS raw_fees")
            cur.execute("""
                CREATE TABLE raw_fees(
                  fee_id INTEGER PRIMARY KEY,
                  account_id INTEGER,
                  fee_amount REAL,
                  fee_type TEXT,
                  posted_at TEXT
                )
            """)
            # small seed fees
            cur.executemany("""
                INSERT INTO raw_fees(fee_id,account_id,fee_amount,fee_type,posted_at)
                VALUES (?,?,?,?,?)
            """, [
                (1, 101, 5.00, "MAINT", "2024-10-01 09:00:00"),
                (2, 102, 2.00, "ATM",   "2024-10-02 10:00:00"),
                (3, 106, 3.50, "MAINT", "2024-10-03 11:00:00"),
            ])

            cur.execute("DROP TABLE IF EXISTS raw_fx")
            cur.execute("""
                CREATE TABLE raw_fx(
                  as_of TEXT,
                  ccy TEXT,
                  rate_to_usd REAL
                )
            """)
            cur.executemany("INSERT INTO raw_fx(as_of,ccy,rate_to_usd) VALUES(?,?,?)", [
                ("2024-10-01","USD",1.00),
                ("2024-10-01","EUR",1.07),
                ("2024-10-01","GBP",1.25),
            ])

            # --- STAGE tables ---
            cur.execute("DROP TABLE IF EXISTS stage_customers")
            cur.execute("""
                CREATE TABLE stage_customers AS
                SELECT
                  customer_id,
                  TRIM(full_name) AS full_name,
                  email, phone, address, kyc_status, risk_rating, created_at
                FROM raw_customers
            """)

            cur.execute("DROP TABLE IF EXISTS stage_accounts")
            cur.execute("""
                CREATE TABLE stage_accounts AS
                SELECT
                  account_id, customer_id,
                  UPPER(account_type) AS account_type,
                  currency,
                  opened_date,
                  status,
                  balance
                FROM raw_accounts
            """)
            # Inject a small discrepancy at stage for account 102 (+50)
            cur.execute("UPDATE stage_accounts SET balance = balance + 50.0 WHERE account_id = 102")

            cur.execute("DROP TABLE IF EXISTS stage_transactions")
            cur.execute("""
                CREATE TABLE stage_transactions AS
                SELECT
                  txn_id, account_id,
                  CASE WHEN typeof(txn_time)='text' THEN txn_time ELSE txn_time END AS txn_time,
                  COALESCE(amount, 0.0) AS amount,
                  currency, txn_type, description, counterparty_account
                FROM raw_transactions
            """)

            cur.execute("DROP TABLE IF EXISTS stage_fees")
            cur.execute("""
                CREATE TABLE stage_fees AS
                SELECT fee_id, account_id, fee_amount, UPPER(fee_type) AS fee_type, posted_at
                FROM raw_fees
            """)

            cur.execute("DROP TABLE IF EXISTS stage_fx")
            cur.execute("""
                CREATE TABLE stage_fx AS
                SELECT as_of, UPPER(ccy) AS ccy, rate_to_usd
                FROM raw_fx
            """)

            # --- MART tables ---
            cur.execute("DROP TABLE IF EXISTS mart_customer_balances")
            cur.execute("""
                CREATE TABLE mart_customer_balances AS
                SELECT c.customer_id, c.full_name, SUM(a.balance) AS total_balance
                FROM stage_customers c
                JOIN stage_accounts  a ON a.customer_id = c.customer_id
                GROUP BY c.customer_id, c.full_name
            """)

            cur.execute("DROP TABLE IF EXISTS mart_txn_monthly")
            cur.execute("""
                CREATE TABLE mart_txn_monthly AS
                SELECT strftime('%Y-%m', t.txn_time) AS month, SUM(t.amount) AS net_amount
                FROM stage_transactions t
                GROUP BY 1
            """)

            cur.execute("DROP TABLE IF EXISTS mart_fees_by_customer")
            cur.execute("""
                CREATE TABLE mart_fees_by_customer AS
                SELECT c.customer_id, c.full_name, SUM(f.fee_amount) AS total_fees
                FROM stage_fees f
                JOIN stage_accounts a ON a.account_id = f.account_id
                JOIN stage_customers c ON c.customer_id = a.customer_id
                GROUP BY 1,2
            """)

            con.commit()

        # Register datasets + edges in lineage DB
        with self._connect_lineage() as con:
            cur = con.cursor()

            datasets = [
                ("raw.customers_raw",        "raw",   "raw_customers"),
                ("raw.accounts_raw",         "raw",   "raw_accounts"),
                ("raw.transactions_raw",     "raw",   "raw_transactions"),
                ("raw.fees_raw",             "raw",   "raw_fees"),
                ("raw.fx_raw",               "raw",   "raw_fx"),

                ("stage.customers_stg",      "stage", "stage_customers"),
                ("stage.accounts_stg",       "stage", "stage_accounts"),
                ("stage.transactions_stg",   "stage", "stage_transactions"),
                ("stage.fees_stg",           "stage", "stage_fees"),
                ("stage.fx_stg",             "stage", "stage_fx"),

                ("mart.customer_balances",   "mart",  "mart_customer_balances"),
                ("mart.txn_monthly",         "mart",  "mart_txn_monthly"),
                ("mart.fees_by_customer",    "mart",  "mart_fees_by_customer"),
            ]

            ids: Dict[str,int] = {}
            for name, stage, tbl in datasets:
                cur.execute("INSERT OR IGNORE INTO datasets(name,stage,physical_table) VALUES(?,?,?)",(name,stage,tbl))
                cur.execute("SELECT id FROM datasets WHERE name=?", (name,))
                ids[name] = cur.fetchone()[0]

            for s_name, t_name, op, expr in DEMO_EDGES:
                s_id, t_id = ids[s_name], ids[t_name]
                cur.execute("SELECT 1 FROM edges WHERE source_id=? AND target_id=?", (s_id,t_id))
                if not cur.fetchone():
                    cur.execute("INSERT INTO edges(source_id,target_id,op,expr) VALUES(?,?,?,?)", (s_id,t_id,op,expr))

            con.commit()

        return {"ok": True, "note": "Seeded raw/stage/mart + fees/fx; injected +$50 discrepancy on stage.accounts(102)."}

    # -------- catalog / graph --------
    def catalog(self) -> Dict[str, Any]:
        with self._connect_lineage() as con:
            cur = con.cursor()
            cur.execute("SELECT id,name,stage,physical_table FROM datasets ORDER BY name")
            ds = [{"id":r[0],"name":r[1],"stage":r[2],"physical_table":r[3]} for r in cur.fetchall()]
            cur.execute("SELECT source_id,target_id,op,expr FROM edges")
            edges = [{"source_id":r[0],"target_id":r[1],"op":r[2],"expr":r[3]} for r in cur.fetchall()]
        return {"datasets": ds, "edges": edges}

    def lineage_graph(self) -> Dict[str, Any]:
        cat = self.catalog()
        nodes = [{"id":d["id"], "name":d["name"], "stage":d["stage"], "table":d["physical_table"]} for d in cat["datasets"]]
        links = [{"source":e["source_id"], "target":e["target_id"], "op":e["op"], "expr":e["expr"]} for e in cat["edges"]]
        return {"nodes": nodes, "links": links}

    # -------- trace path --------
    def trace(self, start: str, end: str) -> Dict[str, Any]:
        with self._connect_lineage() as con:
            cur = con.cursor()
            cur.execute("SELECT id FROM datasets WHERE name=?", (start,))
            r = cur.fetchone()
            if not r: return {"path": [], "note": f"Unknown dataset: {start}"}
            s_id = r[0]
            cur.execute("SELECT id FROM datasets WHERE name=?", (end,))
            r = cur.fetchone()
            if not r: return {"path": [], "note": f"Unknown dataset: {end}"}
            t_id = r[0]
            cur.execute("SELECT source_id,target_id FROM edges")
            edges = cur.fetchall()

        from collections import deque
        adj: Dict[int,List[int]] = {}
        for a,b in edges:
            adj.setdefault(a, []).append(b)

        q = deque([s_id]); prev = {s_id: None}
        while q:
            u = q.popleft()
            if u == t_id: break
            for v in adj.get(u, []):
                if v not in prev:
                    prev[v] = u
                    q.append(v)

        if t_id not in prev: return {"path": [], "note": "No path found."}

        path_ids = []
        u = t_id
        while u is not None:
            path_ids.append(u)
            u = prev[u]
        path_ids.reverse()

        with self._connect_lineage() as con:
            c = con.cursor()
            c.execute("SELECT id,name FROM datasets WHERE id IN (%s)" % ",".join("?"*len(path_ids)), path_ids)
            id2name = {r[0]: r[1] for r in c.fetchall()}

        return {"path": [id2name[i] for i in path_ids], "note": "ok"}

    # -------- reconcile (counts + sums) --------
    def reconcile(self, left: str, right: str) -> Dict[str, Any]:
        with self._connect_lineage() as con:
            cur = con.cursor()
            cur.execute("SELECT id,physical_table FROM datasets WHERE name=?", (left,))
            r = cur.fetchone()
            if not r: return {"ok": False, "error": f"Unknown dataset: {left}"}
            left_id, Ltbl = r
            cur.execute("SELECT id,physical_table FROM datasets WHERE name=?", (right,))
            r = cur.fetchone()
            if not r: return {"ok": False, "error": f"Unknown dataset: {right}"}
            right_id, Rtbl = r

        def _metrics(tbl: str) -> Dict[str, Optional[float]]:
            with self._connect_main() as con:
                cur = con.cursor()
                cur.execute(f"SELECT COUNT(*) FROM {tbl}")
                row_count = cur.fetchone()[0]
                sum_balance = sum_amount = sum_fees = None
                # try common columns
                for col, key in [("balance","sum_balance"), ("amount","sum_amount"), ("fee_amount","sum_fees")]:
                    try:
                        cur.execute(f"SELECT SUM({col}) FROM {tbl}")
                        val = cur.fetchone()[0]
                        if key == "sum_balance": sum_balance = val
                        if key == "sum_amount":  sum_amount  = val
                        if key == "sum_fees":    sum_fees    = val
                    except sqlite3.Error:
                        pass
            return {"row_count": row_count, "sum_balance": sum_balance, "sum_amount": sum_amount, "sum_fees": sum_fees}

        L = _metrics(Ltbl); R = _metrics(Rtbl)

        def _stat(a,b):
            if a is None and b is None: return ("N/A", None)
            if a is None or b is None: return ("FAIL", (a or 0) - (b or 0))
            return ("PASS" if abs((a or 0)-(b or 0)) <= 1e-9 else "FAIL", (a or 0) - (b or 0))

        s_row, d_row = _stat(L["row_count"], R["row_count"])
        s_bal, d_bal = _stat(L["sum_balance"], R["sum_balance"])
        s_amt, d_amt = _stat(L["sum_amount"], R["sum_amount"])
        s_fee, d_fee = _stat(L["sum_fees"],   R["sum_fees"])

        now = time.strftime("%Y-%m-%d %H:%M:%S")
        with self._connect_lineage() as con:
            cur = con.cursor()
            for metric, vals in {
                "row_count":  (L["row_count"],  R["row_count"],  d_row, s_row),
                "sum_balance":(L["sum_balance"],R["sum_balance"],d_bal, s_bal),
                "sum_amount": (L["sum_amount"], R["sum_amount"], d_amt, s_amt),
                "sum_fees":   (L["sum_fees"],   R["sum_fees"],   d_fee, s_fee),
            }.items():
                cur.execute("""
                  INSERT INTO checks(left_dataset_id,right_dataset_id,metric,left_value,right_value,delta,status,run_at,notes)
                  VALUES(?,?,?,?,?,?,?,?,?)
                """, (left_id,right_id,metric,vals[0],vals[1],vals[2],vals[3],now,None))
            con.commit()

        return {
            "ok": True, "run_at": now,
            "left": {"name": left, "table": Ltbl, "metrics": L},
            "right":{"name": right,"table": Rtbl, "metrics": R},
            "status": {"row_count": s_row, "sum_balance": s_bal, "sum_amount": s_amt, "sum_fees": s_fee},
            "delta": {"row_count": d_row, "sum_balance": d_bal, "sum_amount": d_amt, "sum_fees": d_fee}
        }

    # -------- Investigator --------
    def balances_across_stages(self, by: str, key: str | int) -> Dict[str, Any]:
        by = (by or "").lower()
        with self._connect_main() as con:
            cur = con.cursor()

            if by == "customer":
                cust_id = None
                if isinstance(key, int) or str(key).isdigit():
                    cust_id = int(key)
                else:
                    cur.execute("SELECT customer_id FROM raw_customers WHERE lower(full_name)=lower(?) LIMIT 1", (str(key).strip(),))
                    r = cur.fetchone()
                    if r: cust_id = r[0]
                if cust_id is None:
                    return {"ok": False, "error": "Customer not found."}

                def _sum(tbl):
                    cur.execute(f"SELECT SUM(balance) FROM {tbl} WHERE customer_id=?", (cust_id,))
                    return cur.fetchone()[0]
                raw_sum   = _sum("raw_accounts")
                stg_sum   = _sum("stage_accounts")
                cur.execute("SELECT total_balance FROM mart_customer_balances WHERE customer_id=?", (cust_id,))
                r = cur.fetchone(); mart_sum = r[0] if r else None

                details = []
                for stage_tbl, stage in [("raw_accounts","raw"),("stage_accounts","stage")]:
                    cur.execute(f"""
                      SELECT account_id, account_type, balance FROM {stage_tbl}
                      WHERE customer_id=? ORDER BY balance DESC
                    """, (cust_id,))
                    details.append({"stage": stage, "rows": cur.fetchall()})

                # fees by customer (mart)
                cur.execute("SELECT total_fees FROM mart_fees_by_customer WHERE customer_id=?", (cust_id,))
                r = cur.fetchone(); fees_total = r[0] if r else 0.0

                path = ["raw.customers_raw","stage.customers_stg","mart.customer_balances"]
                return {
                    "ok": True, "by":"customer", "key": cust_id,
                    "totals": {"raw": raw_sum, "stage": stg_sum, "mart": mart_sum, "fees": fees_total},
                    "details": details,
                    "lineage_path": path
                }

            elif by == "account":
                if not (isinstance(key,int) or str(key).isdigit()):
                    return {"ok": False, "error": "Account id must be numeric."}
                acct = int(key)

                # base rows
                def _row(tbl):
                    cur.execute(f"""
                    SELECT account_id, customer_id, account_type, balance
                    FROM {tbl}
                    WHERE account_id=?
                    """, (acct,))
                    return cur.fetchone()

                raw_row = _row("raw_accounts")
                stg_row = _row("stage_accounts")

                if not raw_row and not stg_row:
                    return {"ok": False, "error": "Account not found in RAW or STAGE."}

                # account-level fees
                cur.execute("SELECT SUM(fee_amount) FROM stage_fees WHERE account_id=?", (acct,))
                r = cur.fetchone(); acct_fees = r[0] if r else 0.0

                # customer-level mart total and all accounts for that customer (stage)
                cust_id = None
                if stg_row:
                    cust_id = stg_row[1]
                elif raw_row:
                    cust_id = raw_row[1]

                mart_total = None
                customer_accounts_stage: list[tuple] = []
                if cust_id is not None:
                    cur.execute("SELECT total_balance FROM mart_customer_balances WHERE customer_id=?", (cust_id,))
                    rr = cur.fetchone()
                    mart_total = rr[0] if rr else None

                    # All accounts for this customer at stage (for LLM reasoning)
                    cur.execute("""
                    SELECT account_id, account_type, balance
                    FROM stage_accounts
                    WHERE customer_id=?
                    ORDER BY balance DESC
                    """, (cust_id,))
                    customer_accounts_stage = cur.fetchall()

                path = ["raw.accounts_raw","stage.accounts_stg","mart.customer_balances"]
                return {
                    "ok": True,
                    "by": "account",
                    "key": acct,
                    "raw": raw_row,
                    "stage": stg_row,
                    "fees": acct_fees,
                    "mart_customer_total": mart_total,
                    "customer_accounts_stage": customer_accounts_stage,
                    "lineage_path": path,
                }

            else:
                return {"ok": False, "error": "by must be 'customer' or 'account'."}

    # -------- Diffs (per-account) --------
    def diffs(self, by: str, key: str | int) -> Dict[str, Any]:
        by = (by or "").lower()
        with self._connect_main() as con:
            cur = con.cursor()
            if by == "customer":
                cust_id = None
                if isinstance(key, int) or str(key).isdigit():
                    cust_id = int(key)
                else:
                    cur.execute("SELECT customer_id FROM raw_customers WHERE lower(full_name)=lower(?) LIMIT 1", (str(key).strip(),))
                    r = cur.fetchone()
                    if r: cust_id = r[0]
                if cust_id is None:
                    return {"ok": False, "error": "Customer not found."}

                cur.execute("""
                  SELECT a.account_id,
                         COALESCE(r.balance,0) AS raw_balance,
                         COALESCE(s.balance,0) AS stage_balance,
                         (COALESCE(s.balance,0) - COALESCE(r.balance,0)) AS delta
                  FROM (SELECT account_id FROM stage_accounts WHERE customer_id=?
                        UNION
                        SELECT account_id FROM raw_accounts WHERE customer_id=?) a
                  LEFT JOIN raw_accounts   r ON r.account_id = a.account_id
                  LEFT JOIN stage_accounts s ON s.account_id = a.account_id
                  ORDER BY ABS(delta) DESC, a.account_id
                """, (cust_id, cust_id))
                rows = cur.fetchall()
                return {"ok": True, "by": "customer", "key": cust_id,
                        "columns": ["account_id","raw_balance","stage_balance","delta"], "rows": rows}

            elif by == "account":
                if not (isinstance(key,int) or str(key).isdigit()):
                    return {"ok": False, "error": "Account id must be numeric."}
                acct = int(key)
                cur.execute("""
                  SELECT
                    r.account_id,
                    r.balance AS raw_balance,
                    s.balance AS stage_balance,
                    (COALESCE(s.balance,0) - COALESCE(r.balance,0)) AS delta
                  FROM raw_accounts r
                  LEFT JOIN stage_accounts s ON s.account_id = r.account_id
                  WHERE r.account_id=?
                """, (acct,))
                row = cur.fetchone()
                if not row:
                    return {"ok": False, "error": "Account not found in RAW."}
                return {"ok": True, "by":"account", "key": acct,
                        "columns": ["account_id","raw_balance","stage_balance","delta"], "rows": [row]}
            else:
                return {"ok": False, "error": "by must be 'customer' or 'account'."}

    # -------- Alerts job --------
    def run_alerts(self) -> Dict[str, Any]:
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        created = 0

        def _add(kind, title, detail, severity):
            nonlocal created
            with self._connect_lineage() as con:
                cur = con.cursor()
                cur.execute("""
                  INSERT INTO alerts(kind,title,detail,severity,created_at,is_open)
                  VALUES(?,?,?,?,?,1)
                """, (kind, title, detail, severity, now))
                con.commit()
                created += 1

        # Simple checks:
        # 1) Stage vs Mart totals at customer level should match
        with self._connect_main() as con:
            cur = con.cursor()
            cur.execute("""
              SELECT s.customer_id, s.full_name,
                     s.total_balance AS stage_total,
                     m.total_balance AS mart_total,
                     (m.total_balance - s.total_balance) AS delta
              FROM (
                SELECT c.customer_id, c.full_name, SUM(a.balance) AS total_balance
                FROM stage_customers c
                JOIN stage_accounts a ON a.customer_id=c.customer_id
                GROUP BY 1,2
              ) s
              LEFT JOIN mart_customer_balances m ON m.customer_id = s.customer_id
              WHERE ABS(COALESCE(m.total_balance,0) - COALESCE(s.total_balance,0)) > 0.01
            """)
            for cid, name, stg, mart, delta in cur.fetchall():
                _add("RECONCILE",
                     f"Customer balance mismatch • {name}",
                     json.dumps({"customer_id":cid,"stage_total":stg,"mart_total":mart,"delta":delta}),
                     "WARN")

        # 2) Any stage fee with negative value? (quality)
        with self._connect_main() as con:
            cur = con.cursor()
            cur.execute("SELECT fee_id,account_id,fee_amount FROM stage_fees WHERE fee_amount < 0")
            for fid, acct, amt in cur.fetchall():
                _add("QUALITY", "Negative fee detected",
                     json.dumps({"fee_id":fid,"account_id":acct,"fee_amount":amt}), "ERROR")

        return {"ok": True, "created": created, "run_at": now}

    def list_alerts(self, only_open: bool = True) -> Dict[str, Any]:
        with self._connect_lineage() as con:
            cur = con.cursor()
            if only_open:
                cur.execute("SELECT id,kind,title,detail,severity,created_at FROM alerts WHERE is_open=1 ORDER BY id DESC")
            else:
                cur.execute("SELECT id,kind,title,detail,severity,created_at,is_open FROM alerts ORDER BY id DESC")
            rows = cur.fetchall()
        cols = ["id","kind","title","detail","severity","created_at"] if only_open else ["id","kind","title","detail","severity","created_at","is_open"]
        return {"columns": cols, "rows": rows}

    # -------- Sample tables (lineage DB + main DB) --------
    def preview_tables(self, limit: int = 5) -> Dict[str, Any]:
        """
        Preview lineage DB tables (alerts/checks/edges/…) and demo stage/mart tables
        from main DB, in a UI-friendly flat shape:

        {
          "tables": [
            { "name": "...", "stage": "lineage|raw|stage|mart|main", "columns": [...], "rows": [...] },
            ...
          ]
        }
        """
        tables: List[Dict[str, Any]] = []

        # --- lineage db tables ---
        with self._connect_lineage() as con:
            cur = con.cursor()
            cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
            for (t,) in cur.fetchall():
                cur.execute(f"PRAGMA table_info({t});")
                info = cur.fetchall()
                cols = [r[1] for r in info]
                col_meta = [
                    {
                        "name": r[1],
                        "dtype": r[2],
                        "notnull": bool(r[3]),
                        "default": r[4],
                        "pk": bool(r[5]),
                    }
                    for r in info
                ]
                cur.execute(f"SELECT COUNT(*) FROM {t}")
                row_count = cur.fetchone()[0]
                cur.execute(f"SELECT * FROM {t} LIMIT {limit}")
                rows = cur.fetchall()
                tables.append({
                    "name": t,
                    "stage": "lineage",
                    "columns": cols,
                    "column_meta": col_meta,
                    "row_count": row_count,
                    "rows": rows,
                })

        # --- main db (only demo lineage tables) ---
        keep = [
            "raw_customers", "raw_accounts", "raw_transactions", "raw_fees", "raw_fx",
            "stage_customers", "stage_accounts", "stage_transactions", "stage_fees", "stage_fx",
            "mart_customer_balances", "mart_txn_monthly", "mart_fees_by_customer",
        ]

        def _infer_stage(name: str) -> str:
            if name.startswith("raw_"):
                return "raw"
            if name.startswith("stage_"):
                return "stage"
            if name.startswith("mart_"):
                return "mart"
            return "main"

        with self._connect_main() as con:
            cur = con.cursor()
            for t in keep:
                try:
                    cur.execute(f"PRAGMA table_info({t});")
                    info = cur.fetchall()
                    cols = [r[1] for r in info]
                    col_meta = [
                        {
                            "name": r[1],
                            "dtype": r[2],
                            "notnull": bool(r[3]),
                            "default": r[4],
                            "pk": bool(r[5]),
                        }
                        for r in info
                    ]
                    if not cols:
                        # table doesn't exist yet, skip quietly
                        continue
                    cur.execute(f"SELECT COUNT(*) FROM {t}")
                    row_count = cur.fetchone()[0]
                    cur.execute(f"SELECT * FROM {t} LIMIT {limit}")
                    rows = cur.fetchall()
                    tables.append({
                        "name": t,
                        "stage": _infer_stage(t),
                        "columns": cols,
                        "column_meta": col_meta,
                        "row_count": row_count,
                        "rows": rows,
                    })
                except sqlite3.Error:
                    # table missing or other error -> skip
                    continue

        return {"tables": tables}

    # -------- Stage-level summary for UI --------
    def stage_summary(self) -> Dict[str, Any]:
        """
        Compute per-stage metrics for the Stage Overview cards.

        Returns:
        {
          "stages": [
            {
              "stage_id": "raw",
              "label": "...",
              "role": "...",
              "row_count": ...,
              "total_balance": ...,
              "variance_vs_prev": ...,
              "issues_count": ...
            },
            ...
          ]
        }
        """
        with self._connect_main() as con:
            cur = con.cursor()

            def _metrics(table: str, bal_col: str) -> tuple[int, Optional[float]]:
                try:
                    cur.execute(f"SELECT COUNT(*) FROM {table}")
                    row_count = cur.fetchone()[0]
                except sqlite3.Error:
                    return 0, None

                try:
                    cur.execute(f"SELECT SUM({bal_col}) FROM {table}")
                    total_balance = cur.fetchone()[0]
                except sqlite3.Error:
                    total_balance = None

                return row_count, total_balance

            # demo lineage metrics
            raw_rows, raw_bal = _metrics("raw_accounts", "balance")
            stage_rows, stage_bal = _metrics("stage_accounts", "balance")
            mart_rows, mart_bal = _metrics("mart_customer_balances", "total_balance")

        def _var(prev: Optional[float], curr: Optional[float]) -> Optional[float]:
            if prev in (None, 0) or curr is None:
                return None
            return (curr - prev) / prev

        # open issues from alerts table
        with self._connect_lineage() as con:
            cur = con.cursor()
            try:
                cur.execute("SELECT COUNT(*) FROM alerts WHERE is_open=1")
                open_issues = cur.fetchone()[0]
            except sqlite3.Error:
                open_issues = 0

        stages = [
            {
                "stage_id": "raw",
                "label": "Raw landing layer",
                "role": "Ingested customer/account/transaction feeds",
                "row_count": raw_rows,
                "total_balance": raw_bal or 0.0,
                "variance_vs_prev": None,
                "issues_count": 0,
            },
            {
                "stage_id": "stage",
                "label": "Cleansed staging layer",
                "role": "Type casting, standardization, business rules",
                "row_count": stage_rows,
                "total_balance": stage_bal or 0.0,
                "variance_vs_prev": _var(raw_bal, stage_bal),
                "issues_count": open_issues,
            },
            {
                "stage_id": "mart",
                "label": "Curated reporting mart",
                "role": "Customer balance rollups for reporting",
                "row_count": mart_rows,
                "total_balance": mart_bal or 0.0,
                "variance_vs_prev": _var(stage_bal, mart_bal),
                "issues_count": open_issues,
            },
        ]

        return {"stages": stages}

    # -------- LLM narrative --------
    def narrative(self, payload: Dict[str, Any], model_name: Optional[str]) -> Dict[str, Any]:
        """
        payload should contain:
          - focus_by, identifier, issue
          - metrics: numeric drift info
          - semantic_hint: English hint about aggregation (e.g., mart is per-customer)
          - tables: list of {title, columns, rows}
        Returns a short human narrative (if LLM configured).
        """
        if not capgemini_llm:
            return {"ok": False, "error": "LLM client not configured"}

        focus_by = payload.get("focus_by")
        ident = payload.get("identifier")
        issue = payload.get("issue") or "Balances are not matching across stages."
        metrics = payload.get("metrics", {})
        semantic_hint = payload.get("semantic_hint", "")
        tables = payload.get("tables", [])

        # Small helper to render tables in a compact, LLM-friendly markdown form
        def _tabulate_block(title: str, cols: List[str], rows: List[Sequence[Any]], limit: int = 8) -> str:
            if not cols:
                return f"\n### {title}\n(no columns)\n"
            hdr = "| " + " | ".join(cols) + " |"
            sep = "| " + " | ".join(["---"] * len(cols)) + " |"
            body_lines = []
            for r in rows[:limit]:
                body_lines.append("| " + " | ".join("" if v is None else str(v) for v in r) + " |")
            if not body_lines:
                body_lines = ["| (no rows) |"]
            return f"\n### {title}\n" + "\n".join([hdr, sep] + body_lines) + "\n"

        table_blocks = ""
        for t in tables:
            title = t.get("title") or "Table"
            cols = t.get("columns") or []
            rows = t.get("rows") or []
            table_blocks += _tabulate_block(title, cols, rows)

        try:
            prompt = (
                "You are a senior data lineage & reconciliation analyst.\n"
                "Your job is to explain why balances differ across RAW, STAGE and MART layers.\n"
                "You must base your reasoning ONLY on the data provided (metrics and tables).\n"
                "If the MART total clearly looks like a sum of multiple accounts "
                "(e.g., checking + savings for the same customer), call that out explicitly.\n"
                "Do NOT invent causes that are not supported by the numbers.\n\n"
                f"FOCUS ENTITY:\n"
                f"- focus_by: {focus_by}\n"
                f"- identifier: {ident}\n\n"
                f"USER ISSUE (free text):\n{issue}\n\n"
                f"SEMANTIC HINT:\n{semantic_hint}\n\n"
                f"METRICS (JSON):\n{json.dumps(metrics, indent=2)}\n\n"
                f"TABLES:\n{table_blocks}\n\n"
                "Write ONE or TWO plain English sentences (max ~80 words total):\n"
                "- Explain what is off across stages.\n"
                "- Explain the most likely cause, using concrete terms like 'sum of checking and savings accounts'.\n"
                "- Do NOT use markdown, bullets, or code.\n\n"
                "SUMMARY:"
            )

            text = capgemini_llm(
                prompt=prompt,
                system_prompt=(
                    "You are a concise, factual analytics copilot. "
                    "Respond with one or two sentences in plain English. "
                    "Reference specific stages (raw, stage, mart) and account types if visible."
                ),
                model_name=model_name,
            )
            if not text:
                return {"ok": False, "error": "empty LLM response"}
            summary = text.strip()
            # Take the first 2 non-empty lines at most
            lines = [ln.strip() for ln in summary.splitlines() if ln.strip()]
            if not lines:
                return {"ok": False, "error": "no non-empty lines from LLM"}
            merged = " ".join(lines[:2])
            return {"ok": True, "summary": merged[:800]}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    
