"""stub-lms · stands for the Learning system (training currency). Validated system."""

from stubs import canned
from stubs.common import make_app

app = make_app("lms", "Learning system")


@app.get("/training_currency")
async def training_currency(site_id: str | None = None):
    """Who is qualified for which line today."""
    return [r for r in canned.training_currency() if site_id in (None, r["site_id"])]
