"""stub-workday · stands for Workday (HR master). Validated system."""

from fastapi import Body

from stubs import canned
from stubs.common import make_app, record_write

app = make_app("workday", "Workday")


@app.get("/absences")
async def absences(site_id: str | None = None):
    """Approved leave and sickness for the plan date."""
    return [a for a in canned.absences() if site_id in (None, a["site_id"])]


@app.get("/workers")
async def workers(site_id: str | None = None):
    """Contracts, hours worked this week, skills, site."""
    return [w for w in canned.workers() if site_id in (None, w["site_id"])]


@app.post("/schedules")
async def schedules(body: dict = Body(...)):
    """Write path. Publishes the approved roster."""
    record_write(app, "/schedules", body)
    return {"status": "ok"}
