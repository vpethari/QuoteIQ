# QuoteIQ deterministic matching engine

This document describes the Step 3 matching engine. It does **not** call an LLM, embeddings API, or external AI service. An AI reasoning layer can sit on top of these candidate results later.

The engine searches only `record_type="product"` rows. Family/parent Salsify IDs such as `PP_DBL_EXT_CBL`, `F4_LTG_CBL`, and `MECH-GATOR` never become candidates and are never emitted as Atkore part numbers.

## Normalization

Comparison uses `matching.normalizer.normalize_text()`:

- uppercase
- strip and collapse whitespace
- turn most punctuation into spaces
- keep `/` so sizes such as `10/3` stay intact

The original customer `requested_description` is stored unchanged on the result.

`canonical_text()` then expands a small synonym table (`LTG` → `LIGHTING`) and drops stopwords (`W`, `WITH`, `AND`, …). Catalog `official_part_number` values are never rewritten.

## Tokenization

`tokenize_description()` splits on alphanumeric tokens. `W/PAULEX` becomes `PAULEX`. Tokens are used for Dice similarity and attribute extraction.

## Attribute extraction

`extract_attributes()` builds a set from the text itself:

- voltages (`120V`, `277V`) via regex
- wire sizes (`10/3`, `16/2`)
- significant tokens (length ≥ 3)
- known multi-word phrases when those tokens appear in order (`LIGHTING WHIP`, `SWITCH MODULE`, …)

The phrase list is a seed, not the full attribute vocabulary. New tokens in a future catalog are still extracted as `token:…` attributes.

## Scoring

Each product is scored with four signals, then a weighted sum:

| Signal | Function | Weight (default) |
| --- | --- | --- |
| Exact canonical/normalized description | `calculate_exact_score` | 0.40 |
| Token Dice similarity | `calculate_token_score` | 0.25 |
| Character similarity (`difflib`) | `calculate_fuzzy_score` | 0.20 |
| Attribute Jaccard overlap | `calculate_attribute_score` | 0.15 |

`calculate_final_score()` clamps the result to **0–100**. Weights must sum to 1.0 and live on `MatchingConfig` (also exposed via app settings for confidence thresholds).

Candidates below `candidate_floor` (default 35) are dropped. Remaining candidates are sorted by score descending, then `official_part_number`, then `salsify_id` so ranking is deterministic.

`top_score`, `second_score`, and `score_gap = top_score - second_score` are always computed when two or more scores exist.

## Confidence thresholds

Configured on `MatchingConfig` / environment-backed settings — not hard-coded into API handlers:

| Status | Rule |
| --- | --- |
| `EXACT_MATCH` | Canonical description is an exact match, **and** exactly one product has that exact score, **and** the description is not shared by multiple catalog rows |
| `HIGH_CONFIDENCE` | Top score ≥ `high_confidence_min` (default 90) **and** `score_gap` ≥ `min_score_gap` (default 8) **and** not a tied duplicate description |
| `REVIEW_REQUIRED` | At least one candidate reaches `min_match_threshold` (default 58), but the winner is ambiguous (same description, tiny gap, or not unique) |
| `NO_MATCH` | No candidate reaches `min_match_threshold` |

The highest score is **not** enough for `HIGH_CONFIDENCE`. Duplicate catalog descriptions (for example `120V LIGHTING WHIP W/PAULEX` → `1LBP-W` and `1LCP-W`) must return `REVIEW_REQUIRED` with **no** selected `matched_part_number`.

## Ambiguity

The current Atkore extract has many shared short descriptions. When several products share the same canonical description, QuoteIQ returns all of those candidates, explains the duplicate, and refuses to invent a winner.

## Explanations

Reasons are generated from the signals above (exact match, voltage, phrases, notable tokens, duplicate description, score gap). They are not produced by an LLM.

## Examples

Unique exact (catalog has one `10/3 MCT`):

- Input: `10/3 MCT`
- Expected: `EXACT_MATCH` for `2EB40-B-SC`

Duplicate quote line from `inputfile.xlsx`:

- Input: `120V LIGHTING WHIP W/PAULEX`
- Expected: `REVIEW_REQUIRED`, candidates include `1LBP-W` and `1LCP-W`, no automatic part number

Abbreviation:

- Input: `120V LTG WHIP`
- Canonical form matches unique `120V LIGHTING WHIP` (`1LC-W`) if no other product shares that canonical string

## Limitations

- No unit of measure, finish, length, or connector SKU columns exist in the extract, so many lighting/switch descriptions cannot be disambiguated.
- Fuzzy matching is `difflib`, not a phonetic or embedding model.
- Synonym coverage is small (`LTG` → `LIGHTING`). Unknown abbreviations will not become exact matches.
- Matching is description-only unless the requested text already equals a description; customer part numbers are not on the current quote file.

## CSV shape (export later)

`match_result_to_csv_row()` maps a `MatchResult` to:

Source File, Source Sheet, Source Row, Requested Description, Quantity, Matched Atkore Part Number, Matched Atkore Description, Matching Percentage, Confidence, Match Status
