from __future__ import annotations

from collections.abc import Sequence
from functools import lru_cache
from pathlib import Path
import tempfile

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel, Field, model_validator

from ai.azure_provider import AzureOpenAIReasoningProvider
from ai.provider import AINotConfiguredError, AIReasoningProvider, UnconfiguredAIReasoningProvider
from ai.service import AIMatchingService, AIPolicyConfig, InMemoryAuditStore
from app.config import PROJECT_ROOT, get_settings
from catalog.excel_loader import load_catalog_records
from matching.matcher import ProductMatcher
from matching.models import MatchingConfig, QuoteLine
from output.api_results import serialize_process_result, summarize_results
from output.csv_writer import render_csv_bytes, rows_from_results
from output.pipeline import process_quote_results
from output.schema import DOWNLOAD_FILENAME
from quotes.models import QuoteParseError
from quotes.parser import line_items_to_quote_lines, parse_quote_file

app = FastAPI(title="QuoteIQ", version="0.5.0")
_audit_store = InMemoryAuditStore()

_cors_origins = [
    origin.strip()
    for origin in get_settings().cors_origins.split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


class PreviewRequest(BaseModel):
    description: str = Field(min_length=1)
    quantity: int | float | None = None


class QuoteLineRequest(BaseModel):
    source_file: str | None = None
    source_sheet: str | None = None
    source_row: int | None = None
    requested_description: str = Field(min_length=1)
    quantity: int | float | None = None
    requested_part_number: str | None = None


class QuoteMatchRequest(BaseModel):
    lines: list[QuoteLineRequest] | None = None
    source_path: str | None = None
    use_ai: bool | None = None

    @model_validator(mode="after")
    def require_lines_or_path(self) -> QuoteMatchRequest:
        if not self.lines and not self.source_path:
            raise ValueError("Provide lines or source_path")
        return self


@lru_cache
def _cached_catalog_and_matcher() -> tuple[list, ProductMatcher]:
    settings = get_settings()
    catalog_path = Path(settings.catalog_excel_path)
    if not catalog_path.is_file():
        catalog_path = PROJECT_ROOT / "data" / "Atkorepartsfile.xlsx"
    records = load_catalog_records(catalog_path)
    config = MatchingConfig(
        high_confidence_min=settings.match_high_confidence_min,
        min_match_threshold=settings.match_min_threshold,
        min_score_gap=settings.match_min_score_gap,
    )
    return records, ProductMatcher(records, config)


def get_matcher() -> ProductMatcher:
    return _cached_catalog_and_matcher()[1]


def _azure_configured(settings) -> bool:
    return bool(
        settings.azure_openai_endpoint
        and settings.azure_openai_api_key
        and settings.azure_openai_deployment
        and settings.azure_openai_api_version
    )


def build_ai_provider() -> AIReasoningProvider:
    settings = get_settings()
    if not _azure_configured(settings):
        return UnconfiguredAIReasoningProvider()
    return AzureOpenAIReasoningProvider(
        endpoint=settings.azure_openai_endpoint,
        api_key=settings.azure_openai_api_key,
        deployment=settings.azure_openai_deployment,
        api_version=settings.azure_openai_api_version,
    )


def get_ai_provider() -> AIReasoningProvider:
    return build_ai_provider()


def get_ai_service(
    matcher: ProductMatcher = Depends(get_matcher),
    provider: AIReasoningProvider = Depends(get_ai_provider),
) -> AIMatchingService:
    settings = get_settings()
    records = _cached_catalog_and_matcher()[0]
    return AIMatchingService(
        matcher=matcher,
        catalog=records,
        provider=provider,
        policy=AIPolicyConfig(
            confident_threshold=settings.ai_confident_threshold,
            review_threshold=settings.ai_review_threshold,
            max_candidates=settings.ai_max_candidates,
        ),
        audit_store=_audit_store,
    )


class CsvExportRequest(BaseModel):
    results: list[dict] = Field(min_length=1)


def _quote_lines_from_payload(payload: QuoteMatchRequest) -> Sequence[QuoteLine]:
    if payload.source_path:
        path = Path(payload.source_path)
        if not path.is_file():
            path = PROJECT_ROOT / payload.source_path
        if not path.is_file():
            raise HTTPException(status_code=400, detail="Quote file not found.")
        try:
            return line_items_to_quote_lines(parse_quote_file(path))
        except QuoteParseError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    assert payload.lines is not None
    return [
        QuoteLine(
            source_file=item.source_file or "",
            source_sheet=item.source_sheet or "",
            source_row=item.source_row or 0,
            requested_description=item.requested_description,
            quantity=item.quantity,
            requested_part_number=item.requested_part_number,
        )
        for item in payload.lines
    ]


@app.get("/health")
def health() -> dict[str, str]:
    settings = get_settings()
    return {
        "status": "ok",
        "ai_matching_enabled": str(settings.ai_matching_enabled).lower(),
    }


@app.post("/api/matching/preview")
def preview_match(
    payload: PreviewRequest,
    matcher: ProductMatcher = Depends(get_matcher),
) -> dict:
    result = matcher.match_description(
        requested_description=payload.description,
        quantity=payload.quantity,
    )
    return result.to_api_dict()


@app.post("/api/matching/ai-preview")
def ai_preview_match(
    payload: PreviewRequest,
    service: AIMatchingService = Depends(get_ai_service),
) -> dict:
    try:
        result = service.match_description(
            requested_description=payload.description,
            quantity=payload.quantity,
            use_ai=True,
        )
    except AINotConfiguredError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return result.model_dump(mode="json")


@app.post("/api/matching/quote")
def match_quote_endpoint(
    payload: QuoteMatchRequest,
    matcher: ProductMatcher = Depends(get_matcher),
    service: AIMatchingService = Depends(get_ai_service),
) -> dict:
    lines = _quote_lines_from_payload(payload)
    settings = get_settings()
    use_ai = settings.ai_matching_enabled if payload.use_ai is None else payload.use_ai
    if not use_ai:
        results = matcher.match_quote(lines)
        return {"count": len(results), "results": [item.to_api_dict() for item in results]}
    try:
        results = service.match_quote(lines, use_ai=True)
    except AINotConfiguredError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"count": len(results), "results": [item.model_dump(mode="json") for item in results]}


def _csv_response(payload: bytes) -> Response:
    return Response(
        content=payload,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{DOWNLOAD_FILENAME}"',
        },
    )


def _store_upload(upload: UploadFile) -> Path:
    settings = get_settings()
    original = upload.filename or "quote.xlsx"
    suffix = Path(original).suffix.lower()
    if suffix == ".xls":
        raise HTTPException(
            status_code=400,
            detail="Excel .xls files are not supported. Upload an .xlsx workbook.",
        )
    if suffix != ".xlsx":
        raise HTTPException(status_code=400, detail="Only .xlsx quote files are accepted.")
    data = upload.file.read(settings.quote_upload_max_bytes + 1)
    if not data:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")
    if len(data) > settings.quote_upload_max_bytes:
        raise HTTPException(status_code=413, detail="Quote file exceeds the maximum allowed size.")
    handle = tempfile.NamedTemporaryFile(prefix="quoteiq_", suffix=".xlsx", delete=False)
    try:
        handle.write(data)
    finally:
        handle.close()
    return Path(handle.name)


@app.post("/api/output/csv")
def export_csv(payload: CsvExportRequest) -> Response:
    csv_bytes = render_csv_bytes(rows_from_results(payload.results))
    return _csv_response(csv_bytes)


@app.post("/api/quote/process")
def process_quote(
    file: UploadFile = File(...),
    use_ai: bool = Form(False),
    matcher: ProductMatcher = Depends(get_matcher),
    service: AIMatchingService = Depends(get_ai_service),
) -> Response:
    csv_bytes = _process_upload_csv(file, use_ai, matcher, service)
    return _csv_response(csv_bytes)


@app.post("/api/quote/process/results")
def process_quote_results_endpoint(
    file: UploadFile = File(...),
    use_ai: bool = Form(False),
    matcher: ProductMatcher = Depends(get_matcher),
    service: AIMatchingService = Depends(get_ai_service),
) -> dict:
    results = _process_upload_results(file, use_ai, matcher, service)
    payload = [serialize_process_result(item) for item in results]
    return {"summary": summarize_results(payload), "results": payload}


def _process_upload_results(
    upload: UploadFile,
    use_ai: bool,
    matcher: ProductMatcher,
    service: AIMatchingService,
):
    temp_path = _store_upload(upload)
    try:
        return process_quote_results(
            temp_path,
            matcher,
            use_ai=use_ai,
            ai_service=service if use_ai else None,
            source_name="quote.xlsx",
        )
    except QuoteParseError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except AINotConfiguredError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    finally:
        temp_path.unlink(missing_ok=True)


def _process_upload_csv(
    upload: UploadFile,
    use_ai: bool,
    matcher: ProductMatcher,
    service: AIMatchingService,
) -> bytes:
    results = _process_upload_results(upload, use_ai, matcher, service)
    return render_csv_bytes(rows_from_results(results))


