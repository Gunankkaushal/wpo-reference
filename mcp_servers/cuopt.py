"""MCP server · cuopt → stub-cuopt (NVIDIA cuOpt on Azure)."""

from mcp.types import ToolAnnotations

from mcp_servers.common import new_server, serve, upstream, backend_meta

mcp = new_server("cuopt", "NVIDIA cuOpt roster optimisation.")
META = backend_meta("cuopt")

# solve is a POST but it mutates nothing: read-only from the system's point of
# view, though not idempotent in cost (every call is billed solver time).
SOLVE = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=False, open_world_hint=True)


@mcp.tool(name="solve", annotations=SOLVE, meta=META)
async def solve(plan_date: str, demand: list[dict], workers: list[dict], exclude: list[str] | None = None) -> dict:
    """Solve the roster: assigns qualified, available workers to each site/line/shift slot."""
    body = {"plan_date": plan_date, "demand": demand, "workers": workers, "exclude": exclude or []}
    return await upstream("cuopt", "POST", "/solve", body=body)


if __name__ == "__main__":
    serve(mcp, "cuopt")
