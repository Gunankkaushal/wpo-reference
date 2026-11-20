"""Edge ids, matching the NaviStorm journey screen (E01–E18).

Used to tag every span with wpo.edge_id so traces line up with the console.
topology.yaml at the repo root is the same map in declared-topology form.
"""

AGENTS = {
    "demand_forecast": "Demand Forecast Agent",
    "roster_optimizer": "Roster Optimizer Agent",
    "compliance": "Compliance Agent",
    "writeback": "Writeback Agent",
    "manager_copilot": "Manager Copilot",
}

# (agent, target) -> (edge_id, access)
EDGES: dict[tuple[str, str], tuple[str, str]] = {
    ("demand_forecast", "sap.production_plan"): ("E01", "read"),
    ("demand_forecast", "mes.line_availability"): ("E02", "read"),
    ("demand_forecast", "workday.absences"): ("E03", "read"),
    ("demand_forecast", "azure_openai"): ("E04", "read"),
    ("demand_forecast", "forecast-queue"): ("E05", "write"),
    ("roster_optimizer", "forecast-queue"): ("E06", "read"),
    ("roster_optimizer", "workday.workers"): ("E07", "read"),
    ("roster_optimizer", "lms.training_currency"): ("E08", "read"),
    ("roster_optimizer", "cuopt.solve"): ("E09", "read"),
    ("roster_optimizer", "roster.store"): ("E10", "write"),
    ("compliance", "policy.rules"): ("E11", "read"),
    ("compliance", "lms.training_currency"): ("E12", "read"),
    ("compliance", "roster.store"): ("E13", "read_write"),
    ("writeback", "workday.schedules"): ("E14", "write"),
    ("writeback", "sap.shift_confirm"): ("E15", "write"),
    ("writeback", "teams.notify"): ("E16", "write"),
    ("manager_copilot", "roster.store"): ("E17", "read"),
    ("manager_copilot", "azure_openai"): ("E18", "read"),
}


def edge_for(agent: str, target: str) -> tuple[str, str]:
    return EDGES.get((agent, target), ("E??", "unknown"))
