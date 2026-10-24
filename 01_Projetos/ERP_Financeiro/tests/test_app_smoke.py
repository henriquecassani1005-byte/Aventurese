"""Roda o app inteiro em modo headless com banco temporário e os CSVs de exemplo."""
from datetime import date
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from erp import config, database, services
from erp.rules.parsers import load_profiles

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def seeded_db(tmp_path, monkeypatch):
    db_path = tmp_path / "erp.db"
    monkeypatch.setattr(config, "DB_PATH", db_path)
    conn = database.connect(db_path)
    database.init_db(conn)
    profiles = load_profiles(config.PARSERS_PATH)

    br = database.add_account(conn, "Banco BR", "BRL")
    eu = database.add_account(conn, "Banco EU", "EUR")
    for rule, cat in [("ALUGUEL", "Moradia"), ("SUPERMERCADO", "Alimentação"), ("KOTHON ASSINATURA", "Kothon"),
                      ("PIX RECEBIDO", "Receita"), ("RENT", "Moradia")]:
        database.add_rule(conn, rule, cat)
    services.import_csv(conn, (ROOT / "samples/extrato_br_exemplo.csv").read_bytes(), profiles["BR_Generico"], br, "br.csv")
    services.import_csv(conn, (ROOT / "samples/extrato_eu_exemplo.csv").read_bytes(), profiles["EU_Generico"], eu, "eu.csv")
    database.upsert_budget(conn, "Moradia", 4000, "BRL")
    database.upsert_budget(conn, "Alimentação", 1500, "BRL")
    database.upsert_budget(conn, "Lazer", 200, "EUR")
    services.register_installment_purchase(conn, "Notebook", "Kothon", "BRL", 6000, 6, date.today(), "2099-01")
    conn.close()
    return db_path


def test_empty_database_renders(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "empty.db")
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30).run()
    assert not at.exception


def test_populated_app_renders_and_currency_switch(seeded_db):
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30).run()
    assert not at.exception
    metrics = {m.label: m.value for m in at.metric}
    assert metrics["Patrimônio em contas"].startswith("R$")

    at.sidebar.radio[0].set_value("EUR").run()
    assert not at.exception
    assert {m.label: m.value for m in at.metric}["Patrimônio em contas"].startswith("€")
