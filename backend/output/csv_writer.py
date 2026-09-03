from __future__ import annotations

import csv
import io
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from output.rows import (
    csv_row_from_final_result,
    csv_row_from_mapping,
    csv_row_from_match_result,
)
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
    """Part Number + Quantity, for matched rows -- ready to hand to CPQ."""
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


def _normalize_full_result(item: object) -> dict[str, Any]:
    from ai.models import FinalMatchResult
    from matching.models import MatchResult

    if isinstance(item, FinalMatchResult):
        return {
            "raw_row": dict(item.raw_row or {}),
            "requested_description": item.requested_description,
            "quantity": item.quantity,
            "match_status": item.match_status,
            "matched_part_number": item.matched_part_number,
            "matched_orderable_part_number": item.matched_orderable_part_number,
        }
    if isinstance(item, MatchResult):
        return {
            "raw_row": dict(item.raw_row or {}),
            "requested_description": item.requested_description,
            "quantity": item.quantity,
            "match_status": item.match_status.value,
            "matched_part_number": item.matched_part_number,
            "matched_orderable_part_number": item.matched_orderable_part_number,
        }
    if isinstance(item, Mapping):
        raw_row = item.get("raw_row") or {}
        return {
            "raw_row": {str(key): value for key, value in raw_row.items()},
            "requested_description": item.get("requested_description"),
            "quantity": item.get("quantity"),
            "match_status": str(item.get("match_status") or ""),
            "matched_part_number": item.get("matched_part_number"),
            "matched_orderable_part_number": item.get("matched_orderable_part_number"),
        }
    raise TypeError(f"Unsupported result type: {type(item)!r}")


def _full_results_row(data: dict[str, Any]) -> dict[str, str]:
    status = data["match_status"]
    emit = (status or "").upper() in STATUSES_WITH_PART_NUMBER
    raw_row = data["raw_row"]
    if not raw_row:
        raw_row = {
            "Requested Description": data.get("requested_description") or "",
            "Quantity": "" if data.get("quantity") is None else str(data["quantity"]),
        }
    row = {str(key): ("" if value is None else str(value)) for key, value in raw_row.items()}
    row["Matched Part Number"] = str(data.get("matched_part_number") or "") if emit else ""
    row["Orderable Part Number"] = str(data.get("matched_orderable_part_number") or "") if emit else ""
    row["Status"] = status or ""
    return row


def render_full_results_csv_bytes(results: Sequence[object]) -> bytes:
    """"Full Results" -- the input file's own columns, verbatim and in their
    original order, with Matched Part Number / Orderable Part Number (for
    matched rows only) and Status appended. Falls back to Requested
    Description/Quantity when a line has no original columns to mirror
    (a PDF quote, or a headerless data dump)."""
    normalized = [_normalize_full_result(item) for item in results]
    rows = [_full_results_row(item) for item in normalized]
    columns: list[str] = []
    seen: set[str] = set()
    for item in normalized:
        source_columns = item["raw_row"] or {"Requested Description": None, "Quantity": None}
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
