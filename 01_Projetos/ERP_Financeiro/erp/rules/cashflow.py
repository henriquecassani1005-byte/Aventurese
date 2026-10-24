"""Fluxo de caixa futuro: Caixa Livre Real = saldo atual em contas menos faturas projetadas."""
from __future__ import annotations

import pandas as pd

from erp.rules import ledger
from erp.rules.installments import add_months


def _schedule_display(schedule: pd.DataFrame, currency: str, rate: float) -> pd.DataFrame:
    out = schedule[["due_month", "currency", "amount"]].copy()
    out["amount_display"] = ledger.convert_column(out, "amount", "currency", currency, rate)
    return out


def free_cash_summary(
    balance: float, schedule: pd.DataFrame, reference_month: str, currency: str, rate: float
) -> dict:
    """balance: patrimônio em contas já na moeda de exibição. schedule: saída de database.list_schedule."""
    sched = _schedule_display(schedule, currency, rate)
    invoice = float(sched.loc[sched["due_month"] == reference_month, "amount_display"].sum())
    open_liability = float(sched.loc[sched["due_month"] >= reference_month, "amount_display"].sum())
    return {
        "reference_month": reference_month,
        "balance": round(balance, 2),
        "invoice": round(invoice, 2),
        "free_cash": round(balance - invoice, 2),
        "open_liability": round(open_liability, 2),
    }


def cashflow_timeline(
    balance: float, schedule: pd.DataFrame, start_month: str, months: int, currency: str, rate: float
) -> pd.DataFrame:
    """Faturas por mês, acumulado e caixa livre depois de pagar o acumulado (sem novas receitas)."""
    sched = _schedule_display(schedule, currency, rate)
    month_list = [add_months(start_month, i) for i in range(months)]
    per_month = sched.groupby("due_month")["amount_display"].sum().reindex(month_list).fillna(0.0)
    out = pd.DataFrame({"month": month_list, "invoices": per_month.values})
    out["cumulative_invoices"] = out["invoices"].cumsum()
    out["free_cash_after"] = balance - out["cumulative_invoices"]
    return out.round(2)
