"""Higienização e chave de deduplicação das transações importadas."""
from __future__ import annotations

import hashlib

import pandas as pd

from erp.rules.categorization import apply_rules


def normalize_description(s: pd.Series) -> pd.Series:
    return s.fillna("").str.upper().str.replace(r"\s+", " ", regex=True).str.strip()


def build_dedup_hashes(df: pd.DataFrame, account_id: int) -> pd.Series:
    """Hash estável por transação.

    Chave: conta + data + valor + descrição normalizada (ou o ID do banco, quando existe).
    Lançamentos idênticos no mesmo arquivo recebem um índice de ocorrência, então duas compras
    iguais no mesmo dia continuam sendo duas transações, e reimportar o mesmo arquivo não duplica.
    """
    base = f"{account_id}|" + df["date"] + "|" + df["amount"].map(lambda v: f"{v:.2f}") + "|" + normalize_description(df["description"])
    has_id = df["ext_id"].notna() & (df["ext_id"].astype(str).str.strip() != "")
    key = base.where(~has_id, f"{account_id}|ID|" + df["ext_id"].astype(str).str.strip())
    occurrence = key.groupby(key).cumcount().astype(str)
    return (key + "#" + occurrence).map(lambda k: hashlib.sha256(k.encode("utf-8")).hexdigest())


def prepare_transactions(
    parsed: pd.DataFrame,
    account_id: int,
    currency: str,
    source_file: str,
    rules: pd.DataFrame,
) -> pd.DataFrame:
    """Transforma a saída do parser no formato da tabela transactions."""
    out = parsed.copy()
    out["account_id"] = account_id
    out["currency"] = currency
    out["source_file"] = source_file
    out["category"] = apply_rules(out["description"], rules)
    out["dedup_hash"] = build_dedup_hashes(out, account_id) if not out.empty else pd.Series(dtype=object)
    return out
