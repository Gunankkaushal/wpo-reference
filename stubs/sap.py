"""stub-sap · stands for SAP S/4 (production demand). Validated system."""

from fastapi import Body

from stubs import canned
from stubs.common import make_app, record_write

app = make_app("sap", "SAP S/4")


@app.get("/production_plan")
async def production_plan(site_id: str | None = None):
    """Canned plan for 14 sites: planned units per line per shift."""
    rows = canned.production_plan()
    return [r for r in rows if site_id in (None, r["site_id"])]


@app.post("/shift_confirm")
async def shift_confirm(body: dict = Body(...)):
    """Write path. Confirms staffing back to planning."""
    record_write(app, "/shift_confirm", body)
    return {"status": "ok"}
