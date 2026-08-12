"""Deterministic scope repair between planning and validation."""
import pytest

from models.query_plan import QueryPlan
from services.catalogue import get_catalogue
from services.engine import run_plan
from services.plan_repair import repair_plan_scope


def plan(**kwargs) -> QueryPlan:
    base = dict(intent="STRUCTURED_QUERY", primary_dataset="results",
                review_ids=["2026-Q2"], measures=["total_reserve"],
                operation="aggregate")
    base.update(kwargs)
    return QueryPlan(**base)


def repair(question, p):
    return repair_plan_scope(question, p, get_catalogue())


def test_named_accident_year_becomes_a_filter():
    fixed, notes = repair("What were the reserves for accident year 2024?", plan())
    assert [(f.field, f.value) for f in fixed.filters] == [("accident_year", 2024)]
    assert notes and "2024" in notes[0]


def test_multiple_named_accident_years_become_an_in_filter():
    fixed, _ = repair("Reserves for accident years 2023 and 2024", plan())
    f = fixed.filters[0]
    assert f.field == "accident_year" and f.operator == "in"
    assert sorted(f.value) == [2023, 2024]


def test_quarter_year_is_not_mistaken_for_an_accident_year():
    """'2025 Q3' names a review period; only the accident year is filtered."""
    fixed, _ = repair("accident year 2023 in 2025 Q3",
                      plan(review_ids=["2025-Q3"]))
    assert [(f.field, f.value) for f in fixed.filters] == [("accident_year", 2023)]


def test_no_repair_without_accident_year_language():
    """A bare year in a quarter reference must never invent a filter."""
    fixed, notes = repair("How much did reserves change in 2026 Q2?", plan())
    assert fixed.filters == [] and notes == []


def test_existing_filter_is_never_overridden():
    p = plan(filters=[{"field": "accident_year", "operator": "eq", "value": 2022}])
    fixed, notes = repair("accident year 2024 please", p)
    assert [(f.field, f.value) for f in fixed.filters] == [("accident_year", 2022)]
    assert notes == []


def test_grouped_accident_year_is_not_also_filtered():
    p = plan(group_by=["accident_year"])
    fixed, notes = repair("Show accident year 2024 alongside the others", p)
    assert fixed.filters == [] and notes == []


@pytest.mark.parametrize("question,expected", [
    ("Show the reserve movement by Reserving Class", ["reserving_class"]),
    ("Show reserves by finance class", ["finance_class"]),
    ("Split Commercial Lines by region and Loss Type", ["region", "loss_type"]),
    ("reserves broken down by business unit", ["business_unit"]),
    ("Show me reserves per entity", ["entity"]),
    ("what is the reserve by accident year", ["accident_year"]),
])
def test_explicit_by_phrase_restores_grouping(question, expected):
    fixed, notes = repair(question, plan())
    assert fixed.group_by == expected
    assert notes


@pytest.mark.parametrize("question", [
    "How much did reserves change from last quarter?",
    "Compare that with last quarter",
    "What are the key messages from this quarter's review?",
    "Which classes drove the movement?",
])
def test_no_grouping_invented_without_by_phrase(question):
    fixed, notes = repair(question, plan())
    assert fixed.group_by == [] and notes == []


def test_by_phrase_respects_dataset_grain():
    """Premium has no Loss Type: the repair must not create an invalid plan."""
    p = plan(primary_dataset="premium", measures=["earned_premium"])
    fixed, notes = repair("premium by loss type", p)
    assert fixed.group_by == [] and notes == []


def test_by_phrase_does_not_override_existing_grouping():
    fixed, notes = repair("Show reserves by finance class", plan(group_by=["region"]))
    assert fixed.group_by == ["region"] and notes == []


def test_sort_only_dimension_is_promoted_to_grouping():
    p = plan(sort=[{"field": "accident_year", "direction": "asc"}])
    fixed, notes = repair("Show reserves by accident year", p)
    assert fixed.group_by == ["accident_year"]
    assert notes and "Accident Year" in notes[0]


def test_sort_promotion_skipped_when_grouping_present():
    p = plan(group_by=["finance_class"],
             sort=[{"field": "accident_year", "direction": "asc"}])
    fixed, notes = repair("reserves by finance class", p)
    assert fixed.group_by == ["finance_class"] and notes == []


def test_measure_sort_is_not_promoted():
    p = plan(sort=[{"field": "total_reserve", "direction": "desc"}])
    fixed, notes = repair("largest reserves", p)
    assert fixed.group_by == [] and notes == []


def test_repair_reaches_the_executed_result_and_is_recorded():
    """End-to-end: the repaired filter must change the number returned and be
    visible in provenance."""
    unscoped = plan()
    er = run_plan(unscoped, question="What were the reserves for accident year 2024?")
    total = float(er.shaped.df["total_reserve"].iloc[0])
    assert total == pytest.approx(117_213_706.0, rel=1e-6)
    assert total < 640_000_000.0
    assert any("2024" in note for note in er.validated.inferred_defaults)


def test_run_plan_without_question_is_unchanged():
    er = run_plan(plan())
    assert float(er.shaped.df["total_reserve"].iloc[0]) == pytest.approx(640e6)
