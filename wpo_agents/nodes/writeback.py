"""Stage 4 · Writeback Agent. WRITE PATH.

Publishes the approved roster.

Calls: workday.schedules (E14, per site), sap.shift_confirm (E15, per site),
       teams.notify (E16)
Node config: retries on timeout only.

Note for the demo (not a planted defect, just how this node is written): the
retry re-runs the whole node, and the writes carry no idempotency key, so a
timeout on site 9 re-publishes sites 1–8. That is what NaviStorm's
"duplicate write" fault on E14 is there to show, once a sandbox tenant exists.
"""

from __future__ import annotations

from collections import Counter

from langgraph.types import RetryPolicy

from wpo_agents import config
from wpo_agents.mcp_client import ToolTimeout, call_tool
from wpo_agents.state import NightlyState
from wpo_agents.tracing import tracer

AGENT = "writeback"

RETRY_POLICY = RetryPolicy(max_attempts=3, initial_interval=2.0, backoff_factor=2.0, jitter=True, retry_on=ToolTimeout)


async def writeback(state: NightlyState) -> dict:
    plan_date, run_id = state["plan_date"], state["run_id"]
    roster = state["candidate_roster"]
    published: list[str] = []

    with tracer.start_as_current_span("invoke_agent writeback") as span:
        span.set_attribute("gen_ai.operation.name", "invoke_agent")
        span.set_attribute("gen_ai.agent.name", AGENT)

        for site_id in sorted(roster):
            assigns = roster[site_id]
            await call_tool(AGENT, "workday", "schedules",
                            {"site_id": site_id, "plan_date": plan_date, "assignments": assigns, "run_id": run_id})
            staffing = Counter((a["line_id"], a["shift"]) for a in assigns)
            await call_tool(AGENT, "sap", "shift_confirm", {
                "site_id": site_id, "plan_date": plan_date,
                "staffing": [{"line_id": ln, "shift": sh, "headcount": n} for (ln, sh), n in sorted(staffing.items())],
            })
            published.append(site_id)

        unfilled = state.get("unfilled", [])
        msg = (f"Roster for {plan_date} is live for {len(published)} of 14 sites."
               + (f" {len(unfilled)} slot(s) unfilled; check WPO." if unfilled else ""))
        await call_tool(AGENT, "teams", "notify", {"channel": config.TEAMS_CHANNEL, "message": msg, "site_ids": published})

    return {
        "published_sites": published,
        "status": "published",
        "events": [f"writeback: published {len(published)} sites, Teams notified"],
    }
