"""MCP server · workday → stub-workday (Workday HR master)."""

from mcp_servers.common import READ, WRITE, new_server, serve, upstream, backend_meta

mcp = new_server("workday", "Workday absences, worker master data and schedule publishing.")
META = backend_meta("workday")


@mcp.tool(name="absences", annotations=READ, meta=META)
async def absences(site_id: str | None = None) -> dict:
    """Approved leave and sickness for the plan date."""
    return {"items": await upstream("workday", "GET", "/absences", params={"site_id": site_id})}


@mcp.tool(name="workers", annotations=READ, meta=META)
async def workers(site_id: str | None = None) -> dict:
    """Contracts, hours worked this week, skills and site for each worker."""
    return {"items": await upstream("workday", "GET", "/workers", params={"site_id": site_id})}


@mcp.tool(name="schedules", annotations=WRITE, meta=META)
async def schedules(site_id: str, plan_date: str, assignments: list[dict], run_id: str | None = None) -> dict:
    """WRITE. Publishes the approved roster for one site into Workday."""
    body = {"site_id": site_id, "plan_date": plan_date, "assignments": assignments, "run_id": run_id}
    return await upstream("workday", "POST", "/schedules", body=body)


if __name__ == "__main__":
    serve(mcp, "workday")
