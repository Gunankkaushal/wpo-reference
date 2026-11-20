"""MCP server · policy.rules (working time, union terms, site rules).

Internal WPO service with no external system behind it, so the ruleset is
held here rather than in a stub.
"""

from mcp_servers.common import READ, new_server, serve, backend_meta

mcp = new_server("policy", "WPO compliance ruleset.")
META = backend_meta("policy")

RULESET = {
    "ruleset_id": "WPO-RULES-2026.4",
    "max_weekly_hours": 48.0,
    "min_rest_hours_between_shifts": 11,
    "max_shifts_per_worker_per_day": 1,
    "max_consecutive_nights": 3,
    "require_current_training_for_line": True,
    "union_terms": {
        "UNITE": {"max_weekly_hours": 48.0, "night_premium": 0.25},
        "GMB": {"max_weekly_hours": 48.0, "night_premium": 0.20},
    },
    "site_rules": {
        "SITE-03": {"note": "L2 under requalification; no assignments to L2"},
        "SITE-11": {"note": "Two qualified operators per line on early shift when degraded"},
    },
}


@mcp.tool(name="rules", annotations=READ, meta=META)
async def rules() -> dict:
    """The current compliance ruleset."""
    return RULESET


if __name__ == "__main__":
    serve(mcp, "policy")
