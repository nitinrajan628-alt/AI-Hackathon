"""Policy and grain validator (Detailed Build Specification section 7).

Validates a QueryPlan against the catalogue before any SQL exists:
scope, dataset fields, dimension grain, approved operations, filter
operators and values, time semantics, sort fields and row limits.
Raises PlanValidationError with a user-facing message on failure.
"""
from __future__ import annotations

from models.evidence import ValidatedPlan
from models.query_plan import FilterSpec, QueryPlan
from services.catalogue import Catalogue

DERIVED_SORT_FIELDS = {"current", "prior", "absolute_change", "percentage_change",
                       "share_pct", "contribution_pct"}
COMPARISON_OPS = {"compare", "contribution_to_movement"}
SINGLE_MEASURE_OPS = {"compare", "trend", "rank", "share_of_total",
                      "contribution_to_movement"}
DEFAULT_MEASURE = {
    "results": "total_reserve",
    "claims_latest": "paid_claims",
    "claims_triangle": "paid_claims_cumulative",
    "premium": "earned_premium",
    "assumptions": "management_adjustment",
}
# Measures whose cumulative variants map onto the latest-diagonal view.
TRIANGLE_TO_LATEST = {
    "paid_claims_cumulative": "paid_claims",
    "incurred_claims_cumulative": "incurred_claims",
    "reported_claim_count_cumulative": "reported_claim_count",
}


class PlanValidationError(Exception):
    def __init__(self, message: str, alternatives: list[str] | None = None,
                 category: str = "validation"):
        super().__init__(message)
        self.message = message
        self.alternatives = alternatives or []
        self.category = category


def _grain_message(cat: Catalogue, dataset: str, measure_or_field: str,
                   requested: str) -> str:
    grain = cat.grain(dataset)
    grain_labels = ", ".join(cat.dimension_label(dataset, g) for g in grain
                             if g != "development_period_quarters")
    return (f"{measure_or_field} is stored at {grain_labels}. It is not available "
            f"by {requested}. I can show the available view, or show results by "
            f"{requested} from the results dataset separately.")


def validate_plan(plan: QueryPlan, cat: Catalogue, known_reviews: list[str]) -> ValidatedPlan:
    warnings: list[str] = []
    inferred: list[str] = []
    dataset = plan.primary_dataset

    if dataset not in cat.datasets:
        raise PlanValidationError(f"Unknown dataset '{dataset}'.")

    # -- claims triangle control: aggregate questions use the latest diagonal
    measures = list(plan.measures)
    group_by = list(plan.group_by)
    attributes = list(plan.attributes)
    filters = [FilterSpec(**f.model_dump()) for f in plan.filters]

    def references_dev() -> bool:
        fields = group_by + attributes + [f.field for f in filters]
        resolved = [cat.resolve_dimension(f) or f for f in fields]
        return "development_period_quarters" in resolved

    if dataset == "claims_triangle" and not references_dev():
        dataset = "claims_latest"
        measures = [TRIANGLE_TO_LATEST.get(m, m) for m in measures]
        inferred.append(
            "Aggregate claims questions use the latest-diagonal view "
            "(vw_claims_latest) so cumulative triangle cells are not double-counted.")

    ds_measures = cat.measures(dataset)
    ds_dims = cat.dimensions(dataset)
    ds_attrs = cat.attributes(dataset)

    # -- review ids ---------------------------------------------------------
    review_ids: list[str] = []
    for rid in plan.review_ids:
        if rid not in known_reviews:
            raise PlanValidationError(
                f"'{rid}' is not one of the packaged review periods "
                f"({known_reviews[0]} to {known_reviews[-1]}).")
        if rid not in review_ids:
            review_ids.append(rid)

    op = plan.operation
    if op in COMPARISON_OPS or op == "list_changes":
        if len(review_ids) != 2:
            raise PlanValidationError(
                f"The '{op}' operation compares exactly two review periods; "
                f"{len(review_ids)} provided. State the current and comparison review.")
    if op == "trend" and len(review_ids) < 2:
        raise PlanValidationError(
            "A trend needs at least two review periods in chronological order.")

    # -- measures -----------------------------------------------------------
    resolved_measures: list[str] = []
    for m in measures:
        rm = cat.resolve_measure(m)
        if rm is None or rm not in ds_measures:
            valid = ", ".join(sorted(ds_measures))
            raise PlanValidationError(
                f"'{m}' is not a measure of the {dataset} dataset. "
                f"Available measures: {valid}.")
        if rm not in resolved_measures:
            resolved_measures.append(rm)

    if not resolved_measures and op != "list_changes":
        resolved_measures = [DEFAULT_MEASURE[dataset]]
        inferred.append(
            f"No measure was specified; defaulted to "
            f"{cat.measure_label(dataset, resolved_measures[0])}.")

    if op in SINGLE_MEASURE_OPS and len(resolved_measures) > 1:
        raise PlanValidationError(
            f"The '{op}' operation works with one measure at a time; "
            f"{len(resolved_measures)} were requested. Ask for them separately.")

    # -- group_by and attributes -------------------------------------------
    def resolve_field(field: str, purpose: str) -> str:
        rf = cat.resolve_dimension(field)
        if rf is None:
            rf = field
        if rf in ds_dims or rf in ds_attrs:
            return rf
        # Field exists elsewhere but not at this dataset's grain
        exists_elsewhere = any(
            rf in cat.dimensions(d) or rf in cat.attributes(d) for d in cat.datasets)
        if exists_elsewhere:
            label = cat.dataset(dataset).get("label", dataset)
            measure_label = (cat.measure_label(dataset, resolved_measures[0])
                             if resolved_measures else label)
            raise PlanValidationError(
                _grain_message(cat, dataset, measure_label,
                               rf.replace("_", " ").title()),
                category="unsupported_granularity")
        raise PlanValidationError(
            f"'{field}' is not a recognised dimension for {purpose}. "
            f"Valid dimensions for {dataset}: {', '.join(sorted(ds_dims))}.")

    resolved_group_by: list[str] = []
    for g in group_by:
        rg = resolve_field(g, "grouping")
        if rg == "review_id":
            warnings.append("Grouping by review period is applied automatically.")
            continue
        if rg not in resolved_group_by:
            resolved_group_by.append(rg)

    resolved_attributes: list[str] = []
    for a in attributes:
        ra = resolve_field(a, "display")
        if ra not in resolved_attributes and ra not in resolved_group_by:
            resolved_attributes.append(ra)

    # -- non-additive measures listed/compared only at the selection grain --
    non_additive = [m for m in resolved_measures
                    if not ds_measures[m].get("additive", True)]
    if non_additive:
        grain = [g for g in cat.grain(dataset) if g != "development_period_quarters"]
        missing = [g for g in grain if g not in resolved_group_by]
        if missing:
            labels = ", ".join(cat.measure_label(dataset, m) for m in non_additive)
            raise PlanValidationError(
                f"{labels} cannot be summed or averaged. It is listed or compared "
                f"row by row at the selection grain "
                f"({', '.join(cat.dimension_label(dataset, g) for g in grain)}). "
                f"Group by the full selection grain to view it.",
                alternatives=[f"Group by {', '.join(grain)} to list the values."],
                category="non_additive")

    # -- list_changes requirements ------------------------------------------
    if op == "list_changes":
        if not resolved_attributes:
            if dataset == "assumptions":
                resolved_attributes = ["projection_method"]
                inferred.append("Defaulted the compared field to Projection Method.")
            else:
                raise PlanValidationError(
                    "list_changes needs a categorical field to compare "
                    "(for example projection_method on the assumptions dataset).")
        if len(resolved_attributes) > 1:
            raise PlanValidationError(
                "list_changes compares one categorical field at a time.")
        if not resolved_group_by:
            grain = [g for g in cat.grain(dataset) if g != "development_period_quarters"]
            resolved_group_by = list(grain)
            inferred.append("Changes are listed at the dataset's selection grain.")

    # -- filters ------------------------------------------------------------
    resolved_filters: list[FilterSpec] = []
    for f in filters:
        rf = cat.resolve_dimension(f.field) or f.field
        if rf == "review_id":
            # Periods come from review_ids; drop redundant review filters.
            warnings.append("Review periods are taken from the plan's review list.")
            continue
        if rf not in ds_dims:
            resolve_field(f.field, "filtering")  # raises with a useful message
        if f.operator in ("between", "gte", "lte") and rf not in cat.ordered_fields:
            raise PlanValidationError(
                f"Range filters are only supported on "
                f"{', '.join(cat.ordered_fields)}; '{rf}' is a categorical dimension.")
        values = f.value if isinstance(f.value, list) else [f.value]
        if f.operator == "eq" and len(values) != 1:
            raise PlanValidationError("The 'eq' filter takes a single value.")
        if f.operator == "in" and not values:
            raise PlanValidationError("The 'in' filter needs at least one value.")
        if f.operator == "between":
            if len(values) != 2:
                raise PlanValidationError("The 'between' filter takes exactly two values.")
        canonical_values = []
        for v in values:
            cv = cat.resolve_value(rf, v)
            if cv is None:
                valid = cat.dimension_values.get(rf)
                hint = f" Valid values: {', '.join(valid)}." if valid else ""
                raise PlanValidationError(
                    f"'{v}' is not a recognised value for "
                    f"{rf.replace('_', ' ').title()}.{hint}")
            canonical_values.append(cv)
        if f.operator == "between":
            canonical_values = sorted(canonical_values)
        resolved_filters.append(FilterSpec(
            field=rf, operator=f.operator,
            value=canonical_values if f.operator in ("in", "between")
            else canonical_values[0]))

    # -- sort ---------------------------------------------------------------
    allowed_sort = set(resolved_group_by) | set(resolved_attributes) | set(resolved_measures)
    if op in COMPARISON_OPS or (op == "rank" and len(review_ids) == 2):
        allowed_sort |= DERIVED_SORT_FIELDS
    if op == "share_of_total":
        allowed_sort |= {"share_pct"}
    resolved_sort = []
    for s in plan.sort:
        sf = s.field if s.field in DERIVED_SORT_FIELDS else (
            cat.resolve_dimension(s.field) or cat.resolve_measure(s.field) or s.field)
        if sf not in allowed_sort:
            # Sorting is presentational: drop the invalid field (it is never
            # compiled into SQL) and fall back to the default ordering.
            warnings.append(
                f"The requested sort field '{s.field}' is not part of this "
                f"result and was ignored.")
            continue
        resolved_sort.append({"field": sf, "direction": s.direction})

    # -- limits -------------------------------------------------------------
    limit = min(plan.limit, cat.row_limit_max)

    canonical = QueryPlan(
        intent=plan.intent, primary_dataset=dataset, review_ids=review_ids,
        measures=resolved_measures, attributes=resolved_attributes,
        group_by=resolved_group_by,
        filters=resolved_filters, operation=op,
        sort=[{"field": s["field"], "direction": s["direction"]} for s in resolved_sort],
        limit=limit, chart=plan.chart)

    return ValidatedPlan(
        plan=canonical,
        dataset=dataset,
        table=cat.table(dataset),
        measure_columns={m: ds_measures[m]["column"] for m in resolved_measures},
        group_by_columns={g: ds_dims[g]["column"] for g in resolved_group_by},
        attribute_columns={a: (ds_attrs.get(a) or ds_dims.get(a))["column"]
                           for a in resolved_attributes},
        inferred_defaults=inferred,
        warnings=warnings,
    )
