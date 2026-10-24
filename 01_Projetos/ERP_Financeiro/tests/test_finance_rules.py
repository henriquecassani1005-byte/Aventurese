import pandas as pd
import pytest

from erp import database, services
from erp.rules import budget, cashflow, ledger
from erp.rules.installments import add_months, project_schedule

RATE = 6.0  # BRL por EUR


def test_convert_both_directions():
    assert ledger.convert(600, "BRL", "EUR", RATE) == pytest.approx(100)
    assert ledger.convert(100, "EUR", "BRL", RATE) == pytest.approx(600)
    assert ledger.convert(50, "BRL", "BRL", RATE) == 50
    with pytest.raises(ValueError):
        ledger.convert(1, "USD", "BRL", RATE)
    with pytest.raises(ValueError):
        ledger.rate_factor("BRL", "EUR", 0)


def test_net_worth_consolidates_currencies():
    balances = pd.DataFrame({"currency": ["BRL", "EUR"], "balance": [6000.0, 1000.0]})
    assert ledger.net_worth(balances, "BRL", RATE) == pytest.approx(12000.0)
    assert ledger.net_worth(balances, "EUR", RATE) == pytest.approx(2000.0)


def test_fx_rate_panel_overrides_env_default(conn):
    from erp import config
    assert database.get_fx_rate(conn) == config.DEFAULT_BRL_PER_EUR
    database.set_fx_rate(conn, 5.5)
    assert database.get_fx_rate(conn) == 5.5


def test_add_months_crosses_year():
    assert add_months("2026-11", 3) == "2027-02"
    assert add_months("2026-12", 1) == "2027-01"


def test_schedule_sums_exactly_and_spreads_cents():
    sched = project_schedule(100.00, 3, "2026-11")
    assert sched["amount"].tolist() == [33.34, 33.33, 33.33]
    assert round(sched["amount"].sum(), 2) == 100.00
    assert sched["due_month"].tolist() == ["2026-11", "2026-12", "2027-01"]
    assert project_schedule(0.10, 3, "2026-11")["amount"].sum() == pytest.approx(0.10)


def test_schedule_rejects_bad_input():
    with pytest.raises(ValueError):
        project_schedule(100, 0, "2026-11")
    with pytest.raises(ValueError):
        project_schedule(-1, 2, "2026-11")


def _schedule(conn):
    return database.list_schedule(conn)


def test_free_cash_is_balance_minus_next_month_invoices(conn):
    from datetime import date
    services.register_installment_purchase(conn, "Notebook", "Kothon", "BRL", 3000, 3, date(2026, 10, 5), "2026-11")
    services.register_installment_purchase(conn, "Hotel", "Lazer", "EUR", 600, 2, date(2026, 10, 6), "2026-11")
    sched = _schedule(conn)

    s = cashflow.free_cash_summary(20000.0, sched, "2026-11", "BRL", RATE)
    assert s["invoice"] == pytest.approx(1000 + 300 * RATE)       # 1000 BRL + 300 EUR
    assert s["free_cash"] == pytest.approx(20000 - 2800)
    assert s["open_liability"] == pytest.approx(3000 + 600 * RATE)

    in_eur = cashflow.free_cash_summary(3000.0, sched, "2026-11", "EUR", RATE)
    assert in_eur["invoice"] == pytest.approx(1000 / RATE + 300, abs=0.01)   # saída arredondada a 2 casas

    timeline = cashflow.cashflow_timeline(20000.0, sched, "2026-11", 4, "BRL", RATE)
    assert timeline["invoices"].tolist() == [2800.0, 2800.0, 1000.0, 0.0]
    assert timeline["free_cash_after"].iloc[-1] == pytest.approx(20000 - 6600)


def test_deleting_purchase_cascades_schedule(conn):
    from datetime import date
    services.register_installment_purchase(conn, "TV", None, "BRL", 900, 3, date(2026, 10, 1), "2026-11")
    pid = int(database.list_installment_purchases(conn).iloc[0]["id"])
    database.delete_installment_purchase(conn, pid)
    assert _schedule(conn).empty


def test_budget_realized_vs_budgeted(conn):
    from datetime import date
    database.upsert_budget(conn, "Alimentação", 1000, "BRL")
    database.upsert_budget(conn, "Lazer", 100, "EUR")             # 600 BRL
    acc = database.add_account(conn, "BR", "BRL")
    tx = pd.DataFrame(
        {
            "account_id": acc,
            "date": ["2026-10-02", "2026-10-03", "2026-10-04", "2026-10-05", "2026-09-30", "2026-10-06"],
            "description": ["a", "b", "c", "d", "e", "f"],
            "amount": [-400.0, -50.0, -200.0, 5000.0, -999.0, 30.0],
            "currency": "BRL",
            "category": ["Alimentação", "Lazer", None, "Receita", "Alimentação", "Alimentação"],
            "dedup_hash": list("abcdef"),
            "source_file": "t",
        }
    )
    database.insert_transactions(conn, tx)
    services.register_installment_purchase(conn, "Jantar", "Lazer", "BRL", 300, 3, date(2026, 10, 1), "2026-10")

    res = budget.realized_vs_budget(
        database.list_budgets(conn), database.list_categories(conn),
        database.list_transactions(conn), database.list_schedule(conn),
        "2026-10", "BRL", RATE,
    ).set_index("category")

    # Alimentação: 400 gasto menos 30 de estorno; setembro fica fora
    assert res.loc["Alimentação", "realized"] == pytest.approx(370)
    assert res.loc["Alimentação", "pct_used"] == pytest.approx(37.0)
    # Lazer: 50 em conta + 100 de parcela, orçamento de 100 EUR = 600 BRL
    assert res.loc["Lazer", "installments"] == pytest.approx(100)
    assert res.loc["Lazer", "realized"] == pytest.approx(150)
    assert res.loc["Lazer", "pct_used"] == pytest.approx(25.0)
    # Saída sem categoria aparece; Receita (não é despesa) fica fora
    assert res.loc["Sem categoria", "realized"] == pytest.approx(200)
    assert "Receita" not in res.index
    assert res.loc["TOTAL", "realized"] == pytest.approx(720)
    assert res.loc["TOTAL", "budget"] == pytest.approx(1600)

    in_eur = budget.realized_vs_budget(
        database.list_budgets(conn), database.list_categories(conn),
        database.list_transactions(conn), database.list_schedule(conn),
        "2026-10", "EUR", RATE,
    ).set_index("category")
    assert in_eur.loc["Lazer", "pct_used"] == pytest.approx(25.0)   # percentual independe da moeda


def test_budget_empty_database(conn):
    res = budget.realized_vs_budget(
        database.list_budgets(conn), database.list_categories(conn),
        database.list_transactions(conn), database.list_schedule(conn),
        "2026-10", "BRL", RATE,
    )
    assert res.empty
