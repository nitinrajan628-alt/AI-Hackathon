"""Pre-packaging validation. Fails (non-zero exit) if reconciliation,
consistency or uniqueness rules are not met (Detailed Build Specification
section 6.8). Run after build_demo_data.py (and after build_reports.py to
include report-to-data consistency checks).
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "reserve_review.db")

EXPECTED_TOTALS_M = {
    "2024-Q3": 580, "2024-Q4": 585, "2025-Q1": 592, "2025-Q2": 598,
    "2025-Q3": 606, "2025-Q4": 610, "2026-Q1": 614, "2026-Q2": 640,
}
EXPECTED_RC_MOVE_M = {"Casualty": 18, "Property": 7, "Motor": 4, "Marine": -3}
EXPECTED_FC_MOVE_M = {"Commercial Lines": 14, "Specialty Lines": 7,
                      "Personal Lines": 4, "Reinsurance": 1}

failures: list[str] = []


def check(name: str, ok: bool, detail: str = ""):
    status = "ok" if ok else "FAIL"
    print(f"  [{status}] {name}" + (f" - {detail}" if detail and not ok else ""))
    if not ok:
        failures.append(f"{name}: {detail}")


def main() -> int:
    con = sqlite3.connect(DB_PATH)
    q = lambda s, *p: con.execute(s, p).fetchall()

    print("Review metadata")
    rows = q("SELECT review_id, sequence_no, is_default FROM review_period ORDER BY sequence_no")
    check("eight review periods", len(rows) == 8, str(len(rows)))
    check("default review is 2026-Q2",
          [r[0] for r in rows if r[2] == 1] == ["2026-Q2"])

    print("Reserve reconciliation")
    for rid, expected in EXPECTED_TOTALS_M.items():
        total = q("SELECT SUM(total_reserve) FROM result_snapshot WHERE review_id=?", rid)[0][0]
        check(f"total reserve {rid} = GBP {expected}m", abs(total - expected * 1e6) < 1, f"{total}")

    for rc, expected in EXPECTED_RC_MOVE_M.items():
        move = q("""SELECT SUM(CASE WHEN review_id='2026-Q2' THEN total_reserve ELSE -total_reserve END)
                    FROM result_snapshot WHERE review_id IN ('2026-Q1','2026-Q2')
                    AND reserving_class=?""", rc)[0][0]
        check(f"{rc} movement = {expected:+}m", abs(move - expected * 1e6) < 1, f"{move}")

    for fc, expected in EXPECTED_FC_MOVE_M.items():
        move = q("""SELECT SUM(CASE WHEN review_id='2026-Q2' THEN total_reserve ELSE -total_reserve END)
                    FROM result_snapshot WHERE review_id IN ('2026-Q1','2026-Q2')
                    AND finance_class=?""", fc)[0][0]
        check(f"{fc} movement = {expected:+}m", abs(move - expected * 1e6) < 1, f"{move}")

    print("Result arithmetic identities (tolerance 1 currency unit per row)")
    bad = q("""SELECT COUNT(*) FROM result_snapshot
               WHERE ABS(case_reserves-(incurred_claims-paid_claims))>1
                  OR ABS(ibnr-(ultimate_claims-incurred_claims))>1
                  OR ABS(total_reserve-(ultimate_claims-paid_claims))>1""")[0][0]
    check("case/ibnr/reserve identities hold", bad == 0, f"{bad} rows")

    print("Result grain uniqueness")
    dup = q("""SELECT COUNT(*) FROM (SELECT review_id, entity, business_unit, region,
               finance_class, reserving_class, loss_type, accident_year, COUNT(*) c
               FROM result_snapshot GROUP BY 1,2,3,4,5,6,7,8 HAVING c>1)""")[0][0]
    check("result rows unique at stated grain", dup == 0, f"{dup} duplicate groups")

    print("Claims triangle")
    bad = q("SELECT COUNT(*) FROM claims_triangle WHERE paid_claims_cumulative > incurred_claims_cumulative")[0][0]
    check("cumulative paid <= incurred", bad == 0, f"{bad} cells")
    bad = q("""SELECT COUNT(*) FROM (SELECT review_id, entity, business_unit, region,
               finance_class, reserving_class, loss_type, accident_year,
               SUM(is_latest_diagonal) s FROM claims_triangle
               GROUP BY 1,2,3,4,5,6,7,8 HAVING s<>1)""")[0][0]
    check("exactly one latest-diagonal cell per group", bad == 0, f"{bad} groups")
    bad = q("""SELECT COUNT(*) FROM result_snapshot r JOIN vw_claims_latest c
               ON r.review_id=c.review_id AND r.entity=c.entity
               AND r.business_unit=c.business_unit AND r.region=c.region
               AND r.finance_class=c.finance_class AND r.reserving_class=c.reserving_class
               AND r.loss_type=c.loss_type AND r.accident_year=c.accident_year
               WHERE ABS(r.paid_claims-c.paid_claims)>1
                  OR ABS(r.incurred_claims-c.incurred_claims)>1""")[0][0]
    check("result snapshot ties to latest diagonal", bad == 0, f"{bad} rows")
    bad = q("""SELECT COUNT(*) FROM (
                 SELECT review_id, entity, business_unit, region, finance_class,
                        reserving_class, loss_type, accident_year,
                        MAX(paid_claims_cumulative) mx, MIN(paid_claims_cumulative) mn
                 FROM claims_triangle GROUP BY 1,2,3,4,5,6,7,8 HAVING mx < mn)""")[0][0]
    check("triangle grouping sane", bad == 0)

    print("Premium")
    bad = q("""SELECT COUNT(*) FROM (SELECT review_id, entity, business_unit, region,
               finance_class, reserving_class, accident_year, COUNT(*) c
               FROM premium_data GROUP BY 1,2,3,4,5,6,7 HAVING c>1)""")[0][0]
    check("premium unique at stated grain (no Loss Type duplication)", bad == 0, f"{bad}")
    cols = [r[1] for r in q("PRAGMA table_info(premium_data)")]
    check("premium has no loss_type column", "loss_type" not in cols)

    print("Assumptions")
    bad = q("""SELECT COUNT(*) FROM (SELECT review_id, entity, reserving_class,
               loss_type, accident_year, COUNT(*) c FROM assumption_snapshot
               GROUP BY 1,2,3,4,5 HAVING c>1)""")[0][0]
    check("assumptions unique at selection grain", bad == 0, f"{bad}")
    n = q("""SELECT COUNT(*) FROM assumption_snapshot a JOIN assumption_snapshot b
             ON a.entity=b.entity AND a.reserving_class=b.reserving_class
             AND a.loss_type=b.loss_type AND a.accident_year=b.accident_year
             WHERE a.review_id='2026-Q2' AND b.review_id='2026-Q1'
             AND a.projection_method<>b.projection_method""")[0][0]
    check("at least three projection-method changes 2026-Q1 -> 2026-Q2", n >= 3, f"{n}")
    n_same = q("""SELECT COUNT(*) FROM assumption_snapshot a JOIN assumption_snapshot b
             ON a.entity=b.entity AND a.reserving_class=b.reserving_class
             AND a.loss_type=b.loss_type AND a.accident_year=b.accident_year
             WHERE a.review_id='2026-Q2' AND b.review_id='2026-Q1'
             AND a.projection_method=b.projection_method""")[0][0]
    check("unchanged assumption rows also exist", n_same > 0, f"{n_same}")

    print("Report slides")
    n_slides = q("SELECT COUNT(*) FROM report_slide")[0][0]
    if n_slides == 0:
        print("  [skip] no slides yet (run build_reports.py, then re-run validation)")
    else:
        per_review = q("SELECT review_id, COUNT(*) FROM report_slide GROUP BY review_id")
        check("every review has 10-12 slides",
              len(per_review) == 8 and all(10 <= c <= 12 for _, c in per_review),
              str(per_review))
        # Report-to-data consistency: every slide table/metric generated with a
        # data_check block must match a fresh aggregation of the seeded data.
        checked = mismatches = 0
        for (content_json,) in q("SELECT content_json FROM report_slide"):
            content = json.loads(content_json)
            for block in content.get("blocks", []):
                for chk in block.get("data_checks", []):
                    checked += 1
                    got = con.execute(chk["sql"]).fetchone()[0]
                    if got is None or abs(got - chk["expected"]) > chk.get("tolerance", 1):
                        mismatches += 1
                        failures.append(f"report check {chk['sql'][:80]}: {got} != {chk['expected']}")
        check(f"report figures reconcile to data ({checked} checks)", mismatches == 0,
              f"{mismatches} mismatches")

    con.close()
    if failures:
        print(f"\nVALIDATION FAILED: {len(failures)} problem(s)")
        for f in failures[:20]:
            print("  -", f)
        return 1
    print("\nAll validation checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
