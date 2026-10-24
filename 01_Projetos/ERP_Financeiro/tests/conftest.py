import pytest

from erp import database
from erp.rules.parsers import ParserProfile


@pytest.fixture
def conn():
    c = database.connect(":memory:")
    database.init_db(c)
    yield c
    c.close()


@pytest.fixture
def br_profile():
    return ParserProfile(
        name="BR", currency="BRL", delimiter=";", decimal=",", thousands=".",
        date_format="%d/%m/%Y", date_col="Data", description_col="Descrição", amount_col="Valor",
    )


@pytest.fixture
def eu_profile():
    return ParserProfile(
        name="EU", currency="EUR", date_col="Date", description_col="Description", amount_col="Amount",
    )
