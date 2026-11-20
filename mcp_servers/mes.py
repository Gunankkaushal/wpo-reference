"""MCP server · mes → stub-mes (line availability)."""

from mcp_servers.common import READ, new_server, serve, upstream, backend_meta

mcp = new_server("mes", "MES line availability and planned maintenance.")
META = backend_meta("mes")


@mcp.tool(name="line_availability", annotations=READ, meta=META)
async def line_availability(site_id: str | None = None) -> dict:
    """Lines running, in planned maintenance or degraded, per site, with shifts down."""
    return {"items": await upstream("mes", "GET", "/line_availability", params={"site_id": site_id})}


if __name__ == "__main__":
    serve(mcp, "mes")
