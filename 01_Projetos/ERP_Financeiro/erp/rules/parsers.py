"""Parsers configuráveis de extratos CSV.

Cada banco é um perfil (config/parsers.json). Trocar de layout é editar JSON, não código.
Saída padronizada: date (YYYY-MM-DD), description, amount (com sinal), ext_id (opcional).
"""
from __future__ import annotations

import io
import json
from dataclasses import dataclass, fields
from pathlib import Path

import pandas as pd

from erp.config import CURRENCIES


class ParserError(ValueError):
    """Erro de configuração do perfil ou de leitura do arquivo."""


@dataclass(frozen=True)
class ParserProfile:
    name: str
    currency: str
    date_col: str
    description_col: str
    amount_col: str | None = None      # coluna única com sinal
    debit_col: str | None = None       # alternativa: colunas separadas de débito e crédito
    credit_col: str | None = None
    id_col: str | None = None          # ID da transação, se o banco fornecer (melhor chave de dedup)
    delimiter: str = ","
    encoding: str = "utf-8-sig"
    skiprows: int = 0
    decimal: str = "."
    thousands: str | None = None
    date_format: str = "%Y-%m-%d"
    invert_sign: bool = False          # use quando compras aparecem positivas (extratos de cartão)

    def __post_init__(self) -> None:
        if self.currency not in CURRENCIES:
            raise ParserError(f"Perfil '{self.name}': moeda deve ser uma de {', '.join(CURRENCIES)}.")
        if not self.amount_col and not (self.debit_col or self.credit_col):
            raise ParserError(f"Perfil '{self.name}': informe amount_col ou debit_col/credit_col.")

    @classmethod
    def from_dict(cls, name: str, cfg: dict) -> "ParserProfile":
        allowed = {f.name for f in fields(cls)} - {"name"}
        unknown = set(cfg) - allowed
        if unknown:
            raise ParserError(f"Perfil '{name}': chaves desconhecidas {sorted(unknown)}. Válidas: {sorted(allowed)}.")
        missing = {"currency", "date_col", "description_col"} - set(cfg)
        if missing:
            raise ParserError(f"Perfil '{name}': faltam as chaves {sorted(missing)}.")
        return cls(name=name, **cfg)


@dataclass
class ParseResult:
    df: pd.DataFrame
    rejected: int


# ---------------------------------------------------------------- perfis (JSON)

def profiles_from_json(text: str) -> dict[str, ParserProfile]:
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ParserError(f"JSON inválido: {exc}") from exc
    if not isinstance(raw, dict) or not raw:
        raise ParserError("O JSON deve ser um objeto com um perfil por chave.")
    return {name: ParserProfile.from_dict(name, cfg) for name, cfg in raw.items()}


def load_profiles(path: Path) -> dict[str, ParserProfile]:
    return profiles_from_json(Path(path).read_text(encoding="utf-8"))


# ---------------------------------------------------------------- leitura

_CHAR_FIXES = {"−": "-", " ": " "}


def to_number(series: pd.Series, decimal: str = ".", thousands: str | None = None) -> pd.Series:
    """Converte texto monetário em float. Aceita símbolos, (1.234,56), 1.234,56- e sinal unicode."""
    s = series.fillna("").astype(str).str.strip()
    for old, new in _CHAR_FIXES.items():
        s = s.str.replace(old, new, regex=False)
    negative = (s.str.startswith("(") & s.str.endswith(")")) | s.str.endswith("-")
    s = s.str.replace(r"[^\d,.+\-]", "", regex=True).str.rstrip("-")
    if thousands:
        s = s.str.replace(thousands, "", regex=False)
    if decimal != ".":
        s = s.str.replace(decimal, ".", regex=False)
    value = pd.to_numeric(s, errors="coerce")
    return value.where(~negative, -value.abs())


def parse_csv(raw: bytes, profile: ParserProfile) -> ParseResult:
    try:
        df = pd.read_csv(
            io.BytesIO(raw),
            sep=profile.delimiter,
            encoding=profile.encoding,
            skiprows=profile.skiprows,
            dtype=str,
            skipinitialspace=True,
        )
    except (UnicodeDecodeError, pd.errors.ParserError, pd.errors.EmptyDataError) as exc:
        raise ParserError(f"Falha ao ler o CSV com o perfil '{profile.name}': {exc}") from exc

    df.columns = [str(c).strip() for c in df.columns]
    df = df.dropna(how="all")
    lookup = {c.casefold(): c for c in df.columns}

    def col(name: str) -> pd.Series:
        key = name.strip().casefold()
        if key not in lookup:
            raise ParserError(
                f"Coluna '{name}' não encontrada no arquivo. Colunas disponíveis: {', '.join(df.columns)}. "
                f"Ajuste o perfil '{profile.name}'."
            )
        return df[lookup[key]]

    dates = pd.to_datetime(col(profile.date_col).str.strip(), format=profile.date_format, errors="coerce")

    if profile.amount_col:
        amount = to_number(col(profile.amount_col), profile.decimal, profile.thousands)
    else:
        nan = pd.Series(float("nan"), index=df.index)
        debit = to_number(col(profile.debit_col), profile.decimal, profile.thousands) if profile.debit_col else nan
        credit = to_number(col(profile.credit_col), profile.decimal, profile.thousands) if profile.credit_col else nan
        amount = (credit.abs().fillna(0) - debit.abs().fillna(0)).where(debit.notna() | credit.notna())
    if profile.invert_sign:
        amount = -amount

    description = (
        col(profile.description_col).fillna("").str.replace(r"\s+", " ", regex=True).str.strip()
    )
    description = description.where(description != "", "(sem descrição)")

    ext_id = col(profile.id_col).str.strip() if profile.id_col else pd.Series(None, index=df.index, dtype=object)

    out = pd.DataFrame(
        {
            "date": dates.dt.strftime("%Y-%m-%d"),
            "description": description,
            "amount": amount.round(2),
            "ext_id": ext_id,
        }
    )
    valid = dates.notna() & amount.notna()
    return ParseResult(df=out[valid].reset_index(drop=True), rejected=int((~valid).sum()))
