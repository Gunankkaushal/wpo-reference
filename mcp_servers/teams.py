"""MCP server · teams → stub-teams (Microsoft Teams)."""

from mcp_servers.common import WRITE, new_server, serve, upstream, backend_meta

mcp = new_server("teams", "Microsoft Teams notifications.")
META = backend_meta("teams")


@mcp.tool(name="notify", annotations=WRITE, meta=META)
async def notify(channel: str, message: str, site_ids: list[str] | None = None) -> dict:
    """WRITE. Posts a message to a Teams channel (tells managers the roster is live)."""
    return await upstream("teams", "POST", "/notify", body={"channel": channel, "message": message, "site_ids": site_ids or []})


if __name__ == "__main__":
    serve(mcp, "teams")
