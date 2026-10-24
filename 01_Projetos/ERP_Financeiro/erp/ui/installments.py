"""Cartão de crédito: cadastro de compras parceladas e passivo futuro."""
from __future__ import annotations

import streamlit as st

from erp import config, database, services
from erp.rules import ledger
from erp.rules.installments import add_months
from erp.ui.components import AppContext, flash, fmt_money, money_column


def render(ctx: AppContext) -> None:
    categories = database.list_categories(ctx.conn)
    month_options = [add_months(ctx.current_month, i) for i in range(-1, 24)]

    st.subheader("Nova compra parcelada")
    st.caption("Compra à vista no cartão? Cadastre com 1 parcela para ela entrar na fatura projetada.")
    with st.form("new_installment", clear_on_submit=True):
        c1, c2, c3 = st.columns(3)
        description = c1.text_input("Descrição")
        category = c2.selectbox("Categoria", [""] + categories["name"].tolist())
        currency = c3.selectbox("Moeda", config.CURRENCIES)
        c4, c5, c6, c7 = st.columns(4)
        total = c4.number_input("Valor total", min_value=0.0, step=10.0, format="%.2f")
        n = c5.number_input("Parcelas", min_value=1, max_value=120, value=1, step=1)
        purchase_date = c6.date_input("Data da compra", value=ctx.today)
        first_due = c7.selectbox("Mês da 1ª parcela", month_options, index=2)
        submitted = st.form_submit_button("Projetar e salvar", type="primary")
    if submitted:
        if not description.strip() or total <= 0:
            flash("error", "Informe descrição e valor total maior que zero.")
        else:
            schedule = services.register_installment_purchase(
                ctx.conn, description, category or None, currency, float(total), int(n), purchase_date, first_due
            )
            flash(
                "success",
                f"Projetadas {len(schedule)} parcelas de {fmt_money(schedule['amount'].iloc[0], currency)} "
                f"de {schedule['due_month'].iloc[0]} até {schedule['due_month'].iloc[-1]}.",
            )
            st.rerun()

    purchases = database.list_installment_purchases(ctx.conn)
    if purchases.empty:
        st.info("Nenhuma compra parcelada cadastrada.")
        return

    st.subheader("Compras cadastradas")
    st.dataframe(
        purchases.rename(
            columns={
                "id": "ID", "description": "Descrição", "category": "Categoria", "currency": "Moeda",
                "total_amount": "Total", "n_installments": "Parcelas",
                "purchase_date": "Data da compra", "first_due_month": "1ª parcela",
            }
        ),
        hide_index=True,
        column_config={"Total": money_column("Total")},
    )

    schedule = database.list_schedule(ctx.conn)
    schedule["amount_display"] = ledger.convert_column(schedule, "amount", "currency", ctx.currency, ctx.rate)
    by_month = schedule.groupby("due_month")["amount_display"].sum().round(2)

    st.subheader(f"Passivo projetado por mês ({ctx.currency})")
    st.bar_chart(by_month)

    st.subheader("Cronograma detalhado")
    st.dataframe(
        schedule[["due_month", "description", "installment_no", "n_installments", "currency", "amount"]].rename(
            columns={
                "due_month": "Mês", "description": "Descrição", "installment_no": "Parcela",
                "n_installments": "De", "currency": "Moeda", "amount": "Valor",
            }
        ),
        hide_index=True,
        column_config={"Valor": money_column("Valor")},
    )

    with st.expander("Excluir compra"):
        purchase_id = st.selectbox(
            "Compra", purchases["id"].tolist(),
            format_func=lambda i: purchases.set_index("id").loc[i, "description"],
        )
        if st.button("Excluir compra e cronograma"):
            database.delete_installment_purchase(ctx.conn, int(purchase_id))
            flash("success", "Compra excluída.")
            st.rerun()
