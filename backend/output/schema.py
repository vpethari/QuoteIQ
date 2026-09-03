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

CPQ_CSV_COLUMNS: tuple[str, ...] = ("Part Number", "Quantity")
CPQ_DOWNLOAD_FILENAME = "QuoteIQ_CPQ_Ready.csv"

# "Full Results" mirrors the input file's own columns verbatim and appends
# just these three -- it does not use CSV_COLUMNS above.
FULL_RESULTS_APPENDED_COLUMNS: tuple[str, ...] = (
    "Matched Part Number",
    "Orderable Part Number",
    "Status",
)
