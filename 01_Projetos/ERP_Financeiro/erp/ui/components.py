"""Utilitários compartilhados da interface."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date

import streamlit as st

SYMBOLS = {"BRL": "R$", "EUR": "€"}


@dataclass
class AppContext:
    conn: sqlite3.Connection
    currency: str     # moeda global de exibição
    rate: float       # BRL por 1 EUR
    today: date

    @property
    def current_month(self) -> str:
        return self.today.strftime("%Y-%m")


def fmt_money(value: float, currency: str) -> str:
    text = f"{abs(value):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    sign = "-" if value < 0 else ""
    return f"{sign}{SYMBOLS[currency]} {text}"


def flash(kind: str, message: str) -> None:
    """Mensagem que sobrevive ao st.rerun(). kind: success, error, warning ou info."""
    st.session_state.setdefault("_flash", []).append((kind, message))


def show_flash() -> None:
    for kind, message in st.session_state.pop("_flash", []):
        getattr(st, kind)(message)


def money_column(label: str) -> st.column_config.NumberColumn:
    return st.column_config.NumberColumn(label, format="%.2f")
