"""Upload de CSV, pré visualização e importação sem duplicidade."""
from __future__ import annotations

import streamlit as st

from erp import config, database, services
from erp.rules.parsers import ParserError, load_profiles
from erp.ui.components import AppContext, flash, money_column


def render(ctx: AppContext) -> None:
    accounts = database.list_accounts(ctx.conn)
    if accounts.empty:
        st.info("Cadastre uma conta na aba Cadastros antes de importar.")
        return
    try:
        profiles = load_profiles(config.PARSERS_PATH)
    except (ParserError, OSError) as exc:
        st.error(f"Não foi possível carregar os perfis de parser: {exc}")
        return

    col1, col2 = st.columns(2)
    account_id = col1.selectbox(
        "Conta de destino",
        accounts["id"].tolist(),
        format_func=lambda i: "{name} ({currency})".format(**accounts.set_index("id").loc[i]),
    )
    account = accounts.set_index("id").loc[account_id]
    names = list(profiles)
    default = next((i for i, n in enumerate(names) if profiles[n].currency == account["currency"]), 0)
    profile_name = col2.selectbox("Perfil de leitura (layout do banco)", names, index=default)
    profile = profiles[profile_name]

    uploaded = st.file_uploader("Extrato em CSV", type=["csv", "txt"])
    if uploaded is None:
        st.caption("Reimportar o mesmo arquivo, ou extratos com datas sobrepostas, não duplica lançamentos.")
        return

    raw = uploaded.getvalue()
    try:
        preview = services.preview_csv(ctx.conn, raw, profile, int(account_id), uploaded.name)
    except (ParserError, ValueError) as exc:
        st.error(str(exc))
        return

    m1, m2, m3 = st.columns(3)
    m1.metric("Novas", preview.new)
    m2.metric("Já existentes (ignoradas)", preview.duplicates)
    m3.metric("Linhas rejeitadas", preview.rejected, help="Data ou valor ilegível, ou cabeçalhos repetidos.")

    shown = preview.rows[["status", "date", "description", "amount", "currency", "category"]]
    st.dataframe(shown.head(100), hide_index=True, column_config={"amount": money_column("amount")})

    if st.button("Importar", type="primary", disabled=preview.new == 0):
        report = services.import_csv(ctx.conn, raw, profile, int(account_id), uploaded.name)
        flash("success", f"Importação concluída: {report.inserted} novos, {report.duplicates} duplicados ignorados.")
        st.rerun()
