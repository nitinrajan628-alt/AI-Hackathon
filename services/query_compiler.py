"""Compile a validated plan to parameterised read-only SQL.

Every identifier comes from the catalogue mappings carried on the
ValidatedPlan; user- or model-supplied values are bound as parameters and
never interpolated into SQL text.
"""
from __future__ import annotations

from models.evidence import CompiledQuery, ValidatedPlan

# Hard cap applied to every compiled query regardless of plan limit; final
# row limits are applied after deterministic shaping.
SQL_HARD_ROW_CAP = 20000

_OPERATOR_SQL = {"eq": "= ?", "gte": ">= ?", "lte": "<= ?"}


def compile_query(vp: ValidatedPlan) -> CompiledQuery:
    plan = vp.plan
    params: list = []

    select_cols: list[str] = ["review_id AS review_id"]
    group_cols: list[str] = ["review_id"]
    for g, col in vp.group_by_columns.items():
        select_cols.append(f"{col} AS {g}")
        group_cols.append(col)
    for a, col in vp.attribute_columns.items():
        # Grain-unique groups have exactly one value; MAX() is a safe pick.
        select_cols.append(f"MAX({col}) AS {a}")
    for m, col in vp.measure_columns.items():
        select_cols.append(f"SUM({col}) AS {m}")

    where: list[str] = []
    placeholders = ",".join("?" for _ in plan.review_ids)
    where.append(f"review_id IN ({placeholders})")
    params.extend(plan.review_ids)

    for f in plan.filters:
        col = (vp.group_by_columns.get(f.field)
               or vp.attribute_columns.get(f.field))
        if col is None:
            # Filter on a column not selected: resolve from the same catalogue
            # column name (canonical ids equal column names in this schema).
            col = f.field
        if f.operator in _OPERATOR_SQL:
            where.append(f"{col} {_OPERATOR_SQL[f.operator]}")
            params.append(f.value)
        elif f.operator == "in":
            values = f.value if isinstance(f.value, list) else [f.value]
            ph = ",".join("?" for _ in values)
            where.append(f"{col} IN ({ph})")
            params.extend(values)
        elif f.operator == "between":
            lo, hi = f.value
            where.append(f"{col} BETWEEN ? AND ?")
            params.extend([lo, hi])

    sql = (
        f"SELECT {', '.join(select_cols)} FROM {vp.table} "
        f"WHERE {' AND '.join(where)} "
        f"GROUP BY {', '.join(group_cols)} "
        f"LIMIT {SQL_HARD_ROW_CAP}"
    )

    return CompiledQuery(
        sql=sql,
        parameters=params,
        source_tables=[vp.table],
        selected_fields=list(vp.group_by_columns) + list(vp.attribute_columns)
        + list(vp.measure_columns),
        measure_metadata={m: {"column": col} for m, col in vp.measure_columns.items()},
    )
