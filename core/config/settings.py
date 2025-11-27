# core/config/settings.py
import os
from pathlib import Path
from dotenv import load_dotenv

# Load env from project root ".env" if present
ROOT = Path(__file__).resolve().parents[2]
load_dotenv(dotenv_path=ROOT / ".env", override=False)

# Neo4j
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASS = os.getenv("NEO4J_PASS", "neo4j")
NEO4J_DB   = os.getenv("NEO4J_DB",  "neo4j")
CAPGEMINI_API_KEY=os.getenv("CAPGEMINI_API_KEY", "")
CAPGEMINI_MODEL=os.getenv("CAPGEMINI_MODEL", "openai.gpt-4")
CAPGEMINI_LLM_URL=os.getenv("CAPGEMINI_LLM_URL", "https://api.generative.engine.capgemini.com/v2/llm/invoke")

# SQLite
SQLITE_PATH = os.getenv("SQLITE_PATH", str(ROOT / "data" / "banking_mvp.db"))

# CORS (for API)
CORS_ALLOW_ORIGINS = [
    o.strip() for o in os.getenv("CORS_ALLOW_ORIGINS", "*").split(",")
]
