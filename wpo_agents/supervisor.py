"""Nightly roster journey: LangGraph supervisor over nodes 1–4, in order.

    supervisor → forecast_demand → optimize_roster → compliance ─┬─ pass → writeback → END
                                        ▲                        ├─ fail → optimize_roster   (iterations < max_iter)
                                        └────────────────────────┘
                                                                 └─ fail at max_iter → END (status failed_compliance)

Node configs:
  forecast_demand  retry unbounded, fixed delay, ignores Retry-After (inside the node, deliberate defect)
  optimize_roster  retry 2, max_iter 4
  compliance       no retry; conditional edge
  writeback        write path; retries on timeout
"""

from __future__ import annotations

from datetime import date, datetime

from langgraph.graph import END, START, StateGraph

from wpo_agents import config
from wpo_agents.nodes import optimize_roster as opt
from wpo_agents.nodes import writeback as wb
from wpo_agents.nodes.compliance import compliance
from wpo_agents.nodes.forecast_demand import forecast_demand
from wpo_agents.state import NightlyState


def supervisor(state: NightlyState) -> dict:
    """Opens the run. Stamps run id and plan date, then hands to stage 1."""
    now = datetime.now()
    run_id = state.get("run_id") or f"run-{now:%Y%m%d-%H%M%S}"
    plan_date = state.get("plan_date") or date.today().isoformat()
    return {
        "run_id": run_id,
        "plan_date": plan_date,
        "started_at": now.isoformat(timespec="seconds"),
        "status": "running",
        "optimizer_iterations": 0,
        "excluded_workers": [],
        "events": [f"supervisor: {run_id} opened for plan date {plan_date}"],
    }


def route_after_compliance(state: NightlyState) -> str:
    if state["compliance"]["result"] == "pass":
        return "writeback"
    if state.get("optimizer_iterations", 0) < config.OPTIMIZER_MAX_ITER:
        return "optimize_roster"
    return "give_up"


def give_up(state: NightlyState) -> dict:
    """max_iter reached with Compliance still failing. Nothing is written."""
    return {"status": "failed_compliance",
            "events": [f"supervisor: compliance still failing after {config.OPTIMIZER_MAX_ITER} optimizer iterations; nothing published"]}


def build_graph():
    g = StateGraph(NightlyState)
    g.add_node("supervisor", supervisor)
    # No graph-level retry policy here: the unbounded retry lives inside the node.
    g.add_node("forecast_demand", forecast_demand)
    g.add_node("optimize_roster", opt.optimize_roster, retry_policy=opt.RETRY_POLICY)
    g.add_node("compliance", compliance)  # no retry
    g.add_node("writeback", wb.writeback, retry_policy=wb.RETRY_POLICY)
    g.add_node("give_up", give_up)

    g.add_edge(START, "supervisor")
    g.add_edge("supervisor", "forecast_demand")
    g.add_edge("forecast_demand", "optimize_roster")
    g.add_edge("optimize_roster", "compliance")
    g.add_conditional_edges("compliance", route_after_compliance,
                            {"writeback": "writeback", "optimize_roster": "optimize_roster", "give_up": "give_up"})
    g.add_edge("writeback", END)
    g.add_edge("give_up", END)
    return g.compile(name="wpo_nightly_roster")


graph = build_graph()
