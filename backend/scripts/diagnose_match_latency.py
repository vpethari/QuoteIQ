"""Run live PostgreSQL match timings. Instrumentation only; no optimizations."""

from __future__ import annotations

import io
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
os.environ["QUOTEIQ_TIMING"] = "1"
os.environ["CATALOG_SOURCE"] = "postgresql"
sys.path.insert(0, str(ROOT / "backend"))

from fastapi.testclient import TestClient  # noqa: E402
from openpyxl import Workbook  # noqa: E402

from app.main import app  # noqa: E402

REPORT = ROOT / "timing_last.txt"
TEN_LINES = [
    "B1EB5-W",
    "RR2BA",
    "BRP 120 volts whip end extension cable",
    "1MD12BZUZ115EB1",
    "1MD06AZJZ040V1S",
    "120V whip end extension cable",
    "steel conduit 1/2 inch",
    "RR2BA KR",
    "B1EB5-W",
    "extension cable 120 volts",
]


def _xlsx_bytes(descriptions: list[str]) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet["A1"] = "Description"
    sheet["B1"] = "Qty"
    for index, text in enumerate(descriptions, start=2):
        sheet[f"A{index}"] = text
        sheet[f"B{index}"] = 1
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def _quote(client: TestClient, descriptions: list[str], label: str) -> None:
    print(f"\n===== {label} =====", flush=True)
    response = client.post(
        "/api/matching/quote",
        json={
            "use_ai": False,
            "lines": [
                {"requested_description": text, "source_row": index}
                for index, text in enumerate(descriptions, start=1)
            ],
        },
    )
    print(f"HTTP {response.status_code} count={response.json().get('count')}", flush=True)


def main() -> None:
    if REPORT.exists():
        REPORT.unlink()
    with TestClient(app) as client:
        health = client.get("/health")
        print(f"warmup /health HTTP {health.status_code} {health.json()}", flush=True)
        _quote(client, ["B1EB5-W"], "1 exact Productcode B1EB5-W")
        _quote(client, ["RR2BA"], "2 RR2BA")
        _quote(
            client,
            ["BRP 120 volts whip end extension cable"],
            "3 BRP 120 volts whip end extension cable",
        )
        _quote(client, TEN_LINES, "4a 10-line JSON quote")
        print("\n===== 4b 10-line Excel /api/quote/process/results =====", flush=True)
        files = {
            "file": (
                "quote.xlsx",
                _xlsx_bytes(TEN_LINES),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        }
        response = client.post(
            "/api/quote/process/results",
            data={"use_ai": "false"},
            files=files,
        )
        print(f"HTTP {response.status_code} summary={response.json().get('summary')}", flush=True)
    print(f"\nWrote combined report to {REPORT}", flush=True)


if __name__ == "__main__":
    main()
