from core.graphrag.graphrag_router import GraphRAG
from core.config.settings import NEO4J_URI, NEO4J_USER, NEO4J_PASS, NEO4J_DB

def test_accounts_by_customer():
    rag = GraphRAG(NEO4J_URI, NEO4J_USER, NEO4J_PASS, NEO4J_DB)
    res = rag.answer("Which accounts does Asha Patel own?")
    assert res["rows"], "Expected rows"
    rag.close()
