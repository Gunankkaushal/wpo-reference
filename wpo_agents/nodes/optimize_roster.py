"""Stage 2 · Roster Optimizer Agent.

Builds the candidate roster per site.

Calls: workday.workers (E07), lms.training_currency (E08), cuopt.solve (E09),
       roster.store (E10, candidate)
Node config: retry 2 (see RETRY_POLICY), max_iter 4 (enforced in supervisor routing).
"""

from __future__ import annotations

from langgraph.types import RetryPolicy

from wpo_agents.mcp_client import ToolCallError, call_tool
from wpo_agents.state import NightlyState
from wpo_agents.tracing import queue_span, tracer

AGENT = "roster_optimizer"


class SolveFailed(Exception):
    """cuOpt answered, but not with status OK."""


# 1 attempt + 2 retries.
RETRY_POLICY = RetryPolicy(max_attempts=3, initial_interval=1.0, backoff_factor=2.0, jitter=True,
                           retry_on=(ToolCallError, SolveFailed))


async def optimize_roster(state: NightlyState) -> dict:
    plan_date = state["plan_date"]
    excluded = list(state.get("excluded_workers", []))
    iteration = state.get("optimizer_iterations", 0) + 1

    with tracer.start_as_current_span("invoke_agent roster_optimizer") as span:
        span.set_attribute("gen_ai.operation.name", "invoke_agent")
        span.set_attribute("gen_ai.agent.name", AGENT)
        span.set_attribute("wpo.iteration", iteration)

        workers = (await call_tool(AGENT, "workday", "workers"))["items"]
        training = (await call_tool(AGENT, "lms", "training_currency"))["items"]

        current = {(t["worker_id"], t["line_id"]) for t in training if t["valid_until"] >= plan_date}
        absent = {a["worker_id"] for rows in state.get("absences", {}).values() for a in rows}
        pool = [
            {
                "worker_id": w["worker_id"],
                "site_id": w["site_id"],
                "hours_worked_week": w["hours_worked_week"],
                "qualified_lines": [ln for ln in w["skills"] if (w["worker_id"], ln) in current],
            }
            for w in workers
            if w["status"] == "active" and w["worker_id"] not in absent
        ]

        with queue_span(AGENT, "receive") as qspan:  # E06: demand per site from stage 1
            demand = [d for d in state["demand"] if d["headcount"] > 0]
            qspan.set_attribute("messaging.batch.message_count", len(demand))
        result = await call_tool(AGENT, "cuopt", "solve",
                                 {"plan_date": plan_date, "demand": demand, "workers": pool, "exclude": excluded})
        if result.get("status") != "OK":
            raise SolveFailed(f"cuopt status {result.get('status')}")

        hours = {w["worker_id"]: w["hours_worked_week"] for w in workers}
        roster = {
            site: [{**a, "hours_worked_week": hours.get(a["worker_id"], 0.0)} for a in assigns]
            for site, assigns in result["roster"].items()
        }

        await call_tool(AGENT, "roster", "store",
                        {"plan_date": plan_date, "run_id": state["run_id"], "status": "candidate", "roster": roster})

    filled = sum(len(v) for v in roster.values())
    return {
        "candidate_roster": roster,
        "unfilled": result.get("unfilled", []),
        "optimizer_iterations": iteration,
        "events": [f"optimize_roster: iteration {iteration}, {filled} assignments, "
                   f"{len(result.get('unfilled', []))} unfilled, excluded {excluded or 'none'}"],
    }
