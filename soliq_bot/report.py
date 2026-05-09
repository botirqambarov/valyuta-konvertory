"""Failed-checks report writer."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd


@dataclass
class FailedCheck:
    fm_number: str
    check_number: str
    rows_count: int
    error_type: str
    error_details: str
    worker: str
    timestamp: str


COLUMNS = [
    "ФМ рақами",
    "Чек рақами",
    "Қаторлар сони",
    "Хато тури",
    "Хато тафсилоти",
    "Воркер",
    "Вақт",
]


def write_report(failed: list[FailedCheck], directory: str | Path = ".") -> Path:
    """Write the failed_checks_YYYYMMDD.xlsx file. Returns the path written."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    fname = f"failed_checks_{datetime.now():%Y%m%d}.xlsx"
    path = directory / fname

    rows = [
        {
            COLUMNS[0]: f.fm_number,
            COLUMNS[1]: f.check_number,
            COLUMNS[2]: f.rows_count,
            COLUMNS[3]: f.error_type,
            COLUMNS[4]: f.error_details,
            COLUMNS[5]: f.worker,
            COLUMNS[6]: f.timestamp,
        }
        for f in failed
    ]
    df = pd.DataFrame(rows, columns=COLUMNS)
    df.to_excel(path, index=False)
    return path
