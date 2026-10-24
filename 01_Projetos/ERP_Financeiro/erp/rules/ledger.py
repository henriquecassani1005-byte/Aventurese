"""Ledger multimoeda: conversão por taxa estática (BRL por 1 EUR) e consolidação de saldos."""
from __future__ import annotations

import pandas as pd

from erp.config import CURRENCIES


def _check(currency: str) -> None:
    if currency not in CURRENCIES:
        raise ValueError(f"Moeda não suportada: {currency!r}. Use {', '.join(CURRENCIES)}.")


def rate_factor(src: str, dst: str, brl_per_eur: float) -> float:
    _check(src)
    _check(dst)
    if brl_per_eur <= 0:
        raise ValueError("A taxa de câmbio deve ser positiva.")
    if src == dst:
        return 1.0
    return brl_per_eur if (src, dst) == ("EUR", "BRL") else 1.0 / brl_per_eur


def convert(amount: float, src: str, dst: str, brl_per_eur: float) -> float:
    return amount * rate_factor(src, dst, brl_per_eur)


def convert_column(df: pd.DataFrame, amount_col: str, currency_col: str, dst: str, brl_per_eur: float) -> pd.Series:
    """Converte uma coluna de valores para a moeda de destino, linha a linha."""
    if df.empty:
        return pd.Series(dtype=float, index=df.index)
    factors = df[currency_col].map({c: rate_factor(c, dst, brl_per_eur) for c in CURRENCIES})
    if factors.isna().any():
        raise ValueError("Moeda desconhecida encontrada nos dados.")
    return df[amount_col] * factors


def consolidate_balances(balances: pd.DataFrame, dst: str, brl_per_eur: float) -> pd.DataFrame:
    """Adiciona balance_display (saldo na moeda de exibição) à tabela de saldos por conta."""
    out = balances.copy()
    out["balance_display"] = convert_column(out, "balance", "currency", dst, brl_per_eur).round(2)
    return out


def net_worth(balances: pd.DataFrame, dst: str, brl_per_eur: float) -> float:
    return round(float(consolidate_balances(balances, dst, brl_per_eur)["balance_display"].sum()), 2)
