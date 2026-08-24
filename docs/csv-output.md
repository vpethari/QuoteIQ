# QuoteIQ CSV output

QuoteIQ turns a processed quote into a downloadable UTF-8 CSV for agents. Source Excel files are never modified.

## CSV schema

Column order is fixed:

1. Source File
2. Source Sheet
3. Source Row
4. Requested Description
5. Quantity
6. Matched Atkore Part Number
7. Matched Atkore Description
8. Matching Percentage
9. Confidence
10. Match Status
11. Match Reason
12. Candidate Count
13. Top Candidates

## Matching percentage

Numeric text **without** a `%` sign. Whole numbers are written as `100`, not `100.0` or `100%`.

For `REVIEW_REQUIRED` / `NO_MATCH` this is the top deterministic candidate score. For a validated `CONFIDENT_MATCH` it is the final combined confidence.

## Confidence labels

| Match status | Confidence |
| --- | --- |
| `CONFIDENT_MATCH`, `EXACT_MATCH`, `HIGH_CONFIDENCE` | HIGH |
| `REVIEW_REQUIRED` | REVIEW |
| `NO_MATCH` | LOW |

Numeric AI confidence stays on the internal result object; it is not a CSV column.

## Match statuses and part numbers

| Status | Matched Atkore Part Number |
| --- | --- |
| `CONFIDENT_MATCH` / `EXACT_MATCH` / `HIGH_CONFIDENCE` | Validated official part number only |
| `REVIEW_REQUIRED` | blank |
| `NO_MATCH` | blank |

Unvalidated, invented, family, or off-list part numbers never appear in the CSV.

## Top candidates

Compact list, semicolon-separated:

`1LAP-W (100); 1LBP-W (100); 1LCP-W (100)`

The CSV writer quotes fields that contain commas or quotes.

## Review-required behavior

The current `inputfile.xlsx` lines all stay `REVIEW_REQUIRED` because several catalog products share the same description. The part-number column is blank; Top Candidates still lists the ranked products.

## File upload

`POST /api/quote/process` accepts an **`.xlsx`** upload (`multipart/form-data` field `file`) and optional `use_ai=true|false`.

- `.xls` is not supported with the current openpyxl stack (no macro execution).
- Size limit: `QUOTE_UPLOAD_MAX_BYTES` (default 5 MiB).
- Uploads are written to a temporary `.xlsx` and deleted after processing.
- The download name is always `QuoteIQ_results.csv` (the upload filename is not used in paths or the response).

## API examples

Deterministic CSV from a quote file:

```http
POST /api/quote/process
Content-Type: multipart/form-data

file: inputfile.xlsx
use_ai: false
```

Response: `Content-Type: text/csv; charset=utf-8`  
`Content-Disposition: attachment; filename="QuoteIQ_results.csv"`

CSV from already-computed results:

```http
POST /api/output/csv
Content-Type: application/json

{ "results": [ { "requested_description": "...", "match_status": "REVIEW_REQUIRED", ... } ] }
```

AI-enabled processing uses the same upload endpoint with `use_ai=true`. If Azure is not configured, the API returns 503 rather than crashing.
