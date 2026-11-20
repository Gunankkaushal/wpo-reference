"""stub-teams · stands for Microsoft Teams."""

from fastapi import Body

from stubs.common import make_app, record_write

app = make_app("teams", "Microsoft Teams")


@app.post("/notify")
async def notify(body: dict = Body(...)):
    """Write path. Tells line managers the roster is live."""
    record_write(app, "/notify", body)
    return {"status": "ok"}
