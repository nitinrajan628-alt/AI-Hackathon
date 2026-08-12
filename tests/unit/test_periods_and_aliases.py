"""Relative period resolution and canonical alias handling (16.1)."""
import pytest

from services.catalogue import get_catalogue
from services.review_service import (
    default_review_id,
    list_reviews,
    prior_review_id,
    prior_year_review_id,
    resolve_periods,
)

EXPECTED = {
    "2024-Q3": (None, None),
    "2024-Q4": ("2024-Q3", None),
    "2025-Q1": ("2024-Q4", None),
    "2025-Q2": ("2025-Q1", None),
    "2025-Q3": ("2025-Q2", "2024-Q3"),
    "2025-Q4": ("2025-Q3", "2024-Q4"),
    "2026-Q1": ("2025-Q4", "2025-Q1"),
    "2026-Q2": ("2026-Q1", "2025-Q2"),
}


def test_eight_reviews_and_default():
    assert [r["review_id"] for r in list_reviews()] == list(EXPECTED)
    assert default_review_id() == "2026-Q2"


@pytest.mark.parametrize("rid", list(EXPECTED))
def test_relative_period_links(rid):
    prior, prior_year = EXPECTED[rid]
    assert prior_review_id(rid) == prior
    assert prior_year_review_id(rid) == prior_year


def test_resolve_last_quarter_phrase():
    res = resolve_periods("How did reserves change since last quarter?", "2026-Q2")
    assert res.comparison_review_ids == ["2026-Q1"]
    assert "2026 Q2" in res.interpretation_label and "2026 Q1" in res.interpretation_label


def test_resolve_prior_year_phrase():
    res = resolve_periods("Show paid claims this year versus last", "2026-Q2")
    assert res.comparison_review_ids == ["2025-Q2"]


def test_resolve_missing_prior_warns():
    res = resolve_periods("change since last quarter", "2024-Q3")
    assert res.comparison_review_ids == []
    assert res.warnings


def test_measure_aliases():
    cat = get_catalogue()
    assert cat.resolve_measure("reserves") == "total_reserve"
    assert cat.resolve_measure("IBNR reserve") == "ibnr"
    assert cat.resolve_measure("Paid Claims") == "paid_claims"
    assert cat.resolve_measure("nonsense_measure_xyz") is None


def test_dimension_aliases():
    cat = get_catalogue()
    assert cat.resolve_dimension("class") == "reserving_class"
    assert cat.resolve_dimension("Finance Class") == "finance_class"
    assert cat.resolve_dimension("origin year") == "accident_year"


def test_value_aliases_and_rejection():
    cat = get_catalogue()
    assert cat.resolve_value("reserving_class", "casualty") == "Casualty"
    assert cat.resolve_value("loss_type", "large losses") == "Large"
    assert cat.resolve_value("finance_class", "commercial") == "Commercial Lines"
    assert cat.resolve_value("reserving_class", "Aviation") is None
