"""Temporary end-to-end match latency instrumentation. No behavior changes."""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any


def _ms(seconds: float) -> float:
    return round(seconds * 1000.0, 3)


def _pool_snapshot(engine: object) -> str:
    pool = getattr(engine, "pool", None)
    if pool is None:
        return "no-pool"
    bits = [type(pool).__name__]
    for name in ("size", "checkedin", "checkedout", "overflow", "timeout"):
        attr = getattr(pool, name, None)
        if callable(attr):
            try:
                bits.append(f"{name}={attr()}")
            except Exception:
                continue
        elif attr is not None and name == "timeout":
            bits.append(f"{name}={attr}")
    overflow_max = getattr(pool, "_max_overflow", None)
    if overflow_max is not None:
        bits.append(f"max_overflow={overflow_max}")
    return " ".join(bits)


@dataclass
class LineTiming:
    line_number: int
    source_row: int | None
    description: str
    candidate_count: int = 0
    normalize_ms: float = 0.0
    db_connect_ms: float = 0.0
    db_query_ms: float = 0.0
    db_map_ms: float = 0.0
    db_inspect_ms: float = 0.0
    scoring_ms: float = 0.0
    score_prep_ms: float = 0.0
    score_exact_ms: float = 0.0
    score_token_ms: float = 0.0
    score_fuzzy_ms: float = 0.0
    score_attr_ms: float = 0.0
    score_ident_ms: float = 0.0
    score_units_ms: float = 0.0
    score_agg_ms: float = 0.0
    score_fields_ms: float = 0.0
    score_loop_ms: float = 0.0
    decision_ms: float = 0.0
    serialize_ms: float = 0.0
    total_ms: float = 0.0
    sql_queries: int = 0
    inspect_calls: int = 0
    connect_calls: int = 0
    fuzzy_calls: int = 0
    score_pair_calls: int = 0
    searches: list[str] = field(default_factory=list)

    @property
    def db_ms(self) -> float:
        return round(self.db_connect_ms + self.db_query_ms + self.db_map_ms + self.db_inspect_ms, 3)


@dataclass
class TimingSession:
    request_label: str
    started: float = field(default_factory=perf_counter)
    parse_ms: float = 0.0
    extract_ms: float = 0.0
    serialize_ms: float = 0.0
    lines: list[LineTiming] = field(default_factory=list)
    engine_creates: int = 0
    engine_ids: list[int] = field(default_factory=list)
    pool_status: list[str] = field(default_factory=list)
    load_products_calls: int = 0
    candidate_cache_hits: int = 0
    candidate_cache_misses: int = 0
    database_candidate_queries: int = 0
    notes: list[str] = field(default_factory=list)
    current: LineTiming | None = None

    def start_line(self, line_number: int, source_row: int | None, description: str) -> LineTiming:
        line = LineTiming(line_number=line_number, source_row=source_row, description=description)
        self.current = line
        self.lines.append(line)
        return line

    def add(self, **kwargs: float | int | str) -> None:
        line = self.current
        if line is None:
            return
        for key, value in kwargs.items():
            if key == "search":
                line.searches.append(str(value))
                continue
            current = getattr(line, key)
            if isinstance(current, (int, float)) and isinstance(value, (int, float)):
                setattr(line, key, current + value)

    def set_line(self, **kwargs: object) -> None:
        line = self.current
        if line is None:
            return
        for key, value in kwargs.items():
            setattr(line, key, value)

    def note_engine(self, engine: object, *, created: bool) -> None:
        engine_id = id(engine)
        if created:
            self.engine_creates += 1
        if engine_id not in self.engine_ids:
            self.engine_ids.append(engine_id)
        snapshot = _pool_snapshot(engine)
        self.pool_status.append(("created " if created else "reused ") + snapshot)
        ping = getattr(getattr(engine, "pool", None), "_pre_ping", None)
        dialect = getattr(getattr(engine, "dialect", None), "name", "?")
        self.notes.append(
            f"engine_id={engine_id} dialect={dialect} created={created} "
            f"pool_pre_ping={ping} {snapshot}"
        )

    def report(self) -> str:
        total_ms = _ms(perf_counter() - self.started)
        chunks = [
            f"REQUEST {self.request_label}",
            f"parse_excel_ms={self.parse_ms:.3f}",
            f"quote_line_extract_ms={self.extract_ms:.3f}",
            f"serialize_ms={self.serialize_ms:.3f}",
            f"engine_creates={self.engine_creates}",
            f"engine_ids={self.engine_ids}",
            f"pool_status={self.pool_status}",
            f"load_products_calls={self.load_products_calls}",
            f"candidate_cache_hits={self.candidate_cache_hits}",
            f"candidate_cache_misses={self.candidate_cache_misses}",
            f"database_candidate_queries={self.database_candidate_queries}",
        ]
        if self.notes:
            chunks.append("notes=" + " | ".join(self.notes))
        for line in self.lines:
            chunks.append("")
            chunks.append(f"Line {line.line_number}:")
            chunks.append(f"  input: {line.description}")
            chunks.append(f"  source_row: {line.source_row}")
            chunks.append(f"  DB retrieval: {line.db_ms:.3f} ms")
            chunks.append(f"    connect: {line.db_connect_ms:.3f} ms ({line.connect_calls} checkouts)")
            chunks.append(f"    query: {line.db_query_ms:.3f} ms ({line.sql_queries} SQL)")
            chunks.append(f"    inspect/schema: {line.db_inspect_ms:.3f} ms ({line.inspect_calls} inspect)")
            chunks.append(f"    map rows: {line.db_map_ms:.3f} ms")
            chunks.append(f"  Candidates: {line.candidate_count}")
            chunks.append(f"  Normalization: {line.normalize_ms:.3f} ms")
            chunks.append(
                f"  Scoring: {line.scoring_ms:.3f} ms (fuzzy={line.fuzzy_calls}, score_pair={line.score_pair_calls})"
            )
            chunks.append(f"    prep/tokenize/normalize: {line.score_prep_ms:.3f} ms")
            chunks.append(f"    exact: {line.score_exact_ms:.3f} ms")
            chunks.append(f"    token: {line.score_token_ms:.3f} ms")
            chunks.append(f"    fuzzy: {line.score_fuzzy_ms:.3f} ms")
            chunks.append(f"    attributes: {line.score_attr_ms:.3f} ms")
            chunks.append(f"    productcode ident: {line.score_ident_ms:.3f} ms")
            chunks.append(f"    numeric/units: {line.score_units_ms:.3f} ms")
            chunks.append(f"    aggregation: {line.score_agg_ms:.3f} ms")
            chunks.append(f"    score_product_fields: {line.score_fields_ms:.3f} ms")
            chunks.append(f"    candidate loop (reasons/objects): {line.score_loop_ms:.3f} ms")
            chunks.append(f"  Decision: {line.decision_ms:.3f} ms")
            chunks.append(f"  Total: {line.total_ms:.3f} ms")
            if line.searches:
                chunks.append(f"  searches: {', '.join(line.searches)}")
        chunks.append("")
        chunks.append(f"Total request: {total_ms:,.3f} ms")
        return "\n".join(chunks)


_SESSION: ContextVar[TimingSession | None] = ContextVar("quoteiq_timing", default=None)
ENABLED = False


def should_time() -> bool:
    if ENABLED:
        return True
    import os

    return os.environ.get("QUOTEIQ_TIMING", "").strip() in {"1", "true", "TRUE", "yes"}


def enable() -> None:
    global ENABLED
    ENABLED = True


def disable() -> None:
    global ENABLED
    ENABLED = False


def active() -> TimingSession | None:
    if not should_time():
        return None
    return _SESSION.get()


def begin(label: str) -> TimingSession:
    enable()
    session = TimingSession(request_label=label)
    _SESSION.set(session)
    return session


def end() -> TimingSession | None:
    session = _SESSION.get()
    _SESSION.set(None)
    return session


def write_report(session: TimingSession | None, path: str | None = None) -> str:
    if session is None:
        return ""
    text = session.report()
    print(text, flush=True)
    from pathlib import Path

    dest = Path(path) if path else Path(__file__).resolve().parents[2] / "timing_last.txt"
    existing = dest.read_text(encoding="utf-8") if dest.is_file() else ""
    dest.write_text(existing + "\n\n" + text if existing else text, encoding="utf-8")
    return text


class span:
    def __init__(self, field: str, *, on_session: bool = False) -> None:
        self.field = field
        self.on_session = on_session
        self._start = 0.0

    def __enter__(self) -> None:
        self._start = perf_counter()

    def __exit__(self, *_exc: Any) -> None:
        session = active()
        if session is None:
            return
        elapsed = _ms(perf_counter() - self._start)
        if self.on_session or session.current is None:
            setattr(session, self.field, getattr(session, self.field, 0.0) + elapsed)
            return
        if hasattr(session.current, self.field):
            session.add(**{self.field: elapsed})
        elif hasattr(session, self.field):
            setattr(session, self.field, getattr(session, self.field) + elapsed)
