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
    """Part Number + Quantity, for matched rows -- ready to hand to CPQ.

    Part Number is the *orderable* part number, not the "name" identifier
    matching is keyed on -- productmaster.orderablepartnumber sometimes
    differs from name (confirmed live: ~11% of rows), and it's the number
    that's actually meant to be shown/ordered by. Falls back to the
    matched name-based part number when a row has no separate orderable
    code recorded.
    """
    rows: list[dict[str, str]] = []
    for item in results:
        view = normalize_result(item)
        if view.match_status.upper() not in STATUSES_WITH_PART_NUMBER:
            continue
        part_number = view.matched_orderable_part_number or view.matched_part_number or ""
        if not part_number:
            continue
        rows.append(
            {
                "Part Number": part_number,
                "Quantity": "" if view.quantity is None else str(view.quantity),
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


def _top_product_columns(candidates: Sequence[dict], limit: int = TOP_ITEMS_LIMIT) -> dict[str, str]:
    """"Top Product 1".."Top Product {limit}" -- one column per review
    candidate, in their existing (already best-first) rank order, each
    candidate in its own fixed position rather than concatenated into one
    column. Falls back to a candidate's own official_part_number when it
    has no separate orderable code recorded, same reasoning as the CPQ CSV
    export: the orderable number is what's actually meant to be shown, but
    a slot shouldn't go blank just because that field happens to be unset
    -- only genuinely having fewer than `limit` candidates leaves a slot
    blank."""
    columns: dict[str, str] = {}
    for index in range(limit):
        candidate = candidates[index] if index < len(candidates) else None
        value = ""
        if candidate is not None:
            value = candidate.get("orderable_part_number") or candidate.get("official_part_number") or ""
        columns[f"Top Product {index + 1}"] = str(value) if value else ""
    return columns


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
    row.update(_top_product_columns(view.candidates))
    return row


def render_full_results_csv_bytes(results: Sequence[object]) -> bytes:
    """"Full Results" -- the input file's own columns, verbatim and in their
    original order, with Matched Part Number / Orderable Part Number (for
    matched rows only), Status, and Top Product 1..5 (the top 5 review
    candidates' part numbers, one per column, in rank order) appended.
    Falls back to Requested Description/Quantity when a line has no
    original columns to mirror (a PDF quote, or a headerless data dump)."""
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
