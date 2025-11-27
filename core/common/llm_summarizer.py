# core/common/llm_summarizer.py
from __future__ import annotations
import os
import re
from typing import List, Sequence, Any, Optional, Any as AnyType

try:
    from core.common.llm_client import capgemini_llm
except Exception:
    capgemini_llm = None


def _tabulate(cols: List[str], rows: Sequence[Sequence[Any]], limit: int = 10) -> str:
    """Render a small markdown-ish table, used only inside the LLM prompt."""
    hdr = "| " + " | ".join(cols) + " |"
    sep = "| " + " | ".join(["---"] * len(cols)) + " |"
    body = []
    for r in rows[:limit]:
        body.append("| " + " | ".join("" if v is None else str(v) for v in r) + " |")
    return "\n".join([hdr, sep] + body) if rows else hdr + "\n" + sep + "\n| (no rows) |"


def _dedupe(s: str) -> str:
    """Remove obvious repeated words / names in the LLM output."""
    s = re.sub(
        r'(?:\b([A-Z][\w\'-]+)\b(?:,\s*)?)(?:\s*\1\b(?:,\s*)?){2,}',
        r'\1',
        s,
        flags=re.I,
    )
    s = re.sub(
        r'(\b\w+\b)(?:\s+\1\b){2,}',
        r'\1',
        s,
        flags=re.I,
    )
    return s.strip()


class NLMSummarizer:
    """
    NLG layer for SQL / Graph answers.

    Strategy:
      1. Use Capgemini LLM (Bedrock) if configured.
      2. Fall back to a simple deterministic summary if LLM is unavailable / fails.

    Note: this *will* be a second LLM call per question (first for SQL/Cypher, second for NLG).
    If you want zero extra LLM calls, just use `_basic_summary` directly.
    """

    def __init__(self, model_name: Optional[str] = None, **_: AnyType):
        # absorb extra kwargs like `mode=` without breaking
        self.model_name = (
            model_name
            or os.getenv(
                "CAPGEMINI_MODEL",
                "anthropic.claude-3-5-sonnet-20241022-v2:0",
            )
        ).strip()

    # ---------- deterministic fallback ----------
    def _basic_summary(
        self,
        question: str,
        cols: List[str],
        rows: Sequence[Sequence[Any]],
        flavor: str,
    ) -> str:
        if not rows:
            return "No data found for that question."

        # Single scalar
        if len(cols) == 1 and len(rows) == 1:
            return f"{cols[0].replace('_', ' ').title()}: {rows[0][0]}."

        # Generic “top row” style summary
        top = dict(zip(cols, rows[0]))
        return f"{flavor} answer for “{question}” — {len(rows)} row(s). Top row: {top}"

    # ---------- main entry ----------
    def summarize(
        self,
        question: str,
        cols: List[str],
        rows: Sequence[Sequence[Any]],
        flavor: str = "SQL",
        **_: AnyType,  # ignore extra args like source=...
    ) -> str:
        if not rows:
            return "No data found for that question."

        preview = _tabulate(cols, rows, limit=10)

        prompt = (
            "You are a concise data analyst.\n"
            "Given a business question and a small result table, "
            "write ONE short, clear sentence (<= 30 words) summarizing the key insight.\n"
            "- Mention the key entity/value explicitly (e.g., customer name and amount).\n"
            "- Do NOT include SQL, code, markdown, or bullet points.\n\n"
            f"QUESTION:\n{question}\n\n"
            f"RESULT TABLE:\n{preview}\n\n"
            "SUMMARY:"
        )

        # ---------- 1) Capgemini LLM ----------
        if capgemini_llm is not None:
            try:
                text = capgemini_llm(
                    prompt=prompt,
                    system_prompt=(
                        "You are a concise analytics copilot. "
                        "Respond with one plain English sentence explaining the key insight."
                    ),
                    model_name=self.model_name,
                )
                if text:
                    text = text.strip()
                    # Take first non-empty line and strip any role prefix (e.g., 'assistant:')
                    line = next(
                        (ln.strip() for ln in text.splitlines() if ln.strip()),
                        "",
                    )
                    line = re.sub(
                        r'^(assistant|system|user)\s*[:\-–—]\s*',
                        '',
                        line,
                        flags=re.I,
                    )
                    if line:
                        return _dedupe(line)[:280]
            except Exception:
                # fall back to deterministic if LLM call fails
                pass

        # ---------- 2) deterministic fallback ----------
        return self._basic_summary(question, cols, rows, flavor)
