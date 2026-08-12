"""Approved post-query calculations: comparison, trend, ranking, share of
total, contribution to movement and categorical change listing. All figures
are computed here deterministically with pandas; the language model never
performs these calculations."""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from models.evidence import ValidatedPlan

EPS = 1e-9


@dataclass
class ShapedResult:
    df: pd.DataFrame
    operation: str
    dataset: str
    measures: list[str]
    group_by: list[str]
    periods: list[str]
    period_labels: list[str]
    unit: str
    summary: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    total_row_count: int = 0


def _apply_sort_limit(df: pd.DataFrame, vp: ValidatedPlan,
                      default_sort: list[tuple[str, bool]]) -> pd.DataFrame:
    plan = vp.plan
    sorts = [(s.field, s.direction == "asc") for s in plan.sort
             if s.field in df.columns]
    if not sorts:
        sorts = [(f, asc) for f, asc in default_sort if f in df.columns]
    if sorts:
        df = df.sort_values(by=[f for f, _ in sorts],
                            ascending=[a for _, a in sorts],
                            kind="stable")
    return df.head(vp.plan.limit).reset_index(drop=True)


def _additive(vp: ValidatedPlan, cat_measures: dict, measure: str) -> bool:
    return cat_measures.get(measure, {}).get("additive", True)


def apply(vp: ValidatedPlan, df: pd.DataFrame, reviews_meta: dict[str, dict],
          cat_measures: dict) -> ShapedResult:
    plan = vp.plan
    op = plan.operation
    measures = plan.measures
    group_by = plan.group_by
    labels = {rid: reviews_meta.get(rid, {}).get("quarter_label", rid)
              for rid in plan.review_ids}
    unit = ""
    if measures:
        unit = cat_measures.get(measures[0], {}).get("unit", "")
    warnings: list[str] = []
    summary: dict = {}

    def finish(out: pd.DataFrame, total_rows: int | None = None) -> ShapedResult:
        return ShapedResult(
            df=out, operation=op, dataset=vp.dataset, measures=measures,
            group_by=group_by, periods=plan.review_ids,
            period_labels=[labels[r] for r in plan.review_ids],
            unit=unit, summary=summary, warnings=warnings,
            total_row_count=total_rows if total_rows is not None else len(out))

    if df.empty:
        return finish(df)

    # ------------------------------------------------------------------ trend
    if op == "trend":
        seq = {rid: reviews_meta.get(rid, {}).get("sequence_no", 0)
               for rid in plan.review_ids}
        out = df.copy()
        out["_seq"] = out["review_id"].map(seq)
        out = out.sort_values(["_seq"] + group_by, kind="stable")
        out["review"] = out["review_id"].map(labels)
        m = measures[0]
        if group_by:
            totals = out.groupby(group_by[0])[m].sum().sort_values(ascending=False)
            keep = set(totals.head(plan.limit).index)
            dropped = len(totals) - len(keep)
            if dropped > 0:
                warnings.append(f"Showing the top {len(keep)} of {len(totals)} "
                                f"{group_by[0].replace('_', ' ')} groups by total.")
            out = out[out[group_by[0]].isin(keep)]
        out = out[["review"] + group_by + [m]].reset_index(drop=True)
        summary[f"total_{m}_latest"] = float(
            df[df["review_id"] == plan.review_ids[-1]][m].sum())
        return finish(out)

    # ------------------------------------------- comparison-shaped operations
    two_period = (op in ("compare", "contribution_to_movement")
                  or (op == "rank" and len(plan.review_ids) == 2)
                  or (op == "list_changes"))
    if two_period:
        cur_rid, pri_rid = plan.review_ids[0], plan.review_ids[1]

        if op == "list_changes":
            attr = plan.attributes[0]
            keys = group_by
            cur = df[df["review_id"] == cur_rid].set_index(keys)[attr]
            pri = df[df["review_id"] == pri_rid].set_index(keys)[attr]
            joined = pd.DataFrame({"current_value": cur, "prior_value": pri}).dropna()
            changed = joined[joined["current_value"] != joined["prior_value"]]
            out = changed.reset_index()[keys + ["prior_value", "current_value"]]
            total_rows = len(out)
            summary["change_count"] = total_rows
            summary["compared_field"] = attr
            out = _apply_sort_limit(out, vp, [(k, True) for k in keys])
            return finish(out, total_rows)

        m = measures[0]
        additive = _additive(vp, cat_measures, m)
        keys = group_by
        cur = df[df["review_id"] == cur_rid]
        pri = df[df["review_id"] == pri_rid]
        if keys:
            cur_s = cur.set_index(keys)[m]
            pri_s = pri.set_index(keys)[m]
            joined = pd.DataFrame({"current": cur_s, "prior": pri_s})
        else:
            joined = pd.DataFrame({"current": [cur[m].sum() if len(cur) else 0.0],
                                   "prior": [pri[m].sum() if len(pri) else 0.0]})
        if additive:
            joined = joined.fillna(0.0)
        joined["absolute_change"] = joined["current"] - joined["prior"]
        joined["percentage_change"] = [
            (ac / abs(p) * 100.0) if abs(p) > EPS else None
            for ac, p in zip(joined["absolute_change"], joined["prior"])]

        total_cur = float(joined["current"].sum(skipna=True))
        total_pri = float(joined["prior"].sum(skipna=True))
        total_move = total_cur - total_pri
        summary.update({
            "current_total": total_cur, "prior_total": total_pri,
            "absolute_change_total": total_move,
            "percentage_change_total": (total_move / abs(total_pri) * 100.0)
            if abs(total_pri) > EPS else None,
        })

        if op == "contribution_to_movement":
            if abs(total_move) > EPS:
                joined["contribution_pct"] = joined["absolute_change"] / total_move * 100.0
            else:
                joined["contribution_pct"] = None
                warnings.append("Total movement is zero, so contribution to "
                                "movement is not defined.")

        out = joined.reset_index() if keys else joined.reset_index(drop=True)
        total_rows = len(out)
        out = _apply_sort_limit(out, vp, [("absolute_change", False)])
        return finish(out, total_rows)

    # ----------------------------------------- aggregate / rank / share / pivot
    m0 = measures[0] if measures else None
    multi_review = len(plan.review_ids) > 1
    out = df.copy()
    if multi_review:
        out["review"] = out["review_id"].map(labels)
        cols = ["review"] + group_by + plan.attributes + measures
    else:
        cols = group_by + plan.attributes + measures
    out = out[cols]

    if op == "share_of_total" and m0:
        total = float(out[m0].sum())
        summary["total"] = total
        if abs(total) > EPS:
            out["share_pct"] = out[m0] / total * 100.0
        else:
            out["share_pct"] = None
            warnings.append("The total is zero, so shares are not defined.")

    for m in measures:
        summary[f"total_{m}"] = float(df[df["review_id"] == plan.review_ids[0]][m].sum())

    total_rows = len(out)
    default_sort: list[tuple[str, bool]] = [(m0, False)] if m0 else []
    out = _apply_sort_limit(out, vp, default_sort)
    return finish(out, total_rows)
