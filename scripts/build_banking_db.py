#!/usr/bin/env python3
# build_banking_db.py
# Create & seed a small banking schema in SQLite, with helpers to add more rows later.

import sqlite3
from contextlib import contextmanager
from datetime import datetime
import argparse
from typing import Optional, Iterable, Tuple, Any

@contextmanager
def connect(db_path: str):
    conn = sqlite3.connect(db_path)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()

def create_tables(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    cur.executescript("""
    PRAGMA foreign_keys = ON;

    CREATE TABLE IF NOT EXISTS customers (
        customer_id   INTEGER PRIMARY KEY,
        full_name     TEXT NOT NULL,
        email         TEXT UNIQUE,
        phone         TEXT,
        address       TEXT,
        kyc_status    TEXT CHECK(kyc_status IN ('PENDING','VERIFIED','REJECTED')) DEFAULT 'PENDING',
        risk_rating   INTEGER CHECK(risk_rating BETWEEN 1 AND 5) DEFAULT 3,
        created_at    TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS accounts (
        account_id    INTEGER PRIMARY KEY,
        customer_id   INTEGER NOT NULL,
        account_type  TEXT CHECK(account_type IN ('CHECKING','SAVINGS','BROKERAGE')) NOT NULL,
        currency      TEXT DEFAULT 'USD',
        opened_date   TEXT DEFAULT (date('now')),
        status        TEXT CHECK(status IN ('OPEN','FROZEN','CLOSED')) DEFAULT 'OPEN',
        balance       REAL DEFAULT 0,
        FOREIGN KEY (customer_id) REFERENCES customers(customer_id)
    );

    CREATE TABLE IF NOT EXISTS transactions (
        txn_id        INTEGER PRIMARY KEY,
        account_id    INTEGER NOT NULL,
        txn_time      TEXT NOT NULL,
        amount        REAL NOT NULL,
        currency      TEXT DEFAULT 'USD',
        txn_type      TEXT CHECK(txn_type IN ('DEPOSIT','WITHDRAWAL','TRANSFER_IN','TRANSFER_OUT','SEC_BUY','SEC_SELL','INTEREST')) NOT NULL,
        description   TEXT,
        counterparty_account INTEGER,
        FOREIGN KEY (account_id) REFERENCES accounts(account_id)
    );

    CREATE TABLE IF NOT EXISTS time_deposits (
        deposit_id    INTEGER PRIMARY KEY,
        account_id    INTEGER NOT NULL,
        start_date    TEXT NOT NULL,
        maturity_date TEXT NOT NULL,
        principal     REAL NOT NULL,
        interest_rate REAL NOT NULL, -- annual (e.g., 0.035)
        status        TEXT CHECK(status IN ('ACTIVE','MATURED','REDEEMED')) DEFAULT 'ACTIVE',
        FOREIGN KEY (account_id) REFERENCES accounts(account_id)
    );

    CREATE TABLE IF NOT EXISTS securities_positions (
        position_id   INTEGER PRIMARY KEY,
        account_id    INTEGER NOT NULL,
        symbol        TEXT NOT NULL,
        instrument_type TEXT CHECK(instrument_type IN ('STOCK','BOND','ETF','FUND')) NOT NULL,
        quantity      REAL NOT NULL,
        avg_price     REAL NOT NULL,
        last_price    REAL,
        FOREIGN KEY (account_id) REFERENCES accounts(account_id)
    );
    """)

def upsert_many(conn: sqlite3.Connection, sql: str, rows: Iterable[Tuple[Any, ...]]) -> None:
    """Run INSERT OR REPLACE (or INSERT OR IGNORE) on many rows."""
    cur = conn.cursor()
    cur.executemany(sql, list(rows))

def seed_sample_data(conn: sqlite3.Connection) -> None:
    """Seed initial data idempotently (safe to re-run)."""

    customers = [
        (1, "Asha Patel",   "asha.patel@example.com",   "555-0101", "12 Market St, Boston, MA",  "VERIFIED", 2, "2024-09-10 10:00:00"),
        (2, "Miguel Santos","miguel.santos@example.com","555-0102", "45 Pine Ave, Austin, TX",    "VERIFIED", 3, "2024-10-01 11:30:00"),
        (3, "Liam O'Connor","liam.oconnor@example.com", "555-0103", "9 Harbor Rd, Seattle, WA",  "PENDING",  3, "2024-11-03 09:15:00"),
        (4, "Chen Wei",     "chen.wei@example.com",     "555-0104", "18 Sunset Blvd, San Diego", "VERIFIED", 4, "2024-09-21 14:05:00"),
        (5, "Fatima Zahra", "fatima.zahra@example.com", "555-0105", "77 Elm St, Newark, NJ",     "VERIFIED", 2, "2024-10-14 16:45:00"),
        (6, "Noah Johnson", "noah.johnson@example.com", "555-0106", "200 Oak Dr, Chicago, IL",   "REJECTED", 5, "2024-09-29 12:20:00"),
    ]
    upsert_many(conn,
        """INSERT OR REPLACE INTO customers
           (customer_id, full_name, email, phone, address, kyc_status, risk_rating, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?);""",
        customers
    )

    accounts = [
        (101, 1, "CHECKING", "USD", "2024-09-12", "OPEN",   4200.50),
        (102, 1, "SAVINGS",  "USD", "2024-09-12", "OPEN",  15000.00),
        (103, 2, "CHECKING", "USD", "2024-10-03", "OPEN",   2750.00),
        (104, 2, "BROKERAGE","USD", "2024-10-05", "OPEN",   5000.00),
        (105, 3, "CHECKING", "USD", "2024-11-03", "OPEN",    300.00),
        (106, 4, "CHECKING", "USD", "2024-09-22", "OPEN",   9800.75),
        (107, 4, "BROKERAGE","USD", "2024-09-23", "OPEN",  12000.00),
        (108, 5, "SAVINGS",  "USD", "2024-10-20", "OPEN",  25000.00),
        (109, 6, "CHECKING", "USD", "2024-10-01", "FROZEN",   50.00),
    ]
    upsert_many(conn,
        """INSERT OR REPLACE INTO accounts
           (account_id, customer_id, account_type, currency, opened_date, status, balance)
           VALUES (?, ?, ?, ?, ?, ?, ?);""",
        accounts
    )

    transactions = [
        (1, 101, "2024-10-02 10:00:00",  2000.00, "USD", "DEPOSIT",      "Payroll deposit",          None),
        (2, 101, "2024-10-03 18:22:00",  -150.25, "USD", "WITHDRAWAL",    "Groceries",                None),
        (3, 102, "2024-10-04 09:00:00",    15.20, "USD", "INTEREST",      "Monthly savings interest", None),
        (4, 103, "2024-10-05 14:30:00",   -75.00, "USD", "WITHDRAWAL",    "Utilities",                None),
        (5, 104, "2024-10-06 11:00:00", -1200.00, "USD", "SEC_BUY",       "Buy AAPL 5 @ 240",         None),
        (6, 104, "2024-10-07 12:00:00",   300.00, "USD", "TRANSFER_IN",   "From CHECKING 103",        103),
        (7, 106, "2024-10-03 16:10:00",  -500.00, "USD", "TRANSFER_OUT",  "To SAVINGS 108",           108),
        (8, 108, "2024-10-03 16:10:30",   500.00, "USD", "TRANSFER_IN",   "From CHECKING 106",        106),
        (9, 105, "2024-10-02 15:00:00",   500.00, "USD", "DEPOSIT",       "Cash deposit",             None),
        (10,109, "2024-10-08 08:00:00",   -20.00, "USD", "WITHDRAWAL",    "ATM fee",                  None),
    ]
    upsert_many(conn,
        """INSERT OR REPLACE INTO transactions
           (txn_id, account_id, txn_time, amount, currency, txn_type, description, counterparty_account)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?);""",
        transactions
    )

    time_deposits = [
        (1, 102, "2024-10-01", "2025-04-01", 10000.00, 0.035, "ACTIVE"),
        (2, 108, "2024-10-15", "2025-10-15", 15000.00, 0.040, "ACTIVE"),
    ]
    upsert_many(conn,
        """INSERT OR REPLACE INTO time_deposits
           (deposit_id, account_id, start_date, maturity_date, principal, interest_rate, status)
           VALUES (?, ?, ?, ?, ?, ?, ?);""",
        time_deposits
    )

    securities = [
        (1, 104, "AAPL", "STOCK", 5,   240.00, 245.50),
        (2, 107, "MSFT", "STOCK", 10,  330.00, 332.10),
        (3, 107, "BND",  "ETF",   100,  77.50,  78.00),
    ]
    upsert_many(conn,
        """INSERT OR REPLACE INTO securities_positions
           (position_id, account_id, symbol, instrument_type, quantity, avg_price, last_price)
           VALUES (?, ?, ?, ?, ?, ?, ?);""",
        securities
    )

# ---------- Public helpers to add data later ----------

def add_customer(conn: sqlite3.Connection,
                 full_name: str,
                 email: Optional[str] = None,
                 phone: Optional[str] = None,
                 address: Optional[str] = None,
                 kyc_status: str = "PENDING",
                 risk_rating: int = 3,
                 created_at: Optional[str] = None) -> int:
    cur = conn.cursor()
    created_at = created_at or datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    cur.execute("""
        INSERT INTO customers (full_name, email, phone, address, kyc_status, risk_rating, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (full_name, email, phone, address, kyc_status, risk_rating, created_at))
    return cur.lastrowid

def add_account(conn: sqlite3.Connection,
                customer_id: int,
                account_type: str,
                currency: str = "USD",
                opened_date: Optional[str] = None,
                status: str = "OPEN",
                balance: float = 0.0) -> int:
    opened_date = opened_date or datetime.utcnow().strftime("%Y-%m-%d")
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO accounts (customer_id, account_type, currency, opened_date, status, balance)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (customer_id, account_type, currency, opened_date, status, balance))
    return cur.lastrowid

def add_transaction(conn: sqlite3.Connection,
                    account_id: int,
                    amount: float,
                    txn_type: str,
                    txn_time: Optional[str] = None,
                    currency: str = "USD",
                    description: Optional[str] = None,
                    counterparty_account: Optional[int] = None) -> int:
    txn_time = txn_time or datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO transactions (account_id, txn_time, amount, currency, txn_type, description, counterparty_account)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (account_id, txn_time, amount, currency, txn_type, description, counterparty_account))
    return cur.lastrowid

def add_time_deposit(conn: sqlite3.Connection,
                     account_id: int,
                     start_date: str,
                     maturity_date: str,
                     principal: float,
                     interest_rate: float,
                     status: str = "ACTIVE") -> int:
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO time_deposits (account_id, start_date, maturity_date, principal, interest_rate, status)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (account_id, start_date, maturity_date, principal, interest_rate, status))
    return cur.lastrowid

def add_security_position(conn: sqlite3.Connection,
                          account_id: int,
                          symbol: str,
                          instrument_type: str,
                          quantity: float,
                          avg_price: float,
                          last_price: Optional[float] = None) -> int:
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO securities_positions (account_id, symbol, instrument_type, quantity, avg_price, last_price)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (account_id, symbol, instrument_type, quantity, avg_price, last_price))
    return cur.lastrowid

# ---------- CLI ----------

def main():
    parser = argparse.ArgumentParser(description="Build/seed SQLite banking DB.")
    parser.add_argument("--db", default="banking_mvp.db", help="SQLite file path (default: banking_mvp.db)")
    parser.add_argument("--no-seed", action="store_true", help="Create tables only (skip sample data)")
    args = parser.parse_args()

    with connect(args.db) as conn:
        create_tables(conn)
        if not args.no_seed:
            seed_sample_data(conn)

    print(f"✅ Database ready at: {args.db}")

if __name__ == "__main__":
    main()
