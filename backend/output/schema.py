from __future__ import annotations

CSV_COLUMNS: tuple[str, ...] = (
    "Source File",
    "Source Sheet",
    "Source Row",
    "Requested Description",
    "Quantity",
    "Matched Atkore Part Number",
    "Matched Salsify ID",
    "Matched Atkore Description",
    "Matching Percentage",
    "Confidence",
    "Match Status",
    "Match Reason",
    "Candidate Count",
    "Top Candidates",
    "Requested Part Number",
    "Part Number Match %",
    "Description Match %",
    "Overall Match %",
)

STATUSES_WITH_PART_NUMBER = frozenset(
    {"CONFIDENT_MATCH", "EXACT_MATCH", "HIGH_CONFIDENCE"}
)
DOWNLOAD_FILENAME = "QuoteIQ_results.csv"

CPQ_CSV_COLUMNS: tuple[str, ...] = ("Productcode", "Qty", "Requested Product")
CPQ_DOWNLOAD_FILENAME = "QuoteIQ_CPQ_Ready.csv"
