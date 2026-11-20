"""stub-cuopt · stands for NVIDIA cuOpt on Azure. Internal service.

Returns {"status": "OK", "roster": {...}}. The "solve" is a trivial greedy fill
so the roster is non-empty and downstream agents have something to check. It
knows nothing about working-time rules; that is Compliance's job.
"""

import time

from fastapi import Body

from stubs import canned
from stubs.common import make_app

app = make_app("cuopt", "NVIDIA cuOpt")


@app.post("/solve")
async def solve(body: dict = Body(...)):
    t0 = time.perf_counter()
    demand = body.get("demand", [])
    exclude = set(body.get("exclude", []))
    pool: dict[str, list[dict]] = {}
    for w in body.get("workers", []):
        if w["worker_id"] not in exclude:
            pool.setdefault(w["site_id"], []).append(w)

    roster: dict[str, list[dict]] = {}
    unfilled: list[dict] = []
    used: set[str] = set()
    for slot in demand:
        site, line, shift = slot["site_id"], slot["line_id"], slot["shift"]
        for _ in range(slot.get("headcount", 0)):
            pick = next(
                (w for w in pool.get(site, []) if w["worker_id"] not in used and line in w.get("qualified_lines", [])),
                None,
            )
            if pick is None:
                unfilled.append({"site_id": site, "line_id": line, "shift": shift})
                continue
            used.add(pick["worker_id"])
            s = canned.SHIFTS[shift]
            roster.setdefault(site, []).append({
                "worker_id": pick["worker_id"], "line_id": line, "shift": shift,
                "start": s["start"], "end": s["end"], "hours": s["hours"],
            })

    return {
        "status": "OK",
        "roster": roster,
        "unfilled": unfilled,
        "objective": len(used),
        "solve_time_ms": round((time.perf_counter() - t0) * 1000, 2),
    }
