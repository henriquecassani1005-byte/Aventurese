"""Dashboard: patrimônio consolidado, Caixa Livre Real, fluxo futuro e Realizado vs. Orçado."""
from __future__ import annotations

import streamlit as st

from erp import database
from erp.rules import budget, cashflow, ledger
from erp.rules.installments import add_months
from erp.ui.components import AppContext, fmt_money, money_column


def render(ctx: AppContext) -> None:
    balances = database.account_balances(ctx.conn)
    if balances.empty:
        st.info("Nenhuma conta cadastrada. Vá em Cadastros, crie as contas e depois importe os CSVs.")
        return

    cur = ctx.currency
    consolidated = ledger.consolidate_balances(balances, cur, ctx.rate)
    net_worth = round(float(consolidated["balance_display"].sum()), 2)
    schedule = database.list_schedule(ctx.conn)

    months = [add_months(ctx.current_month, i) for i in range(13)]
    reference = st.selectbox(
        "Mês de referência da fatura",
        months,
        index=1,
        help="Padrão: próximo mês. Escolha o mês corrente se a fatura dele ainda não foi paga.",
    )
    summary = cashflow.free_cash_summary(net_worth, schedule, reference, cur, ctx.rate)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Patrimônio em contas", fmt_money(summary["balance"], cur))
    c2.metric(f"Faturas projetadas {reference}", fmt_money(summary["invoice"], cur))
    c3.metric("Caixa Livre Real", fmt_money(summary["free_cash"], cur))
    c4.metric("Passivo parcelado em aberto", fmt_money(summary["open_liability"], cur), help=f"Parcelas de {reference} em diante.")

    left, right = st.columns(2)
    with left:
        st.subheader("Saldos por conta")
        view = consolidated[["name", "currency", "balance", "balance_display"]].rename(
            columns={"name": "Conta", "currency": "Moeda", "balance": "Saldo original", "balance_display": f"Saldo em {cur}"}
        )
        st.dataframe(
            view, hide_index=True,
            column_config={"Saldo original": money_column("Saldo original"), f"Saldo em {cur}": money_column(f"Saldo em {cur}")},
        )
    with right:
        st.subheader("Fluxo futuro por mês")
        timeline = cashflow.cashflow_timeline(net_worth, schedule, reference, 12, cur, ctx.rate)
        st.dataframe(
            timeline.rename(
                columns={
                    "month": "Mês",
                    "invoices": f"Faturas ({cur})",
                    "cumulative_invoices": "Acumulado",
                    "free_cash_after": "Caixa livre após",
                }
            ),
            hide_index=True,
            column_config={c: money_column(c) for c in [f"Faturas ({cur})", "Acumulado", "Caixa livre após"]},
        )
    st.caption(
        "Caixa livre após considera apenas o saldo atual menos as parcelas acumuladas, sem novas receitas nem gastos."
    )

    st.subheader(f"Realizado vs. Orçado em {ctx.current_month}")
    result = budget.realized_vs_budget(
        database.list_budgets(ctx.conn),
        database.list_categories(ctx.conn),
        database.list_transactions(ctx.conn),
        schedule,
        ctx.current_month,
        cur,
        ctx.rate,
    )
    render_budget_table(result, cur)


def render_budget_table(result, currency: str) -> None:
    if result.empty:
        st.info("Sem orçamento cadastrado nem gastos no mês. Cadastre limites na aba Orçamento.")
        return
    view = result.rename(
        columns={
            "category": "Categoria",
            "budget": f"Orçado ({currency})",
            "account_spend": "Em conta",
            "installments": "Parcelas do mês",
            "realized": "Realizado",
            "pct_used": "% consumo",
            "remaining": "Restante",
        }
    )
    st.dataframe(
        view,
        hide_index=True,
        column_config={
            f"Orçado ({currency})": money_column(f"Orçado ({currency})"),
            "Em conta": money_column("Em conta"),
            "Parcelas do mês": money_column("Parcelas do mês"),
            "Realizado": money_column("Realizado"),
            "% consumo": st.column_config.NumberColumn("% consumo", format="%.1f%%"),
            "Restante": money_column("Restante"),
        },
    )
    over = result[(result["category"] != budget.TOTAL) & (result["pct_used"] > 100)]
    if not over.empty:
        st.warning("Orçamento estourado em: " + ", ".join(over["category"]))
    if (result["category"] == budget.UNCATEGORIZED).any():
        st.caption("Há gastos sem categoria. Classifique na aba Lançamentos ou crie regras em Cadastros.")
