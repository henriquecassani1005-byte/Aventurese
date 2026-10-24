"""Categorização por palavra chave: a regra mais específica (maior) vence."""
from __future__ import annotations

import pandas as pd


def apply_rules(descriptions: pd.Series, rules: pd.DataFrame) -> pd.Series:
    """Retorna a categoria por linha (None quando nenhuma regra casa). rules: keyword, category."""
    result = pd.Series([None] * len(descriptions), index=descriptions.index, dtype=object)
    if rules.empty or descriptions.empty:
        return result
    text = descriptions.fillna("").str.upper()
    ordered = rules.assign(_len=rules["keyword"].str.len()).sort_values("_len", ascending=False)
    for keyword, category in zip(ordered["keyword"], ordered["category"]):
        hit = result.isna() & text.str.contains(keyword.upper(), regex=False)
        result.loc[hit] = category
    return result
