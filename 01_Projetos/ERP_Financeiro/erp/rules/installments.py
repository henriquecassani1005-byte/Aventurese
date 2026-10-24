"""Projeção de parcelamentos: divide o total e aloca cada parcela em um mês futuro."""
from __future__ import annotations

from datetime import date

import pandas as pd


def month_of(d: date) -> str:
    return d.strftime("%Y-%m")


def add_months(month: str, k: int) -> str:
    """'2026-11' + 3 = '2027-02'."""
    return str(pd.Period(month, freq="M") + k)


def project_schedule(total_amount: float, n_installments: int, first_due_month: str) -> pd.DataFrame:
    """Cronograma com installment_no, due_month, amount.

    Trabalha em centavos: a soma das parcelas é exatamente o total. O resto da divisão
    (até n menos 1 centavos) é distribuído um centavo por parcela, começando pela primeira.
    """
    if n_installments < 1:
        raise ValueError("O número de parcelas deve ser de pelo menos 1.")
    if total_amount <= 0:
        raise ValueError("O valor total deve ser positivo.")
    total_cents = int(round(total_amount * 100))
    base, rest = divmod(total_cents, n_installments)
    return pd.DataFrame(
        {
            "installment_no": range(1, n_installments + 1),
            "due_month": [add_months(first_due_month, i) for i in range(n_installments)],
            "amount": [(base + (1 if i < rest else 0)) / 100 for i in range(n_installments)],
        }
    )
