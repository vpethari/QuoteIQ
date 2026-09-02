from __future__ import annotations

import dataclasses
from collections import Counter, defaultdict
from collections.abc import Sequence
from contextlib import nullcontext

from matching.explanations import build_candidate_reasons, build_result_reasons
from matching.models import (
    MatchCandidate,
    MatchingConfig,
    MatchResult,
    MatchStatus,
    ProductRecord,
    QuoteLine,
)
from matching.normalizer import (
    canonical_text,
    fold_whitespace,
    looks_like_part_number,
    normalize_part_number,
    part_number_lookup_keys,
)
from matching.category_defaults import normalize_strut_catalog_codes
from matching.request_text import InterpretedRequest, interpret_customer_text
from matching.description_normalize import (
    ABBREV_REASON,
    abbreviation_evidence,
    catalog_description_blob,
    description_retrieval_hit,
    expand_query_for_retrieval,
)
from matching.noise import prepare_product_search_text, strip_quantity_and_noise
from matching.request_cache import (
    candidate_cache_key,
    end_request_cache,
    get_request_cache,
    start_request_cache,
)
from matching.scoring_prep import prepare_scoring_text
from matching.productcode import (
    EXACT_IDENTITY_TYPES,
    IDENTITY_MATCH_TYPES,
    identifier_retrieval_hit,
    is_product_code_query,
    productcode_as_text,
)
from matching.confidence import (
    cap_confidence_for_decision,
    competing_productcode_candidates,
    decide_match_status as decide_confidence_status,
)
from matching.selection import prepare_published_result
from matching.scoring import (
    calculate_score_gap,
    catalog_text_fields,
    clamp_score,
    descriptions_compatible,
    descriptions_conflict,
    score_pair,
    score_product_fields,
    variant_conflict,
)
from matching.timing_diag import _ms, active, span
from time import perf_counter

PN_PRODUCTCODE_EXACT = "Exact Productcode match"
PN_PRODUCTCODE_NORMALIZED = "Normalized Productcode match"
PN_PRODUCTCODE_NA1 = "Productcode match with NA1 prefix equivalence"
PN_SALSIFY_EXACT = "Exact Salsify ID match"
PN_CATALOG_EXACT = "Exact Atkore part number match"
PN_EXACT_COMPATIBLE = "Exact Atkore part number match and compatible product description."
PN_EXACT_CONFLICT = (
    "Exact part number found, but the requested description conflicts with the "
    "catalog description. Review required."
)
DESC_UNIQUE = "Description matched a unique Atkore catalog product."
DESC_AMBIGUOUS = (
    "Description matched multiple Atkore catalog products. A part number or "
    "additional product attributes are required."
)
PN_NOT_FOUND = (
    "Requested part number was not found in the Atkore catalog. Description candidates require review."
)


def _catalog_connection_scope(catalog_search: object | None):
    """One pooled connection for all searches made while matching one line,
    when the catalog search backend supports it (e.g. real Postgres, not the
    in-memory fallback or a test double)."""
    scope = getattr(catalog_search, "connection_scope", None)
    if scope is None:
        return nullcontext()
    return scope()


class ProductMatcher:
    """Deterministic catalog matcher. Family records are never candidates."""

    def __init__(
        self,
        products: Sequence[ProductRecord],
        config: MatchingConfig | None = None,
        *,
        catalog_search: object | None = None,
    ) -> None:
        self.config = config or MatchingConfig()
        self.catalog_search = catalog_search
        self.products = [
            product
            for product in products
            if product.record_type == "product" and product.product_code
        ]
        self._description_counts: Counter[str] = Counter(
            canonical_text(product.description)
            for product in self.products
            if product.description
        )
        self._by_identifier: dict[str, list[ProductRecord]] = defaultdict(list)
        self._by_salsify: dict[str, list[ProductRecord]] = defaultdict(list)
        self._by_official: dict[str, list[ProductRecord]] = defaultdict(list)
        for product in self.products:
            for key in part_number_lookup_keys(product.product_code):
                self._by_identifier[key].append(product)
            if looks_like_part_number(product.name) and (
                normalize_part_number(product.name) != normalize_part_number(product.product_code)
            ):
                for key in part_number_lookup_keys(product.name):
                    if product not in self._by_identifier[key]:
                        self._by_identifier[key].append(product)
            salsify_key = normalize_part_number(product.salsify_id)
            official_key = normalize_part_number(product.official_part_number)
            if salsify_key:
                self._by_salsify[salsify_key].append(product)
            if official_key:
                self._by_official[official_key].append(product)
        identifier_keys = tuple(self._by_identifier)
        self._identifier_keys = identifier_keys
        self._salsify_keys = tuple(self._by_salsify)
        self._official_and_identifier_keys = tuple(self._by_official) + identifier_keys

    def match_line(self, line: QuoteLine) -> MatchResult:
        requested_description = productcode_as_text(line.requested_description) or fold_whitespace(
            line.requested_description
        )
        requested_part_number = productcode_as_text(line.requested_part_number) or None
        session = active()
        started = perf_counter()
        if session is not None:
            session.start_line(
                line_number=len(session.lines) + 1,
                source_row=line.source_row,
                description=requested_description,
            )
        with span("normalize_ms"):
            interpreted = interpret_customer_text(
                normalize_strut_catalog_codes(requested_description),
                explicit_part_number=requested_part_number,
                salsify_keys=self._salsify_keys,
                official_keys=self._official_and_identifier_keys,
            )
        quantity = line.quantity if line.quantity is not None else interpreted.quantity_from_text
        with _catalog_connection_scope(self.catalog_search):
            result = self._match_interpreted(
                raw_description=requested_description,
                interpreted=interpreted,
                quantity=quantity,
                source_file=line.source_file,
                source_sheet=line.source_sheet,
                source_row=line.source_row,
            )
            result = self._attach_identity(result, requested_description, interpreted)
        published = prepare_published_result(result, self.config)
        if session is not None and session.current is not None:
            session.current.total_ms = _ms(perf_counter() - started)
            if session.current.candidate_count == 0:
                session.current.candidate_count = published.candidate_count
        return published

    def match_quote(self, lines: Sequence[QuoteLine]) -> list[MatchResult]:
        cache = start_request_cache()
        try:
            return [self.match_line(line) for line in lines]
        finally:
            session = active()
            finished = end_request_cache()
            if session is not None and finished is not None:
                session.candidate_cache_hits = finished.hits
                session.candidate_cache_misses = finished.misses
                session.database_candidate_queries = finished.database_candidate_queries
                session.notes.append(
                    f"candidate_cache_hits={finished.hits} "
                    f"candidate_cache_misses={finished.misses} "
                    f"database_candidate_queries={finished.database_candidate_queries}"
                )

    def match_description(
        self,
        requested_description: str,
        quantity: int | float | None = None,
        source_file: str | None = None,
        source_sheet: str | None = None,
        source_row: int | None = None,
    ) -> MatchResult:
        session = active()
        started = perf_counter()
        if session is not None:
            session.start_line(1, source_row, requested_description)
        with span("normalize_ms"):
            interpreted = interpret_customer_text(
                normalize_strut_catalog_codes(requested_description),
                salsify_keys=self._salsify_keys,
                official_keys=self._official_and_identifier_keys,
            )
        resolved_qty = quantity if quantity is not None else interpreted.quantity_from_text
        with _catalog_connection_scope(self.catalog_search):
            result = self._match_interpreted(
                raw_description=requested_description,
                interpreted=interpreted,
                quantity=resolved_qty,
                source_file=source_file,
                source_sheet=source_sheet,
                source_row=source_row,
            )
            result = self._attach_identity(result, requested_description, interpreted)
        published = prepare_published_result(result, self.config)
        if session is not None and session.current is not None:
            session.current.total_ms = _ms(perf_counter() - started)
            if session.current.candidate_count == 0:
                session.current.candidate_count = published.candidate_count
        return published

    def _match_interpreted(
        self,
        *,
        raw_description: str,
        interpreted: InterpretedRequest,
        quantity: int | float | None,
        source_file: str | None,
        source_sheet: str | None,
        source_row: int | None,
    ) -> MatchResult:
        product = None
        source = None
        for identifier in interpreted.lookup_identifiers:
            product, source = self._lookup_product_by_identifier(identifier)
            if product is not None and source in {"salsify", "catalog", "productcode"}:
                break
            if source == "ambiguous":
                break

        display_pn = interpreted.lookup_identifiers[0] if interpreted.lookup_identifiers else None
        scoring_description = interpreted.description_text if interpreted.has_description else ""

        if product is not None and source in {"salsify", "catalog", "productcode"}:
            return self._exact_part_number_result(
                product=product,
                requested_description=raw_description,
                requested_part_number=display_pn or product.official_part_number or "",
                quantity=quantity,
                source_file=source_file,
                source_sheet=source_sheet,
                source_row=source_row,
                match_source=source,
                description_for_scoring=scoring_description,
            )
        if source == "ambiguous":
            return self._match_description_only(
                requested_description=raw_description,
                quantity=quantity,
                source_file=source_file,
                source_sheet=source_sheet,
                source_row=source_row,
                requested_part_number=display_pn,
                part_number_match_score=0.0 if interpreted.has_identifier else None,
                description_for_scoring=scoring_description,
                extra_reasons=[
                    "Multiple catalog products share this part number. Review required.",
                    PN_NOT_FOUND,
                ],
                force_review=True,
                has_description_signal=interpreted.has_description,
            )
        if interpreted.has_identifier:
            extras = [PN_NOT_FOUND]
            if interpreted.has_description:
                return self._match_description_only(
                    requested_description=raw_description,
                    quantity=quantity,
                    source_file=source_file,
                    source_sheet=source_sheet,
                    source_row=source_row,
                    requested_part_number=display_pn,
                    part_number_match_score=0.0,
                    description_for_scoring=scoring_description,
                    extra_reasons=extras,
                    force_review=True,
                    has_description_signal=True,
                )
            return self._empty_result(
                requested_description=raw_description,
                quantity=quantity,
                source_file=source_file,
                source_sheet=source_sheet,
                source_row=source_row,
                requested_part_number=display_pn,
                part_number_match_score=0.0,
                description_match_score=None,
                reasons=extras,
            )
        if interpreted.has_description:
            return self._match_description_only(
                requested_description=raw_description,
                quantity=quantity,
                source_file=source_file,
                source_sheet=source_sheet,
                source_row=source_row,
                requested_part_number=None,
                description_for_scoring=scoring_description,
                has_description_signal=True,
            )
        return self._empty_result(
            requested_description=raw_description,
            quantity=quantity,
            source_file=source_file,
            source_sheet=source_sheet,
            source_row=source_row,
            requested_part_number=None,
            part_number_match_score=None,
            description_match_score=None,
            reasons=["No identifier or description candidate could be found."],
        )

    def _attach_abbrev_evidence(
        self,
        query: str,
        product: ProductRecord,
        identifier_evidence: dict[str, object] | None,
        field_scores: dict[str, float],
    ) -> dict[str, object]:
        evidence = dict(identifier_evidence or {})
        if float(field_scores.get("productcode") or 0.0) >= 40.0:
            return evidence
        terms = abbreviation_evidence(query, catalog_description_blob(product))
        if not terms:
            terms = abbreviation_evidence(query, product.description or product.name or "")
        if terms:
            evidence["normalized_terms"] = terms
            evidence["abbrev_reason"] = ABBREV_REASON
        return evidence

    def _cached_lookup_productcode(
        self, identifier: str, limit: int | None = None
    ) -> list[ProductRecord]:
        cap = self.config.retrieval_candidate_limit if limit is None else limit
        cache = get_request_cache()
        key = f"lookup:{cap}:{candidate_cache_key(identifier)}"
        if cache is not None and key in cache.lookups:
            return list(cache.lookups[key])
        found = list(self.catalog_search.lookup_productcode(identifier, limit=cap))
        if cache is not None:
            cache.lookups[key] = tuple(found)
        return found

    def _products_for_query(self, query: str) -> Sequence[ProductRecord]:
        query = strip_quantity_and_noise(query)
        cache = get_request_cache()
        key = candidate_cache_key(query)
        if cache is not None and key in cache.candidates:
            cache.record_hit()
            return list(cache.candidates[key])
        if cache is not None:
            cache.record_miss()
        if self.catalog_search is not None:
            limit = self.config.retrieval_candidate_limit
            if cache is not None:
                cache.record_database_query()
            if is_product_code_query(query):
                lookups = self._cached_lookup_productcode(query, limit)
                if lookups:
                    products = list(lookups)
                    if cache is not None:
                        cache.candidates[key] = tuple(products)
                    return products
                hits = self.catalog_search.fetch_identifier_candidates(query, limit=limit)
                if hits:
                    products = list(hits)
                    if cache is not None:
                        cache.candidates[key] = tuple(products)
                    return products
            text_limit = self.config.search_text_candidate_limit
            text_hits = self.catalog_search.search_text_candidates(query, limit=text_limit)
            if text_hits:
                products = list(text_hits)
                if cache is not None:
                    cache.candidates[key] = tuple(products)
                return products
            lookups = self._cached_lookup_productcode(query, limit)
            products = list(lookups)
            if cache is not None:
                cache.candidates[key] = tuple(products)
            return products
        if is_product_code_query(query):
            hits = [product for product in self.products if identifier_retrieval_hit(query, product)]
            if hits:
                products = hits
            else:
                products = [
                    product for product in self.products if description_retrieval_hit(query, product)
                ]
        else:
            description_hits = [
                product for product in self.products if description_retrieval_hit(query, product)
            ]
            products = description_hits if description_hits else list(self.products)
        if cache is not None:
            cache.candidates[key] = tuple(products)
        return products

    def _score_description_candidates(self, requested_description: str) -> list[MatchCandidate]:
        cache = get_request_cache()
        key = candidate_cache_key(requested_description)
        if cache is not None and key in cache.scored:
            cache.record_hit()
            return list(cache.scored[key])
        scored: list[MatchCandidate] = []
        query = expand_query_for_retrieval(strip_quantity_and_noise(requested_description))
        pool = list(self._products_for_query(query))
        session = active()
        if session is not None:
            session.set_line(candidate_count=len(pool))
        description_counts = self._description_counts
        prep_cache = cache.prepared_text if cache is not None else {}
        if self.catalog_search is not None:
            description_counts = Counter(
                prepare_scoring_text(product.description, prep_cache).canonical
                for product in pool
                if product.description
            )
        query_prep = prepare_scoring_text(query, prep_cache)
        score_started = perf_counter()
        for product in pool:
            field_started = perf_counter() if session is not None else None
            breakdown, field_scores, matched_field, identifier_evidence = score_product_fields(
                query,
                product,
                self.config,
                prep_cache=prep_cache,
                query_prep=query_prep,
            )
            if session is not None and field_started is not None:
                session.add(score_fields_ms=_ms(perf_counter() - field_started))
            loop_started = perf_counter() if session is not None else None
            identifier_hit = (identifier_evidence or {}).get("match_type") in IDENTITY_MATCH_TYPES
            if not identifier_hit and variant_conflict(query, catalog_description_blob(product)):
                breakdown = dataclasses.replace(
                    breakdown, final=min(breakdown.final, self.config.description_conflict_max)
                )
            if breakdown.final < self.config.candidate_floor and not identifier_hit:
                continue
            identifier_evidence = self._attach_abbrev_evidence(
                query, product, identifier_evidence, field_scores
            )
            duplicate = bool(
                product.description
                and description_counts[prepare_scoring_text(product.description, prep_cache).canonical] > 1
            )
            candidate = MatchCandidate(
                official_part_number=product.product_code,
                description=product.description or product.name or "",
                salsify_id=product.salsify_id or product.product_code,
                score=breakdown.final,
                score_percentage=breakdown.final,
                match_reasons=build_candidate_reasons(
                    query,
                    product,
                    breakdown,
                    duplicate_description=duplicate,
                    field_scores=field_scores,
                    matched_field=matched_field,
                    identifier_evidence=identifier_evidence,
                    prep_cache=prep_cache,
                    query_prep=query_prep,
                ),
                breakdown=breakdown,
                field_scores=field_scores,
                matched_field=matched_field,
                identifier_evidence=identifier_evidence,
                name=product.name,
                description2=product.description2,
            )
            scored.append(candidate)
            if session is not None and loop_started is not None:
                session.add(score_loop_ms=_ms(perf_counter() - loop_started))
        if session is not None:
            session.add(scoring_ms=_ms(perf_counter() - score_started))
        scored.sort(
            key=lambda item: (
                0 if (item.identifier_evidence or {}).get("match_type") in IDENTITY_MATCH_TYPES else 1,
                -item.score,
                item.official_part_number,
                item.salsify_id,
            )
        )
        if cache is not None:
            cache.scored[key] = tuple(scored)
        return scored

    def _candidate_from_product(
        self,
        requested_description: str,
        product: ProductRecord,
        breakdown,
        *,
        extra_reasons: list[str] | None = None,
        field_scores: dict[str, float] | None = None,
        matched_field: str | None = None,
        identifier_evidence: dict[str, object] | None = None,
    ) -> MatchCandidate:
        duplicate = bool(
            product.description
            and self._description_counts[canonical_text(product.description)] > 1
        )
        identifier_evidence = self._attach_abbrev_evidence(
            requested_description, product, identifier_evidence, field_scores or {}
        )
        reasons = build_candidate_reasons(
            requested_description,
            product,
            breakdown,
            duplicate_description=duplicate,
            field_scores=field_scores,
            matched_field=matched_field,
            identifier_evidence=identifier_evidence,
        )
        if extra_reasons:
            reasons = list(dict.fromkeys([*extra_reasons, *reasons]))
        return MatchCandidate(
            official_part_number=product.product_code,
            description=product.description or product.name or "",
            salsify_id=product.salsify_id or product.product_code,
            score=breakdown.final,
            score_percentage=breakdown.final,
            match_reasons=reasons,
            breakdown=breakdown,
            field_scores=field_scores or {},
            matched_field=matched_field,
            identifier_evidence=identifier_evidence or {},
            name=product.name,
            description2=product.description2,
        )

    def _match_description_only(
        self,
        *,
        requested_description: str,
        quantity: int | float | None,
        source_file: str | None,
        source_sheet: str | None,
        source_row: int | None,
        requested_part_number: str | None,
        part_number_match_score: float | None = None,
        extra_reasons: list[str] | None = None,
        force_review: bool = False,
        description_for_scoring: str | None = None,
        has_description_signal: bool = True,
    ) -> MatchResult:
        query = description_for_scoring if description_for_scoring is not None else requested_description
        scored = self._score_description_candidates(query) if fold_whitespace(query) else []
        decision_started = perf_counter()
        candidates = scored[: self.config.max_candidates]
        scores = [item.score for item in scored]
        top_score, second_score, score_gap = calculate_score_gap(scores)
        top_score = clamp_score(top_score)

        exact_group = [
            item
            for item in scored
            if item.breakdown is not None and item.breakdown.exact >= 100.0
        ]
        identifier_exact = [
            item
            for item in scored
            if (item.identifier_evidence or {}).get("match_type") in EXACT_IDENTITY_TYPES
        ]
        duplicate_top = False
        if candidates:
            top_canon = canonical_text(candidates[0].description)
            same_desc = [
                item for item in scored if canonical_text(item.description) == top_canon
            ]
            duplicate_top = len(same_desc) > 1 and abs(
                same_desc[0].score - same_desc[-1].score
            ) <= self.config.score_tie_epsilon

        identifier_led = bool(
            candidates
            and (candidates[0].identifier_evidence or {}).get("match_type") in IDENTITY_MATCH_TYPES
        )
        ident_type = str((candidates[0].identifier_evidence or {}).get("match_type") or "none") if candidates else "none"
        ident_source = (candidates[0].identifier_evidence or {}).get("source_field") if candidates else None
        ident_exact = ident_type in EXACT_IDENTITY_TYPES and ident_source in {"productcode", "name"}
        competing_productcodes = competing_productcode_candidates(list(candidates)) or bool(
            identifier_led
            and ident_source in {"productcode", "name"}
            and len(candidates) >= 2
            and second_score is not None
            and (score_gap is None or score_gap < self.config.min_score_gap)
            and candidates[0].official_part_number != candidates[1].official_part_number
        )
        exact_unique = (
            (len(exact_group) == 1 or (len(identifier_exact) == 1 and ident_exact))
            and not competing_productcodes
        )
        numeric_conflict = bool(
            candidates and (candidates[0].identifier_evidence or {}).get("numeric_conflict")
        )
        status = decide_match_status(
            top_score=top_score,
            second_score=second_score,
            score_gap=score_gap,
            exact_unique=exact_unique,
            duplicate_top=duplicate_top,
            candidate_count=len(candidates),
            config=self.config,
            ident_type=ident_type,
            competing_productcodes=competing_productcodes,
            numeric_conflict=numeric_conflict,
        )
        if ident_type == "partial" and status in {MatchStatus.EXACT_MATCH, MatchStatus.HIGH_CONFIDENCE}:
            status = MatchStatus.REVIEW_REQUIRED
        if status == MatchStatus.NO_MATCH and identifier_led:
            status = MatchStatus.REVIEW_REQUIRED
        if force_review and status != MatchStatus.NO_MATCH:
            status = MatchStatus.REVIEW_REQUIRED
        if competing_productcodes and status != MatchStatus.NO_MATCH:
            status = MatchStatus.REVIEW_REQUIRED

        matched_part = matched_description = matched_salsify = None
        winner_scores: dict[str, float] = dict(candidates[0].field_scores) if candidates else {}
        if status in {MatchStatus.EXACT_MATCH, MatchStatus.HIGH_CONFIDENCE} and candidates:
            winner = candidates[0]
            matched_part = winner.official_part_number
            matched_description = winner.description
            matched_salsify = winner.salsify_id

        matching_percentage = top_score if candidates else 0.0
        if status == MatchStatus.NO_MATCH:
            matched_part = matched_description = matched_salsify = None

        result_reasons = build_result_reasons(
            match_status=status.value,
            exact_unique=exact_unique,
            duplicate_top=duplicate_top,
            top_score=top_score,
            score_gap=score_gap,
            min_score_gap=self.config.min_score_gap,
            min_match_threshold=self.config.min_match_threshold,
            candidate_count=len(candidates),
        )
        if competing_productcodes:
            result_reasons.insert(0, "Multiple possible Productcode candidates")
            result_reasons.insert(0, "Multiple possible Productcode matches")
        elif status in {MatchStatus.EXACT_MATCH, MatchStatus.HIGH_CONFIDENCE}:
            result_reasons.insert(0, DESC_UNIQUE)
        elif status == MatchStatus.REVIEW_REQUIRED and duplicate_top:
            result_reasons.insert(0, DESC_AMBIGUOUS)
        if extra_reasons:
            result_reasons = list(dict.fromkeys([*extra_reasons, *result_reasons]))
        if candidates:
            result_reasons.extend(candidates[0].match_reasons[:4])
            result_reasons = list(dict.fromkeys(result_reasons))
            evidence = candidates[0].identifier_evidence or {}
            productcode_score = float((candidates[0].field_scores or {}).get("productcode") or 0.0)
            if competing_productcodes:
                result_reasons.insert(0, "Multiple possible Productcode matches")
            elif evidence.get("match_type") == "partial" and productcode_score > 0:
                result_reasons.insert(0, str(evidence.get("headline") or "Partial Productcode / Name Match"))
                tokens = evidence.get("matching_tokens") or []
                if tokens:
                    result_reasons.insert(1, "Matching tokens: " + ", ".join(str(item) for item in tokens))
            elif evidence.get("match_type") in EXACT_IDENTITY_TYPES and productcode_score > 0:
                result_reasons.insert(0, str(evidence.get("headline") or "Exact Productcode Match"))
            result_reasons = list(dict.fromkeys(result_reasons))

        description_score = matching_percentage if has_description_signal else None
        description_match = bool(
            has_description_signal
            and candidates
            and not ident_exact
            and (
                (candidates[0].breakdown is not None and candidates[0].breakdown.exact >= 100.0)
                or (
                    float((candidates[0].field_scores or {}).get("description") or 0.0) >= 70.0
                    and not identifier_led
                )
            )
        )
        overall = matching_percentage
        if part_number_match_score is not None:
            overall = self._combined_overall(part_number_match_score, description_score)
        overall = cap_confidence_for_decision(
            overall,
            status=status,
            competing=competing_productcodes,
            config=self.config,
        )
        if status == MatchStatus.NO_MATCH and not candidates:
            overall = 0.0

        breakdown_payload = self._breakdown_dict(
            winner_scores,
            overall,
            "; ".join(result_reasons[:3]) if result_reasons else "",
            identifier_evidence=candidates[0].identifier_evidence if candidates else None,
        )

        result = MatchResult(
            source_file=source_file,
            source_sheet=source_sheet,
            source_row=source_row,
            requested_description=requested_description,
            quantity=quantity,
            matched_part_number=matched_part,
            matched_description=matched_description,
            matched_salsify_id=matched_salsify,
            matching_percentage=overall,
            confidence_level=status.value,
            match_status=status,
            candidate_count=len(candidates),
            candidates=candidates,
            match_reasons=result_reasons,
            top_score=top_score,
            second_score=second_score,
            score_gap=score_gap,
            requested_part_number=requested_part_number,
            part_number_match_score=100.0 if ident_exact else part_number_match_score,
            description_match_score=description_score,
            overall_match_score=overall,
            part_number_match=bool(ident_exact),
            description_match=description_match,
            match_breakdown=breakdown_payload,
        )
        session = active()
        if session is not None:
            session.add(decision_ms=_ms(perf_counter() - decision_started))
        return result

    def _lookup_product_by_identifier(
        self, requested_part_number: str
    ) -> tuple[ProductRecord | None, str | None]:
        seen: list[ProductRecord] = []
        for key in part_number_lookup_keys(requested_part_number):
            for product in self._by_identifier.get(key, []):
                if product not in seen:
                    seen.append(product)
        unique = list(dict.fromkeys(seen))
        if len(unique) == 1:
            return unique[0], "productcode"
        if len(unique) > 1:
            return None, "ambiguous"
        if self.catalog_search is not None:
            found = self._cached_lookup_productcode(requested_part_number, limit=20)
            unique = list(dict.fromkeys(found))
            if len(unique) == 1:
                return unique[0], "productcode"
            if len(unique) > 1:
                return None, "ambiguous"
        return None, None

    def _productcode_reason(self, identifier: str, product: ProductRecord) -> str:
        customer = normalize_part_number(identifier)
        salsify = normalize_part_number(product.salsify_id)
        official = normalize_part_number(product.official_part_number)
        if salsify and official and salsify != official:
            if customer == salsify:
                return PN_SALSIFY_EXACT
            if customer == official:
                return PN_CATALOG_EXACT
            if customer in part_number_lookup_keys(product.salsify_id):
                return PN_SALSIFY_EXACT
            return PN_CATALOG_EXACT
        stored = official or salsify
        if customer == stored:
            return PN_PRODUCTCODE_EXACT
        if customer in part_number_lookup_keys(product.product_code):
            customer_na1 = customer.startswith("NA1-")
            stored_na1 = stored.startswith("NA1-")
            if customer_na1 != stored_na1:
                return PN_PRODUCTCODE_NA1
            return PN_PRODUCTCODE_NORMALIZED
        return PN_PRODUCTCODE_NORMALIZED

    def _breakdown_dict(
        self,
        field_scores: dict[str, float] | None,
        overall: float,
        match_reason: str,
        identifier_evidence: dict[str, object] | None = None,
    ) -> dict[str, object]:
        scores = field_scores or {}
        evidence = identifier_evidence or {}
        payload: dict[str, object] = {
            "productcode_score": round(float(scores.get("productcode", 0.0)), 4),
            "name_score": round(float(scores.get("name", 0.0)), 4),
            "description_score": round(float(scores.get("description", 0.0)), 4),
            "description2_score": round(float(scores.get("description2", 0.0)), 4),
            "overall_score": round(float(overall or 0.0), 4),
            "match_reason": match_reason,
            "numeric_unit_score": round(float(evidence.get("numeric_unit_score") or 0.0), 4),
            "token_coverage_score": round(float(evidence.get("token_coverage_score") or 0.0), 4),
            "numeric_conflict": bool(evidence.get("numeric_conflict")),
            "productcode_match_type": evidence.get("match_type") or evidence.get("productcode_match_type") or "none",
            "similarity_score": round(float(evidence.get("similarity_score") or overall or 0.0), 4),
        }
        if evidence:
            payload["identifier_match_type"] = evidence.get("match_type") or ""
            payload["matching_tokens"] = list(evidence.get("matching_tokens") or [])
            payload["additional_catalog_tokens"] = list(evidence.get("additional_catalog_tokens") or [])
            payload["identifier_headline"] = evidence.get("headline") or ""
            if evidence.get("normalized_terms"):
                payload["normalized_terms"] = list(evidence.get("normalized_terms") or [])
                payload["abbrev_reason"] = evidence.get("abbrev_reason") or ABBREV_REASON
            if evidence.get("unit_evidence"):
                payload["unit_evidence"] = dict(evidence.get("unit_evidence") or {})
                payload["voltage_evidence"] = list(
                    (evidence.get("unit_evidence") or {}).get("lines") or []
                )
        return payload

    def _exact_part_number_result(
        self,
        *,
        product: ProductRecord,
        requested_description: str,
        requested_part_number: str,
        quantity: int | float | None,
        source_file: str | None,
        source_sheet: str | None,
        source_row: int | None,
        match_source: str,
        description_for_scoring: str = "",
    ) -> MatchResult:
        scoring_query = strip_quantity_and_noise(fold_whitespace(description_for_scoring))
        description_blank = not scoring_query
        with span("scoring_ms"):
            scoring_text = scoring_query or requested_part_number or requested_description
            req_cache = get_request_cache()
            prep_cache = req_cache.prepared_text if req_cache is not None else {}
            query_prep = prepare_scoring_text(scoring_text, prep_cache)
            field_breakdown, field_scores, matched_field, identifier_evidence = score_product_fields(
                scoring_text,
                product,
                self.config,
                prep_cache=prep_cache,
                query_prep=query_prep,
            )
            field_scores = {
                **field_scores,
                "productcode": 100.0,
            }
            if description_blank:
                compatible = True
                conflict = False
                description_score = None
                breakdown = field_breakdown
            else:
                text_targets = [
                    value
                    for key, value in catalog_text_fields(product).items()
                    if key != "productcode" and value
                ]
                if not text_targets:
                    text_targets = [product.product_code]
                best_target = text_targets[0]
                desc_prep = prepare_scoring_text(scoring_query, prep_cache)
                breakdown = score_pair(
                    scoring_query, best_target, self.config, prep_cache=prep_cache, query_prep=desc_prep
                )
                for target in text_targets[1:]:
                    candidate_breakdown = score_pair(
                        scoring_query, target, self.config, prep_cache=prep_cache, query_prep=desc_prep
                    )
                    if candidate_breakdown.final > breakdown.final:
                        breakdown = candidate_breakdown
                        best_target = target
                compatible = descriptions_compatible(
                    scoring_query, best_target, breakdown, self.config
                )
                conflict = descriptions_conflict(
                    scoring_query, best_target, breakdown, self.config
                )
                description_score = clamp_score(breakdown.final)
        identity_reason = self._productcode_reason(requested_part_number, product)
        if match_source == "salsify" and product.salsify_id != product.official_part_number:
            identity_reason = PN_SALSIFY_EXACT
        pn_candidate = self._candidate_from_product(
            scoring_query or requested_description,
            product,
            breakdown,
            extra_reasons=[identity_reason],
            field_scores=field_scores,
            matched_field=matched_field or "productcode",
            identifier_evidence=identifier_evidence,
        )
        pn_candidate.score = 100.0
        pn_candidate.score_percentage = 100.0
        description_candidates: list[MatchCandidate] = []
        if not description_blank:
            description_candidates = [
                item
                for item in self._score_description_candidates(scoring_query)
                if item.official_part_number != product.product_code
            ]
        decision_started = perf_counter()
        if conflict or not compatible:
            status = MatchStatus.REVIEW_REQUIRED
            matched_part = matched_description = matched_salsify = None
            overall = self._combined_overall(100.0, description_score)
            reasons = [PN_EXACT_CONFLICT]
            candidates = [pn_candidate, *description_candidates][: self.config.max_candidates]
        else:
            status = MatchStatus.EXACT_MATCH
            matched_part = product.product_code
            matched_description = product.description or product.name
            matched_salsify = product.salsify_id or product.product_code
            overall = self._combined_overall(100.0, description_score)
            if description_blank:
                reasons = [identity_reason]
            elif (product.salsify_id or "") != (product.official_part_number or ""):
                reasons = (
                    [PN_SALSIFY_EXACT]
                    if identity_reason == PN_SALSIFY_EXACT
                    else [PN_EXACT_COMPATIBLE]
                )
            else:
                reasons = [identity_reason, "Compatible name/description evidence"]
            candidates = [pn_candidate]

        scores = [item.score for item in candidates]
        top_score, second_score, score_gap = calculate_score_gap(scores)
        reasons = list(dict.fromkeys([*reasons, *pn_candidate.match_reasons[:4]]))
        result = MatchResult(
            source_file=source_file,
            source_sheet=source_sheet,
            source_row=source_row,
            requested_description=requested_description,
            quantity=quantity,
            matched_part_number=matched_part,
            matched_description=matched_description,
            matched_salsify_id=matched_salsify,
            matching_percentage=overall,
            confidence_level=status.value,
            match_status=status,
            candidate_count=len(candidates),
            candidates=candidates,
            match_reasons=reasons,
            top_score=top_score,
            second_score=second_score,
            score_gap=score_gap,
            requested_part_number=requested_part_number,
            part_number_match_score=100.0,
            description_match_score=description_score,
            overall_match_score=overall,
            part_number_match=True,
            description_match=bool(not description_blank and compatible and not conflict),
            match_breakdown=self._breakdown_dict(
                field_scores,
                overall,
                "; ".join(reasons[:3]),
                identifier_evidence=pn_candidate.identifier_evidence,
            ),
        )
        session = active()
        if session is not None:
            session.add(decision_ms=_ms(perf_counter() - decision_started))
            if session.current is not None and session.current.candidate_count == 0:
                session.current.candidate_count = 1
        return result

    def _combined_overall(
        self, part_number_score: float | None, description_score: float | None
    ) -> float:
        if part_number_score is None and description_score is None:
            return 0.0
        if part_number_score is None:
            return clamp_score(description_score or 0.0)
        if description_score is None:
            return clamp_score(part_number_score)
        return clamp_score(
            self.config.part_number_weight * part_number_score
            + self.config.description_weight * description_score
        )

    def _empty_result(
        self,
        *,
        requested_description: str,
        quantity: int | float | None,
        source_file: str | None,
        source_sheet: str | None,
        source_row: int | None,
        requested_part_number: str | None,
        part_number_match_score: float | None,
        description_match_score: float | None,
        reasons: list[str],
    ) -> MatchResult:
        return MatchResult(
            source_file=source_file,
            source_sheet=source_sheet,
            source_row=source_row,
            requested_description=requested_description,
            quantity=quantity,
            matched_part_number=None,
            matched_description=None,
            matched_salsify_id=None,
            matching_percentage=0.0,
            confidence_level=MatchStatus.NO_MATCH.value,
            match_status=MatchStatus.NO_MATCH,
            candidate_count=0,
            candidates=[],
            match_reasons=reasons,
            top_score=0.0,
            second_score=None,
            score_gap=None,
            requested_part_number=requested_part_number,
            part_number_match_score=part_number_match_score,
            description_match_score=description_match_score,
            overall_match_score=0.0,
            part_number_match=False,
            description_match=False,
            match_breakdown=self._breakdown_dict(None, 0.0, "; ".join(reasons[:3])),
        )

    def _attach_identity(
        self,
        result: MatchResult,
        raw_description: str,
        interpreted: InterpretedRequest,
    ) -> MatchResult:
        result.customer_raw_text = raw_description
        result.detected_salsify_id = (
            interpreted.extracted_salsify_ids[0] if interpreted.extracted_salsify_ids else None
        )
        result.detected_part_number = (
            interpreted.extracted_catalog_numbers[0] if interpreted.extracted_catalog_numbers else None
        )
        prep = prepare_product_search_text(raw_description)
        breakdown = dict(result.match_breakdown or {})
        breakdown["search_normalization"] = prep.as_debug_dict()
        result.match_breakdown = breakdown
        return result


def decide_match_status(
    *,
    top_score: float,
    second_score: float | None,
    score_gap: float | None,
    exact_unique: bool,
    duplicate_top: bool,
    candidate_count: int,
    config: MatchingConfig,
    ident_type: str = "none",
    competing_productcodes: bool = False,
    numeric_conflict: bool = False,
) -> MatchStatus:
    return decide_confidence_status(
        top_score=top_score,
        second_score=second_score,
        score_gap=score_gap,
        exact_unique=exact_unique,
        duplicate_top=duplicate_top,
        candidate_count=candidate_count,
        config=config,
        ident_type=ident_type,
        competing_productcodes=competing_productcodes,
        numeric_conflict=numeric_conflict,
    )


def match_quote(
    lines: Sequence[QuoteLine],
    products: Sequence[ProductRecord],
    config: MatchingConfig | None = None,
) -> list[MatchResult]:
    return ProductMatcher(products, config).match_quote(lines)
