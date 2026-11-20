"""MCP server · lms → stub-lms (Learning system)."""

from mcp_servers.common import READ, new_server, serve, upstream, backend_meta

mcp = new_server("lms", "Learning system training currency.")
META = backend_meta("lms")


@mcp.tool(name="training_currency", annotations=READ, meta=META)
async def training_currency(site_id: str | None = None) -> dict:
    """Who is qualified for which line today, with valid_until per course."""
    return {"items": await upstream("lms", "GET", "/training_currency", params={"site_id": site_id})}


if __name__ == "__main__":
    serve(mcp, "lms")
