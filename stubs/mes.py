"""stub-mes · stands for the MES (line availability). Operational system."""

from stubs import canned
from stubs.common import make_app

app = make_app("mes", "MES")


@app.get("/line_availability")
async def line_availability(site_id: str | None = None):
    """Lines running, planned maintenance, degraded."""
    return [r for r in canned.line_availability() if site_id in (None, r["site_id"])]
