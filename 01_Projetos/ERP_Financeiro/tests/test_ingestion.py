import pandas as pd
import pytest

from erp import database, services
from erp.rules.parsers import ParserError, ParserProfile, parse_csv, profiles_from_json, to_number

BR_CSV = (
    "Data;Descrição;Valor\n"
    "01/10/2026;PIX RECEBIDO;15.000,00\n"
    "03/10/2026;SUPERMERCADO EXTRA;-412,35\n"
    "05/10/2026;PADARIA CENTRAL;-18,50\n"
    "05/10/2026;PADARIA CENTRAL;-18,50\n"
    "xx/10/2026;LINHA INVALIDA;-1,00\n"
).encode("utf-8")


def test_to_number_formats():
    s = pd.Series(["R$ 1.234,56", "(100,00)", "50,00-", "−7,10", "", "abc"])
    out = to_number(s, decimal=",", thousands=".")
    assert out.iloc[:4].tolist() == [1234.56, -100.0, -50.0, -7.1]
    assert out.iloc[4:].isna().all()


def test_parse_br_layout(br_profile):
    res = parse_csv(BR_CSV, br_profile)
    assert len(res.df) == 4
    assert res.rejected == 1
    assert res.df["date"].tolist()[0] == "2026-10-01"
    assert res.df["amount"].tolist() == [15000.0, -412.35, -18.5, -18.5]


def test_parse_eu_layout(eu_profile):
    raw = b"Date,Description,Amount\n2026-10-01,SALARY,2500.00\n2026-10-03,RENT,-900.00\n"
    res = parse_csv(raw, eu_profile)
    assert res.df["amount"].tolist() == [2500.0, -900.0]


def test_debit_credit_columns():
    profile = ParserProfile(
        name="DC", currency="BRL", delimiter=";", decimal=",", date_format="%d/%m/%Y",
        date_col="Data", description_col="Histórico", debit_col="Débito", credit_col="Crédito",
    )
    raw = "Data;Histórico;Débito;Crédito\n01/10/2026;COMPRA;50,00;\n02/10/2026;SALARIO;;1000,00\n".encode()
    assert parse_csv(raw, profile).df["amount"].tolist() == [-50.0, 1000.0]


def test_invert_sign(eu_profile):
    profile = ParserProfile(**{**eu_profile.__dict__, "invert_sign": True})
    raw = b"Date,Description,Amount\n2026-10-01,SHOP,25.00\n"
    assert parse_csv(raw, profile).df["amount"].tolist() == [-25.0]


def test_missing_column_has_helpful_error(eu_profile):
    with pytest.raises(ParserError, match="Colunas disponíveis"):
        parse_csv(b"Foo,Bar\n1,2\n", eu_profile)


def test_profile_validation():
    with pytest.raises(ParserError, match="chaves desconhecidas"):
        profiles_from_json('{"X": {"currency": "BRL", "date_col": "a", "description_col": "b", "amount": "c"}}')
    with pytest.raises(ParserError, match="amount_col"):
        profiles_from_json('{"X": {"currency": "BRL", "date_col": "a", "description_col": "b"}}')


def test_import_is_idempotent_and_keeps_legit_repeats(conn, br_profile):
    acc = database.add_account(conn, "Banco BR", "BRL")
    first = services.import_csv(conn, BR_CSV, br_profile, acc, "a.csv")
    assert (first.inserted, first.duplicates, first.rejected) == (4, 0, 1)

    again = services.import_csv(conn, BR_CSV, br_profile, acc, "a.csv")
    assert (again.inserted, again.duplicates) == (0, 4)
    assert len(database.list_transactions(conn)) == 4   # duas padarias iguais continuam sendo duas


def test_overlapping_weekly_extracts_do_not_duplicate(conn, br_profile):
    acc = database.add_account(conn, "Banco BR", "BRL")
    week1 = b"Data;Descri\xc3\xa7\xc3\xa3o;Valor\n01/10/2026;A;-10,00\n02/10/2026;B;-20,00\n"
    week2 = b"Data;Descri\xc3\xa7\xc3\xa3o;Valor\n02/10/2026;B;-20,00\n03/10/2026;C;-30,00\n"
    services.import_csv(conn, week1, br_profile, acc, "w1.csv")
    report = services.import_csv(conn, week2, br_profile, acc, "w2.csv")
    assert (report.inserted, report.duplicates) == (1, 1)


def test_preview_matches_import(conn, br_profile):
    acc = database.add_account(conn, "Banco BR", "BRL")
    services.import_csv(conn, BR_CSV, br_profile, acc, "a.csv")
    preview = services.preview_csv(conn, BR_CSV, br_profile, acc, "a.csv")
    assert (preview.new, preview.duplicates) == (0, 4)
    assert set(preview.rows["status"]) == {"Já existe"}

    extra = BR_CSV + "06/10/2026;NOVA;-5,00\n".encode()
    preview = services.preview_csv(conn, extra, br_profile, acc, "b.csv")
    assert (preview.new, preview.duplicates) == (1, 4)
    assert preview.rows["status"].iloc[0] == "Nova"   # novas primeiro


def test_currency_mismatch_is_blocked(conn, eu_profile):
    acc = database.add_account(conn, "Banco BR", "BRL")
    with pytest.raises(ValueError, match="perfil"):
        services.import_csv(conn, b"Date,Description,Amount\n", eu_profile, acc, "x.csv")


def test_rules_categorize_on_import_and_reapply(conn, br_profile):
    database.add_rule(conn, "supermercado", "Alimentação")
    acc = database.add_account(conn, "Banco BR", "BRL")
    services.import_csv(conn, BR_CSV, br_profile, acc, "a.csv")
    tx = database.list_transactions(conn)
    assert tx.loc[tx["description"] == "SUPERMERCADO EXTRA", "category"].iloc[0] == "Alimentação"
    assert tx["category"].isna().sum() == 3

    database.add_rule(conn, "PADARIA", "Alimentação")
    assert services.reapply_rules(conn) == 2


def test_balance_and_calibration(conn, br_profile):
    acc = database.add_account(conn, "Banco BR", "BRL")
    services.import_csv(conn, BR_CSV, br_profile, acc, "a.csv")
    assert database.account_balances(conn).iloc[0]["balance"] == pytest.approx(14550.65)
    opening = database.calibrate_opening_balance(conn, acc, 20000.00)
    assert opening == pytest.approx(5449.35)
    assert database.account_balances(conn).iloc[0]["balance"] == pytest.approx(20000.00)
