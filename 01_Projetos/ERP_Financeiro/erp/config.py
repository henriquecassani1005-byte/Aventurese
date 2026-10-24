"""Configuração central: caminhos, moedas suportadas e taxa de câmbio padrão (.env)."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

CURRENCIES = ("BRL", "EUR")

DB_PATH = Path(os.getenv("ERP_DB_PATH") or BASE_DIR / "data" / "erp.db")
PARSERS_PATH = Path(os.getenv("ERP_PARSERS_PATH") or BASE_DIR / "config" / "parsers.json")


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        return float(raw.replace(",", "."))
    except ValueError:
        raise ValueError(f"{name} inválida no .env: {raw!r}") from None


# Quantos BRL valem 1 EUR. O painel pode sobrescrever e persiste no SQLite.
DEFAULT_BRL_PER_EUR = _env_float("BRL_PER_EUR", 6.0)

DEFAULT_CURRENCY = os.getenv("DEFAULT_CURRENCY", "BRL").upper()
if DEFAULT_CURRENCY not in CURRENCIES:
    DEFAULT_CURRENCY = "BRL"
