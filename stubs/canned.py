"""Canned data served by the stubs.

Hardcoded and deterministic. Dates are relative to "today" so the nightly run
always has a plan for the current day, and roster.store can be seeded with
yesterday's roster (the one Manager Copilot falls back to on a bad night).

Figures and names are illustrative only.
"""

from __future__ import annotations

from datetime import date, timedelta


def plan_date() -> str:
    return date.today().isoformat()


# ── 14 sites ────────────────────────────────────────────────────────────────
SITES = [
    {"site_id": "SITE-01", "name": "Northfield"},
    {"site_id": "SITE-02", "name": "Eastbrook"},
    {"site_id": "SITE-03", "name": "Westmoor"},
    {"site_id": "SITE-04", "name": "Southgate"},
    {"site_id": "SITE-05", "name": "Riverside"},
    {"site_id": "SITE-06", "name": "Hillcrest"},
    {"site_id": "SITE-07", "name": "Lakeside"},
    {"site_id": "SITE-08", "name": "Oakridge"},
    {"site_id": "SITE-09", "name": "Millbrook"},
    {"site_id": "SITE-10", "name": "Stonebridge"},
    {"site_id": "SITE-11", "name": "Kingsmead"},
    {"site_id": "SITE-12", "name": "Fairhaven"},
    {"site_id": "SITE-13", "name": "Brookvale"},
    {"site_id": "SITE-14", "name": "Harbourside"},
]
SITE_IDS = [s["site_id"] for s in SITES]
LINES = ["L1", "L2"]
SHIFTS = {
    "early": {"start": "06:00", "end": "14:00", "hours": 8},
    "late": {"start": "14:00", "end": "22:00", "hours": 8},
    "night": {"start": "22:00", "end": "06:00", "hours": 8},
}


# ── SAP S/4 · production plan ───────────────────────────────────────────────
def production_plan() -> list[dict]:
    out = []
    for i, site in enumerate(SITES, start=1):
        lines = []
        for li, line in enumerate(LINES, start=1):
            shifts = {
                shift: 800 + (i * 37 + li * 53 + si * 29) % 500
                for si, shift in enumerate(SHIFTS, start=1)
            }
            lines.append({"line_id": line, "planned_units": shifts})
        out.append({**site, "plan_date": plan_date(), "material": "PACK-STD", "lines": lines})
    return out


# ── MES · line availability ─────────────────────────────────────────────────
_DOWNTIME = {
    ("SITE-03", "L2"): {"status": "planned_maintenance", "shifts_down": ["early", "late", "night"], "reason": "Annual line qualification"},
    ("SITE-07", "L1"): {"status": "planned_maintenance", "shifts_down": ["night"], "reason": "Changeover"},
    ("SITE-11", "L2"): {"status": "degraded", "shifts_down": ["early"], "reason": "Labeller fault, engineer booked"},
}


def line_availability() -> list[dict]:
    out = []
    for site_id in SITE_IDS:
        for line in LINES:
            d = _DOWNTIME.get((site_id, line), {"status": "running", "shifts_down": [], "reason": None})
            out.append({"site_id": site_id, "line_id": line, "date": plan_date(), **d})
    return out


# ── Workday · workers ───────────────────────────────────────────────────────
# Two workers are already near the 48h weekly cap. The solver does not know the
# working-time rule, so the first candidate roster assigns them and Compliance
# sends it back to the optimizer once. That exercises the fail → optimizer edge.
_NEAR_CAP = {"W-0101": 44.0, "W-0605": 43.5}


def workers() -> list[dict]:
    out = []
    for i, site_id in enumerate(SITE_IDS, start=1):
        for j in range(1, 13):
            wid = f"W-{i:02d}{j:02d}"
            out.append({
                "worker_id": wid,
                "name": f"Operator {i:02d}-{j:02d}",
                "site_id": site_id,
                "contract_hours_week": 37.5 if j % 4 == 0 else 40.0,
                "hours_worked_week": _NEAR_CAP.get(wid, float((j * 7 + i * 3) % 25 + 8)),
                "skills": ["L1"] if j in (11, 12) else ["L1", "L2"],
                "union": "UNITE" if j % 3 else "GMB",
                "status": "active",
            })
    return out


# ── Workday · absences ──────────────────────────────────────────────────────
def absences() -> list[dict]:
    d = plan_date()
    rows = [
        ("W-0102", "SITE-01", "annual_leave"),
        ("W-0207", "SITE-02", "sickness"),
        ("W-0304", "SITE-03", "annual_leave"),
        ("W-0409", "SITE-04", "sickness"),
        ("W-0501", "SITE-05", "parental_leave"),
        ("W-0606", "SITE-06", "annual_leave"),
        ("W-0703", "SITE-07", "sickness"),
        ("W-0805", "SITE-08", "annual_leave"),
        ("W-0910", "SITE-09", "training_offsite"),
        ("W-1002", "SITE-10", "sickness"),
        ("W-1108", "SITE-11", "annual_leave"),
        ("W-1301", "SITE-13", "sickness"),
        ("W-1404", "SITE-14", "annual_leave"),
    ]
    return [
        {"absence_id": f"ABS-{n:04d}", "worker_id": w, "site_id": s, "type": t, "from": d, "to": d, "approved": True}
        for n, (w, s, t) in enumerate(rows, start=1001)
    ]


# ── Learning system · training currency ─────────────────────────────────────
_EXPIRED = {("W-0203", "L1"), ("W-0408", "L2"), ("W-0902", "L1"), ("W-1206", "L1"), ("W-1206", "L2")}


def training_currency() -> list[dict]:
    today = date.today()
    out = []
    for w in workers():
        for line in w["skills"]:
            expired = (w["worker_id"], line) in _EXPIRED
            valid_until = today - timedelta(days=3) if expired else today + timedelta(days=120)
            out.append({
                "worker_id": w["worker_id"],
                "site_id": w["site_id"],
                "line_id": line,
                "course": f"GMP-{line}-OPERATOR",
                "valid_until": valid_until.isoformat(),
                "current": not expired,
            })
    return out
