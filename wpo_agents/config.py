"""Settings, all from environment so NaviStorm proxies can be slotted in front."""

from __future__ import annotations

import os

MCP_DEFAULT_PORTS = {
    "sap": 9101, "workday": 9102, "mes": 9103, "lms": 9104,
    "cuopt": 9105, "teams": 9106, "policy": 9107, "roster": 9108,
}


def _f(name: str, default: str) -> float:
    return float(os.getenv(name, default))


def mcp_url(server: str) -> str:
    """MCP_<SERVER>_URL overrides, e.g. point MCP_WORKDAY_URL at the NaviStorm MCP proxy."""
    host = os.getenv("MCP_BASE_HOST", "127.0.0.1")
    return os.getenv(f"MCP_{server.upper()}_URL", f"http://{host}:{MCP_DEFAULT_PORTS[server]}/mcp")


TOOL_TIMEOUT_S = _f("TOOL_TIMEOUT_S", "15")

# forecast_demand: fixed delay between retries (see the defect note in nodes/forecast_demand.py)
FORECAST_RETRY_DELAY_S = _f("FORECAST_RETRY_DELAY_S", "0.5")

# optimize_roster ⇄ compliance loop limit
OPTIMIZER_MAX_ITER = int(os.getenv("OPTIMIZER_MAX_ITER", "4"))

# Azure OpenAI. With no endpoint/key set, agents use a deterministic offline responder.
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT", "")
AZURE_OPENAI_API_KEY = os.getenv("AZURE_OPENAI_API_KEY", "")
AZURE_OPENAI_DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o-mini")
AZURE_OPENAI_API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-21")

# Manager Copilot business hours
COPILOT_TZ = os.getenv("COPILOT_TZ", "Europe/London")
COPILOT_HOURS = os.getenv("COPILOT_HOURS", "08:00-18:00")
COPILOT_DAYS = os.getenv("COPILOT_DAYS", "0,1,2,3,4")  # Mon=0 … Fri=4

TEAMS_CHANNEL = os.getenv("TEAMS_CHANNEL", "wpo-line-managers")
