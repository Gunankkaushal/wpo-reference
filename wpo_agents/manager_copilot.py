"""Stage 5 · Manager Copilot. Separate graph, own entry point, business hours.

06:00 onward, line managers ask about today's roster.

Calls: roster.store (E17, action=latest: latest approved roster), Azure OpenAI (E18)

    business_hours_gate ─┬─ open   → load_roster → answer → END
                         └─ closed → END

Behaviour the NaviStorm findings rely on (not planted, just how it is
written): the copilot answers from whatever roster is latest in the store and
does not say when that roster was generated. After a bad night it serves
yesterday's roster as if it were today's.
"""

from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo

from langgraph.graph import END, START, StateGraph

from wpo_agents import config, llm
from wpo_agents.mcp_client import call_tool
from wpo_agents.state import CopilotState
from wpo_agents.tracing import tracer

AGENT = "manager_copilot"


def _is_open(now: datetime | None = None) -> bool:
    now = now or datetime.now(ZoneInfo(config.COPILOT_TZ))
    start_s, end_s = config.COPILOT_HOURS.split("-")
    days = {int(d) for d in config.COPILOT_DAYS.split(",")}
    return now.weekday() in days and time.fromisoformat(start_s) <= now.time() < time.fromisoformat(end_s)


def business_hours_gate(state: CopilotState) -> dict:
    if state.get("ignore_hours") or _is_open():
        return {"open": True}
    return {"open": False,
            "answer": f"Manager Copilot is available {config.COPILOT_HOURS} ({config.COPILOT_TZ}), Monday to Friday."}


async def load_roster(state: CopilotState) -> dict:
    record = await call_tool(AGENT, "roster", "store", {"action": "latest", "site_id": state.get("site_id")})
    return {"roster_record": record}


def _offline_answer(state: CopilotState) -> str:
    rec = state["roster_record"]
    if not rec.get("found"):
        return "I couldn't find a roster."
    lines = []
    for site, assigns in rec["roster"].items():
        lines.append(f"{site}:")
        for a in sorted(assigns, key=lambda a: (a["shift"], a["line_id"])):
            lines.append(f"  {a['shift']:<5} {a['line_id']}  {a['worker_id']}  {a['start']}-{a['end']}")
    return "Here is the roster:\n" + "\n".join(lines)


async def answer(state: CopilotState) -> dict:
    with tracer.start_as_current_span("invoke_agent manager_copilot") as span:
        span.set_attribute("gen_ai.operation.name", "invoke_agent")
        span.set_attribute("gen_ai.agent.name", AGENT)
        text = await llm.complete(
            AGENT,
            "You help manufacturing line managers with today's shift roster. Answer briefly from the roster given.",
            f"Roster: {state['roster_record'].get('roster')}\n\nQuestion: {state['question']}",
            offline=_offline_answer(state),
            max_tokens=400,
        )
    return {"answer": text}


def build_graph():
    g = StateGraph(CopilotState)
    g.add_node("business_hours_gate", business_hours_gate)
    g.add_node("load_roster", load_roster)
    g.add_node("answer", answer)
    g.add_edge(START, "business_hours_gate")
    g.add_conditional_edges("business_hours_gate", lambda s: "load_roster" if s["open"] else END,
                            {"load_roster": "load_roster", END: END})
    g.add_edge("load_roster", "answer")
    g.add_edge("answer", END)
    return g.compile(name="wpo_manager_copilot")


graph = build_graph()
