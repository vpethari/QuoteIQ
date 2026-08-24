# QuoteIQ AI reasoning layer

The deterministic matcher from Step 3 is unchanged and remains the first stage. This layer only reasons over **top candidates** that matcher already produced. It never searches the full catalog and never invents Atkore part numbers.

## Architecture

```text
Quote Line
    → Deterministic Candidate Generation
    → Top N product candidates (default 5)
    → AIReasoningProvider.reason_about_candidates(...)
    → Pydantic parse (AIReasoningResult)
    → Candidate + approved-catalog validation
    → Policy (thresholds)
    → Validated Match Decision
         CONFIDENT_MATCH | REVIEW_REQUIRED | NO_MATCH
```

When `AI_MATCHING_ENABLED=false` (default), APIs use the deterministic matcher only. The application still starts if Azure is not configured.

## Responsibilities

**Deterministic matcher**

- Score every `record_type=product` row
- Exclude family/parent rows
- Rank candidates and compute score gaps
- Flag ambiguous identical descriptions as `REVIEW_REQUIRED`

**AI layer**

- Judge whether **one** supplied candidate is a confident semantic match
- Explain abbreviations, voltage, whip vs cable, connectors, conflicts
- Return structured JSON only
- Must choose `selected_part_number` from the supplied list or return null

## Candidate generation

Only the top `AI_MAX_CANDIDATES` (default 5) candidates are sent. Each item includes:

- `official_part_number`
- `description`
- `salsify_id`
- `deterministic_score`
- `match_reasons`

The model does not receive the Excel files, database URLs, family rows, or the rest of the catalog.

## Prompt structure

Versioned in `backend/ai/prompt_builder.py` (`PROMPT_VERSION=v1`).

- **System prompt:** product-matching assistant; never invent part numbers; family IDs invalid; identical descriptions require review; do not use quantity; do not use outside catalog knowledge.
- **User prompt:** requested description, quantity (explicitly unused for identity), and JSON candidates.

Prompts are not logged at INFO. DEBUG logs prompt version and candidate count only. API keys are never logged.

## Structured output

`AIReasoningResult` (Pydantic) requires:

- `decision`: `CONFIDENT_MATCH` | `REVIEW_REQUIRED` | `NO_MATCH`
- `selected_part_number`: string or null
- `confidence_percentage`: 0–100
- `reasoning_summary`
- `matched_attributes` / `conflicting_attributes`
- `candidate_evaluations` (`official_part_number`, `assessment`, `score`)

Raw model JSON is parsed and validated. Invalid payloads become `REVIEW_REQUIRED`.

## Validation / hallucination protection

After the model returns, QuoteIQ checks:

1. Selected part is non-empty only if present
2. Part is in the **candidate list**
3. Part is an approved **product** `official_part_number` (not a family Salsify ID)
4. Malformed strings are rejected

Any failure → `REVIEW_REQUIRED`, `matched_part_number=null`. Catalog validation is never skipped because the model claimed 100% confidence.

## Confidence policy

Environment (not hard-coded in the service body):

| Variable | Default | Role |
| --- | --- | --- |
| `AI_CONFIDENT_THRESHOLD` | 90 | Minimum AI confidence for `CONFIDENT_MATCH` |
| `AI_REVIEW_THRESHOLD` | 50 | Below this, a claimed match is not accepted |
| `AI_MAX_CANDIDATES` | 5 | Candidates sent to the model |
| `AI_MATCHING_ENABLED` | false | Quote endpoint uses AI when true |

`CONFIDENT_MATCH` requires: AI decision `CONFIDENT_MATCH` **and** confidence ≥ 90 **and** candidate list hit **and** catalog hit.

`final_confidence` is `min(deterministic_score, ai_confidence)` on a validated confident match. The deterministic score is never overwritten.

## Azure configuration

```env
AZURE_OPENAI_ENDPOINT=https://YOUR_RESOURCE.openai.azure.com/
AZURE_OPENAI_API_KEY=
AZURE_OPENAI_DEPLOYMENT=YOUR_DEPLOYMENT_NAME
AZURE_OPENAI_API_VERSION=2024-10-21
```

See `.env.example`. Do not commit real keys. `AzureOpenAIReasoningProvider` calls the Azure OpenAI chat completions API with JSON mode. Missing credentials → `UnconfiguredAIReasoningProvider`; `POST /api/matching/ai-preview` returns HTTP 503 instead of crashing the process.

## Local development

1. Keep `AI_MATCHING_ENABLED=false` to use deterministic matching.
2. Tests use `MockAIReasoningProvider` and do not need Azure.
3. To try Azure: fill the four variables, set `AI_MATCHING_ENABLED=true`, call `/api/matching/ai-preview`.

## API

- `POST /api/matching/preview` — deterministic only
- `POST /api/matching/ai-preview` — deterministic + AI + validation
- `POST /api/matching/quote` — deterministic by default; `use_ai: true` or `AI_MATCHING_ENABLED=true` enables AI

## Auditability

Each AI attempt stores (in-memory `InMemoryAuditStore`):

source file/sheet/row, requested description, candidate part numbers and deterministic scores, AI decision, selected part, AI confidence, reasoning summary, provider/model, prompt version, validation_rejected, timestamp.

No API keys.

## Testing

`tests/test_ai_reasoning.py` covers valid selection, invented parts, family IDs, null, low/high confidence, candidate+catalog enforcement, ambiguity, AI disabled fallback, missing Azure config, malformed JSON, multi-line quotes, and audit records.

## Limitations

- The current quote lines have duplicate catalog descriptions; both the matcher and a honest AI should return `REVIEW_REQUIRED`.
- The mock heuristic is for tests only; production uses Azure.
- In-memory audit is not yet a database table.
- Azure latency, cost, and content filters are out of scope for this step.
