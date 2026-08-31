from __future__ import annotations

import csv
import io
from collections.abc import Sequence
from pathlib import Path

from output.rows import (
    csv_row_from_final_result,
    csv_row_from_mapping,
    csv_row_from_match_result,
)
from output.schema import CPQ_CSV_COLUMNS, CSV_COLUMNS, STATUSES_WITH_PART_NUMBER


def render_csv(rows: Sequence[dict[str, str]]) -> str:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(
        buffer,
        fieldnames=list(CSV_COLUMNS),
        extrasaction="ignore",
        quoting=csv.QUOTE_MINIMAL,
        lineterminator="\r\n",
    )
    writer.writeheader()
    for row in rows:
        writer.writerow({column: row.get(column, "") for column in CSV_COLUMNS})
    return buffer.getvalue()


def render_csv_bytes(rows: Sequence[dict[str, str]]) -> bytes:
    text = render_csv(rows)
    return text.encode("utf-8-sig")


def write_csv_file(path: str | Path, rows: Sequence[dict[str, str]]) -> None:
    Path(path).write_bytes(render_csv_bytes(rows))


def cpq_rows_from_results(results: Sequence[object]) -> list[dict[str, str]]:
    """Productcode + Qty + Requested Product, for matched rows -- ready to hand to CPQ."""
    rows: list[dict[str, str]] = []
    for row in rows_from_results(results):
        if row.get("Match Status", "").upper() not in STATUSES_WITH_PART_NUMBER:
            continue
        productcode = row.get("Matched Atkore Part Number", "")
        if not productcode:
            continue
        rows.append(
            {
                "Productcode": productcode,
                "Qty": row.get("Quantity", ""),
                "Requested Product": row.get("Requested Description", ""),
            }
        )
    return rows


def render_cpq_csv_bytes(results: Sequence[object]) -> bytes:
    rows = cpq_rows_from_results(results)
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(
        buffer,
        fieldnames=list(CPQ_CSV_COLUMNS),
        extrasaction="ignore",
        quoting=csv.QUOTE_MINIMAL,
        lineterminator="\r\n",
    )
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return buffer.getvalue().encode("utf-8-sig")


def rows_from_results(results: Sequence[object]) -> list[dict[str, str]]:
    from ai.models import FinalMatchResult
    from matching.models import MatchResult

    output: list[dict[str, str]] = []
    for item in results:
        if isinstance(item, FinalMatchResult):
            output.append(csv_row_from_final_result(item))
        elif isinstance(item, MatchResult):
            output.append(csv_row_from_match_result(item))
        elif isinstance(item, dict):
            output.append(csv_row_from_mapping(item))
        else:
            raise TypeError(f"Unsupported CSV result type: {type(item)!r}")
    return output
