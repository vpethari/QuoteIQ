from __future__ import annotations

from unittest.mock import MagicMock

from catalog.postgres_repository import product_from_postgres_row
from matching.matcher import ProductMatcher
from matching.models import MatchingConfig, QuoteLine


def _product(code: str, description: str) -> object:
    record = product_from_postgres_row(
        productcode=code,
        name=code,
        description=description,
        description2=description,
        orderablepartnumber=code,
    )
    assert record is not None
    return record


def _search(hits: list, purchase_quantities: dict[str, int] | None = None) -> MagicMock:
    search = MagicMock()
    search.lookup_productcode.return_value = []
    search.fetch_identifier_candidates.return_value = []
    search.search_text_candidates.return_value = hits
    search.customer_purchase_quantities.return_value = purchase_quantities or {}
    return search


def test_customer_purchase_history_reorders_otherwise_tied_candidates() -> None:
    # Three equally-valid "1\" PVC" pipe candidates, differing only by
    # length -- text scoring alone ties them (same description shape,
    # same boilerplate). A customer who has historically bought the 10ft
    # version far more than the 8ft/20ft versions should see it ranked
    # first.
    eight = _product("PVC-1-8FT", "1\" PVC Pipe 8 FT")
    ten = _product("PVC-1-10FT", "1\" PVC Pipe 10 FT")
    twenty = _product("PVC-1-20FT", "1\" PVC Pipe 20 FT")
    search = _search(
        [eight, ten, twenty],
        purchase_quantities={"PVC-1-8FT": 2, "PVC-1-10FT": 96, "PVC-1-20FT": 2},
    )
    matcher = ProductMatcher([], catalog_search=search)
    line = QuoteLine("quote.xlsx", "Sheet1", 2, "1\" PVC Pipe 10 FT", 1, customer_name="ACME CORP")
    result = matcher.match_line(line)
    search.customer_purchase_quantities.assert_called_once()
    called_args = search.customer_purchase_quantities.call_args.args
    assert called_args[0] == "ACME CORP"
    assert set(called_args[1]) == {"PVC-1-8FT", "PVC-1-10FT", "PVC-1-20FT"}
    # matched_part_number is only populated at high-confidence status tiers
    # -- ranking itself is what this test cares about, so check the top
    # candidate directly regardless of overall status.
    assert result.candidates[0].official_part_number == "PVC-1-10FT"
    assert result.candidates[0].customer_purchase_quantity == 96


def test_no_customer_selected_leaves_score_unchanged() -> None:
    eight = _product("PVC-1-8FT", "1\" PVC Pipe 8 FT")
    ten = _product("PVC-1-10FT", "1\" PVC Pipe 10 FT")
    search = _search([eight, ten])
    matcher = ProductMatcher([], catalog_search=search)
    line = QuoteLine("quote.xlsx", "Sheet1", 2, "1\" PVC Pipe 10 FT", 1)
    matcher.match_line(line)
    search.customer_purchase_quantities.assert_not_called()


def test_purchase_history_never_rescues_a_wrong_family_candidate() -> None:
    # The important rule from the feature request: purchase history must
    # only re-rank among otherwise-valid candidates, never override
    # genuine product matching. A PVC coupling should never outrank -- or
    # even appear as the top candidate over -- a correct PVC elbow just
    # because the customer buys a lot of couplings, once a real
    # variant-conflict exists between the query and that candidate.
    elbow = _product("PVC-90-1", "1\" PVC 90 Degree Elbow")
    coupling = _product("PVC-CPL-1", "1\" PVC Coupling")
    search = _search(
        [elbow, coupling],
        purchase_quantities={"PVC-CPL-1": 500},
    )
    matcher = ProductMatcher([], catalog_search=search)
    line = QuoteLine(
        "quote.xlsx", "Sheet1", 2, "1\" PVC 90 Degree Elbow", 1, customer_name="ACME CORP"
    )
    result = matcher.match_line(line)
    assert result.matched_part_number == "PVC-90-1"


def test_even_split_purchase_history_does_not_reshuffle_ranking() -> None:
    # A customer who buys two variants about equally shouldn't have their
    # ranking reshuffled by noise -- the proportional-share design means
    # a near-even split contributes a similarly small bonus to each, not
    # a decisive tilt toward whichever one is queried.
    eight = _product("PVC-1-8FT", "1\" PVC Pipe 8 FT")
    ten = _product("PVC-1-10FT", "1\" PVC Pipe 10 FT")
    search = _search(
        [eight, ten],
        purchase_quantities={"PVC-1-8FT": 50, "PVC-1-10FT": 50},
    )
    config = MatchingConfig()
    matcher = ProductMatcher([], config, catalog_search=search)
    line = QuoteLine(
        "quote.xlsx", "Sheet1", 2, "1\" PVC Pipe", 1, customer_name="ACME CORP"
    )
    result = matcher.match_line(line)
    # Both get exactly half of customer_purchase_bonus -- ties on
    # everything else, so the outcome is a coin flip decided by the
    # existing stable tie-break (official_part_number), not by a lopsided
    # history bonus.
    assert result.score_gap == 0
