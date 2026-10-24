"""Orçamento: limites mensais por categoria e Realizado vs. Orçado."""
from __future__ import annotations

import streamlit as st

from erp import config, database
from erp.rules import budget
from erp.ui.components import AppContext, flash, money_column
from erp.ui.dashboard import render_budget_table
from erp.rules.installments import add_months


def render(ctx: AppContext) -> None:
    categories = database.list_categories(ctx.conn)
    expense_names = categories.loc[categories["is_expense"] == 1, "name"].tolist()

    st.subheader("Limite mensal por categoria")
    with st.form("budget_form"):
        c1, c2, c3 = st.columns(3)
        category = c1.selectbox("Categoria", expense_names)
        limit = c2.number_input("Limite mensal", min_value=0.0, step=50.0, format="%.2f")
        currency = c3.selectbox("Moeda do limite", config.CURRENCIES)
        if st.form_submit_button("Salvar limite", type="primary"):
            database.upsert_budget(ctx.conn, category, float(limit), currency)
            flash("success", f"Limite de {category} salvo.")
            st.rerun()

    budgets = database.list_budgets(ctx.conn)
    if not budgets.empty:
        st.dataframe(
            budgets.rename(columns={"category": "Categoria", "monthly_limit": "Limite", "currency": "Moeda"}),
            hide_index=True,
            column_config={"Limite": money_column("Limite")},
        )
        with st.expander("Remover limite"):
            to_remove = st.selectbox("Categoria", budgets["category"].tolist(), key="budget_remove")
            if st.button("Remover"):
                database.delete_budget(ctx.conn, to_remove)
                flash("success", f"Limite de {to_remove} removido.")
                st.rerun()

    st.subheader("Realizado vs. Orçado")
    months = [add_months(ctx.current_month, i) for i in range(-11, 1)]
    month = st.selectbox("Mês", months, index=len(months) - 1)
    result = budget.realized_vs_budget(
        budgets, categories, database.list_transactions(ctx.conn), database.list_schedule(ctx.conn),
        month, ctx.currency, ctx.rate,
    )
    render_budget_table(result, ctx.currency)
