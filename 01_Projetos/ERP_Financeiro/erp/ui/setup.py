"""Cadastros: contas, categorias, regras de classificação e perfis de parser."""
from __future__ import annotations

import sqlite3

import streamlit as st

from erp import config, database
from erp.rules.parsers import ParserError, profiles_from_json
from erp.ui.components import AppContext, flash, fmt_money, money_column


def render(ctx: AppContext) -> None:
    _accounts(ctx)
    _categories_and_rules(ctx)
    _parsers()


def _accounts(ctx: AppContext) -> None:
    st.subheader("Contas")
    with st.form("new_account", clear_on_submit=True):
        c1, c2, c3 = st.columns(3)
        name = c1.text_input("Nome da conta")
        currency = c2.selectbox("Moeda", config.CURRENCIES)
        opening = c3.number_input("Saldo inicial (antes do 1º lançamento)", step=100.0, format="%.2f")
        if st.form_submit_button("Criar conta", type="primary"):
            try:
                database.add_account(ctx.conn, name, currency, float(opening))
                flash("success", f"Conta {name} criada.")
                st.rerun()
            except (sqlite3.IntegrityError, ValueError):
                st.error("Nome vazio ou já existente.")

    balances = database.account_balances(ctx.conn)
    if balances.empty:
        return
    st.dataframe(
        balances.rename(
            columns={
                "id": "ID", "name": "Conta", "currency": "Moeda", "opening_balance": "Saldo inicial",
                "movement": "Movimentação importada", "balance": "Saldo atual",
            }
        ),
        hide_index=True,
        column_config={c: money_column(c) for c in ["Saldo inicial", "Movimentação importada", "Saldo atual"]},
    )
    with st.expander("Calibrar saldo pelo extrato do banco"):
        st.caption("Informe o saldo real que o banco mostra hoje. O sistema ajusta o saldo inicial para fechar com ele.")
        by_id = balances.set_index("id")
        account_id = st.selectbox("Conta", by_id.index.tolist(), format_func=lambda i: by_id.loc[i, "name"], key="cal_acc")
        informed = st.number_input("Saldo atual no banco", step=100.0, format="%.2f", key="cal_value")
        if st.button("Calibrar"):
            opening = database.calibrate_opening_balance(ctx.conn, int(account_id), float(informed))
            flash("success", f"Saldo inicial ajustado para {fmt_money(opening, by_id.loc[account_id, 'currency'])}.")
            st.rerun()


def _categories_and_rules(ctx: AppContext) -> None:
    categories = database.list_categories(ctx.conn)
    st.subheader("Categorias")
    with st.form("new_category", clear_on_submit=True):
        c1, c2 = st.columns([3, 1])
        name = c1.text_input("Nova categoria")
        is_expense = c2.checkbox("É despesa", value=True, help="Despesas entram no Realizado vs. Orçado.")
        if st.form_submit_button("Adicionar categoria"):
            try:
                database.add_category(ctx.conn, name, is_expense)
                flash("success", f"Categoria {name} criada.")
                st.rerun()
            except (sqlite3.IntegrityError, ValueError):
                st.error("Nome vazio ou já existente.")
    st.dataframe(
        categories.assign(is_expense=categories["is_expense"].map({1: "Sim", 0: "Não"})).rename(
            columns={"name": "Categoria", "is_expense": "Despesa"}
        ),
        hide_index=True,
    )

    st.subheader("Regras de classificação")
    st.caption("Se a descrição contém a palavra chave, a transação recebe a categoria. Vale na importação e no botão de reaplicar.")
    with st.form("new_rule", clear_on_submit=True):
        c1, c2 = st.columns(2)
        keyword = c1.text_input("Palavra chave")
        category = c2.selectbox("Categoria", categories["name"].tolist())
        if st.form_submit_button("Salvar regra"):
            if keyword.strip():
                database.add_rule(ctx.conn, keyword, category)
                flash("success", f"Regra {keyword.strip().upper()} para {category} salva.")
                st.rerun()
            else:
                st.error("Informe a palavra chave.")
    rules = database.list_rules(ctx.conn)
    if not rules.empty:
        st.dataframe(rules.rename(columns={"id": "ID", "keyword": "Palavra chave", "category": "Categoria"}), hide_index=True)
        with st.expander("Excluir regra"):
            rule_id = st.selectbox(
                "Regra", rules["id"].tolist(), format_func=lambda i: rules.set_index("id").loc[i, "keyword"]
            )
            if st.button("Excluir regra"):
                database.delete_rule(ctx.conn, int(rule_id))
                flash("success", "Regra excluída.")
                st.rerun()


def _parsers() -> None:
    st.subheader("Perfis de parser (layout dos CSVs)")
    st.caption(
        "Um perfil por banco: delimitador, formato de data, separador decimal e nomes das colunas. "
        f"Arquivo: {config.PARSERS_PATH.name}"
    )
    current = config.PARSERS_PATH.read_text(encoding="utf-8") if config.PARSERS_PATH.exists() else "{}"
    text = st.text_area("JSON dos perfis", value=current, height=360)
    if st.button("Validar e salvar perfis"):
        try:
            profiles = profiles_from_json(text)
        except ParserError as exc:
            st.error(str(exc))
            return
        config.PARSERS_PATH.write_text(text, encoding="utf-8")
        flash("success", f"{len(profiles)} perfis salvos.")
        st.rerun()
