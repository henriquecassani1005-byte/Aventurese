"""Realizado vs. Orçado do mês: contas bancárias mais parcelas de cartão que vencem no mês."""
from __future__ import annotations

import numpy as np
import pandas as pd

from erp.rules import ledger

UNCATEGORIZED = "Sem categoria"
TOTAL = "TOTAL"
COLUMNS = ["category", "budget", "account_spend", "installments", "realized", "pct_used", "remaining"]


def _spend_by_category(
    df: pd.DataFrame, amount_col: str, sign: int, currency: str, rate: float, expense_cats: set[str]
) -> pd.Series:
    """Soma o gasto por categoria na moeda de exibição. Sem categoria só conta se for saída de caixa."""
    if df.empty:
        return pd.Series(dtype=float)
    spend = sign * ledger.convert_column(df, amount_col, "currency", currency, rate)
    category = df["category"]
    keep = (category.isna() & (spend > 0)) | category.isin(expense_cats)
    return spend[keep].groupby(category[keep].fillna(UNCATEGORIZED)).sum()


def realized_vs_budget(
    budgets: pd.DataFrame,
    categories: pd.DataFrame,
    transactions: pd.DataFrame,
    schedule: pd.DataFrame,
    month: str,
    currency: str,
    rate: float,
) -> pd.DataFrame:
    """Uma linha por categoria com orçamento ou gasto no mês, mais a linha TOTAL.

    budgets: category, monthly_limit, currency | categories: name, is_expense
    transactions: date, amount, currency, category | schedule: due_month, amount, currency, category
    """
    expense_cats = set(categories.loc[categories["is_expense"] == 1, "name"])

    if budgets.empty:
        budget = pd.Series(dtype=float)
    else:
        budget = ledger.convert_column(budgets, "monthly_limit", "currency", currency, rate)
        budget = budget.groupby(budgets["category"]).sum()

    tx_month = transactions[transactions["date"].str[:7] == month] if not transactions.empty else transactions
    account_spend = _spend_by_category(tx_month, "amount", -1, currency, rate, expense_cats)

    sched_month = schedule[schedule["due_month"] == month] if not schedule.empty else schedule
    installments = _spend_by_category(sched_month, "amount", 1, currency, rate, expense_cats)

    index = sorted(set(budget.index) | set(account_spend.index) | set(installments.index))
    if not index:
        return pd.DataFrame(columns=COLUMNS)

    out = pd.DataFrame(
        {
            "budget": budget.reindex(index).fillna(0.0),
            "account_spend": account_spend.reindex(index).fillna(0.0),
            "installments": installments.reindex(index).fillna(0.0),
        }
    )
    out["realized"] = out["account_spend"] + out["installments"]
    out = out.sort_values(["budget", "realized"], ascending=False)
    out.loc[TOTAL] = out[["budget", "account_spend", "installments", "realized"]].sum()
    out["pct_used"] = np.where(out["budget"] > 0, out["realized"] / out["budget"].where(out["budget"] > 0) * 100, np.nan)
    out["remaining"] = np.where(out["budget"] > 0, out["budget"] - out["realized"], np.nan)
    out.index.name = "category"
    return out.reset_index()[COLUMNS].round(2)
