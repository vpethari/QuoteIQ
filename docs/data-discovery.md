# QuoteIQ data discovery

This document records the actual contents of the two Excel workbooks in `data/`. Original files were not renamed or modified.

- `data/Atkorepartsfile.xlsx`
- `data/inputfile.xlsx`

Inspection was performed with `backend/scripts/inspect_excel.py` (openpyxl, read-only).

---

## Atkore workbook: `Atkorepartsfile.xlsx`

### Structure

| Item | Value |
| --- | --- |
| File size | 11,568 bytes |
| Worksheets | `Sheet1` (1 sheet) |
| Used range | A1:D63 |
| Rows | 63 (1 header + 62 data rows) |
| Columns | 4 |
| Merged cells | none |
| Formulas | none |
| Freeze panes / auto-filter | none |
| Blank rows | none |
| Duplicate full rows | none |
| Possible header rows | row 1 |
| Possible subtotal/total rows | none |

openpyxl reports: `Unknown extension is not supported and will be removed`. This is a load warning from extra Excel XML that openpyxl does not implement. It does not change cell values in this file. All stored values are strings (`data_type=s`) with `General` number format. No bold header styling, no fills, no merged cells.

### Exact column names (row 1)

1. `Salsify ID`
2. `Catalog Number - Short Description`
3. `Short Description - en-US`
4. `salsify:parent_id`

### Data types

Every populated cell is a string. There are no numeric, date, boolean, or formula cells.

### Missing / null values (among 62 data rows)

| Column | Null / empty count | Notes |
| --- | --- | --- |
| Salsify ID | 0 | Always populated |
| Catalog Number - Short Description | 0 | Parent/family rows use the placeholder `-` |
| Short Description - en-US | 12 | All 12 parent/family rows |
| salsify:parent_id | 12 | All 12 parent/family rows |

### First 10 data rows (Excel rows 2–11)

| Row | Salsify ID | Catalog Number - Short Description | Short Description - en-US | salsify:parent_id |
| --- | --- | --- | --- | --- |
| 2 | PP_DBL_EXT_CBL | - | (empty) | (empty) |
| 3 | NA1-1EEC | 1EEC -  120V DBL HEAD EXT CABLE | 120V DBL HEAD EXT CABLE | PP_DBL_EXT_CBL |
| 4 | NA1-1EAG/A | 1EAG/A -  120V EXT CABLE ISO GROUND | 120V EXT CABLE ISO GROUND | PP_DBL_EXT_CBL |
| 5 | GS_RMC_NPL_HDG | - | (empty) | (empty) |
| 6 | NA1-920033 | 920033 - "1/2"" X 16""   GALV CONDUIT N | "1/2"" X 16""   GALV CONDUIT N | GS_RMC_NPL_HDG |
| 7 | F4_WIP_END_EXT_CBL | - | (empty) | (empty) |
| 8 | NA1-1LBM-W | 1LBM-W -  120V LTG WHIP W/MOLEX | 120V LTG WHIP W/MOLEX | F4_WIP_END_EXT_CBL |
| 9 | NA1-2EA-W | 2EA-W -  277V EXT CABLE | 277V EXT CABLE | F4_WIP_END_EXT_CBL |
| 10 | NA1-1LC-W | 1LC-W -  120V LIGHTING WHIP | 120V LIGHTING WHIP | F4_WIP_END_EXT_CBL |
| 11 | NA1-2EB40-B-SC | 2EB40-B-SC -  10/3 MCT | 10/3 MCT | F4_WIP_END_EXT_CBL |

### Last 5 rows (Excel rows 59–63)

| Row | Salsify ID | Catalog Number - Short Description | Short Description - en-US | salsify:parent_id |
| --- | --- | --- | --- | --- |
| 59 | NA1-2LAP | 2LAP -  277V LIGHTING CABLE W/PAULEX | 277V LIGHTING CABLE W/PAULEX | F4_EXT_CBL |
| 60 | NA1-1EAG | 1EAG -  120V EXT CABLE ISO GROUND | 120V EXT CABLE ISO GROUND | F4_EXT_CBL |
| 61 | NA1-2EB-W | 2EB-W -  277V EXT WHIP | 277V EXT WHIP | F4_EXT_CBL |
| 62 | MECH-GATOR | - | (empty) | (empty) |
| 63 | NA1-922309 | 922309 - !GTRCW 4SQX10X468.5 Y SQ SSG50 | !GTRCW 4SQX10X468.5 Y SQ SSG50 | MECH-GATOR |

### Official Atkore part / catalog number

Two identifiers are present. They are related but not the same field.

**Official catalog number (for quoting / matching to customer language):** the **catalog number prefix** inside `Catalog Number - Short Description`.

That column is a concatenated field with the pattern:

`{catalog number} -  {short description}`

Examples actually in the file:

- `1EEC` from `1EEC -  120V DBL HEAD EXT CABLE`
- `1EAG/A` from `1EAG/A -  120V EXT CABLE ISO GROUND`
- `920033` from `920033 - "1/2"" X 16""   GALV CONDUIT N`
- `2EB40-B-SC` from `2EB40-B-SC -  10/3 MCT`

On parent/family rows the same column is `-` (not a catalog number).

**Salsify ID** is a PIM record key, unique across all 62 data rows. Every **product** row uses prefix `NA1-` plus the catalog number (`NA1-1EEC`, `NA1-920033`, `NA1-1EAG/A`). Every **parent/family** row uses a different code (`PP_DBL_EXT_CBL`, `F4_LTG_CBL`, `MECH-GATOR`, etc.) and is not an Atkore catalog number.

Recommended mapping:

- `official_part_number` = catalog number parsed from `Catalog Number - Short Description` (text before ` - `), product rows only
- `salsify_id` = `Salsify ID` (unique PIM key; keep it, but do not treat parent IDs as sellable parts)

### Product description fields

| Field | Role |
| --- | --- |
| `Short Description - en-US` | Clean product description. Best field for description matching. |
| `Catalog Number - Short Description` | Catalog number plus description. Useful for search; redundant with the two parsed parts. |

There is no long description, marketing copy, UPC, manufacturer name, or unit-of-measure column in this workbook.

### Actual products vs non-product rows

**50 product rows** share all of:

- `Salsify ID` starts with `NA1-`
- `Catalog Number - Short Description` is not `-`
- `Short Description - en-US` is populated
- `salsify:parent_id` is populated

**12 parent / family / section rows** share all of:

- `Salsify ID` does **not** start with `NA1-`
- `Catalog Number - Short Description` is `-`
- description and parent_id are empty

Those 12 non-product rows:

| Excel row | Salsify ID (family / parent code) |
| --- | --- |
| 2 | PP_DBL_EXT_CBL |
| 5 | GS_RMC_NPL_HDG |
| 7 | F4_WIP_END_EXT_CBL |
| 21 | F4_LTG_CBL |
| 34 | F4_DIST_CBL |
| 36 | F3+_DBL_DIST_CBL |
| 40 | F3+_DBL_EXT_CBL |
| 44 | F4_SW_MOD |
| 50 | F4_WIP_END_LTG_CBL |
| 55 | MECH-FLOCOAT |
| 57 | F4_EXT_CBL |
| 62 | MECH-GATOR |

They are mixed into the same sheet as products (not a separate category sheet). They should not be offered as matchable catalog items. `salsify:parent_id` on product rows points at these family codes.

### Uniqueness

| Identifier | Unique? |
| --- | --- |
| `Salsify ID` (all 62 rows) | Yes (62 distinct, no duplicates) |
| Catalog number on 50 product rows | Yes (50 distinct, no duplicates) |
| Full row values | No duplicate rows |
| `Short Description - en-US` | **No** — many descriptions are shared by multiple catalog numbers |

Duplicate descriptions (same text, different parts):

| Description | Salsify IDs |
| --- | --- |
| 120V EXT CABLE ISO GROUND | NA1-1EAG/A, NA1-1EAG |
| 120V LTG WHIP W/MOLEX | NA1-1LBM-W, NA1-1LCM-W |
| 120V EXT WHIP | NA1-1EA-W, NA1-1EB-W |
| 120V LIGHTING WHIP W/PAULEX | NA1-1LBP-W, NA1-1LCP-W |
| 120V LIGHTING CABLE W/PAULEX | NA1-1LBP, NA1-1LCP |
| 277V LIGHTING CABLE | NA1-2LB, NA1-2LC, NA1-2LA |
| 120V LIGHTING CABLE W/MOLEX | NA1-1LAM, NA1-1LCM |
| 120V LIGHTING CABLE | NA1-1LA, NA1-1LB |
| 277V LIGHTING CABLE W/PAULEX | NA1-2LCP, NA1-2LAP |
| 277V DBL HEAD DIST CABLE | NA1-2DDC, NA1-2DDB |
| 277V DBL END EXT CABLE | NA1-2EEA, NA1-2EEC, NA1-2EEB |
| 120V SWITCH MODULE | NA1-1SA, NA1-1SC |
| 277V SWITCH MODULE | NA1-2SA, NA1-2SB, NA1-2SC |
| 277V WHIP END LIGHTING CABLE | NA1-2LC-W, NA1-2LA-W, NA1-2LB-W |

Description-only matching will be ambiguous. Catalog number matching is unique in this extract.

### Missing part numbers / descriptions

- No product row is missing a catalog number or a short description.
- Parent rows have no catalog number (`-`) and no description. That is expected for family records, not missing product data.
- No inactive, discontinued, status, or lifecycle column exists. Nothing in this file indicates inactive products.

### Useful product attributes actually present

- Family / parent code (`salsify:parent_id`)
- Catalog number (parsed)
- Short description
- Concatenated catalog+description
- Record kind (product vs parent), derived from the patterns above

Voltage (120V / 277V), connector type (MOLEX, PAULEX), and product family words (WHIP, CABLE, SWITCH MODULE) appear **inside the description text**, not as separate columns.

### Search vs do-not-match

**Searchable / useful for matching**

- Catalog number (parsed from column 2)
- `Short Description - en-US`
- `Catalog Number - Short Description` (full text)
- `Salsify ID` for exact ID lookup only (`NA1-…` product IDs)

**Should not be used as the customer-description match target**

- `salsify:parent_id` (internal family codes such as `F4_LTG_CBL`)
- Parent-row `Salsify ID` values (same family codes)
- Parent rows themselves

### Atkore Product Catalog

| Excel Column | Proposed Field | Description | Example | Match/Search Use |
| --- | --- | --- | --- | --- |
| Salsify ID | `salsify_id` | Unique PIM record key. Products use `NA1-` + catalog number. Parents use family codes. | `NA1-1EEC` | Exact ID lookup only. Do not match customer prose to parent IDs. |
| Catalog Number - Short Description (prefix before ` - `) | `official_part_number` | Atkore catalog number. Unique on product rows in this file. | `1EEC` | Primary exact part-number match. |
| Catalog Number - Short Description | `catalog_number_and_description` | Concatenated catalog number and description. | `1EEC -  120V DBL HEAD EXT CABLE` | Searchable text; redundant if number and description are stored separately. |
| Short Description - en-US | `description` | English short description. | `120V DBL HEAD EXT CABLE` | Primary description search / AI match input. Ambiguous when duplicated. |
| salsify:parent_id | `parent_id` | Family / parent code; empty on parent rows. | `PP_DBL_EXT_CBL` | Filter / grouping only. Do not use for quote-line matching. |
| *(derived)* | `record_type` | `product` vs `family` from the patterns above. | `product` | Exclude `family` rows from matching. |

---

## Quote workbook: `inputfile.xlsx`

### Structure

| Item | Value |
| --- | --- |
| File size | 9,286 bytes |
| Worksheets | `Sheet1` (1 sheet) |
| Used range | A1:B4 |
| Rows | 4 (1 header + 3 line items) |
| Columns | 2 |
| Merged cells | none |
| Formulas | none |
| Freeze panes / auto-filter | none |
| Blank rows | none |
| Duplicate full rows | none |
| Possible header rows | row 1 |
| Possible subtotal/total rows | none |
| Notes / other text | none |

openpyxl also reports the same unknown-extension warning on this file. Values: `Name` is string; `Qty` is numeric integer (`data_type=n`).

### Exact column names (row 1)

1. `Name`
2. `Qty`

### Data types

| Column | Type |
| --- | --- |
| Name | str (3 values) |
| Qty | int (3 values) |

### Missing / null values

None. Both columns are populated on all 3 data rows.

### All data rows (file has only 3; shown as first 10 and last 5)

| Row | Name | Qty |
| --- | --- | --- |
| 2 | 120V LIGHTING WHIP W/PAULEX | 5 |
| 3 | 277V LIGHTING CABLE | 20 |
| 4 | 120V SWITCH MODULE | 10 |

### Which worksheet contains quote line items

`Sheet1` is the only worksheet. Rows 2–4 are quote line items. Row 1 is the header.

### Customer requested product description

**`Name`** is the customer’s requested product description. All three values are free-text descriptions, not catalog numbers. They match catalog **short descriptions** (not unique — see catalog duplicates above).

### Quantity

**`Qty`** is the line quantity. Values found: `5`, `20`, `10`. No unit of measure column.

### Part numbers on the quote

| Kind | Present in this file? |
| --- | --- |
| Customer / vendor part number | No |
| Atkore catalog / Salsify ID | No |
| Manufacturer name | No |
| Price, UOM, notes, job name | No |

There are no header banners, section titles, subtotal rows, total rows, or comment rows in this workbook.

### Which fields should become the normalized QuoteIQ LineItem

Only fields that exist in this file, plus source coordinates for traceability:

- `source_file` (this workbook’s filename)
- `source_sheet` (`Sheet1`)
- `source_row` (Excel row 2, 3, or 4)
- `requested_description` from `Name`
- `quantity` from `Qty`

`customer_part_number` is **not** in this workbook and is not included in the model below.

### Quote Input

| Excel Column | Proposed Field | Description | Example | Matching Use |
| --- | --- | --- | --- | --- |
| *(file name)* | `source_file` | Workbook the line came from. | `inputfile.xlsx` | Traceability only. |
| *(sheet name)* | `source_sheet` | Worksheet name. | `Sheet1` | Traceability only. |
| *(row number)* | `source_row` | 1-based Excel row. | `2` | Traceability only. |
| Name | `requested_description` | Customer-requested product text. | `120V LIGHTING WHIP W/PAULEX` | Primary match input against catalog `description`. |
| Qty | `quantity` | Requested quantity. Integer in this file. | `5` | Not used for product matching; used for the quote line. |

---

## Proposed normalized application models

Fields below are limited to what these two workbooks actually support.

### Product

```text
Product
  salsify_id: str                 # Excel: Salsify ID (unique)
  official_part_number: str       # Catalog number parsed from column 2
  catalog_number_and_description: str
  description: str                # Excel: Short Description - en-US
  parent_id: str | None           # Excel: salsify:parent_id
  record_type: "product" | "family"
```

Load **product** rows into the matchable catalog. Keep **family** rows only if hierarchy is needed later; do not match quotes to them.

### LineItem

```text
LineItem
  source_file: str
  source_sheet: str
  source_row: int
  requested_description: str      # Excel: Name
  quantity: int                   # Excel: Qty
```

No customer part number, vendor part number, or pre-filled Atkore part number exists on the current quote file.

---

## Data-quality issues that will affect later matching

1. **Duplicate catalog descriptions.** Several distinct catalog numbers share the same `Short Description - en-US`. The three quote lines all use description text that is duplicated in the catalog (`120V LIGHTING WHIP W/PAULEX`, `277V LIGHTING CABLE`, `120V SWITCH MODULE`). Description-only matching cannot pick a single part without more attributes or human review.
2. **Near-duplicate wording.** Example: `120V LIGHTING WHIP W/PAULEX` vs `120V LTG WHIP W/PAULEX` (NA1-1LAP-W). Abbreviation differences will affect naive exact matching.
3. **Family rows mixed with products.** Twelve rows are parents (`Catalog Number - Short Description` = `-`). They must be excluded from product matching.
4. **Concatenated catalog column.** Official catalog number is not its own Excel column; it must be parsed from `Catalog Number - Short Description`.
5. **Truncated / odd descriptions.** `NA1-920033` description ends at `GALV CONDUIT N`. `NA1-922320` and `NA1-922309` descriptions start with `!` and look like encoded mill/process strings, not sellable electrical-product names.
6. **Quote file has no part numbers.** Matching must be description-based for this input.
7. **Tiny extracts.** 50 products and 3 quote lines. Treat this as a sample, not a full Atkore catalog or a full bid sheet. Later files may add columns (UOM, customer PN, prices, extra sheets).

---

## Inspection tooling

- Script: `backend/scripts/inspect_excel.py`
- Tests: `tests/test_inspect_excel.py` (temporary workbooks only; real `data/` files are not modified)
- Packages: `openpyxl==3.1.5`, `pytest==9.1.1` (`requirements.txt`)

Example:

```text
python backend/scripts/inspect_excel.py "data/inputfile.xlsx"
python backend/scripts/inspect_excel.py "data/Atkorepartsfile.xlsx"
```
