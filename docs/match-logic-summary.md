# How QuoteIQ decides Matched, Review Required, or No Match

Leadership-level summary of the matching engine. Every line on a customer quote goes through the
same three-step, rule-based process before anything is shown to a reviewer. AI is an optional
add-on layered on top, not a replacement for it.

A rendered, visual version of this summary is published as a Claude Artifact:
https://claude.ai/code/artifact/a003e2b5-543b-4e80-8b98-b331aacfb5ff

## The process: search, score, decide

1. **Search** — find every catalog item that could plausibly be what the customer meant.
2. **Score** — rate each candidate found in Step 1 on a 0–100 scale.
3. **Decide** — turn the top score (and how it compares to the runner-up) into one of three statuses.

## Step 1 — Search: finding candidates

Two search strategies run for every line:

- **Identifier search** — if the text looks like a part number, look it up directly (exact and partial).
- **Text search** — search the catalog's product names and descriptions for the meaningful words in the request.

Customers and the catalog don't always use the same word for the same thing, so a built-in
synonym list keeps common variants connected:

| Customer might say | Catalog says |
| --- | --- |
| CABLE | CBL |
| UNISTRUT | STRUT |
| TRAY | TROF / TROUGH |
| SWITCH | SW |
| ASSEMBLY | ASSY |

**If nothing matches every word:** the search retries requiring most of the meaningful words
(currently 60%+) instead of all of them, so a close-but-imperfectly-worded request still surfaces
something for a human to check rather than coming back empty.

## Step 2 — Score: rating each candidate, 0–100

How the score is built depends on whether the customer gave a usable part number.

**If a part number was given:**

| Signal | Weight |
| --- | --- |
| Part number match | 70% |
| Description agrees | 30% |

**If it's description-only:**

| Signal | Weight |
| --- | --- |
| Exact phrase match | 40% |
| Shared key words | 25% |
| Spelling closeness | 20% |
| Matching attributes | 15% |

A real spec mismatch overrides a good text score: if the customer asked for 120V and the
closest-worded candidate is 277V, that conflict actively caps the score — good wording can't
paper over the wrong voltage, amperage, or size.

## Step 3 — Decide: turning a score into a status

| Score | Status |
| --- | --- |
| 0–4 | **No Match** — nothing close enough to suggest |
| 5–89 | **Review Required** — a plausible candidate exists, a person should confirm it |
| 90–100 | **Matched** — confident enough to accept automatically |

**Ambiguity overrides a high score.** If there's a close second-place candidate (within 8 points,
or a tie), the line is routed to Review Required regardless of how confident the top score looks —
two real possibilities that can't be told apart is itself a reason for a human to decide, not the
engine.

## Where AI fits in

AI matching is an optional toggle, layered strictly on top of the three steps above — it is never
the search engine itself.

- It can only choose from the candidates the deterministic search already found — it never
  invents, guesses, or completes a part number.
- Its job is to double-check the top candidate: does the wording genuinely agree, or is this a
  coincidental text match hiding a real conflict?
- It's automatically skipped when there's nothing to review — zero candidates, or a part number
  that's already a verified exact match — so no wasted calls.

## Today's thresholds

These are configuration values (`matching/models.py::MatchingConfig`), not hardcoded rules — they
can be tuned at any time as SME and user feedback comes in.

| Setting | Current value | What it controls |
| --- | --- | --- |
| Review threshold | 5 | Minimum score to avoid an automatic No Match |
| High-confidence threshold | 90 | Minimum score to auto-accept as Matched |
| Ambiguity gap | 8 pts | How far ahead the top candidate must be to avoid Review |
| Partial-match word overlap | 60% | Minimum share of key words needed to surface a fallback candidate |

The Review threshold was deliberately set low (5, not a stricter number) so borderline lines get a
human's attention instead of silently disappearing into No Match. Expect more lines in Review
Required than a stricter setting would produce — that's the intended trade: fewer real misses, in
exchange for a larger review queue.

## Honest limits

- Matching depends on real word or spelling overlap between the request and the catalog. If a
  product exists under a completely different name, or genuinely isn't carried, the correct result
  is No Match — that's a catalog-coverage question, not a scoring bug.
- The synonym list and fallback logic are being expanded on an ongoing basis as real customer
  files surface new gaps — this is a living system, not a one-time build.
