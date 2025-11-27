#!/usr/bin/env python3
# ask_graph.py
import argparse, json, os
from core.graphrag.graphrag_router import GraphRAG
from dotenv import load_dotenv

def main():
    load_dotenv()
    ap = argparse.ArgumentParser(description="Ask questions against Neo4j via GraphRAG.")
    ap.add_argument("--q", required=True, help="Natural language question")
    ap.add_argument("--json", action="store_true", help="Print full JSON result")
    # Optional overrides
    ap.add_argument("--neo4j-uri", default=os.getenv("NEO4J_URI"))
    ap.add_argument("--neo4j-user", default=os.getenv("NEO4J_USER"))
    ap.add_argument("--neo4j-pass", default=os.getenv("NEO4J_PASS"))
    args = ap.parse_args()

    # ask_graph.py (only the construction line changes)
    rag = GraphRAG(uri=args.neo4j_uri, user=args.neo4j_user, password=args.neo4j_pass, database=os.getenv("NEO4J_DB"))

    try:
        result = rag.answer(args.q)
        if args.json:
            print(json.dumps(result, indent=2, default=str))
        else:
            print("— Cypher —")
            print(result["cypher"].strip())
            if result["params"]:
                print("Params:", result["params"])
            print("\n— Summary —")
            print(result["summary"])
            print("\n— Rows —")
            print([result["columns"]])
            for r in result["rows"]:
                print(list(r))
    finally:
        rag.close()

if __name__ == "__main__":
    main()
