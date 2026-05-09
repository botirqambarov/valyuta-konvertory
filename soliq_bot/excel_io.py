"""Excel reading/grouping utilities.

Excel format (Cyrillic headers):
    ФМ рақами | Чек рақами | Махсулот номи | Миқдори | Нархи | Махсулот коди

Each (FM number, Check number) pair groups several product rows belonging
to the same receipt/check.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

import pandas as pd

# Canonical Uzbek column names
COL_FM = "ФМ рақами"
COL_CHECK = "Чек рақами"
COL_NAME = "Махсулот номи"
COL_QTY = "Миқдори"
COL_PRICE = "Нархи"
COL_CODE = "Махсулот коди"

# Possible header aliases (case-insensitive, accent-tolerant)
HEADER_ALIASES: dict[str, list[str]] = {
    COL_FM: ["фм рақами", "фм раками", "фм", "fm", "касса"],
    COL_CHECK: ["чек рақами", "чек раками", "чек", "check"],
    COL_NAME: ["махсулот номи", "номи", "name", "товар"],
    COL_QTY: ["миқдори", "микдори", "сони", "qty", "soni"],
    COL_PRICE: ["нархи", "сумма", "narx", "price"],
    COL_CODE: ["махсулот коди", "мхик", "mxik", "код"],
}


@dataclass
class ProductRow:
    name: str
    qty: float
    price: float
    code: str


@dataclass
class CheckGroup:
    fm_number: str
    check_number: str
    rows: list[ProductRow] = field(default_factory=list)

    @property
    def total_sum(self) -> float:
        return sum(r.qty * r.price for r in self.rows)

    def key(self) -> tuple[str, str]:
        return (str(self.fm_number).strip(), str(self.check_number).strip())


def _normalize_header(h: str) -> str:
    return str(h).strip().lower().replace("ё", "е").replace("ў", "у").replace("қ", "к").replace("ҳ", "х").replace("ғ", "г")


def _resolve_columns(df_columns: Iterable[str]) -> dict[str, str]:
    """Map canonical name → actual column name in the DataFrame."""
    norm_map = {_normalize_header(c): c for c in df_columns}
    resolved: dict[str, str] = {}
    for canonical, aliases in HEADER_ALIASES.items():
        for alias in aliases:
            if alias in norm_map:
                resolved[canonical] = norm_map[alias]
                break
        if canonical not in resolved:
            raise ValueError(
                f"Excel'да '{canonical}' устуни топилмади. "
                f"Топилган устунлар: {list(df_columns)}"
            )
    return resolved


def load_excel(path: str | Path) -> list[CheckGroup]:
    """Load and group an Excel file into CheckGroup objects."""
    df = pd.read_excel(path, dtype=str).fillna("")
    cols = _resolve_columns(df.columns)

    groups: dict[tuple[str, str], CheckGroup] = {}
    for _, row in df.iterrows():
        fm = str(row[cols[COL_FM]]).strip()
        chk = str(row[cols[COL_CHECK]]).strip()
        if not fm or not chk:
            continue
        key = (fm, chk)
        group = groups.setdefault(key, CheckGroup(fm_number=fm, check_number=chk))
        try:
            qty = float(str(row[cols[COL_QTY]]).replace(",", ".") or 0)
        except ValueError:
            qty = 0.0
        try:
            price = float(str(row[cols[COL_PRICE]]).replace(",", ".") or 0)
        except ValueError:
            price = 0.0
        group.rows.append(
            ProductRow(
                name=str(row[cols[COL_NAME]]).strip(),
                qty=qty,
                price=price,
                code=str(row[cols[COL_CODE]]).strip(),
            )
        )
    return list(groups.values())
