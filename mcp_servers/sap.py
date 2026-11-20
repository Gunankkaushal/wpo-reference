"""MCP server · sap → stub-sap (SAP S/4)."""

from mcp_servers.common import READ, WRITE, new_server, serve, upstream, backend_meta

mcp = new_server("sap", "SAP S/4 production demand and shift confirmation.")
META = backend_meta("sap")


@mcp.tool(name="production_plan", annotations=READ, meta=META)
async def production_plan(site_id: str | None = None) -> dict:
    """Planned output per line per shift, for all 14 sites or one site."""
    return {"items": await upstream("sap", "GET", "/production_plan", params={"site_id": site_id})}


@mcp.tool(name="shift_confirm", annotations=WRITE, meta=META)
async def shift_confirm(site_id: str, plan_date: str, staffing: list[dict]) -> dict:
    """WRITE. Confirms staffed headcount per line and shift back to SAP planning."""
    return await upstream("sap", "POST", "/shift_confirm", body={"site_id": site_id, "plan_date": plan_date, "staffing": staffing})


if __name__ == "__main__":
    serve(mcp, "sap")
