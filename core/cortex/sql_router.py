# core/cortex/sql_router.py
from __future__ import annotations

import os, re, sqlite3, yaml, logging, textwrap, json
from dataclasses import dataclass
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime
import uuid

from dotenv import load_dotenv
from core.config.settings import SQLITE_PATH
from core.common.llm_client import capgemini_llm_io

logger = logging.getLogger("cortex_sql")
load_dotenv()

@dataclass
class SemanticModel:
    tables: Dict[str, Dict[str, Any]]
    relationships: List[Dict[str, Any]]
    metrics: List[Dict[str, Any]]
    raw_yaml: str

def load_semantic_model(yaml_path: str) -> SemanticModel:
    with open(yaml_path, "r") as f:
        txt = f.read()
        data = yaml.safe_load(txt)
    tmap = {}
    for t in data.get("tables", []):
        cols = [c["name"] for c in t.get("columns", [])]
        tmap[t["name"]] = {**t, "columns_list": cols}
    return SemanticModel(
        tables=tmap,
        relationships=data.get("relationships", []),
        metrics=data.get("metrics", []),
        raw_yaml=txt
    )

_SQL_FENCE_RE = re.compile(r"^```+(\w+)?|```+$", re.MULTILINE)
_FROM_JOIN_RE = re.compile(r"(?is)\b(from|join)\s+([A-Za-z_][A-Za-z0-9_]*)")

def _extract_first_select(sqlish: str) -> Optional[str]:
    if not sqlish:
        return None
    s = _SQL_FENCE_RE.sub("", sqlish).strip()
    s = re.sub(r"(?is)^\s*(sql|answer|query)\s*:\s*", "", s).strip("` \n\r\t")
    m = re.search(r"(?is)\bSELECT\b", s)
    if not m:
        return None
    s = s[m.start():]
    semi = s.find(";")
    if semi >= 0:
        s = s[:semi + 1]
    else:
        s = s + ";"
    return s.strip()

def _normalize_table_identifiers(sql: str, sm: SemanticModel) -> str:
    if not sql:
        return sql
    canon = {t.lower(): t for t in sm.tables.keys()}
    def _fix(m: re.Match) -> str:
        kw = m.group(1)
        tbl = m.group(2)
        return f"{kw} {canon.get(tbl.lower(), tbl)}"
    return _FROM_JOIN_RE.sub(_fix, sql)

def validate_sql_against_semantic(sql: str, sm: SemanticModel) -> str:
    """
    Validate the generated SQL:
      - Must be a non-empty SELECT
      - Must contain a FROM (or JOIN) clause (robust to newlines/spacing/case)
      - Must only reference known tables from the semantic model
      - No mutating statements
    Returns the SQL with a trailing semicolon.
    """
    if not sql or not isinstance(sql, str):
        raise ValueError("Empty SQL from generator.")

    s = sql.strip().rstrip(";")
    if not re.search(r"(?is)\bselect\b", s):
        raise ValueError("Invalid SQL: not a SELECT.")

    # Disallow mutating statements
    if re.search(r"(?i)\b(drop|delete|update|insert|alter|truncate|create)\b", s):
        raise ValueError("Only SELECT queries are allowed.")

    # Must contain a FROM (or JOIN) token — handle newlines/tabs/extra spaces/case
    if not re.search(r"(?is)\b(from|join)\b", s):
        raise ValueError("Invalid SQL: missing FROM clause.")

    # Collect referenced tables after FROM/JOIN (robust to case/whitespace/newlines)
    used_tables = set(m.group(1) for m in re.finditer(r"(?is)\bfrom\s+([A-Za-z_][A-Za-z0-9_]*)", s))
    used_tables.update(m.group(1) for m in re.finditer(r"(?is)\bjoin\s+([A-Za-z_][A-Za-z0-9_]*)", s))

    sm_lowers = {t.lower() for t in sm.tables.keys()}
    unknown = [t for t in used_tables if t.lower() not in sm_lowers]
    if unknown:
        raise ValueError(f"Unknown table(s) in SQL: {unknown}")

    return s + ";"


def _fallback_default() -> str:
    # Safe open-accounts leaderboard fallback
    return """
    SELECT c.full_name, a.account_id, a.account_type, a.balance
    FROM customers c
    JOIN accounts a ON a.customer_id = c.customer_id
    WHERE a.status = 'OPEN'
    ORDER BY a.balance DESC
    LIMIT 10;
    """

class CortexSQLRouter:
    """
    Single-mode LLM: always try Capgemini for YAML→SQL; log I/O; deterministic fallback if needed.
    """
    def __init__(self, yaml_path: str, sqlite_path: str = SQLITE_PATH, model_name: str | None = None):
        self.sm = load_semantic_model(yaml_path)
        self.sqlite_path = sqlite_path
        self.model_name = model_name or os.getenv("CAPGEMINI_MODEL", "anthropic.claude-3-5-sonnet-20241022-v2:0")
        self.last_source = "llm"

    def set_model(self, model_name: str):
        self.model_name = (model_name or self.model_name).strip()

    def answer(self, question: str) -> Dict[str, Any]:
        yaml_spec = self.sm.raw_yaml.strip()
        sql = None

        # LLM FIRST
        try:
            os.makedirs("logs", exist_ok=True)
            ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            rid = uuid.uuid4().hex[:8]

            prompt = textwrap.dedent(f"""
                You are an expert SQLite query generator.
                Task: Produce ONE valid, read-only SELECT statement for SQLite that answers the user's question.
                Return ONLY the SQL. No explanations, no markdown, no code fences, no comments.

                SEMANTIC MODEL (YAML):
                ---
                {yaml_spec}
                ---

                QUESTION:
                {question}

                SQL:
            """).strip()

            gen, req1, resp1 = capgemini_llm_io(
                prompt=prompt,
                system_prompt="Output only the SQL SELECT statement for SQLite. No prose.",
                model_name=self.model_name,
            )
            sql_try = _extract_first_select(gen) or ""
            with open(f"logs/llm_sql_{ts}_{rid}.json", "w") as f:
                json.dump({
                    "attempt": 1,
                    "model": self.model_name,
                    "question": question,
                    "request": req1,
                    "response": resp1,
                    "extracted_sql": sql_try
                }, f, indent=2)

            if not sql_try:
                prompt2 = textwrap.dedent(f"""
                    Only output one SQLite SELECT statement. No words. No markdown.
                    Use the following YAML schema.

                    YAML:
                    {yaml_spec}

                    Q: {question}
                    SQL:
                """).strip()
                gen2, req2, resp2 = capgemini_llm_io(
                    prompt=prompt2,
                    system_prompt="Only SQL. No extra text.",
                    model_name=self.model_name,
                )
                sql_try = _extract_first_select(gen2) or ""
                with open(f"logs/llm_sql_{ts}_{rid}_retry.json", "w") as f:
                    json.dump({
                        "attempt": 2,
                        "model": self.model_name,
                        "question": question,
                        "request": req2,
                        "response": resp2,
                        "extracted_sql": sql_try
                    }, f, indent=2)

            if sql_try:
                sql = sql_try

        except Exception as e:
            logger.warning("[CortexSQL] LLM error: %s", e)
            sql = None

        # Normalize, validate or fallback
        if not sql:
            sql = _fallback_default()
            self.last_source = "fallback"
        else:
            sql = _normalize_table_identifiers(sql, self.sm)
            try:
                sql = validate_sql_against_semantic(sql, self.sm)
                self.last_source = "llm"
            except ValueError as ve:
                logger.warning("[CortexSQL] Validation failed: %s; using fallback.", ve)
                sql = _fallback_default()
                self.last_source = "fallback"

        cols, rows = self._run_sql(sql)
        summary = f"Ran SQL with {len(rows)} row(s)."
        return {"sql": sql, "columns": cols, "rows": rows, "summary": summary, "source": self.last_source}

    def _run_sql(self, sql: str) -> Tuple[List[str], List[tuple]]:
        try:
            con = sqlite3.connect(self.sqlite_path)
            cur = con.cursor()
            cur.execute(sql)
            cols = [d[0] for d in cur.description]
            rows = cur.fetchall()
            con.close()
            return cols, rows
        except sqlite3.Error as e:
            raise ValueError(f"SQLite error: {e}. SQL was: {sql}")
