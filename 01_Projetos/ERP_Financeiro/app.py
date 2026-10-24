"""ERP Financeiro local. Execução: streamlit run app.py"""
import streamlit as st

from erp import database
from erp.ui import budget, components, dashboard, ingestion, installments, setup, sidebar, transactions

st.set_page_config(page_title="ERP Financeiro", layout="wide")


def main() -> None:
    conn = database.connect()
    try:
        database.init_db(conn)
        ctx = sidebar.render(conn)
        st.title("ERP Financeiro")
        components.show_flash()

        tabs = st.tabs(["Dashboard", "Importar CSV", "Lançamentos", "Parcelamentos", "Orçamento", "Cadastros"])
        for tab, page in zip(tabs, [dashboard, ingestion, transactions, installments, budget, setup]):
            with tab:
                page.render(ctx)
    finally:
        conn.close()


main()
