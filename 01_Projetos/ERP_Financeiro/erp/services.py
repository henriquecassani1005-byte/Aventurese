"""Orquestração: combina database e rules. É o que a interface chama."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date

import pandas as pd

from erp import database
from erp.rules import categorization, etl, installments
from erp.rules.parsers import ParserProfile, parse_csv


@dataclass
class IngestPreview:
    rows: pd.DataFrame   # linhas prontas para inserir
    new: int
    duplicates: int
    rejected: int


@dataclass
class IngestReport:
    inserted: int
    duplicates: int
    rejected: int


def _prepare(
    conn: sqlite3.Connection, raw: bytes, profile: ParserProfile, account_id: int, source_name: str
) -> tuple[pd.DataFrame, int]:
    accounts = database.list_accounts(conn)
    match = accounts[accounts["id"] == account_id]
    if match.empty:
        raise ValueError("Conta não encontrada.")
    account_currency = match.iloc[0]["currency"]
    if account_currency != profile.currency:
        raise ValueError(
            f"A conta está em {account_currency} mas o perfil '{profile.name}' é {profile.currency}. "
            "Escolha o perfil do banco correto."
        )
    parsed = parse_csv(raw, profile)
    rows = etl.prepare_transactions(
        parsed.df, account_id, profile.currency, source_name, database.list_rules(conn)
    )
    return rows, parsed.rejected


def preview_csv(
    conn: sqlite3.Connection, raw: bytes, profile: ParserProfile, account_id: int, source_name: str
) -> IngestPreview:
    rows, rejected = _prepare(conn, raw, profile, account_id, source_name)
    known = database.existing_hashes(conn, account_id)
    is_dup = rows["dedup_hash"].isin(known) if not rows.empty else pd.Series(dtype=bool)
    rows = rows.assign(status=is_dup.map({True: "Já existe", False: "Nova"})).sort_values(
        "status", ascending=False, kind="stable"
    )
    duplicates = int(is_dup.sum())
    return IngestPreview(rows=rows, new=len(rows) - duplicates, duplicates=duplicates, rejected=rejected)


def import_csv(
    conn: sqlite3.Connection, raw: bytes, profile: ParserProfile, account_id: int, source_name: str
) -> IngestReport:
    rows, rejected = _prepare(conn, raw, profile, account_id, source_name)
    inserted = database.insert_transactions(conn, rows)
    return IngestReport(inserted=inserted, duplicates=len(rows) - inserted, rejected=rejected)


def reapply_rules(conn: sqlite3.Connection) -> int:
    """Aplica as regras às transações sem categoria. Nunca sobrescreve categoria já definida."""
    pending = database.list_transactions(conn, only_uncategorized=True)
    if pending.empty:
        return 0
    suggested = categorization.apply_rules(pending["description"], database.list_rules(conn))
    hits = pending.assign(suggested=suggested).dropna(subset=["suggested"])
    database.update_transaction_categories(conn, [(r.suggested, int(r.id)) for r in hits.itertuples()])
    return len(hits)


def register_installment_purchase(
    conn: sqlite3.Connection,
    description: str,
    category: str | None,
    currency: str,
    total_amount: float,
    n_installments: int,
    purchase_date: date,
    first_due_month: str,
) -> pd.DataFrame:
    """Projeta o passivo e grava compra e cronograma. Retorna o cronograma criado."""
    schedule = installments.project_schedule(total_amount, n_installments, first_due_month)
    database.insert_installment_purchase(
        conn,
        {
            "description": description.strip(),
            "category": category,
            "currency": currency,
            "total_amount": round(total_amount, 2),
            "n_installments": n_installments,
            "purchase_date": purchase_date.isoformat(),
            "first_due_month": first_due_month,
        },
        schedule,
    )
    return schedule
