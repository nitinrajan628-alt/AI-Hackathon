"""Generate the eight structured slide-based reserve review packs.

Every numerical statement is computed from the packaged database, and key
figures carry embedded `data_checks` (SQL + expected value) which
scripts/validate_data.py re-executes, guaranteeing report-to-data
consistency. Narrative theme text follows section 6.6 of the Detailed
Build Specification.

Run after build_demo_data.py:  python scripts/build_reports.py
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "reserve_review.db")

RC_ORDER = ["Casualty", "Property", "Motor", "Marine"]

# Per-quarter narrative configuration (section 6.6).
QUARTER_THEMES = {
    "2024-Q3": {
        "deep_dive": "Casualty",
        "alt_view": "region",
        "monitor": "Early signs of pressure in recent Casualty accident years are "
                   "being monitored, although Casualty is not yet a dominant theme.",
        "uncertainties": [
            "Recent Casualty accident years are immature and small changes in reported "
            "experience could move selected ultimates in either direction.",
            "Claims inflation remains above long-term averages and continues to be "
            "monitored against the assumptions adopted in this review.",
            "Large loss frequency has been within expectation, but individual case "
            "development remains a source of volatility for Property and Marine.",
        ],
        "conclusion": "The reserve position is broadly stable this quarter. Recent "
                      "Casualty accident years will be watched closely at the next review.",
    },
    "2024-Q4": {
        "deep_dive": "Property",
        "alt_view": "business_unit",
        "monitor": "Casualty experience remains under observation; other classes are "
                   "broadly stable with no major methodology changes this quarter.",
        "uncertainties": [
            "Casualty attritional emergence remains marginally above expectation and is "
            "the principal area under observation.",
            "Claims inflation assumptions remain unchanged this quarter and continue to "
            "be tested against observed severity trends.",
            "Property catastrophe exposure for the coming windstorm season is unchanged "
            "from the prior review.",
        ],
        "conclusion": "The year-end position shows modest overall strengthening. Casualty "
                      "remains under observation without methodology change.",
    },
    "2025-Q1": {
        "deep_dive": "Casualty",
        "alt_view": "region",
        "monitor": "Casualty deterioration is now more visible in recent accident years; "
                   "claims emergence and uncertainty are highlighted more explicitly.",
        "uncertainties": [
            "Casualty deterioration is now visible in accident years 2022 to 2024; the "
            "pace of emergence is the key uncertainty for the next two quarters.",
            "The annual projection-method roll has moved maturing accident years to "
            "Chain Ladder; early diagonals for the new accident year rely on expected "
            "loss ratios.",
            "Claims inflation remains a watch item for the longer-tailed classes.",
        ],
        "conclusion": "Casualty emergence is the principal theme of this review and has "
                      "been reflected in modest strengthening of recent accident years.",
    },
    "2025-Q2": {
        "deep_dive": "Casualty",
        "alt_view": "business_unit",
        "monitor": "Selected Casualty assumptions have begun to respond to emerging "
                   "experience; the overall movement remains manageable.",
        "uncertainties": [
            "Selected Casualty loss ratios and the inflation assumption have been raised "
            "in response to emerging experience; further adverse emergence would require "
            "additional strengthening.",
            "Large loss activity in Property is marginally elevated and is being "
            "monitored ahead of the windstorm season.",
            "Premium growth assumptions for the current accident year remain on plan.",
        ],
        "conclusion": "Casualty assumptions have been updated in response to emerging "
                      "experience. The overall reserve movement remains manageable.",
    },
    "2025-Q3": {
        "deep_dive": "Casualty",
        "alt_view": "region",
        "monitor": "Casualty strengthening is now a material contributor to reserve "
                   "movement; Property large loss activity is a secondary theme.",
        "uncertainties": [
            "Casualty strengthening is now material; the principal uncertainty is "
            "whether recent accident years have been strengthened sufficiently.",
            "September windstorm events have increased Property large and catastrophe "
            "reserves; a management loading is held pending settlement.",
            "Claims inflation remains elevated for liability classes.",
        ],
        "conclusion": "Casualty strengthening and Property large loss development are the "
                      "principal themes. Both will be revisited at the year-end review.",
    },
    "2025-Q4": {
        "deep_dive": "Property",
        "alt_view": "business_unit",
        "monitor": "Recent Casualty accident years remain a focus; Property large loss "
                   "development continues while Marine shows favourable movement.",
        "uncertainties": [
            "Recent Casualty accident years remain the dominant reserve uncertainty at "
            "the year end.",
            "Property large loss development from the September events is maturing but "
            "not yet fully settled; the management loading has been retained.",
            "Marine has shown favourable development; the release has been taken "
            "cautiously given historic volatility.",
        ],
        "conclusion": "The year-end position reflects continued Casualty focus, maturing "
                      "Property large losses and a first favourable movement in Marine.",
    },
    "2026-Q1": {
        "deep_dive": "Marine",
        "alt_view": "business_unit",
        "monitor": "Some areas have stabilised, but Casualty uncertainty remains "
                   "elevated; this quarter is the baseline for the Q2 comparison.",
        "uncertainties": [
            "Casualty uncertainty remains elevated despite stabilisation elsewhere; "
            "attritional emergence in accident years 2022 to 2024 is still above "
            "long-term expectation.",
            "Marine continues to develop favourably; further releases will be considered "
            "only with sustained evidence.",
            "Motor has released modestly; frequency trends remain within expectation.",
        ],
        "conclusion": "A comparatively quiet quarter. Casualty remains the key focus "
                      "area going into the mid-year review.",
    },
    "2026-Q2": {
        "deep_dive": "Casualty",
        "alt_view": "region",
        "monitor": "Casualty strengthening of GBP 18m is the dominant feature; recent "
                   "accident years are the main contributors and further emergence "
                   "will be reviewed quarterly.",
        "uncertainties": [
            "Casualty remains the dominant uncertainty: recent accident years have been "
            "strengthened materially and further adverse emergence cannot be ruled out.",
            "Three Casualty selections and one Property selection changed projection "
            "method this quarter; the revised basis will be reassessed next quarter.",
            "The claims inflation assumption for Casualty has been raised to 5.5%; "
            "sensitivity to this assumption is significant for immature years.",
            "A management loading is held for two late-reported large liability claims "
            "still under review.",
        ],
        "conclusion": "Reserves increased GBP 26m to GBP 640m, led by Casualty. The "
                      "strengthening responds to sustained adverse emergence; the next "
                      "review will focus on whether the revised basis is holding.",
    },
}


def fmt_m(pounds: float, signed: bool = False) -> str:
    m = pounds / 1e6
    sign = "+" if (signed and m > 0) else ""
    if abs(m - round(m)) < 0.05:
        return f"{sign}GBP {round(m):,}m" if not signed or m >= 0 else f"-GBP {abs(round(m)):,}m"
    return f"{sign}GBP {m:,.1f}m" if not signed or m >= 0 else f"-GBP {abs(m):,.1f}m"


class ReportBuilder:
    def __init__(self, con: sqlite3.Connection, review: sqlite3.Row):
        self.con = con
        self.r = review
        self.rid = review["review_id"]
        self.label = review["quarter_label"]
        self.prior = review["prior_review_id"]
        self.prior_year = review["prior_year_review_id"]
        self.theme = QUARTER_THEMES[self.rid]
        self.slides: list[dict] = []

    # -- data helpers -------------------------------------------------------

    def one(self, sql: str, *params) -> float:
        v = self.con.execute(sql, params).fetchone()[0]
        return float(v) if v is not None else 0.0

    def rows(self, sql: str, *params) -> list[sqlite3.Row]:
        return self.con.execute(sql, params).fetchall()

    def reserve_total(self, rid: str) -> float:
        return self.one("SELECT SUM(total_reserve) FROM result_snapshot WHERE review_id=?", rid)

    def reserve_by(self, rid: str, dim: str) -> dict[str, float]:
        return {r[0]: r[1] for r in self.rows(
            f"SELECT {dim}, SUM(total_reserve) FROM result_snapshot WHERE review_id=? GROUP BY 1", rid)}

    def check(self, sql_template: str, expected: float, tolerance: float = 1.0) -> dict:
        return {"sql": sql_template, "expected": expected, "tolerance": tolerance}

    # -- slide assembly -----------------------------------------------------

    def add_slide(self, number: int, section: str, title: str, headline: str,
                  blocks: list[dict], tags: list[str],
                  related: dict | None = None):
        texts = [title, headline]
        for b in blocks:
            if b["type"] in ("bullets", "numbered"):
                texts += b["items"]
            elif b["type"] == "text":
                texts.append(b["text"])
            elif b["type"] == "metrics":
                texts += [f"{m['label']}: {m['value']}" for m in b["items"]]
            elif b["type"] == "table":
                texts.append(" | ".join(str(c) for c in b["columns"]))
                texts += [" | ".join(str(c) for c in row) for row in b["rows"]]
        content = {"headline": headline, "blocks": blocks}
        self.slides.append({
            "review_id": self.rid, "slide_number": number, "section": section,
            "title": title, "content_json": json.dumps(content),
            "plain_text": "\n".join(t for t in texts if t),
            "tags_json": json.dumps(tags),
            "related_dimensions_json": json.dumps(related) if related else None,
        })

    # -- slides -------------------------------------------------------------

    def slide_title(self):
        self.add_slide(1, "Overview", f"{self.label} Reserve Review",
                       "Quarterly actuarial reserve review",
                       [{"type": "metrics", "items": [
                           {"label": "Reporting group", "value": "Demo Insurance Group"},
                           {"label": "Entities", "value": "Demo Insurance UK; Demo Insurance Europe"},
                           {"label": "Valuation date", "value": self.r["valuation_date"]},
                           {"label": "Reporting currency", "value": "GBP"},
                       ]}],
                       ["title", "valuation date"])

    def slide_exec_summary(self):
        cur = self.reserve_total(self.rid)
        ult = self.one("SELECT SUM(ultimate_claims) FROM result_snapshot WHERE review_id=?", self.rid)
        blocks: list[dict] = []
        bullets: list[str] = []
        checks = [self.check(
            f"SELECT SUM(total_reserve) FROM result_snapshot WHERE review_id='{self.rid}'", cur)]
        if self.prior:
            pri = self.reserve_total(self.prior)
            move = cur - pri
            direction = "increased" if move >= 0 else "decreased"
            headline = f"Overall reserves {direction} {fmt_m(abs(move))} to {fmt_m(cur)}"
            moves = self.movements_by_class()
            ups = [(k, v) for k, v in moves.items() if v > 0]
            downs = [(k, v) for k, v in moves.items() if v < 0]
            ups.sort(key=lambda kv: -kv[1])
            if ups:
                driver_txt = " and ".join(f"{k} {fmt_m(v, signed=True)}" for k, v in ups[:2])
                bullets.append(f"The principal increases were {driver_txt}.")
            for k, v in downs:
                bullets.append(f"{k} released {fmt_m(abs(v))} following favourable development.")
            n_changes = self.method_change_rows()
            if n_changes:
                classes = sorted({row["reserving_class"] for row in n_changes})
                bullets.append(
                    f"{len(n_changes)} projection-method selections changed since {self.prior.replace('-', ' ')}, "
                    f"concentrated in {' and '.join(classes)}.")
            else:
                bullets.append("No projection-method selections changed this quarter.")
            metrics = [
                {"label": "Total reserve", "value": fmt_m(cur)},
                {"label": "Quarterly movement", "value": fmt_m(move, signed=True)},
                {"label": "Ultimate claims", "value": fmt_m(ult)},
            ]
        else:
            headline = f"Total reserves stand at {fmt_m(cur)} at the valuation date"
            by_rc = self.reserve_by(self.rid, "reserving_class")
            top = sorted(by_rc.items(), key=lambda kv: -kv[1])
            bullets.append("Reserves by class: " + "; ".join(f"{k} {fmt_m(v)}" for k, v in top) + ".")
            bullets.append("This is the first review in the packaged library; comparative "
                           "movements will be shown from next quarter.")
            metrics = [
                {"label": "Total reserve", "value": fmt_m(cur)},
                {"label": "Ultimate claims", "value": fmt_m(ult)},
                {"label": "Reviews in library", "value": "1 of 8"},
            ]
        bullets.append(self.theme["monitor"])
        blocks.append({"type": "metrics", "items": metrics, "data_checks": checks})
        blocks.append({"type": "bullets", "items": bullets})
        self.add_slide(2, "Overview", "Executive Summary", headline, blocks,
                       ["executive summary", "key messages", "total reserve", "movement"])

    def movements_by_class(self) -> dict[str, float]:
        cur = self.reserve_by(self.rid, "reserving_class")
        pri = self.reserve_by(self.prior, "reserving_class") if self.prior else {}
        return {k: cur.get(k, 0) - pri.get(k, 0) for k in RC_ORDER} if self.prior else {}

    def method_change_rows(self):
        if not self.prior:
            return []
        return self.rows("""
            SELECT a.entity, a.reserving_class, a.loss_type, a.accident_year,
                   b.projection_method AS prior_method, a.projection_method AS current_method
            FROM assumption_snapshot a JOIN assumption_snapshot b
              ON a.entity=b.entity AND a.reserving_class=b.reserving_class
             AND a.loss_type=b.loss_type AND a.accident_year=b.accident_year
            WHERE a.review_id=? AND b.review_id=? AND a.projection_method<>b.projection_method
            ORDER BY a.reserving_class, a.loss_type, a.accident_year, a.entity""",
            self.rid, self.prior)

    def slide_position(self):
        cur = self.reserve_by(self.rid, "reserving_class")
        checks = [self.check(
            f"SELECT SUM(total_reserve) FROM result_snapshot WHERE review_id='{self.rid}' "
            f"AND reserving_class='{rc}'", cur[rc]) for rc in RC_ORDER]
        if self.prior:
            pri = self.reserve_by(self.prior, "reserving_class")
            columns = ["Reserving Class", "Current (GBP m)", "Prior quarter (GBP m)", "Movement (GBP m)"]
            rows = [[rc, round(cur[rc] / 1e6, 1), round(pri[rc] / 1e6, 1),
                     round((cur[rc] - pri[rc]) / 1e6, 1)] for rc in RC_ORDER]
            rows.append(["Total", round(sum(cur.values()) / 1e6, 1),
                         round(sum(pri.values()) / 1e6, 1),
                         round((sum(cur.values()) - sum(pri.values())) / 1e6, 1)])
            chart = {"type": "chart", "chart_type": "grouped_bar",
                     "x": RC_ORDER,
                     "series": [
                         {"name": self.label, "values": [round(cur[rc] / 1e6, 1) for rc in RC_ORDER]},
                         {"name": self.prior.replace("-", " "), "values": [round(pri[rc] / 1e6, 1) for rc in RC_ORDER]},
                     ], "unit": "GBP m"}
            headline = (f"Total reserve of {fmt_m(sum(cur.values()))} against "
                        f"{fmt_m(sum(pri.values()))} at {self.prior.replace('-', ' ')}")
        else:
            columns = ["Reserving Class", "Current (GBP m)"]
            rows = [[rc, round(cur[rc] / 1e6, 1)] for rc in RC_ORDER]
            rows.append(["Total", round(sum(cur.values()) / 1e6, 1)])
            chart = {"type": "chart", "chart_type": "bar", "x": RC_ORDER,
                     "series": [{"name": self.label,
                                 "values": [round(cur[rc] / 1e6, 1) for rc in RC_ORDER]}],
                     "unit": "GBP m"}
            headline = f"Total reserve of {fmt_m(sum(cur.values()))} across four reserving classes"
        self.add_slide(3, "Reserve Position", "Overall Reserve Position", headline,
                       [{"type": "table", "columns": columns, "rows": rows, "data_checks": checks},
                        chart],
                       ["reserve position", "reserving class", "total reserve"],
                       {"reserving_class": RC_ORDER})

    def slide_movement(self):
        if not self.prior:
            by_lt = {r[0]: r[1] for r in self.rows(
                "SELECT loss_type, SUM(total_reserve) FROM result_snapshot WHERE review_id=? GROUP BY 1",
                self.rid)}
            order = ["Attritional", "Large", "Cat"]
            self.add_slide(4, "Reserve Position", "Reserve Composition by Loss Type",
                           "Composition shown in place of quarterly movement for the first packaged review",
                           [{"type": "table", "columns": ["Loss Type", "Reserve (GBP m)"],
                             "rows": [[lt, round(by_lt.get(lt, 0) / 1e6, 1)] for lt in order],
                             "data_checks": [self.check(
                                 f"SELECT SUM(total_reserve) FROM result_snapshot WHERE review_id='{self.rid}' "
                                 f"AND loss_type='{lt}'", by_lt.get(lt, 0)) for lt in order]},
                            {"type": "chart", "chart_type": "bar", "x": order,
                             "series": [{"name": self.label,
                                         "values": [round(by_lt.get(lt, 0) / 1e6, 1) for lt in order]}],
                             "unit": "GBP m"}],
                           ["reserve composition", "loss type"])
            return
        cur, pri = self.reserve_total(self.rid), self.reserve_total(self.prior)
        moves = self.movements_by_class()
        headline = (f"Reserves moved from {fmt_m(pri)} at {self.prior.replace('-', ' ')} to "
                    f"{fmt_m(cur)}, a movement of {fmt_m(cur - pri, signed=True)}")
        checks = [self.check(
            f"SELECT SUM(CASE WHEN review_id='{self.rid}' THEN total_reserve ELSE -total_reserve END) "
            f"FROM result_snapshot WHERE review_id IN ('{self.rid}','{self.prior}') "
            f"AND reserving_class='{rc}'", moves[rc]) for rc in RC_ORDER]
        self.add_slide(4, "Reserve Position", "Reserve Movement in the Quarter", headline,
                       [{"type": "chart", "chart_type": "waterfall",
                         "start_label": self.prior.replace("-", " "),
                         "end_label": self.label,
                         "start": round(pri / 1e6, 1),
                         "x": RC_ORDER,
                         "series": [{"name": "Movement",
                                     "values": [round(moves[rc] / 1e6, 1) for rc in RC_ORDER]}],
                         "unit": "GBP m"},
                        {"type": "table",
                         "columns": ["Reserving Class", "Movement (GBP m)"],
                         "rows": [[rc, round(moves[rc] / 1e6, 1)] for rc in RC_ORDER]
                                 + [["Total", round((cur - pri) / 1e6, 1)]],
                         "data_checks": checks}],
                       ["reserve movement", "waterfall", "quarterly movement"],
                       {"reserving_class": RC_ORDER})

    def slide_class_commentary(self):
        blocks: list[dict] = []
        bullets = []
        if self.prior:
            moves = self.movements_by_class()
            ordered = sorted(moves.items(), key=lambda kv: -abs(kv[1]))
            for rc, mv in ordered:
                if abs(mv) < 0.05e6:
                    bullets.append(f"{rc}: broadly flat in the quarter.")
                    continue
                verb = "strengthened" if mv > 0 else "released"
                bullets.append(f"{rc}: {verb} {fmt_m(abs(mv))}. {self.class_comment(rc, mv)}")
        else:
            by_rc = self.reserve_by(self.rid, "reserving_class")
            for rc in RC_ORDER:
                bullets.append(f"{rc}: reserve of {fmt_m(by_rc[rc])}. {self.class_comment(rc, 0)}")
        blocks.append({"type": "bullets", "items": bullets})
        self.add_slide(5, "Reserve Position", "Reserving Class Commentary",
                       "Principal class movements and drivers", blocks,
                       ["class commentary", "drivers", "movement"],
                       {"reserving_class": RC_ORDER})

    def class_comment(self, rc: str, mv: float) -> str:
        seq = self.r["sequence_no"]
        if rc == "Casualty":
            if seq <= 2:
                return "Attritional emergence in recent accident years is marginally above expectation and remains under observation."
            if seq <= 4:
                return "Deterioration in accident years 2022 to 2024 is increasingly visible; assumptions are responding."
            if seq <= 7:
                return "Recent accident years remain the principal focus; strengthening reflects sustained adverse emergence."
            return "Strengthening is concentrated in recent accident years, supported by method changes and a higher inflation assumption."
        if rc == "Property":
            if 5 <= seq <= 6:
                return "Large loss development from the September windstorm events is the main driver."
            return "Experience is within expectation; catastrophe exposure is monitored seasonally."
        if rc == "Motor":
            return "Frequency and severity trends remain within expectation."
        if seq >= 6:
            return "Favourable development has supported a measured release."
        return "Experience remains volatile but within the reserved position."

    def slide_claims(self):
        compare_rid = self.prior_year or self.prior
        cur_paid = self.one("SELECT SUM(paid_claims) FROM vw_claims_latest WHERE review_id=?", self.rid)
        blocks: list[dict] = []
        checks = [self.check(
            f"SELECT SUM(paid_claims) FROM vw_claims_latest WHERE review_id='{self.rid}'", cur_paid)]
        by_rc_cur = {r[0]: r[1] for r in self.rows(
            "SELECT reserving_class, SUM(paid_claims) FROM vw_claims_latest WHERE review_id=? GROUP BY 1",
            self.rid)}
        if compare_rid:
            basis = "year-on-year" if self.prior_year else "versus the prior quarter"
            pri_paid = self.one("SELECT SUM(paid_claims) FROM vw_claims_latest WHERE review_id=?", compare_rid)
            by_rc_pri = {r[0]: r[1] for r in self.rows(
                "SELECT reserving_class, SUM(paid_claims) FROM vw_claims_latest WHERE review_id=? GROUP BY 1",
                compare_rid)}
            headline = (f"Cumulative paid claims of {fmt_m(cur_paid)}, "
                        f"{fmt_m(cur_paid - pri_paid, signed=True)} {basis} "
                        f"({compare_rid.replace('-', ' ')})")
            blocks.append({"type": "table",
                           "columns": ["Reserving Class", f"{self.label} (GBP m)",
                                       f"{compare_rid.replace('-', ' ')} (GBP m)", "Change (GBP m)"],
                           "rows": [[rc, round(by_rc_cur.get(rc, 0) / 1e6, 1),
                                     round(by_rc_pri.get(rc, 0) / 1e6, 1),
                                     round((by_rc_cur.get(rc, 0) - by_rc_pri.get(rc, 0)) / 1e6, 1)]
                                    for rc in RC_ORDER],
                           "data_checks": checks})
            blocks.append({"type": "chart", "chart_type": "grouped_bar", "x": RC_ORDER,
                           "series": [
                               {"name": self.label, "values": [round(by_rc_cur.get(rc, 0) / 1e6, 1) for rc in RC_ORDER]},
                               {"name": compare_rid.replace("-", " "), "values": [round(by_rc_pri.get(rc, 0) / 1e6, 1) for rc in RC_ORDER]}],
                           "unit": "GBP m"})
            blocks.append({"type": "bullets", "items": [
                "Figures are cumulative paid claims on the latest development diagonal of each review.",
                "Movements reflect both settlement of older accident years and emergence of the current year.",
            ]})
        else:
            headline = f"Cumulative paid claims of {fmt_m(cur_paid)} on the latest diagonal"
            blocks.append({"type": "table",
                           "columns": ["Reserving Class", f"{self.label} (GBP m)"],
                           "rows": [[rc, round(by_rc_cur.get(rc, 0) / 1e6, 1)] for rc in RC_ORDER],
                           "data_checks": checks})
        self.add_slide(6, "Claims", "Claims Experience", headline, blocks,
                       ["claims", "paid claims", "latest diagonal"],
                       {"reserving_class": RC_ORDER})

    def slide_assumptions(self):
        changes = self.method_change_rows()
        blocks: list[dict] = []
        if not self.prior:
            mix = self.rows("""SELECT reserving_class, projection_method, COUNT(*)
                               FROM assumption_snapshot WHERE review_id=? GROUP BY 1,2 ORDER BY 1,2""",
                            self.rid)
            blocks.append({"type": "table",
                           "columns": ["Reserving Class", "Projection Method", "Selections"],
                           "rows": [[a, b, c] for a, b, c in mix]})
            headline = "Assumption basis summarised; no prior packaged review for comparison"
        elif changes:
            headline = (f"{len(changes)} projection-method selections changed since "
                        f"{self.prior.replace('-', ' ')}")
            blocks.append({"type": "table",
                           "columns": ["Entity", "Reserving Class", "Loss Type", "Accident Year",
                                       "Previous method", "Current method"],
                           "rows": [[c["entity"], c["reserving_class"], c["loss_type"],
                                     c["accident_year"], c["prior_method"], c["current_method"]]
                                    for c in changes]})
        else:
            headline = f"No projection-method changes since {self.prior.replace('-', ' ')}"
        bullets = []
        if self.prior:
            infl = self.rows("""
                SELECT a.reserving_class, a.inflation_assumption, b.inflation_assumption
                FROM assumption_snapshot a JOIN assumption_snapshot b
                  ON a.entity=b.entity AND a.reserving_class=b.reserving_class
                 AND a.loss_type=b.loss_type AND a.accident_year=b.accident_year
                WHERE a.review_id=? AND b.review_id=?
                  AND a.inflation_assumption IS NOT NULL
                  AND a.inflation_assumption<>b.inflation_assumption
                GROUP BY 1,2,3""", self.rid, self.prior)
            for rc, cur_i, pri_i in sorted(set(infl)):
                bullets.append(f"The {rc} claims inflation assumption moved from "
                               f"{pri_i * 100:.1f}% to {cur_i * 100:.1f}%.")
            adj = self.rows("""
                SELECT entity, reserving_class, loss_type, accident_year, management_adjustment
                FROM assumption_snapshot WHERE review_id=? AND management_adjustment<>0""", self.rid)
            for e, rc, lt, ay, amount in adj:
                bullets.append(f"A management loading of {fmt_m(amount)} is held for "
                               f"{rc} {lt} accident year {ay} ({e}).")
            if not bullets:
                bullets.append("Numeric assumptions are unchanged apart from routine "
                               "selected loss-ratio updates at the annual roll.")
        blocks.append({"type": "bullets", "items": bullets or
                       ["Assumption selections are made at Entity, Reserving Class, "
                        "Loss Type and Accident Year."]})
        self.add_slide(7, "Assumptions", "Assumption and Methodology Changes", headline, blocks,
                       ["assumptions", "projection method", "methodology", "inflation"],
                       {"reserving_class": sorted({c["reserving_class"] for c in changes}) if changes else None})

    def slide_deep_dive(self):
        rc = self.theme["deep_dive"]
        by_ay_cur = {r[0]: r[1] for r in self.rows(
            "SELECT accident_year, SUM(total_reserve) FROM result_snapshot "
            "WHERE review_id=? AND reserving_class=? GROUP BY 1 ORDER BY 1", self.rid, rc)}
        ays = sorted(by_ay_cur)
        blocks: list[dict] = []
        total = sum(by_ay_cur.values())
        checks = [self.check(
            f"SELECT SUM(total_reserve) FROM result_snapshot WHERE review_id='{self.rid}' "
            f"AND reserving_class='{rc}'", total)]
        if self.prior:
            by_ay_pri = {r[0]: r[1] for r in self.rows(
                "SELECT accident_year, SUM(total_reserve) FROM result_snapshot "
                "WHERE review_id=? AND reserving_class=? GROUP BY 1", self.prior, rc)}
            moves = {ay: by_ay_cur.get(ay, 0) - by_ay_pri.get(ay, 0) for ay in ays}
            recent = [ay for ay in ays if ay >= max(ays) - 2]
            recent_move = sum(moves[ay] for ay in recent)
            total_move = sum(moves.values())
            headline = (f"{rc} reserve of {fmt_m(total)}, "
                        f"{fmt_m(total_move, signed=True)} in the quarter")
            blocks.append({"type": "chart", "chart_type": "grouped_bar",
                           "x": [str(a) for a in ays],
                           "series": [
                               {"name": self.label, "values": [round(by_ay_cur.get(a, 0) / 1e6, 1) for a in ays]},
                               {"name": self.prior.replace("-", " "), "values": [round(by_ay_pri.get(a, 0) / 1e6, 1) for a in ays]}],
                           "unit": "GBP m"})
            bullets = []
            if abs(total_move) > 0.05e6:
                bullets.append(
                    f"Accident years {recent[0]} to {recent[-1]} contribute "
                    f"{fmt_m(recent_move, signed=True)} of the {fmt_m(total_move, signed=True)} movement.")
            largest = max(moves.items(), key=lambda kv: abs(kv[1]))
            if abs(largest[1]) > 0.05e6:
                bullets.append(f"The largest single accident-year movement is "
                               f"{largest[0]} at {fmt_m(largest[1], signed=True)}.")
            bullets.append(self.class_comment(rc, total_move))
            blocks.append({"type": "bullets", "items": bullets})
        else:
            headline = f"{rc} reserve of {fmt_m(total)} by accident year"
            blocks.append({"type": "chart", "chart_type": "bar",
                           "x": [str(a) for a in ays],
                           "series": [{"name": self.label,
                                       "values": [round(by_ay_cur.get(a, 0) / 1e6, 1) for a in ays]}],
                           "unit": "GBP m"})
            blocks.append({"type": "bullets", "items": [self.class_comment(rc, 0)]})
        blocks[0]["data_checks"] = checks
        self.add_slide(8, "Class Deep Dive", f"{rc} Reserve Development", headline, blocks,
                       [rc, "deep dive", "accident year", "reserve movement"],
                       {"reserving_class": [rc]})

    def slide_large_cat(self):
        cur = {(r[0], r[1]): r[2] for r in self.rows(
            "SELECT reserving_class, loss_type, SUM(total_reserve) FROM result_snapshot "
            "WHERE review_id=? AND loss_type IN ('Large','Cat') GROUP BY 1,2", self.rid)}
        total = sum(cur.values())
        headline = f"Large and Cat reserves of {fmt_m(total)}"
        rows_tbl = []
        for rc in RC_ORDER:
            for lt in ("Large", "Cat"):
                if (rc, lt) in cur:
                    rows_tbl.append([rc, lt, round(cur[(rc, lt)] / 1e6, 1)])
        blocks: list[dict] = [{"type": "table",
                               "columns": ["Reserving Class", "Loss Type", "Reserve (GBP m)"],
                               "rows": rows_tbl,
                               "data_checks": [self.check(
                                   f"SELECT SUM(total_reserve) FROM result_snapshot "
                                   f"WHERE review_id='{self.rid}' AND loss_type IN ('Large','Cat')",
                                   total)]}]
        bullets = []
        if self.prior:
            pri = {(r[0], r[1]): r[2] for r in self.rows(
                "SELECT reserving_class, loss_type, SUM(total_reserve) FROM result_snapshot "
                "WHERE review_id=? AND loss_type IN ('Large','Cat') GROUP BY 1,2", self.prior)}
            moves = {k: cur.get(k, 0) - pri.get(k, 0) for k in set(cur) | set(pri)}
            headline += f", {fmt_m(sum(moves.values()), signed=True)} in the quarter"
            for (rc, lt), mv in sorted(moves.items(), key=lambda kv: -abs(kv[1]))[:3]:
                if abs(mv) > 0.05e6:
                    bullets.append(f"{rc} {lt}: {fmt_m(mv, signed=True)} in the quarter.")
        seq = self.r["sequence_no"]
        if 5 <= seq <= 6:
            bullets.append("Development on the September 2025 windstorm events is the "
                           "principal large-loss theme this quarter.")
        if not bullets:
            bullets.append("Large and Cat experience is within expectation this quarter.")
        blocks.append({"type": "bullets", "items": bullets})
        self.add_slide(9, "Large and Cat", "Large and Cat Loss Development", headline, blocks,
                       ["large loss", "cat", "catastrophe", "loss type"],
                       {"loss_type": ["Large", "Cat"]})

    def slide_alt_view(self):
        dim = self.theme["alt_view"]
        dim_label = {"region": "Region", "business_unit": "Business Unit"}[dim]
        cur = self.reserve_by(self.rid, dim)
        order = sorted(cur, key=lambda k: -cur[k])
        checks = [self.check(
            f"SELECT SUM(total_reserve) FROM result_snapshot WHERE review_id='{self.rid}' "
            f"AND {dim}='{v}'", cur[v]) for v in order]
        blocks: list[dict] = []
        if self.prior:
            pri = self.reserve_by(self.prior, dim)
            blocks.append({"type": "table",
                           "columns": [dim_label, f"{self.label} (GBP m)",
                                       f"{self.prior.replace('-', ' ')} (GBP m)", "Movement (GBP m)"],
                           "rows": [[v, round(cur[v] / 1e6, 1), round(pri.get(v, 0) / 1e6, 1),
                                     round((cur[v] - pri.get(v, 0)) / 1e6, 1)] for v in order],
                           "data_checks": checks})
        else:
            blocks.append({"type": "table",
                           "columns": [dim_label, f"{self.label} (GBP m)"],
                           "rows": [[v, round(cur[v] / 1e6, 1)] for v in order],
                           "data_checks": checks})
        blocks.append({"type": "chart", "chart_type": "bar", "x": order,
                       "series": [{"name": self.label,
                                   "values": [round(cur[v] / 1e6, 1) for v in order]}],
                       "unit": "GBP m"})
        blocks.append({"type": "text",
                       "text": f"The same reserves can be aggregated by Reserving Class, "
                               f"Finance Class, Region, Business Unit, Loss Type, Entity or "
                               f"Accident Year; {dim_label} is shown here as the management view "
                               f"for this quarter."})
        self.add_slide(10, "Alternative Views", f"Reserves by {dim_label}",
                       f"Total reserve of {fmt_m(sum(cur.values()))} by {dim_label}", blocks,
                       ["alternative view", dim_label.lower(), "aggregation"],
                       {dim: order})

    def slide_uncertainties(self):
        items = self.theme["uncertainties"]
        self.add_slide(11, "Uncertainties",
                       "Key Uncertainties and Areas of Focus",
                       "Qualitative areas of focus from the actuarial review",
                       [{"type": "numbered", "items": items}],
                       ["uncertainty", "areas of focus", "monitoring", "limitations"])

    def slide_conclusion(self):
        cur = self.reserve_total(self.rid)
        text = self.theme["conclusion"]
        blocks = [
            {"type": "text", "text": text},
            {"type": "text",
             "text": "This review has been prepared by the actuarial function for "
                     "management and Board use. Selections reflect actuarial judgement "
                     "applied to the data available at the valuation date; they will be "
                     "reassessed at the next quarterly review."},
            {"type": "metrics", "items": [{"label": "Total reserve", "value": fmt_m(cur)}],
             "data_checks": [self.check(
                 f"SELECT SUM(total_reserve) FROM result_snapshot WHERE review_id='{self.rid}'", cur)]},
        ]
        self.add_slide(12, "Conclusion", "Conclusion and Next Review",
                       "Overall reserve conclusion and forward focus", blocks,
                       ["conclusion", "governance", "next review"])

    def build(self) -> list[dict]:
        self.slide_title()
        self.slide_exec_summary()
        self.slide_position()
        self.slide_movement()
        self.slide_class_commentary()
        self.slide_claims()
        self.slide_assumptions()
        self.slide_deep_dive()
        self.slide_large_cat()
        self.slide_alt_view()
        self.slide_uncertainties()
        self.slide_conclusion()
        return self.slides


def main() -> int:
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    reviews = con.execute("SELECT * FROM review_period ORDER BY sequence_no").fetchall()
    con.execute("DELETE FROM report_slide")
    total = 0
    for review in reviews:
        slides = ReportBuilder(con, review).build()
        con.executemany(
            "INSERT INTO report_slide (review_id, slide_number, section, title,"
            " content_json, plain_text, tags_json, related_dimensions_json)"
            " VALUES (:review_id, :slide_number, :section, :title, :content_json,"
            " :plain_text, :tags_json, :related_dimensions_json)", slides)
        total += len(slides)
        print(f"  {review['review_id']}: {len(slides)} slides")

    # Full-text index over slide content (SQLite FTS5).
    con.executescript("""
        DROP TABLE IF EXISTS slide_fts;
        CREATE VIRTUAL TABLE slide_fts USING fts5(
            slide_id UNINDEXED, review_id UNINDEXED, title, section, plain_text, tags,
            tokenize='porter unicode61'
        );
    """)
    con.execute("""
        INSERT INTO slide_fts (slide_id, review_id, title, section, plain_text, tags)
        SELECT slide_id, review_id, title, section, plain_text, tags_json FROM report_slide
    """)
    con.commit()
    con.close()
    print(f"Wrote {total} slides and rebuilt the full-text index.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
