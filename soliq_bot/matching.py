"""Row matching: pair Excel rows with site rows."""
from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher

from .excel_io import ProductRow


@dataclass
class SiteRow:
    index: int  # 0-based row index in the edit modal
    name: str
    sum_value: float  # qty × price displayed on site


def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()


def match_rows(
    site_rows: list[SiteRow],
    excel_rows: list[ProductRow],
    tolerance: float = 0.5,
) -> dict[int, ProductRow]:
    """Return mapping {site_row_index: ProductRow}.

    Strategy:
      1. Primary key = sum equality (qty × price). For each site row, find all
         Excel rows whose qty*price ≈ site sum (within tolerance).
      2. If multiple candidates, pick the one with highest name similarity.
      3. Assign greedily, removing matched Excel rows so they aren't reused.
    """
    remaining = list(excel_rows)
    result: dict[int, ProductRow] = {}

    for site in site_rows:
        candidates: list[tuple[float, ProductRow]] = []
        for ex in remaining:
            ex_sum = ex.qty * ex.price
            if abs(ex_sum - site.sum_value) <= tolerance:
                candidates.append((_similarity(ex.name, site.name), ex))

        if not candidates:
            # Fall-back: pick by closest sum
            if remaining:
                best = min(remaining, key=lambda r: abs(r.qty * r.price - site.sum_value))
                result[site.index] = best
                remaining.remove(best)
            continue

        candidates.sort(key=lambda t: t[0], reverse=True)
        best_row = candidates[0][1]
        result[site.index] = best_row
        remaining.remove(best_row)

    return result
