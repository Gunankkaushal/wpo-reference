"""Shared plumbing for the MCP servers."""

from __future__ import annotations

import json
import os
from typing import Any

import httpx
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

# Port plan. Stubs on 81xx, MCP servers on 91xx. Override any URL by env so a
# NaviStorm proxy can be put in front without code changes.
STUB_PORTS = {"sap": 8101, "workday": 8102, "mes": 8103, "lms": 8104, "cuopt": 8105, "teams": 8106}
MCP_PORTS = {
    "sap": 9101, "workday": 9102, "mes": 9103, "lms": 9104,
    "cuopt": 9105, "teams": 9106, "policy": 9107, "roster": 9108,
}

READ = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=True)
# Every write tool is marked destructiveHint: true.
WRITE = ToolAnnotations(read_only_hint=False, destructive_hint=True, idempotent_hint=False, open_world_hint=True)

# What sits behind each MCP server, published in every tool's _meta so a
# discovery tool can tell the six external systems from internal services
# using the MCP manifest alone (tools/list), with nothing hand-configured.
BACKENDS = {
    "sap":     {"id": "sap",     "name": "SAP S/4",         "kind": "external_system"},
    "workday": {"id": "workday", "name": "Workday",         "kind": "external_system"},
    "mes":     {"id": "mes",     "name": "MES",             "kind": "external_system"},
    "lms":     {"id": "lms",     "name": "Learning system", "kind": "external_system"},
    "cuopt":   {"id": "cuopt",   "name": "NVIDIA cuOpt",    "kind": "external_system"},
    "teams":   {"id": "teams",   "name": "Microsoft Teams", "kind": "external_system"},
    "policy":  {"id": "policy",  "name": "WPO policy rules", "kind": "internal_service"},
    "roster":  {"id": "roster",  "name": "WPO roster store", "kind": "internal_service"},
}


def backend_meta(server: str) -> dict:
    return {"wpo/backend": BACKENDS[server]}


UPSTREAM_TIMEOUT_S = float(os.getenv("UPSTREAM_TIMEOUT_S", "10"))


def stub_url(system: str) -> str:
    return os.getenv(f"STUB_{system.upper()}_URL", f"http://127.0.0.1:{STUB_PORTS[system]}")


def tool_error(**detail: Any) -> ToolError:
    """Errors carry a JSON body so the agent side can read status and Retry-After."""
    return ToolError(json.dumps(detail))


_clients: dict[str, httpx.AsyncClient] = {}


def _client(system: str) -> httpx.AsyncClient:
    # One pooled client per system for the life of the server process. Building
    # a client per call reloads the CA bundle each time (~0.5 s on Windows).
    if system not in _clients:
        _clients[system] = httpx.AsyncClient(base_url=stub_url(system), timeout=UPSTREAM_TIMEOUT_S)
    return _clients[system]


async def upstream(system: str, method: str, path: str, *, params: dict | None = None, body: Any = None) -> Any:
    """Call a stub. Upstream status, Retry-After and timeouts are passed through, not swallowed."""
    params = {k: v for k, v in (params or {}).items() if v is not None}
    try:
        resp = await _client(system).request(method, path, params=params, json=body)
    except httpx.TimeoutException:
        raise tool_error(error="timeout", system=system, path=path) from None
    except httpx.HTTPError as exc:
        raise tool_error(error="unreachable", system=system, path=path, detail=str(exc)) from None
    if resp.status_code >= 400:
        raise tool_error(
            error="upstream_error",
            system=system,
            path=path,
            upstream_status=resp.status_code,
            retry_after=resp.headers.get("Retry-After"),
            body=resp.text[:300],
        )
    return resp.json()


def new_server(name: str, description: str) -> MCPServer:
    return MCPServer(name=name, title=f"WPO {name} MCP server", description=description, version="0.1.0")


def serve(server: MCPServer, name: str) -> None:
    server.run(
        transport="streamable-http",
        host=os.getenv("MCP_HOST", "0.0.0.0"),
        port=int(os.getenv(f"MCP_{name.upper()}_PORT", MCP_PORTS[name])),
        stateless_http=True,
        json_response=True,
    )
