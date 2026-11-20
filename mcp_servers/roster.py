"""MCP server · roster.store (candidate rosters and compliance verdicts).

Internal WPO store, persisted to a JSON file. On first start it is seeded with
yesterday's approved roster, which is what Manager Copilot falls back to if
tonight's run never gets a roster through Compliance.
"""

from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta
from pathlib import Path

from mcp_servers.common import WRITE, new_server, serve, backend_meta
from stubs import canned

STORE_PATH = Path(os.getenv("ROSTER_STORE_PATH", "data/roster_store.json"))

mcp = new_server("roster", "WPO roster store.")
META = backend_meta("roster")


def _load() -> list[dict]:
    if STORE_PATH.exists():
        return json.loads(STORE_PATH.read_text(encoding="utf-8"))
    return []


def _save(records: list[dict]) -> None:
    STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STORE_PATH.write_text(json.dumps(records, indent=1), encoding="utf-8")


def _seed() -> None:
    if _load():
        return
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    roster: dict[str, list[dict]] = {}
    by_site: dict[str, list[dict]] = {}
    for w in canned.workers():
        by_site.setdefault(w["site_id"], []).append(w)
    for site_id, ws in by_site.items():
        slots = [(line, shift) for line in canned.LINES for shift in canned.SHIFTS]
        roster[site_id] = [
            {"worker_id": w["worker_id"], "line_id": line, "shift": shift,
             "start": canned.SHIFTS[shift]["start"], "end": canned.SHIFTS[shift]["end"], "hours": 8}
            for w, (line, shift) in zip(ws, slots)
        ]
    _save([{
        "plan_date": yesterday,
        "run_id": "run-seed",
        "status": "approved",
        "written_at": f"{yesterday}T04:12:00",
        "roster": roster,
        "verdict": {"result": "pass", "violations": []},
    }])


@mcp.tool(name="store", annotations=WRITE, meta=META)
async def store(action: str = "put", plan_date: str | None = None, run_id: str | None = None,
                status: str | None = None, roster: dict | None = None, verdict: dict | None = None,
                site_id: str | None = None) -> dict:
    """WRITE. The WPO roster store, one tool for both directions (as on edges E10, E13, E17).

    action="put"     store a roster record; status is candidate, approved or rejected
    action="latest"  read the most recent record with `status` (default approved),
                     optionally narrowed to one site
    """
    if action == "latest":
        return _latest(site_id, status or "approved")
    if action != "put":
        raise ValueError(f"unknown action {action!r}; use 'put' or 'latest'")
    missing = [k for k, v in (("plan_date", plan_date), ("run_id", run_id), ("status", status), ("roster", roster)) if v is None]
    if missing:
        raise ValueError(f"action='put' needs {', '.join(missing)}")
    records = _load()
    records.append({
        "plan_date": plan_date, "run_id": run_id, "status": status,
        "written_at": datetime.now().isoformat(timespec="seconds"),
        "roster": roster, "verdict": verdict,
    })
    _save(records[-200:])
    return {"status": "ok", "stored": {"plan_date": plan_date, "run_id": run_id, "status": status}}


def _latest(site_id: str | None, status: str) -> dict:
    matches = [r for r in _load() if r["status"] == status]
    if not matches:
        return {"found": False}
    rec = max(matches, key=lambda r: (r["plan_date"], r["written_at"]))
    roster = rec["roster"] if site_id is None else {site_id: rec["roster"].get(site_id, [])}
    return {"found": True, **{k: rec[k] for k in ("plan_date", "run_id", "status", "written_at")}, "roster": roster}


if __name__ == "__main__":
    _seed()
    serve(mcp, "roster")
