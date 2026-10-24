"""Lançamentos: revisão e classificação manual de categorias."""
from __future__ import annotations

import streamlit as st

from erp import database, services
from erp.ui.components import AppContext, flash, money_column


def render(ctx: AppContext) -> None:
    accounts = database.list_accounts(ctx.conn)
    categories = database.list_categories(ctx.conn)["name"].tolist()

    f1, f2, f3 = st.columns(3)
    month = f1.text_input("Mês (AAAA-MM, vazio para todos)", value=ctx.current_month)
    account_id = f2.selectbox(
        "Conta", [0] + accounts["id"].tolist(),
        format_func=lambda i: "Todas" if i == 0 else accounts.set_index("id").loc[i, "name"],
    )
    only_pending = f3.checkbox("Somente sem categoria")

    if st.button("Aplicar regras às transações sem categoria"):
        flash("success", f"{services.reapply_rules(ctx.conn)} transações classificadas pelas regras.")
        st.rerun()

    df = database.list_transactions(
        ctx.conn, month=month.strip() or None, account_id=account_id or None, only_uncategorized=only_pending
    )
    if df.empty:
        st.info("Nenhum lançamento para o filtro.")
        return

    edited = st.data_editor(
        df,
        hide_index=True,
        disabled=["id", "date", "account", "description", "amount", "currency"],
        column_config={
            "category": st.column_config.SelectboxColumn("category", options=categories),
            "amount": money_column("amount"),
        },
        key="tx_editor",
    )
    changed = edited["category"].fillna("") != df["category"].fillna("")
    if st.button("Salvar categorias", disabled=not changed.any()):
        updates = [(row.category or None, int(row.id)) for row in edited[changed].itertuples()]
        database.update_transaction_categories(ctx.conn, updates)
        flash("success", f"{len(updates)} categorias atualizadas.")
        st.rerun()
