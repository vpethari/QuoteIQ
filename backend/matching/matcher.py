from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Sequence

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
    normalize_part_number,
)
from matching.request_text import InterpretedRequest, interpret_customer_text
from matching.scoring import (
    calculate_score_gap,
    clamp_score,
    descriptions_compatible,
    descriptions_conflict,
    score_pair,
)

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


class ProductMatcher:
    """Deterministic catalog matcher. Family records are never candidates."""

    def __init__(
        self,
        products: Sequence[ProductRecord],
        config: MatchingConfig | None = None,
    ) -> None:
        self.config = config or MatchingConfig()
        self.products = [
            product
            for product in products
            if product.record_type == "product"
            and product.official_part_number
            and product.description
        ]
        self._description_counts: Counter[str] = Counter(
            canonical_text(product.description) for product in self.products
        )
        self._by_salsify: dict[str, list[ProductRecord]] = defaultdict(list)
        self._by_official: dict[str, list[ProductRecord]] = defaultdict(list)
        for product in self.products:
            salsify_key = normalize_part_number(product.salsify_id)
            official_key = normalize_part_number(product.official_part_number)
            if salsify_key:
                self._by_salsify[salsify_key].append(product)
            if official_key:
                self._by_official[official_key].append(product)

    def match_line(self, line: QuoteLine) -> MatchResult:
        interpreted = interpret_customer_text(
            line.requested_description,
            explicit_part_number=line.requested_part_number,
            salsify_keys=tuple(self._by_salsify),
            official_keys=tuple(self._by_official),
        )
        quantity = line.quantity if line.quantity is not None else interpreted.quantity_from_text
        result = self._match_interpreted(
            raw_description=line.requested_description or "",
            interpreted=interpreted,
            quantity=quantity,
            source_file=line.source_file,
            source_sheet=line.source_sheet,
            source_row=line.source_row,
        )
        return self._attach_identity(result, line.requested_description or "", interpreted)

    def match_quote(self, lines: Sequence[QuoteLine]) -> list[MatchResult]:
        return [self.match_line(line) for line in lines]

    def match_description(
        self,
        requested_description: str,
        quantity: int | float | None = None,
        source_file: str | None = None,
        source_sheet: str | None = None,
        source_row: int | None = None,
    ) -> MatchResult:
        interpreted = interpret_customer_text(
            requested_description,
            salsify_keys=tuple(self._by_salsify),
            official_keys=tuple(self._by_official),
        )
        resolved_qty = quantity if quantity is not None else interpreted.quantity_from_text
        result = self._match_interpreted(
            raw_description=requested_description,
            interpreted=interpreted,
            quantity=resolved_qty,
            source_file=source_file,
            source_sheet=source_sheet,
            source_row=source_row,
        )
        return self._attach_identity(result, requested_description, interpreted)

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
            if product is not None and source in {"salsify", "catalog"}:
                break
            if source == "ambiguous":
                break

        display_pn = interpreted.lookup_identifiers[0] if interpreted.lookup_identifiers else None
        scoring_description = interpreted.description_text if interpreted.has_description else ""

        if product is not None and source in {"salsify", "catalog"}:
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

    def _score_description_candidates(self, requested_description: str) -> list[MatchCandidate]:
        scored: list[MatchCandidate] = []
        for product in self.products:
            breakdown = score_pair(
                requested_description, product.description or "", self.config
            )
            if breakdown.final < self.config.candidate_floor:
                continue
            duplicate = self._description_counts[canonical_text(product.description)] > 1
            candidate = MatchCandidate(
                official_part_number=product.official_part_number or "",
                description=product.description or "",
                salsify_id=product.salsify_id,
                score=breakdown.final,
                score_percentage=breakdown.final,
                match_reasons=build_candidate_reasons(
                    requested_description,
                    product,
                    breakdown,
                    duplicate_description=duplicate,
                ),
                breakdown=breakdown,
            )
            scored.append(candidate)
        scored.sort(key=lambda item: (-item.score, item.official_part_number, item.salsify_id))
        return scored

    def _candidate_from_product(
        self,
        requested_description: str,
        product: ProductRecord,
        breakdown,
        *,
        extra_reasons: list[str] | None = None,
    ) -> MatchCandidate:
        duplicate = self._description_counts[canonical_text(product.description)] > 1
        reasons = build_candidate_reasons(
            requested_description,
            product,
            breakdown,
            duplicate_description=duplicate,
        )
        if extra_reasons:
            reasons = list(dict.fromkeys([*extra_reasons, *reasons]))
        return MatchCandidate(
            official_part_number=product.official_part_number or "",
            description=product.description or "",
            salsify_id=product.salsify_id,
            score=breakdown.final,
            score_percentage=breakdown.final,
            match_reasons=reasons,
            breakdown=breakdown,
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
        candidates = scored[: self.config.max_candidates]
        scores = [item.score for item in scored]
        top_score, second_score, score_gap = calculate_score_gap(scores)
        top_score = clamp_score(top_score)

        exact_group = [
            item
            for item in scored
            if item.breakdown is not None and item.breakdown.exact >= 100.0
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

        exact_unique = len(exact_group) == 1
        status = decide_match_status(
            top_score=top_score,
            second_score=second_score,
            score_gap=score_gap,
            exact_unique=exact_unique,
            duplicate_top=duplicate_top,
            candidate_count=len(candidates),
            config=self.config,
        )
        if force_review and status != MatchStatus.NO_MATCH:
            status = MatchStatus.REVIEW_REQUIRED

        matched_part = matched_description = matched_salsify = None
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
        if status in {MatchStatus.EXACT_MATCH, MatchStatus.HIGH_CONFIDENCE}:
            result_reasons.insert(0, DESC_UNIQUE)
        elif status == MatchStatus.REVIEW_REQUIRED and duplicate_top:
            result_reasons.insert(0, DESC_AMBIGUOUS)
        if extra_reasons:
            result_reasons = list(dict.fromkeys([*extra_reasons, *result_reasons]))
        if candidates:
            result_reasons.extend(candidates[0].match_reasons[:4])
            result_reasons = list(dict.fromkeys(result_reasons))

        description_score = matching_percentage if has_description_signal else None
        description_match = bool(
            has_description_signal
            and candidates
            and (
                (candidates[0].breakdown is not None and candidates[0].breakdown.exact >= 100.0)
                or top_score >= self.config.high_confidence_min
            )
        )
        overall = self._combined_overall(part_number_match_score, description_score)
        if status == MatchStatus.NO_MATCH:
            overall = 0.0

        return MatchResult(
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
            part_number_match_score=part_number_match_score,
            description_match_score=description_score,
            overall_match_score=overall,
            part_number_match=False,
            description_match=description_match,
        )

    def _lookup_product_by_identifier(
        self, requested_part_number: str
    ) -> tuple[ProductRecord | None, str | None]:
        key = normalize_part_number(requested_part_number)
        if not key:
            return None, None
        salsify_hits = self._by_salsify.get(key, [])
        if len(salsify_hits) == 1:
            return salsify_hits[0], "salsify"
        if len(salsify_hits) > 1:
            return None, "ambiguous"
        official_hits = self._by_official.get(key, [])
        if len(official_hits) == 1:
            return official_hits[0], "catalog"
        if len(official_hits) > 1:
            return None, "ambiguous"
        return None, None

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
        scoring_query = fold_whitespace(description_for_scoring)
        description_blank = not scoring_query
        breakdown = score_pair(scoring_query or "", product.description or "", self.config)
        if description_blank:
            compatible = True
            conflict = False
            description_score = None
        else:
            compatible = descriptions_compatible(
                scoring_query, product.description or "", breakdown, self.config
            )
            conflict = descriptions_conflict(
                scoring_query, product.description or "", breakdown, self.config
            )
            description_score = clamp_score(breakdown.final)
        identity_reason = PN_SALSIFY_EXACT if match_source == "salsify" else PN_CATALOG_EXACT
        pn_candidate = self._candidate_from_product(
            scoring_query or requested_description,
            product,
            breakdown,
            extra_reasons=[identity_reason],
        )
        pn_candidate.score = 100.0
        pn_candidate.score_percentage = 100.0
        description_candidates: list[MatchCandidate] = []
        if not description_blank:
            description_candidates = [
                item
                for item in self._score_description_candidates(scoring_query)
                if item.salsify_id != product.salsify_id
            ]
        if conflict or not compatible:
            status = MatchStatus.REVIEW_REQUIRED
            matched_part = matched_description = matched_salsify = None
            overall = self._combined_overall(100.0, description_score)
            reasons = [PN_EXACT_CONFLICT]
            candidates = [pn_candidate, *description_candidates][: self.config.max_candidates]
        else:
            status = MatchStatus.EXACT_MATCH
            matched_part = product.official_part_number
            matched_description = product.description
            matched_salsify = product.salsify_id
            overall = self._combined_overall(100.0, description_score)
            if description_blank:
                reasons = [identity_reason]
            elif match_source == "salsify":
                reasons = [PN_SALSIFY_EXACT]
            else:
                reasons = [PN_EXACT_COMPATIBLE]
            candidates = [pn_candidate]

        scores = [item.score for item in candidates]
        top_score, second_score, score_gap = calculate_score_gap(scores)
        reasons = list(dict.fromkeys([*reasons, *pn_candidate.match_reasons[:4]]))
        return MatchResult(
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
        )

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
) -> MatchStatus:
    if candidate_count == 0 or top_score < config.min_match_threshold:
        return MatchStatus.NO_MATCH

    tied = (
        duplicate_top
        or score_gap is None
        or score_gap <= config.score_tie_epsilon
        or (second_score is not None and score_gap < config.min_score_gap)
    )

    if exact_unique and top_score >= 99.0 and not duplicate_top:
        if score_gap is None or score_gap > config.score_tie_epsilon:
            return MatchStatus.EXACT_MATCH

    if tied:
        return MatchStatus.REVIEW_REQUIRED

    if top_score >= config.high_confidence_min and not duplicate_top:
        return MatchStatus.HIGH_CONFIDENCE

    return MatchStatus.REVIEW_REQUIRED


def match_quote(
    lines: Sequence[QuoteLine],
    products: Sequence[ProductRecord],
    config: MatchingConfig | None = None,
) -> list[MatchResult]:
    return ProductMatcher(products, config).match_quote(lines)
