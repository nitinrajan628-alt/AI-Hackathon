"""Policy and grain validation rules (16.1)."""
import pytest

from models.query_plan import QueryPlan
from services.catalogue import get_catalogue
from services.policy import PlanValidationError, validate_plan
from services.review_service import review_ids


def make_plan(**kwargs) -> QueryPlan:
    base = dict(intent="STRUCTURED_QUERY", primary_dataset="results",
                review_ids=["2026-Q2"], measures=["total_reserve"],
                operation="aggregate")
    base.update(kwargs)
    return QueryPlan(**base)


def validate(plan):
    return validate_plan(plan, get_catalogue(), review_ids())


def test_loss_type_rejected_on_premium():
    plan = make_plan(primary_dataset="premium", measures=["earned_premium"],
                     filters=[{"field": "loss_type", "operator": "eq",
                               "value": "Large"}])
    with pytest.raises(PlanValidationError) as err:
        validate(plan)
    assert "loss type" in str(err.value).lower() or "Loss Type" in str(err.value)


def test_region_rejected_on_assumptions_with_grain_message():
    plan = make_plan(primary_dataset="assumptions",
                     measures=["inflation_assumption"],
                     group_by=["region"], operation="aggregate")
    with pytest.raises(PlanValidationError) as err:
        validate(plan)
    msg = str(err.value)
    assert "Reserving Class" in msg and "Accident Year" in msg


def test_latest_diagonal_enforced_for_aggregate_claims():
    plan = make_plan(primary_dataset="claims_triangle",
                     measures=["paid_claims_cumulative"],
                     group_by=["reserving_class"])
    vp = validate(plan)
    assert vp.dataset == "claims_latest"
    assert vp.table == "vw_claims_latest"
    assert vp.plan.measures == ["paid_claims"]
    assert vp.inferred_defaults


def test_triangle_allowed_with_explicit_development_period():
    plan = make_plan(primary_dataset="claims_triangle",
                     measures=["paid_claims_cumulative"],
                     group_by=["development_period_quarters"],
                     filters=[{"field": "accident_year", "operator": "eq",
                               "value": 2023}])
    vp = validate(plan)
    assert vp.dataset == "claims_triangle"


def test_unknown_dimension_value_rejected():
    plan = make_plan(filters=[{"field": "reserving_class", "operator": "eq",
                               "value": "Aviation"}])
    with pytest.raises(PlanValidationError) as err:
        validate(plan)
    assert "Aviation" in str(err.value) and "Motor" in str(err.value)


def test_alias_values_resolved_to_canonical():
    plan = make_plan(filters=[{"field": "class", "operator": "eq",
                               "value": "casualty"}])
    vp = validate(plan)
    f = vp.plan.filters[0]
    assert f.field == "reserving_class" and f.value == "Casualty"


def test_unknown_review_rejected():
    plan = make_plan(review_ids=["2030-Q1"])
    with pytest.raises(PlanValidationError):
        validate(plan)


def test_compare_requires_two_reviews():
    plan = make_plan(operation="compare", review_ids=["2026-Q2"])
    with pytest.raises(PlanValidationError):
        validate(plan)


def test_non_additive_measure_requires_selection_grain():
    plan = make_plan(primary_dataset="assumptions",
                     measures=["selected_loss_ratio"],
                     group_by=["reserving_class"], operation="aggregate")
    with pytest.raises(PlanValidationError) as err:
        validate(plan)
    assert "cannot be summed" in str(err.value)


def test_non_additive_ok_at_full_grain():
    plan = make_plan(primary_dataset="assumptions",
                     measures=["selected_loss_ratio"],
                     group_by=["entity", "reserving_class", "loss_type",
                               "accident_year"],
                     operation="compare", review_ids=["2026-Q2", "2026-Q1"],
                     limit=200)
    vp = validate(plan)
    assert vp.plan.measures == ["selected_loss_ratio"]


def test_range_filter_only_on_ordered_fields():
    plan = make_plan(filters=[{"field": "reserving_class", "operator": "between",
                               "value": ["Casualty", "Motor"]}])
    with pytest.raises(PlanValidationError):
        validate(plan)


def test_range_filter_allowed_on_accident_year():
    plan = make_plan(filters=[{"field": "accident_year", "operator": "between",
                               "value": [2022, 2024]}])
    vp = validate(plan)
    assert vp.plan.filters[0].value == [2022, 2024]


def test_invalid_sort_dropped_with_warning():
    plan = make_plan(operation="compare", review_ids=["2026-Q2", "2026-Q1"],
                     group_by=["finance_class"],
                     sort=[{"field": "made_up_field", "direction": "desc"}])
    vp = validate(plan)
    assert vp.plan.sort == []
    assert any("sort" in w.lower() for w in vp.warnings)


def test_limit_clamped_to_catalogue_max():
    plan = make_plan(limit=200)
    vp = validate(plan)
    assert vp.plan.limit <= get_catalogue().row_limit_max


def test_default_measure_inferred():
    plan = make_plan(measures=[], group_by=["reserving_class"])
    vp = validate(plan)
    assert vp.plan.measures == ["total_reserve"]
    assert vp.inferred_defaults
