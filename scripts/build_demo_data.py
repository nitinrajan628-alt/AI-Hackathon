"""Deterministic demonstration-data generator.

Builds data/reserve_review.db with eight quarterly review snapshots whose
totals reconcile exactly to the narrative in the Detailed Build
Specification (section 6): total reserve GBP 614m at 2026 Q1 rising to
GBP 640m at 2026 Q2, class movements Casualty +18m / Property +7m /
Motor +4m / Marine -3m, and Finance Class movements Commercial +14m /
Specialty +7m / Personal +4m / Reinsurance +1m.

All allocation is integer-pound largest-remainder, so every aggregate is
exact. Leaf-level variation comes from stable hash-based jitter, not RNG
state, so the build is reproducible byte-for-byte.

Run:  python scripts/build_demo_data.py
"""
from __future__ import annotations

import hashlib
import os
import sqlite3
import sys

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "reserve_review.db")

# ---------------------------------------------------------------------------
# Review periods
# ---------------------------------------------------------------------------

REVIEWS = [
    # (review_id, label, valuation_date, sequence, prior, prior_year)
    ("2024-Q3", "2024 Q3", "2024-09-30", 1, None, None),
    ("2024-Q4", "2024 Q4", "2024-12-31", 2, "2024-Q3", None),
    ("2025-Q1", "2025 Q1", "2025-03-31", 3, "2024-Q4", None),
    ("2025-Q2", "2025 Q2", "2025-06-30", 4, "2025-Q1", None),
    ("2025-Q3", "2025 Q3", "2025-09-30", 5, "2025-Q2", "2024-Q3"),
    ("2025-Q4", "2025 Q4", "2025-12-31", 6, "2025-Q3", "2024-Q4"),
    ("2026-Q1", "2026 Q1", "2026-03-31", 7, "2025-Q4", "2025-Q1"),
    ("2026-Q2", "2026 Q2", "2026-06-30", 8, "2026-Q1", "2025-Q2"),
]
DEFAULT_REVIEW = "2026-Q2"
FIRST_AY = 2017

ENTITIES = ["Demo Insurance UK", "Demo Insurance Europe"]
REGIONS_BY_ENTITY = {
    "Demo Insurance UK": [("UK and Ireland", 0.80), ("International", 0.20)],
    "Demo Insurance Europe": [("Continental Europe", 0.85), ("International", 0.15)],
}
ENTITY_SHARE = {  # share of each reserving class written by the UK entity
    "Motor": 0.75, "Property": 0.60, "Casualty": 0.55, "Marine": 0.50,
}
BU_BY_FC = {
    "Personal Lines": "Retail",
    "Commercial Lines": "Commercial",
    "Specialty Lines": "Specialty",
    "Reinsurance": "Specialty",
}

# Reserve narrative by Reserving Class, GBP millions, one value per review.
RC_RESERVE_M = {
    "Motor":    [148, 149, 149, 150, 150, 151, 150, 154],
    "Property": [138, 139, 141, 142, 146, 149, 150, 157],
    "Casualty": [196, 199, 204, 208, 212, 214, 220, 238],
    "Marine":   [98,  98,  98,  98,  98,  96,  94,  91],
}

# Finance Class structure within each Reserving Class. Shares apply to
# reviews 1..7; the 2026 Q2 position is the 2026 Q1 position plus the
# specified movement (GBP millions), which reconciles the +26m movement to
# Commercial +14 / Specialty +7 / Personal +4 / Reinsurance +1.
FC_STRUCTURE = {
    "Motor": [("Personal Lines", 0.70, 3), ("Commercial Lines", 0.30, 1)],
    "Property": [("Personal Lines", 0.40, 1), ("Commercial Lines", 0.52, 6), ("Reinsurance", 0.08, 0)],
    "Casualty": [("Commercial Lines", 0.60, 9), ("Specialty Lines", 0.30, 8), ("Reinsurance", 0.10, 1)],
    "Marine": [("Commercial Lines", 24 / 94, -2), ("Specialty Lines", 70 / 94, -1)],
}

# Loss-type reserve shares by class. Property Large drifts up from 2025 Q3
# to support the Large-loss narrative; other classes are stable.
def loss_type_shares(rc: str, q_idx: int) -> list[tuple[str, float]]:
    if rc == "Motor":
        return [("Attritional", 0.80), ("Large", 0.20)]
    if rc == "Property":
        large = [0.28, 0.28, 0.28, 0.28, 0.30, 0.31, 0.31, 0.32][q_idx]
        return [("Attritional", 1 - 0.20 - large), ("Large", large), ("Cat", 0.20)]
    if rc == "Casualty":
        return [("Attritional", 0.55), ("Large", 0.45)]
    return [("Attritional", 0.45), ("Large", 0.40), ("Cat", 0.15)]  # Marine


# Accident-year weight decay by (class, loss type): weight = decay ** age.
AY_DECAY = {
    ("Motor", "Attritional"): 0.55, ("Motor", "Large"): 0.65,
    ("Property", "Attritional"): 0.60, ("Property", "Large"): 0.70, ("Property", "Cat"): 0.65,
    ("Casualty", "Attritional"): 0.75, ("Casualty", "Large"): 0.80,
    ("Marine", "Attritional"): 0.65, ("Marine", "Large"): 0.70, ("Marine", "Cat"): 0.60,
}

# Casualty deterioration: recent accident years (age 1-4) receive a growing
# weight multiplier across the eight quarters, concentrating the 2026 Q2
# strengthening in recent accident years.
CASUALTY_RECENT_BOOST = [1.00, 1.05, 1.12, 1.18, 1.25, 1.30, 1.35, 1.60]

# Annual paid-settlement speed by (class, loss type) for the payment curve.
SETTLEMENT = {
    ("Motor", "Attritional"): 0.55, ("Motor", "Large"): 0.35,
    ("Property", "Attritional"): 0.50, ("Property", "Large"): 0.40, ("Property", "Cat"): 0.45,
    ("Casualty", "Attritional"): 0.30, ("Casualty", "Large"): 0.20,
    ("Marine", "Attritional"): 0.35, ("Marine", "Large"): 0.30, ("Marine", "Cat"): 0.40,
}

# Average claim severity (GBP) for cumulative count derivation.
SEVERITY = {
    ("Motor", "Attritional"): 9_000, ("Motor", "Large"): 180_000,
    ("Property", "Attritional"): 15_000, ("Property", "Large"): 300_000, ("Property", "Cat"): 450_000,
    ("Casualty", "Attritional"): 25_000, ("Casualty", "Large"): 400_000,
    ("Marine", "Attritional"): 30_000, ("Marine", "Large"): 350_000, ("Marine", "Cat"): 600_000,
}

# Annual written-premium plan by class at the first accident year (GBP),
# growing 4% per accident year.
PREMIUM_BASE = {"Motor": 250e6, "Property": 210e6, "Casualty": 240e6, "Marine": 120e6}
PREMIUM_GROWTH = 1.04

# Claims inflation assumption by class and review (Casualty rises with the
# deterioration narrative).
INFLATION = {
    "Motor":    [0.030] * 8,
    "Property": [0.035] * 8,
    "Casualty": [0.035, 0.035, 0.035, 0.040, 0.040, 0.045, 0.045, 0.055],
    "Marine":   [0.030] * 8,
}

# Projection-method overrides for 2026-Q2 (at least three rows must change
# between 2026 Q1 and 2026 Q2; ages are identical between those reviews so
# every change is deliberate).
METHOD_OVERRIDES_2026Q2 = {
    ("Demo Insurance UK", "Casualty", "Attritional", 2023): "Bornhuetter-Ferguson",
    ("Demo Insurance Europe", "Casualty", "Attritional", 2023): "Bornhuetter-Ferguson",
    ("Demo Insurance UK", "Casualty", "Large", 2022): "Bornhuetter-Ferguson",
    ("Demo Insurance UK", "Property", "Large", 2024): "Chain Ladder",
}
OVERRIDE_COMMENTARY = {
    ("Demo Insurance UK", "Casualty", "Attritional", 2023):
        "Moved to Bornhuetter-Ferguson in response to continued adverse attritional emergence.",
    ("Demo Insurance Europe", "Casualty", "Attritional", 2023):
        "Moved to Bornhuetter-Ferguson in response to continued adverse attritional emergence.",
    ("Demo Insurance UK", "Casualty", "Large", 2022):
        "Moved to Bornhuetter-Ferguson; large-loss development remains volatile at this maturity.",
    ("Demo Insurance UK", "Property", "Large", 2024):
        "Moved to Chain Ladder; reported development is now sufficiently stable.",
}

# Management adjustments (entity, class, loss type, accident year) ->
# {review_id: amount GBP}.
MANAGEMENT_ADJUSTMENTS = {
    ("Demo Insurance UK", "Property", "Cat", 2025): {"2025-Q3": 1_500_000, "2025-Q4": 1_500_000},
    ("Demo Insurance UK", "Casualty", "Large", 2023): {"2026-Q2": 2_000_000},
}
ADJUSTMENT_COMMENTARY = {
    ("Demo Insurance UK", "Property", "Cat", 2025):
        "Management loading for the September 2025 European windstorm events pending settlement.",
    ("Demo Insurance UK", "Casualty", "Large", 2023):
        "Management loading reflecting two late-reported large liability claims under review.",
}


# ---------------------------------------------------------------------------
# Deterministic helpers
# ---------------------------------------------------------------------------

def jitter(key: str, lo: float, hi: float) -> float:
    """Stable pseudo-random factor in [lo, hi] derived from an md5 hash."""
    h = int(hashlib.md5(key.encode("utf-8")).hexdigest()[:8], 16)
    return lo + (hi - lo) * (h / 0xFFFFFFFF)


def allocate(total: int, weights: list[float]) -> list[int]:
    """Largest-remainder allocation of an integer total by float weights."""
    s = sum(weights)
    if s <= 0 or total == 0:
        out = [0] * len(weights)
        if total and weights:
            out[0] = total
        return out
    shares = [w / s * total for w in weights]
    floors = [int(x) for x in shares]
    remainder = total - sum(floors)
    order = sorted(range(len(weights)), key=lambda i: shares[i] - floors[i], reverse=True)
    for i in order[:remainder]:
        floors[i] += 1
    return floors


def val_quarter_num(review_id: str) -> int:
    return int(review_id.split("-Q")[1])


def val_year(review_id: str) -> int:
    return int(review_id.split("-Q")[0])


def dev_latest(review_id: str, ay: int) -> int:
    """Latest development period (quarters, 0-based) for an accident year."""
    return (val_year(review_id) - ay) * 4 + val_quarter_num(review_id) - 1


def paid_fraction(elapsed_quarters: int, annual_speed: float) -> float:
    """Cumulative paid development fraction after a number of quarters."""
    years = (elapsed_quarters + 1) / 4.0
    return min(0.98, 1.0 - (1.0 - annual_speed) ** years)


def incurred_fraction(elapsed_quarters: int, annual_speed: float) -> float:
    years = (elapsed_quarters + 1) / 4.0
    speed = min(0.95, annual_speed + 0.30)
    return min(0.995, 1.0 - (1.0 - speed) ** years)


def case_fraction(age: int, loss_type: str) -> float:
    base = 0.30 + 0.05 * min(age, 8)
    adj = {"Attritional": 0.05, "Large": -0.05, "Cat": 0.15}[loss_type]
    return max(0.15, min(0.80, base + adj))


def projection_method(entity: str, rc: str, lt: str, ay: int, review_id: str) -> str:
    if review_id == "2026-Q2":
        override = METHOD_OVERRIDES_2026Q2.get((entity, rc, lt, ay))
        if override:
            return override
    age = val_year(review_id) - ay
    if age >= 3:
        return "Chain Ladder"
    if age >= 1:
        return "Bornhuetter-Ferguson"
    return "Expected Loss Ratio"


# ---------------------------------------------------------------------------
# Leaf structure
# ---------------------------------------------------------------------------

def build_leaves(rc: str, q_idx: int) -> list[dict]:
    """All (finance_class, entity, region, loss_type) leaves for a class,
    with allocation weights. Structure is identical across reviews; only
    the Property loss-type share drifts by quarter."""
    leaves = []
    uk_share = ENTITY_SHARE[rc]
    for fc, _, _ in FC_STRUCTURE[rc]:
        for entity in ENTITIES:
            e_share = uk_share if entity == "Demo Insurance UK" else 1 - uk_share
            for region, r_share in REGIONS_BY_ENTITY[entity]:
                for lt, lt_share in loss_type_shares(rc, q_idx):
                    j = jitter(f"leaf|{rc}|{fc}|{entity}|{region}|{lt}", 0.85, 1.15)
                    leaves.append({
                        "finance_class": fc,
                        "business_unit": BU_BY_FC[fc],
                        "entity": entity,
                        "region": region,
                        "loss_type": lt,
                        "weight": e_share * r_share * lt_share * j,
                    })
    return leaves


def ay_weights(rc: str, lt: str, ays: list[int], review_id: str, q_idx: int,
               leaf_key: str) -> list[float]:
    decay = AY_DECAY[(rc, lt)]
    vy, vq = val_year(review_id), val_quarter_num(review_id)
    weights = []
    for ay in ays:
        age = vy - ay
        w = decay ** age
        if age == 0:
            w *= vq / 4.0  # partial exposure year
        if rc == "Casualty" and 1 <= age <= 4:
            w *= CASUALTY_RECENT_BOOST[q_idx]
        w *= jitter(f"ay|{leaf_key}|{ay}", 0.92, 1.08)
        weights.append(w)
    return weights


# ---------------------------------------------------------------------------
# Reserve allocation
# ---------------------------------------------------------------------------

def rc_fc_totals(rc: str, q_idx: int) -> dict[str, int]:
    """Reserve total (GBP, integer) per finance class for one review."""
    rc_total = RC_RESERVE_M[rc][q_idx] * 1_000_000
    cells = FC_STRUCTURE[rc]
    if q_idx < 7:
        weights = [share for _, share, _ in cells]
        alloc = allocate(rc_total, weights)
        return {fc: amount for (fc, _, _), amount in zip(cells, alloc)}
    # 2026-Q2: prior-quarter level plus the specified movement matrix.
    prior = rc_fc_totals(rc, 6)
    out = {}
    for fc, _, move_m in cells:
        out[fc] = prior[fc] + move_m * 1_000_000
    total = sum(out.values())
    assert total == rc_total, f"{rc}: FC movement does not reconcile ({total} != {rc_total})"
    return out


def allocate_reserves(review_id: str, q_idx: int) -> list[dict]:
    """Integer reserve per (rc, fc, entity, region, lt, ay) leaf."""
    ays = list(range(FIRST_AY, val_year(review_id) + 1))
    rows = []
    for rc in RC_RESERVE_M:
        fc_totals = rc_fc_totals(rc, q_idx)
        leaves = build_leaves(rc, q_idx)
        for fc, fc_total in fc_totals.items():
            fc_leaves = [lf for lf in leaves if lf["finance_class"] == fc]
            leaf_alloc = allocate(fc_total, [lf["weight"] for lf in fc_leaves])
            for lf, leaf_total in zip(fc_leaves, leaf_alloc):
                leaf_key = f"{rc}|{fc}|{lf['entity']}|{lf['region']}|{lf['loss_type']}"
                w = ay_weights(rc, lf["loss_type"], ays, review_id, q_idx, leaf_key)
                for ay, reserve in zip(ays, allocate(leaf_total, w)):
                    rows.append({
                        "review_id": review_id, "rc": rc, "fc": fc,
                        "entity": lf["entity"], "bu": lf["business_unit"],
                        "region": lf["region"], "lt": lf["loss_type"],
                        "ay": ay, "reserve": reserve,
                    })
    return rows


# ---------------------------------------------------------------------------
# Claims and results derivation
# ---------------------------------------------------------------------------

def build_all():
    # Reserve allocation for every review, plus the 2026-Q2 allocation used
    # as the base ultimate for a payment path that is consistent (monotonic)
    # across reviews.
    per_review: dict[str, list[dict]] = {}
    for q_idx, (rid, *_rest) in enumerate(REVIEWS):
        per_review[rid] = allocate_reserves(rid, q_idx)

    final_rid = REVIEWS[-1][0]
    base_ultimate: dict[tuple, float] = {}
    for row in per_review[final_rid]:
        key = (row["rc"], row["fc"], row["entity"], row["region"], row["lt"], row["ay"])
        speed = SETTLEMENT[(row["rc"], row["lt"])]
        g_final = paid_fraction(dev_latest(final_rid, row["ay"]), speed)
        base_ultimate[key] = row["reserve"] / max(1e-9, (1.0 - g_final))

    results_rows = []
    claims_rows = []
    for q_idx, (rid, *_rest) in enumerate(REVIEWS):
        for row in per_review[rid]:
            rc, fc, lt, ay = row["rc"], row["fc"], row["lt"], row["ay"]
            key = (rc, fc, row["entity"], row["region"], lt, ay)
            speed = SETTLEMENT[(rc, lt)]
            dl = dev_latest(rid, ay)
            g = paid_fraction(dl, speed)
            u_base = base_ultimate.get(key, row["reserve"] / max(1e-9, 1.0 - g))
            reserve = row["reserve"]
            paid = int(round(u_base * g))
            age = val_year(rid) - ay
            case = int(round(reserve * case_fraction(age, lt)))
            incurred = paid + case
            ultimate = paid + reserve
            ibnr = reserve - case
            base = dict(row)
            base.update(paid=paid, incurred=incurred, case=case,
                        ultimate=ultimate, ibnr=ibnr)
            results_rows.append(base)

            # Claims triangle: cumulative paid/incurred by development quarter,
            # scaled so the latest diagonal equals the result snapshot exactly.
            g_scale = paid_fraction(dl, speed)
            r_scale = incurred_fraction(dl, speed)
            sev = SEVERITY[(rc, lt)]
            prev_paid = prev_inc = 0
            for d in range(dl + 1):
                if d == dl:
                    p_cum, i_cum = paid, incurred
                else:
                    p_cum = int(round(paid * paid_fraction(d, speed) / max(1e-9, g_scale)))
                    i_cum = int(round(incurred * incurred_fraction(d, speed) / max(1e-9, r_scale)))
                p_cum = max(p_cum, prev_paid)
                i_cum = max(i_cum, prev_inc, p_cum)
                prev_paid, prev_inc = p_cum, i_cum
                claims_rows.append({
                    "review_id": rid, "entity": row["entity"], "bu": row["bu"],
                    "region": row["region"], "fc": fc, "rc": rc, "lt": lt,
                    "ay": ay, "dev": d,
                    "paid_cum": p_cum, "inc_cum": i_cum,
                    "rep_count": int(i_cum // sev),
                    "paid_count": int(p_cum // sev),
                    "latest": 1 if d == dl else 0,
                })

    return per_review, results_rows, claims_rows


# ---------------------------------------------------------------------------
# Premium
# ---------------------------------------------------------------------------

def build_premium() -> list[dict]:
    rows = []
    for q_idx, (rid, *_rest) in enumerate(REVIEWS):
        vy, vq = val_year(rid), val_quarter_num(rid)
        ays = list(range(FIRST_AY, vy + 1))
        for rc in RC_RESERVE_M:
            leaves = []
            uk_share = ENTITY_SHARE[rc]
            for fc, fc_share, _ in FC_STRUCTURE[rc]:
                for entity in ENTITIES:
                    e_share = uk_share if entity == "Demo Insurance UK" else 1 - uk_share
                    for region, r_share in REGIONS_BY_ENTITY[entity]:
                        j = jitter(f"prem|{rc}|{fc}|{entity}|{region}", 0.9, 1.1)
                        leaves.append((fc, entity, region, fc_share * e_share * r_share * j))
            for ay in ays:
                plan = int(round(PREMIUM_BASE[rc] * PREMIUM_GROWTH ** (ay - FIRST_AY)))
                if ay == vy:
                    # Written accrues evenly through the year; uniform writing
                    # earns at roughly half the written-to-date rate.
                    elapsed = vq / 4.0
                    written_total = int(round(plan * elapsed))
                    earned_total = int(round(plan * elapsed * 0.5))
                else:
                    written_total = plan
                    earned_total = plan
                w_alloc = allocate(written_total, [w for *_ignore, w in leaves])
                e_alloc = allocate(earned_total, [w for *_ignore, w in leaves])
                for (fc, entity, region, _w), wp, ep in zip(leaves, w_alloc, e_alloc):
                    rows.append({
                        "review_id": rid, "entity": entity, "bu": BU_BY_FC[fc],
                        "region": region, "fc": fc, "rc": rc, "ay": ay,
                        "written": wp, "earned": ep,
                    })
    return rows


# ---------------------------------------------------------------------------
# Assumptions
# ---------------------------------------------------------------------------

def build_assumptions(results_rows: list[dict], premium_rows: list[dict]) -> list[dict]:
    # Aggregate results to the assumption selection grain and premium to
    # entity x class x accident year so the selected loss ratio is derived
    # from the same seeded data the application queries.
    ult: dict[tuple, float] = {}
    lt_reserve: dict[tuple, float] = {}
    for r in results_rows:
        k = (r["review_id"], r["entity"], r["rc"], r["lt"], r["ay"])
        ult[k] = ult.get(k, 0) + r["ultimate"]
        kk = (r["review_id"], r["entity"], r["rc"], r["ay"])
        lt_reserve[(kk, r["lt"])] = lt_reserve.get((kk, r["lt"]), 0) + r["ultimate"]
    earned: dict[tuple, float] = {}
    for p in premium_rows:
        k = (p["review_id"], p["entity"], p["rc"], p["ay"])
        earned[k] = earned.get(k, 0) + p["earned"]

    rows = []
    for q_idx, (rid, *_rest) in enumerate(REVIEWS):
        vy = val_year(rid)
        ays = list(range(FIRST_AY, vy + 1))
        for entity in ENTITIES:
            for rc in RC_RESERVE_M:
                for lt, _s in loss_type_shares(rc, q_idx):
                    for ay in ays:
                        k = (rid, entity, rc, lt, ay)
                        u = ult.get(k, 0.0)
                        kk = (rid, entity, rc, ay)
                        total_u = sum(v for (kk2, _lt2), v in lt_reserve.items() if kk2 == kk)
                        e = earned.get(kk, 0.0)
                        lt_share = (u / total_u) if total_u else 0.0
                        lr = None
                        if e > 0 and u > 0 and lt_share > 0:
                            lr = round(min(1.25, max(0.05, u / (e * lt_share))), 3)
                        method = projection_method(entity, rc, lt, ay, rid)
                        infl = None
                        if lt in ("Attritional", "Large"):
                            infl = INFLATION[rc][q_idx]
                        tail = None
                        pattern = None
                        if method == "Chain Ladder":
                            tail = {"Motor": 1.01, "Property": 1.02,
                                    "Casualty": 1.05, "Marine": 1.03}[rc]
                            pattern = f"{rc[:3].upper()}-{lt[:3].upper()}-{vy}v1"
                        adj_map = MANAGEMENT_ADJUSTMENTS.get((entity, rc, lt, ay), {})
                        adj = adj_map.get(rid, 0)
                        commentary = None
                        if rid == "2026-Q2" and (entity, rc, lt, ay) in METHOD_OVERRIDES_2026Q2:
                            commentary = OVERRIDE_COMMENTARY[(entity, rc, lt, ay)]
                        elif adj:
                            commentary = ADJUSTMENT_COMMENTARY.get((entity, rc, lt, ay))
                        rows.append({
                            "review_id": rid, "entity": entity, "rc": rc, "lt": lt,
                            "ay": ay, "method": method, "lr": lr, "infl": infl,
                            "adj": adj, "pattern": pattern, "tail": tail,
                            "commentary": commentary,
                        })
    return rows


# ---------------------------------------------------------------------------
# Database packaging
# ---------------------------------------------------------------------------

SCHEMA = """
PRAGMA journal_mode = DELETE;

DROP TABLE IF EXISTS review_period;
DROP TABLE IF EXISTS claims_triangle;
DROP TABLE IF EXISTS premium_data;
DROP TABLE IF EXISTS assumption_snapshot;
DROP TABLE IF EXISTS result_snapshot;
DROP TABLE IF EXISTS report_slide;
DROP VIEW IF EXISTS vw_claims_latest;

CREATE TABLE review_period (
  review_id TEXT PRIMARY KEY,
  quarter_label TEXT NOT NULL,
  valuation_date TEXT NOT NULL,
  sequence_no INTEGER NOT NULL UNIQUE,
  prior_review_id TEXT,
  prior_year_review_id TEXT,
  is_default INTEGER NOT NULL DEFAULT 0,
  report_title TEXT NOT NULL,
  reporting_currency TEXT NOT NULL,
  status TEXT NOT NULL
);

CREATE TABLE claims_triangle (
  claims_cell_id INTEGER PRIMARY KEY,
  review_id TEXT NOT NULL REFERENCES review_period(review_id),
  entity TEXT NOT NULL,
  business_unit TEXT NOT NULL,
  region TEXT NOT NULL,
  finance_class TEXT NOT NULL,
  reserving_class TEXT NOT NULL,
  loss_type TEXT NOT NULL CHECK (loss_type IN ('Attritional','Large','Cat')),
  accident_year INTEGER NOT NULL,
  development_period_quarters INTEGER NOT NULL,
  paid_claims_cumulative REAL NOT NULL,
  incurred_claims_cumulative REAL NOT NULL,
  reported_claim_count_cumulative INTEGER NOT NULL,
  paid_claim_count_cumulative INTEGER,
  is_latest_diagonal INTEGER NOT NULL,
  source_key TEXT NOT NULL UNIQUE
);
CREATE INDEX ix_claims_review ON claims_triangle(review_id, is_latest_diagonal);

CREATE VIEW vw_claims_latest AS
SELECT review_id, entity, business_unit, region, finance_class,
       reserving_class, loss_type, accident_year,
       paid_claims_cumulative AS paid_claims,
       incurred_claims_cumulative AS incurred_claims,
       reported_claim_count_cumulative AS reported_claim_count,
       paid_claim_count_cumulative AS paid_claim_count,
       source_key
FROM claims_triangle
WHERE is_latest_diagonal = 1;

CREATE TABLE premium_data (
  premium_row_id INTEGER PRIMARY KEY,
  review_id TEXT NOT NULL REFERENCES review_period(review_id),
  entity TEXT NOT NULL,
  business_unit TEXT NOT NULL,
  region TEXT NOT NULL,
  finance_class TEXT NOT NULL,
  reserving_class TEXT NOT NULL,
  accident_year INTEGER NOT NULL,
  written_premium REAL NOT NULL,
  earned_premium REAL NOT NULL,
  source_key TEXT NOT NULL UNIQUE
);

CREATE TABLE assumption_snapshot (
  assumption_row_id INTEGER PRIMARY KEY,
  review_id TEXT NOT NULL REFERENCES review_period(review_id),
  entity TEXT NOT NULL,
  reserving_class TEXT NOT NULL,
  loss_type TEXT NOT NULL,
  accident_year INTEGER NOT NULL,
  projection_method TEXT NOT NULL,
  selected_loss_ratio REAL,
  inflation_assumption REAL,
  management_adjustment REAL NOT NULL DEFAULT 0,
  selected_development_pattern TEXT,
  tail_factor REAL,
  assumption_commentary TEXT,
  source_key TEXT NOT NULL UNIQUE
);

CREATE TABLE result_snapshot (
  result_row_id INTEGER PRIMARY KEY,
  review_id TEXT NOT NULL REFERENCES review_period(review_id),
  entity TEXT NOT NULL,
  business_unit TEXT NOT NULL,
  region TEXT NOT NULL,
  finance_class TEXT NOT NULL,
  reserving_class TEXT NOT NULL,
  loss_type TEXT NOT NULL,
  accident_year INTEGER NOT NULL,
  paid_claims REAL NOT NULL,
  incurred_claims REAL NOT NULL,
  case_reserves REAL NOT NULL,
  ultimate_claims REAL NOT NULL,
  ibnr REAL NOT NULL,
  total_reserve REAL NOT NULL,
  source_key TEXT NOT NULL UNIQUE
);
CREATE INDEX ix_results_review ON result_snapshot(review_id);

CREATE TABLE report_slide (
  slide_id INTEGER PRIMARY KEY,
  review_id TEXT NOT NULL REFERENCES review_period(review_id),
  slide_number INTEGER NOT NULL,
  section TEXT NOT NULL,
  title TEXT NOT NULL,
  content_json TEXT NOT NULL,
  plain_text TEXT NOT NULL,
  tags_json TEXT NOT NULL,
  related_dimensions_json TEXT,
  rendered_html TEXT,
  UNIQUE (review_id, slide_number)
);
"""


def package(results_rows, claims_rows, premium_rows, assumption_rows):
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.executescript(SCHEMA)

    con.executemany(
        "INSERT INTO review_period VALUES (?,?,?,?,?,?,?,?,?,?)",
        [
            (rid, label, vdate, seq, prior, prior_year,
             1 if rid == DEFAULT_REVIEW else 0,
             f"{label} Reserve Review", "GBP", "ACTIVE")
            for rid, label, vdate, seq, prior, prior_year in REVIEWS
        ],
    )

    con.executemany(
        "INSERT INTO result_snapshot (review_id, entity, business_unit, region,"
        " finance_class, reserving_class, loss_type, accident_year, paid_claims,"
        " incurred_claims, case_reserves, ultimate_claims, ibnr, total_reserve,"
        " source_key) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            (r["review_id"], r["entity"], r["bu"], r["region"], r["fc"], r["rc"],
             r["lt"], r["ay"], r["paid"], r["incurred"], r["case"], r["ultimate"],
             r["ibnr"], r["reserve"],
             f"RES|{r['review_id']}|{r['entity']}|{r['bu']}|{r['region']}|{r['fc']}"
             f"|{r['rc']}|{r['lt']}|{r['ay']}")
            for r in results_rows
        ],
    )

    con.executemany(
        "INSERT INTO claims_triangle (review_id, entity, business_unit, region,"
        " finance_class, reserving_class, loss_type, accident_year,"
        " development_period_quarters, paid_claims_cumulative,"
        " incurred_claims_cumulative, reported_claim_count_cumulative,"
        " paid_claim_count_cumulative, is_latest_diagonal, source_key)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            (c["review_id"], c["entity"], c["bu"], c["region"], c["fc"], c["rc"],
             c["lt"], c["ay"], c["dev"], c["paid_cum"], c["inc_cum"],
             c["rep_count"], c["paid_count"], c["latest"],
             f"CLM|{c['review_id']}|{c['entity']}|{c['bu']}|{c['region']}|{c['fc']}"
             f"|{c['rc']}|{c['lt']}|{c['ay']}|{c['dev']}")
            for c in claims_rows
        ],
    )

    con.executemany(
        "INSERT INTO premium_data (review_id, entity, business_unit, region,"
        " finance_class, reserving_class, accident_year, written_premium,"
        " earned_premium, source_key) VALUES (?,?,?,?,?,?,?,?,?,?)",
        [
            (p["review_id"], p["entity"], p["bu"], p["region"], p["fc"], p["rc"],
             p["ay"], p["written"], p["earned"],
             f"PRM|{p['review_id']}|{p['entity']}|{p['bu']}|{p['region']}|{p['fc']}"
             f"|{p['rc']}|{p['ay']}")
            for p in premium_rows
        ],
    )

    con.executemany(
        "INSERT INTO assumption_snapshot (review_id, entity, reserving_class,"
        " loss_type, accident_year, projection_method, selected_loss_ratio,"
        " inflation_assumption, management_adjustment,"
        " selected_development_pattern, tail_factor, assumption_commentary,"
        " source_key) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            (a["review_id"], a["entity"], a["rc"], a["lt"], a["ay"], a["method"],
             a["lr"], a["infl"], a["adj"], a["pattern"], a["tail"], a["commentary"],
             f"ASM|{a['review_id']}|{a['entity']}|{a['rc']}|{a['lt']}|{a['ay']}")
            for a in assumption_rows
        ],
    )

    con.commit()
    counts = {
        t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        for t in ("review_period", "result_snapshot", "claims_triangle",
                  "premium_data", "assumption_snapshot")
    }
    con.close()
    return counts


def main() -> int:
    print("Building demonstration data ...")
    _per_review, results_rows, claims_rows = build_all()
    premium_rows = build_premium()
    assumption_rows = build_assumptions(results_rows, premium_rows)
    counts = package(results_rows, claims_rows, premium_rows, assumption_rows)
    for table, n in counts.items():
        print(f"  {table}: {n} rows")
    print(f"Database written to {os.path.abspath(DB_PATH)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
