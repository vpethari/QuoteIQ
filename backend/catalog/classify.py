from __future__ import annotations

from typing import Any, Literal

from catalog.normalize import is_blank, normalize_whitespace

RecordType = Literal["product", "family"]
Classification = Literal["product", "family", "invalid"]

PRODUCT_SALSIFY_PREFIX = "NA1-"
FAMILY_CATALOG_PLACEHOLDER = "-"


def classify_row(
    salsify_id: Any,
    catalog_number_and_description: Any,
    description: Any,
    parent_id: Any,
) -> Classification:
    """Classify a catalog row using structural rules, not row numbers."""
    salsify = "" if is_blank(salsify_id) else str(salsify_id).strip()
    catalog = normalize_whitespace(
        None if is_blank(catalog_number_and_description) else str(catalog_number_and_description)
    )
    desc_blank = is_blank(description)
    parent_blank = is_blank(parent_id)

    is_product = (
        salsify.startswith(PRODUCT_SALSIFY_PREFIX)
        and catalog is not None
        and catalog != FAMILY_CATALOG_PLACEHOLDER
        and not desc_blank
        and not parent_blank
    )
    is_family = (
        bool(salsify)
        and not salsify.startswith(PRODUCT_SALSIFY_PREFIX)
        and catalog == FAMILY_CATALOG_PLACEHOLDER
        and desc_blank
        and parent_blank
    )
    if is_product:
        return "product"
    if is_family:
        return "family"
    return "invalid"
