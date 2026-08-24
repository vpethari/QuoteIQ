from __future__ import annotations

from catalog.normalize import is_blank, normalize_whitespace


CATALOG_DELIMITER = " - "


class CatalogNumberParseError(ValueError):
    """Raised when a catalog-number-and-description value cannot be parsed."""


def parse_catalog_number(value: str | None) -> str:
    """Parse official_part_number from 'Catalog Number - Short Description'.

    The Atkore extract uses the delimiter ' - ' (space, hyphen, space).
    Catalog numbers themselves may contain hyphens, so the value is not
    split on every hyphen.
    """
    text = normalize_whitespace(value)
    if text is None:
        raise CatalogNumberParseError("catalog number value is empty")
    if text == "-":
        raise CatalogNumberParseError("placeholder '-' is not a catalog number")
    if CATALOG_DELIMITER not in text:
        raise CatalogNumberParseError(
            f"value {value!r} does not contain delimiter {CATALOG_DELIMITER!r}"
        )
    catalog, _rest = text.split(CATALOG_DELIMITER, 1)
    catalog = catalog.strip()
    if not catalog:
        raise CatalogNumberParseError(f"empty catalog number in {value!r}")
    return catalog
