#!/usr/bin/env python3
# load_to_neo4j.py
# Mirror the SQLite banking schema into Neo4j with a pragmatic property graph.

import sqlite3
from neo4j import GraphDatabase
import argparse
from typing import Dict, Any

# --------- Cypher helpers ---------

CONSTRAINTS = [
    "CREATE CONSTRAINT customer_id IF NOT EXISTS FOR (c:Customer) REQUIRE c.customer_id IS UNIQUE",
    "CREATE CONSTRAINT account_id IF NOT EXISTS FOR (a:Account) REQUIRE a.account_id IS UNIQUE",
    "CREATE CONSTRAINT txn_id IF NOT EXISTS FOR (t:Transaction) REQUIRE t.txn_id IS UNIQUE",
    "CREATE CONSTRAINT deposit_id IF NOT EXISTS FOR (d:TimeDeposit) REQUIRE d.deposit_id IS UNIQUE",
    "CREATE CONSTRAINT position_id IF NOT EXISTS FOR (p:SecurityPosition) REQUIRE p.position_id IS UNIQUE",
]

UPSERTS = {
    "customer": """
    MERGE (c:Customer {customer_id: $customer_id})
    SET c.full_name=$full_name,
        c.email=$email,
        c.phone=$phone,
        c.address=$address,
        c.kyc_status=$kyc_status,
        c.risk_rating=$risk_rating,
        c.created_at=$created_at
    """,
    "account": """
    MERGE (a:Account {account_id: $account_id})
    SET a.account_type=$account_type,
        a.currency=$currency,
        a.opened_date=$opened_date,
        a.status=$status,
        a.balance=$balance
    WITH a
    MATCH (c:Customer {customer_id: $customer_id})
    MERGE (c)-[:OWNS]->(a)
    """,
    "transaction": """
    MERGE (t:Transaction {txn_id: $txn_id})
    SET t.txn_time=$txn_time,
        t.amount=$amount,
        t.currency=$currency,
        t.txn_type=$txn_type,
        t.description=$description
    WITH t
    MATCH (a:Account {account_id: $account_id})
    MERGE (a)-[:POSTED]->(t)
    """,
    "transaction_counterparty": """
    MATCH (t:Transaction {txn_id: $txn_id})
    MATCH (cp:Account {account_id: $counterparty_account})
    MERGE (t)-[:COUNTERPARTY]->(cp)
    """,
    "time_deposit": """
    MERGE (d:TimeDeposit {deposit_id: $deposit_id})
    SET d.start_date=$start_date,
        d.maturity_date=$maturity_date,
        d.principal=$principal,
        d.interest_rate=$interest_rate,
        d.status=$status
    WITH d
    MATCH (a:Account {account_id: $account_id})
    MERGE (a)-[:HAS_DEPOSIT]->(d)
    """,
    "security_position": """
    MERGE (p:SecurityPosition {position_id: $position_id})
    SET p.symbol=$symbol,
        p.instrument_type=$instrument_type,
        p.quantity=$quantity,
        p.avg_price=$avg_price,
        p.last_price=$last_price
    WITH p
    MATCH (a:Account {account_id: $account_id})
    MERGE (a)-[:HAS_POSITION]->(p)
    """,
}

def run_constraints(session):
    for c in CONSTRAINTS:
        session.run(c)

def dict_row(row, cols) -> Dict[str, Any]:
    return {k: row[i] for i, k in enumerate(cols)}

# --------- Main ETL ---------

def main():
    parser = argparse.ArgumentParser(description="Load SQLite banking data into Neo4j.")
    parser.add_argument("--sqlite", default="banking_mvp.db", help="Path to SQLite DB (default: banking_mvp.db)")
    parser.add_argument("--neo4j-uri", required=True, help="Neo4j bolt URI, e.g. bolt://localhost:7687")
    parser.add_argument("--neo4j-user", default="neo4j")
    parser.add_argument("--neo4j-pass", required=True)
    args = parser.parse_args()

    # Connect
    drv = GraphDatabase.driver(args.neo4j_uri, auth=(args.neo4j_user, args.neo4j_pass))
    con = sqlite3.connect(args.sqlite)

    with drv.session() as s:
        # constraints
        run_constraints(s)

        cur = con.cursor()

        # --- customers
        cur.execute("SELECT customer_id, full_name, email, phone, address, kyc_status, risk_rating, created_at FROM customers")
        cols = [d[0] for d in cur.description]
        for row in cur.fetchall():
            s.run(UPSERTS["customer"], **dict_row(row, cols))

        # --- accounts (and OWNS)
        cur.execute("SELECT account_id, customer_id, account_type, currency, opened_date, status, balance FROM accounts")
        cols = [d[0] for d in cur.description]
        for row in cur.fetchall():
            s.run(UPSERTS["account"], **dict_row(row, cols))

        # --- transactions (and POSTED)
        cur.execute("""SELECT txn_id, account_id, txn_time, amount, currency, txn_type, description, counterparty_account
                       FROM transactions""")
        cols = [d[0] for d in cur.description]
        for row in cur.fetchall():
            data = dict_row(row, cols)
            s.run(UPSERTS["transaction"], **data)
            if data.get("counterparty_account") is not None:
                s.run(UPSERTS["transaction_counterparty"],
                      txn_id=data["txn_id"],
                      counterparty_account=data["counterparty_account"])

        # --- time deposits
        cur.execute("""SELECT deposit_id, account_id, start_date, maturity_date, principal, interest_rate, status
                       FROM time_deposits""")
        cols = [d[0] for d in cur.description]
        for row in cur.fetchall():
            s.run(UPSERTS["time_deposit"], **dict_row(row, cols))

        # --- security positions
        cur.execute("""SELECT position_id, account_id, symbol, instrument_type, quantity, avg_price, last_price
                       FROM securities_positions""")
        cols = [d[0] for d in cur.description]
        for row in cur.fetchall():
            s.run(UPSERTS["security_position"], **dict_row(row, cols))

    con.close()
    drv.close()
    print("✅ Loaded SQLite → Neo4j successfully.")

if __name__ == "__main__":
    main()
