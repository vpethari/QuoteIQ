from __future__ import annotations

import csv
import io
from collections.abc import Sequence
from pathlib import Path

from output.result_view import ResultView, normalize_result
from output.rows import csv_row_from_result
from output.schema import (
    CPQ_CSV_COLUMNS,
    CSV_COLUMNS,
    FULL_RESULTS_APPENDED_COLUMNS,
    STATUSES_WITH_PART_NUMBER,
)


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
    """Part Number + Quantity + Description, for matched rows -- ready to hand to CPQ.

    Description is the customer's own requested text, not the matched
    Atkore product's description -- CPQ needs to see what was actually
    asked for.
    """
    rows: list[dict[str, str]] = []
    for row in rows_from_results(results):
        if row.get("Match Status", "").upper() not in STATUSES_WITH_PART_NUMBER:
            continue
        part_number = row.get("Matched Atkore Part Number", "")
        if not part_number:
            continue
        rows.append(
            {
                "Part Number": part_number,
                "Quantity": row.get("Quantity", ""),
                "Description": row.get("Requested Description", ""),
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


TOP_ITEMS_LIMIT = 5
TOP_ITEMS_SEPARATOR = "||"


def _top_orderable_items(candidates: Sequence[dict], limit: int = TOP_ITEMS_LIMIT) -> list[str]:
    """Orderable part numbers for the top `limit` review candidates, in their
    existing (already best-first) order, skipping any without one."""
    items: list[str] = []
    for candidate in candidates[:limit]:
        value = candidate.get("orderable_part_number")
        if value:
            items.append(str(value))
    return items


def _full_results_row(view: ResultView) -> dict[str, str]:
    raw_row = view.raw_row
    if not raw_row:
        raw_row = {
            "Requested Description": view.requested_description or "",
            "Quantity": "" if view.quantity is None else str(view.quantity),
        }
    row = {str(key): ("" if value is None else str(value)) for key, value in raw_row.items()}
    row["Matched Part Number"] = view.matched_part_number or ""
    row["Orderable Part Number"] = view.matched_orderable_part_number or ""
    row["Status"] = view.match_status or ""
    row["Top Items"] = TOP_ITEMS_SEPARATOR.join(_top_orderable_items(view.candidates))
    return row


def render_full_results_csv_bytes(results: Sequence[object]) -> bytes:
    """"Full Results" -- the input file's own columns, verbatim and in their
    original order, with Matched Part Number / Orderable Part Number (for
    matched rows only), Status, and Top Items (the top 5 review candidates'
    Orderablepartnumbers, "||"-joined) appended. Falls back to Requested
    Description/Quantity when a line has no original columns to mirror
    (a PDF quote, or a headerless data dump)."""
    views = [normalize_result(item) for item in results]
    rows = [_full_results_row(view) for view in views]
    columns: list[str] = []
    seen: set[str] = set()
    for view in views:
        source_columns = view.raw_row or {"Requested Description": None, "Quantity": None}
        for key in source_columns:
            if key not in seen:
                seen.add(key)
                columns.append(key)
    fieldnames = [*columns, *FULL_RESULTS_APPENDED_COLUMNS]
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(
        buffer,
        fieldnames=fieldnames,
        extrasaction="ignore",
        quoting=csv.QUOTE_MINIMAL,
        lineterminator="\r\n",
    )
    writer.writeheader()
    for row in rows:
        writer.writerow({column: row.get(column, "") for column in fieldnames})
    return buffer.getvalue().encode("utf-8-sig")


def rows_from_results(results: Sequence[object]) -> list[dict[str, str]]:
    return [csv_row_from_result(item) for item in results]
