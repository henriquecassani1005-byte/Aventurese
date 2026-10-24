"""Camada de persistência: único módulo com SQL. Regras de negócio ficam em erp/rules."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd

from erp import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS accounts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL UNIQUE,
    currency        TEXT NOT NULL CHECK (currency IN ('BRL', 'EUR')),
    opening_balance REAL NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS categories (
    name       TEXT PRIMARY KEY,
    is_expense INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS category_rules (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    keyword  TEXT NOT NULL UNIQUE,
    category TEXT NOT NULL REFERENCES categories(name)
);

CREATE TABLE IF NOT EXISTS transactions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id  INTEGER NOT NULL REFERENCES accounts(id),
    date        TEXT NOT NULL,
    description TEXT NOT NULL,
    amount      REAL NOT NULL,
    currency    TEXT NOT NULL CHECK (currency IN ('BRL', 'EUR')),
    category    TEXT REFERENCES categories(name),
    dedup_hash  TEXT NOT NULL,
    source_file TEXT,
    imported_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (account_id, dedup_hash)
);
CREATE INDEX IF NOT EXISTS idx_transactions_date ON transactions(date);

CREATE TABLE IF NOT EXISTS budgets (
    category      TEXT PRIMARY KEY REFERENCES categories(name),
    monthly_limit REAL NOT NULL CHECK (monthly_limit >= 0),
    currency      TEXT NOT NULL CHECK (currency IN ('BRL', 'EUR'))
);

CREATE TABLE IF NOT EXISTS installment_purchases (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    description     TEXT NOT NULL,
    category        TEXT REFERENCES categories(name),
    currency        TEXT NOT NULL CHECK (currency IN ('BRL', 'EUR')),
    total_amount    REAL NOT NULL CHECK (total_amount > 0),
    n_installments  INTEGER NOT NULL CHECK (n_installments >= 1),
    purchase_date   TEXT NOT NULL,
    first_due_month TEXT NOT NULL,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS installment_schedule (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    purchase_id    INTEGER NOT NULL REFERENCES installment_purchases(id) ON DELETE CASCADE,
    installment_no INTEGER NOT NULL,
    due_month      TEXT NOT NULL,
    amount         REAL NOT NULL,
    UNIQUE (purchase_id, installment_no)
);
CREATE INDEX IF NOT EXISTS idx_schedule_month ON installment_schedule(due_month);
"""

# (nome, is_expense). Categorias que não são despesa ficam fora do Realizado vs. Orçado.
DEFAULT_CATEGORIES = [
    ("Moradia", 1),
    ("Alimentação", 1),
    ("Kothon", 1),
    ("Lazer", 1),
    ("Transporte", 1),
    ("Saúde", 1),
    ("Educação", 1),
    ("Receita", 0),
    ("Transferência", 0),
    ("Fatura Cartão", 0),
]

TRANSACTION_COLUMNS = [
    "account_id", "date", "description", "amount", "currency", "category", "dedup_hash", "source_file",
]


# ---------------------------------------------------------------- conexão

def connect(path: str | Path | None = None) -> sqlite3.Connection:
    path = path or config.DB_PATH
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    with conn:
        conn.executemany("INSERT OR IGNORE INTO categories (name, is_expense) VALUES (?, ?)", DEFAULT_CATEGORIES)
        conn.execute("INSERT OR IGNORE INTO category_rules (keyword, category) VALUES ('FATURA', 'Fatura Cartão')")


def _df(conn: sqlite3.Connection, sql: str, params: tuple | dict = ()) -> pd.DataFrame:
    return pd.read_sql_query(sql, conn, params=params)


# ---------------------------------------------------------------- settings

def get_setting(conn: sqlite3.Connection, key: str, default: str | None = None) -> str | None:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(conn: sqlite3.Connection, key: str, value: str) -> None:
    with conn:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, str(value)),
        )


def get_fx_rate(conn: sqlite3.Connection) -> float:
    """Taxa BRL por 1 EUR: painel (SQLite) tem prioridade sobre o .env."""
    saved = get_setting(conn, "brl_per_eur")
    return float(saved) if saved else config.DEFAULT_BRL_PER_EUR


def set_fx_rate(conn: sqlite3.Connection, brl_per_eur: float) -> None:
    if brl_per_eur <= 0:
        raise ValueError("A taxa de câmbio deve ser positiva.")
    set_setting(conn, "brl_per_eur", repr(float(brl_per_eur)))


# ---------------------------------------------------------------- contas

def add_account(conn: sqlite3.Connection, name: str, currency: str, opening_balance: float = 0.0) -> int:
    with conn:
        cur = conn.execute(
            "INSERT INTO accounts (name, currency, opening_balance) VALUES (?, ?, ?)",
            (name.strip(), currency, round(opening_balance, 2)),
        )
    return cur.lastrowid


def list_accounts(conn: sqlite3.Connection) -> pd.DataFrame:
    return _df(conn, "SELECT id, name, currency, opening_balance FROM accounts ORDER BY name")


def account_balances(conn: sqlite3.Connection) -> pd.DataFrame:
    df = _df(
        conn,
        """
        SELECT a.id, a.name, a.currency, a.opening_balance,
               COALESCE(SUM(t.amount), 0) AS movement
        FROM accounts a LEFT JOIN transactions t ON t.account_id = a.id
        GROUP BY a.id ORDER BY a.name
        """,
    )
    df["balance"] = (df["opening_balance"] + df["movement"]).round(2)
    return df


def calibrate_opening_balance(conn: sqlite3.Connection, account_id: int, current_balance: float) -> float:
    """Ajusta o saldo inicial para que saldo = movimentação importada + inicial == saldo informado."""
    row = conn.execute(
        "SELECT COALESCE(SUM(amount), 0) AS movement FROM transactions WHERE account_id = ?", (account_id,)
    ).fetchone()
    opening = round(current_balance - row["movement"], 2)
    with conn:
        conn.execute("UPDATE accounts SET opening_balance = ? WHERE id = ?", (opening, account_id))
    return opening


# ---------------------------------------------------------------- categorias e regras

def list_categories(conn: sqlite3.Connection) -> pd.DataFrame:
    return _df(conn, "SELECT name, is_expense FROM categories ORDER BY name")


def add_category(conn: sqlite3.Connection, name: str, is_expense: bool = True) -> None:
    with conn:
        conn.execute("INSERT INTO categories (name, is_expense) VALUES (?, ?)", (name.strip(), int(is_expense)))


def list_rules(conn: sqlite3.Connection) -> pd.DataFrame:
    return _df(conn, "SELECT id, keyword, category FROM category_rules ORDER BY category, keyword")


def add_rule(conn: sqlite3.Connection, keyword: str, category: str) -> None:
    with conn:
        conn.execute(
            "INSERT INTO category_rules (keyword, category) VALUES (?, ?) "
            "ON CONFLICT(keyword) DO UPDATE SET category = excluded.category",
            (keyword.strip().upper(), category),
        )


def delete_rule(conn: sqlite3.Connection, rule_id: int) -> None:
    with conn:
        conn.execute("DELETE FROM category_rules WHERE id = ?", (rule_id,))


# ---------------------------------------------------------------- transações

def existing_hashes(conn: sqlite3.Connection, account_id: int) -> set[str]:
    rows = conn.execute("SELECT dedup_hash FROM transactions WHERE account_id = ?", (account_id,)).fetchall()
    return {r["dedup_hash"] for r in rows}


def insert_transactions(conn: sqlite3.Connection, df: pd.DataFrame) -> int:
    """Insere ignorando duplicatas (UNIQUE account_id + dedup_hash). Retorna quantas linhas entraram."""
    if df.empty:
        return 0
    clean = df[TRANSACTION_COLUMNS].astype(object)
    clean = clean.where(clean.notna(), None)
    before = conn.total_changes
    with conn:
        conn.executemany(
            "INSERT OR IGNORE INTO transactions "
            "(account_id, date, description, amount, currency, category, dedup_hash, source_file) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            clean.itertuples(index=False, name=None),
        )
    return conn.total_changes - before


def list_transactions(
    conn: sqlite3.Connection,
    month: str | None = None,
    account_id: int | None = None,
    only_uncategorized: bool = False,
) -> pd.DataFrame:
    where, params = [], []
    if month:
        where.append("substr(t.date, 1, 7) = ?")
        params.append(month)
    if account_id:
        where.append("t.account_id = ?")
        params.append(account_id)
    if only_uncategorized:
        where.append("t.category IS NULL")
    clause = f"WHERE {' AND '.join(where)}" if where else ""
    return _df(
        conn,
        f"""
        SELECT t.id, t.date, a.name AS account, t.description, t.amount, t.currency, t.category
        FROM transactions t JOIN accounts a ON a.id = t.account_id
        {clause}
        ORDER BY t.date DESC, t.id DESC
        """,
        tuple(params),
    )


def update_transaction_categories(conn: sqlite3.Connection, updates: list[tuple[str | None, int]]) -> None:
    """updates: lista de (categoria, id_transacao)."""
    with conn:
        conn.executemany("UPDATE transactions SET category = ? WHERE id = ?", updates)


# ---------------------------------------------------------------- orçamento

def list_budgets(conn: sqlite3.Connection) -> pd.DataFrame:
    return _df(conn, "SELECT category, monthly_limit, currency FROM budgets ORDER BY category")


def upsert_budget(conn: sqlite3.Connection, category: str, monthly_limit: float, currency: str) -> None:
    with conn:
        conn.execute(
            "INSERT INTO budgets (category, monthly_limit, currency) VALUES (?, ?, ?) "
            "ON CONFLICT(category) DO UPDATE SET monthly_limit = excluded.monthly_limit, "
            "currency = excluded.currency",
            (category, round(monthly_limit, 2), currency),
        )


def delete_budget(conn: sqlite3.Connection, category: str) -> None:
    with conn:
        conn.execute("DELETE FROM budgets WHERE category = ?", (category,))


# ---------------------------------------------------------------- parcelamentos

def insert_installment_purchase(conn: sqlite3.Connection, purchase: dict, schedule: pd.DataFrame) -> int:
    """Grava a compra e o cronograma projetado na mesma transação."""
    with conn:
        cur = conn.execute(
            "INSERT INTO installment_purchases "
            "(description, category, currency, total_amount, n_installments, purchase_date, first_due_month) "
            "VALUES (:description, :category, :currency, :total_amount, :n_installments, "
            ":purchase_date, :first_due_month)",
            purchase,
        )
        purchase_id = cur.lastrowid
        conn.executemany(
            "INSERT INTO installment_schedule (purchase_id, installment_no, due_month, amount) VALUES (?, ?, ?, ?)",
            [(purchase_id, int(r.installment_no), r.due_month, float(r.amount)) for r in schedule.itertuples()],
        )
    return purchase_id


def list_installment_purchases(conn: sqlite3.Connection) -> pd.DataFrame:
    return _df(
        conn,
        """
        SELECT id, description, category, currency, total_amount, n_installments, purchase_date, first_due_month
        FROM installment_purchases ORDER BY purchase_date DESC, id DESC
        """,
    )


def delete_installment_purchase(conn: sqlite3.Connection, purchase_id: int) -> None:
    with conn:
        conn.execute("DELETE FROM installment_purchases WHERE id = ?", (purchase_id,))


def list_schedule(conn: sqlite3.Connection) -> pd.DataFrame:
    return _df(
        conn,
        """
        SELECT s.purchase_id, p.description, p.category, p.currency,
               s.installment_no, p.n_installments, s.due_month, s.amount
        FROM installment_schedule s JOIN installment_purchases p ON p.id = s.purchase_id
        ORDER BY s.due_month, p.description
        """,
    )
