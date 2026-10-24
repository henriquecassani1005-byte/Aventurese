"""Barra lateral: seletor global de moeda e taxa de câmbio estática."""
from __future__ import annotations

import sqlite3
from datetime import date

import streamlit as st

from erp import config, database
from erp.ui.components import AppContext, flash


def render(conn: sqlite3.Connection) -> AppContext:
    st.sidebar.header("Moeda global")
    currency = st.sidebar.radio(
        "Exibir valores em",
        config.CURRENCIES,
        index=config.CURRENCIES.index(config.DEFAULT_CURRENCY),
        horizontal=True,
    )
    rate = st.sidebar.number_input(
        "Taxa estática: BRL por 1 EUR",
        min_value=0.0001,
        value=float(database.get_fx_rate(conn)),
        step=0.01,
        format="%.4f",
        help="Vale para esta sessão. Use o botão abaixo para gravar como padrão.",
    )
    if st.sidebar.button("Salvar taxa como padrão"):
        database.set_fx_rate(conn, rate)
        flash("success", f"Taxa gravada: 1 EUR = {rate:.4f} BRL.")
        st.rerun()
    st.sidebar.caption("A taxa é fixa, não é cotação em tempo real. Confirme o valor antes de decidir.")
    return AppContext(conn=conn, currency=currency, rate=rate, today=date.today())
