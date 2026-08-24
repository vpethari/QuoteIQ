from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from ai.models import AIDecision, AIReasoningResult
from matching.models import MatchCandidate, ProductRecord


@dataclass(frozen=True)
class ValidationOutcome:
    accepted: bool
    selected_part_number: str | None
    selected_description: str | None
    selected_salsify_id: str | None
    reason: str
    catalog_validated: bool
    candidate_validated: bool


def validate_ai_selection(
    result: AIReasoningResult,
    candidates: Sequence[MatchCandidate],
    catalog: Sequence[ProductRecord],
) -> ValidationOutcome:
    """Reject any part number that is not a supplied product candidate."""
    candidate_by_pn = {
        item.official_part_number: item
        for item in candidates
        if item.official_part_number
    }
    family_ids = {
        item.salsify_id
        for item in catalog
        if item.record_type == "family" and item.salsify_id
    }
    family_ids.update(
        item.parent_id for item in catalog if item.record_type == "family" and item.parent_id
    )
    approved_parts = {
        item.official_part_number
        for item in catalog
        if item.record_type == "product" and item.official_part_number
    }
    product_by_pn = {
        item.official_part_number: item
        for item in catalog
        if item.record_type == "product" and item.official_part_number
    }

    selected = result.selected_part_number
    if selected is None:
        return ValidationOutcome(
            accepted=False,
            selected_part_number=None,
            selected_description=None,
            selected_salsify_id=None,
            reason="AI returned no part number",
            catalog_validated=False,
            candidate_validated=False,
        )

    if not isinstance(selected, str) or selected.strip() != selected or "\n" in selected:
        return ValidationOutcome(
            accepted=False,
            selected_part_number=None,
            selected_description=None,
            selected_salsify_id=None,
            reason="AI returned a malformed part number",
            catalog_validated=False,
            candidate_validated=False,
        )

    if selected in family_ids:
        return ValidationOutcome(
            accepted=False,
            selected_part_number=None,
            selected_description=None,
            selected_salsify_id=None,
            reason="AI returned a family/parent identifier",
            catalog_validated=False,
            candidate_validated=False,
        )

    if selected not in candidate_by_pn:
        return ValidationOutcome(
            accepted=False,
            selected_part_number=None,
            selected_description=None,
            selected_salsify_id=None,
            reason="AI selected a part number that was not in the candidate list",
            catalog_validated=False,
            candidate_validated=False,
        )

    if selected not in approved_parts:
        return ValidationOutcome(
            accepted=False,
            selected_part_number=None,
            selected_description=None,
            selected_salsify_id=None,
            reason="AI selected a part number that is not in the approved product catalog",
            catalog_validated=False,
            candidate_validated=True,
        )

    product = product_by_pn[selected]
    candidate = candidate_by_pn[selected]
    if product.record_type != "product":
        return ValidationOutcome(
            accepted=False,
            selected_part_number=None,
            selected_description=None,
            selected_salsify_id=None,
            reason="Selected record is not a matchable product",
            catalog_validated=False,
            candidate_validated=True,
        )

    return ValidationOutcome(
        accepted=True,
        selected_part_number=selected,
        selected_description=candidate.description,
        selected_salsify_id=candidate.salsify_id,
        reason="Selection is present in candidates and approved catalog",
        catalog_validated=True,
        candidate_validated=True,
    )
