"""Stage 3 · Compliance Agent.

Blocks a roster that breaks a rule.

Calls: policy.rules (E11), lms.training_currency (E12, re-check at assignment),
       roster.store (E13, verdict)
Node config: no retry. Conditional edge: pass → writeback, fail → back to optimizer.
"""

from __future__ import annotations

from collections import Counter

from wpo_agents.mcp_client import call_tool
from wpo_agents.state import NightlyState
from wpo_agents.tracing import tracer

AGENT = "compliance"


async def compliance(state: NightlyState) -> dict:
    plan_date = state["plan_date"]
    roster = state["candidate_roster"]

    with tracer.start_as_current_span("invoke_agent compliance") as span:
        span.set_attribute("gen_ai.operation.name", "invoke_agent")
        span.set_attribute("gen_ai.agent.name", AGENT)

        rules = await call_tool(AGENT, "policy", "rules")
        training = (await call_tool(AGENT, "lms", "training_currency"))["items"]
        current = {(t["worker_id"], t["line_id"]) for t in training if t["valid_until"] >= plan_date}

        violations: list[dict] = []
        for site, assigns in roster.items():
            per_worker = Counter(a["worker_id"] for a in assigns)
            for a in assigns:
                wid, line = a["worker_id"], a["line_id"]
                projected = a["hours_worked_week"] + a["hours"]
                if projected > rules["max_weekly_hours"]:
                    violations.append({"site_id": site, "worker_id": wid, "rule": "max_weekly_hours",
                                       "detail": f"{projected}h > {rules['max_weekly_hours']}h"})
                if rules["require_current_training_for_line"] and (wid, line) not in current:
                    violations.append({"site_id": site, "worker_id": wid, "rule": "training_not_current",
                                       "detail": f"no current training for {line}"})
                if per_worker[wid] > rules["max_shifts_per_worker_per_day"]:
                    violations.append({"site_id": site, "worker_id": wid, "rule": "max_shifts_per_day",
                                       "detail": f"{per_worker[wid]} shifts"})

        verdict = {"result": "fail" if violations else "pass", "ruleset": rules["ruleset_id"],
                   "violations": violations, "iteration": state.get("optimizer_iterations", 0)}
        span.set_attribute("wpo.verdict", verdict["result"])

        await call_tool(AGENT, "roster", "store", {
            "plan_date": plan_date, "run_id": state["run_id"],
            "status": "rejected" if violations else "approved", "roster": roster, "verdict": verdict,
        })

    excluded = sorted(set(state.get("excluded_workers", [])) | {v["worker_id"] for v in violations})
    return {
        "compliance": verdict,
        "excluded_workers": excluded,
        "events": [f"compliance: {verdict['result']}"
                   + (f" ({len(violations)} violation(s): {', '.join(v['worker_id'] + ' ' + v['rule'] for v in violations)})"
                      if violations else "")],
    }
