"""Stage 1 · Demand Forecast Agent.

02:00. Builds staffing demand per site, per line, per shift.

Calls: sap.production_plan (E01), mes.line_availability (E02),
       workday.absences (E03, once per site), Azure OpenAI (E04, once per site)
Node config: retry unbounded, fixed delay, ignores Retry-After.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable

from wpo_agents import config, llm
from wpo_agents.mcp_client import call_tool
from wpo_agents.state import NightlyState
from wpo_agents.tracing import queue_span, tracer

AGENT = "demand_forecast"
log = logging.getLogger("wpo.forecast")


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  DELIBERATE DEFECT — DO NOT FIX.                                         ║
# ║                                                                          ║
# ║  This retry loop is unbounded, waits a fixed delay, has no jitter, and   ║
# ║  ignores the Retry-After header that Workday sends with a 429. Under a   ║
# ║  throttle it multiplies load on Workday (the "6.2x self-inflicted load"  ║
# ║  finding) and pushes the nightly roster past the 05:00 SLO.              ║
# ║                                                                          ║
# ║  It is the weakness the first NaviStorm demo is built on (experiment     ║
# ║  exp-0117, edge E03, fault: Rate limit HTTP 429). Fixing it breaks the   ║
# ║  demo. The recommended guardrail NaviStorm produces is: honour           ║
# ║  Retry-After, cap at 3 attempts, add jitter. Leave that to the demo.     ║
# ╚══════════════════════════════════════════════════════════════════════════╝
async def _until_ok(counter: dict[str, int], label: str, fn: Callable[..., Awaitable[Any]], *args, **kwargs) -> Any:
    attempt = 0
    while True:  # unbounded on purpose; see box above
        attempt += 1
        try:
            return await fn(*args, **kwargs)
        except Exception as exc:  # retries everything, including 429s
            counter["retries"] += 1
            retry_after = getattr(exc, "retry_after", None)  # read, then ignored on purpose
            log.warning("%s attempt %d failed (%s); Retry-After=%s ignored; retrying in %.1fs",
                        label, attempt, exc, retry_after, config.FORECAST_RETRY_DELAY_S)
            await asyncio.sleep(config.FORECAST_RETRY_DELAY_S)  # fixed delay, no backoff, no jitter


def _headcount(units: int) -> int:
    return 1 if units < 1150 else 2


async def forecast_demand(state: NightlyState) -> dict:
    plan_date = state["plan_date"]
    counter = {"retries": 0}
    with tracer.start_as_current_span("invoke_agent demand_forecast") as span:
        span.set_attribute("gen_ai.operation.name", "invoke_agent")
        span.set_attribute("gen_ai.agent.name", AGENT)

        plan = (await _until_ok(counter, "sap.production_plan", call_tool, AGENT, "sap", "production_plan"))["items"]
        lines = (await _until_ok(counter, "mes.line_availability", call_tool, AGENT, "mes", "line_availability"))["items"]
        down = {(r["site_id"], r["line_id"]): set(r["shifts_down"]) for r in lines}

        demand: list[dict] = []
        absences: dict[str, list[dict]] = {}
        notes: dict[str, str] = {}

        # Sites are processed one after another, and stage 2 starts only when
        # all 14 are done: one slow site stalls every site.
        for site in plan:
            sid = site["site_id"]
            absences[sid] = (await _until_ok(
                counter, f"workday.absences[{sid}]", call_tool, AGENT, "workday", "absences", {"site_id": sid}
            ))["items"]

            slots = []
            for line in site["lines"]:
                for shift, units in line["planned_units"].items():
                    is_down = shift in down.get((sid, line["line_id"]), set())
                    slots.append({
                        "site_id": sid, "line_id": line["line_id"], "shift": shift,
                        "planned_units": units, "headcount": 0 if is_down else _headcount(units),
                        "line_down": is_down,
                    })
            with queue_span(AGENT, "send") as qspan:  # E05: per-site demand to stage 2
                qspan.set_attribute("wpo.site_id", sid)
                qspan.set_attribute("messaging.batch.message_count", len(slots))
                demand.extend(slots)

            need = sum(s["headcount"] for s in slots)
            downs = [f"{s['line_id']}/{s['shift']}" for s in slots if s["line_down"]]
            notes[sid] = await _until_ok(
                counter, f"azure_openai[{sid}]", llm.complete, AGENT,
                "You are a manufacturing workforce planner. In two sentences, explain tomorrow's staffing demand for one site.",
                f"Site {sid} ({site['name']}), plan date {plan_date}. Slots: {slots}. Absences: {absences[sid]}.",
                offline=(f"{site['name']}: {need} operators needed across {len(slots)} line-shifts"
                         + (f"; {', '.join(downs)} down for maintenance" if downs else "")
                         + f"; {len(absences[sid])} approved absence(s)."),
            )

        span.set_attribute("wpo.retries", counter["retries"])

    return {
        "demand": demand,
        "absences": absences,
        "forecast_notes": notes,
        "forecast_retries": counter["retries"],
        "events": [f"forecast_demand: {len(plan)} sites, {sum(d['headcount'] for d in demand)} slots, {counter['retries']} retries"],
    }
