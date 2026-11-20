"""The only path from an agent to a system: an MCP tool call.

Errors are typed so node configs can decide what to retry:
  ToolCallError  any failed tool call; carries upstream status and Retry-After
  ToolTimeout    the call (or the system behind it) timed out
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from mcp import Client
from opentelemetry.trace import Status, StatusCode

from wpo_agents import config
from wpo_agents.topology import edge_for
from wpo_agents.tracing import tracer

log = logging.getLogger("wpo.mcp")


class ToolCallError(Exception):
    def __init__(self, target: str, message: str, status: int | None = None, retry_after: str | None = None):
        super().__init__(f"{target}: {message}")
        self.target = target
        self.status = status
        self.retry_after = retry_after


class ToolTimeout(ToolCallError):
    pass


def _parse_error(target: str, text: str) -> ToolCallError:
    detail: dict[str, Any] = {}
    if "{" in text:
        try:
            detail = json.loads(text[text.index("{"):])
        except json.JSONDecodeError:
            pass
    if detail.get("error") == "timeout":
        return ToolTimeout(target, "upstream timeout")
    status = detail.get("upstream_status")
    message = f"HTTP {status}" if status else detail.get("error", text)
    return ToolCallError(target, message, status, detail.get("retry_after"))


async def call_tool(agent: str, server: str, tool: str, args: dict | None = None, *, timeout: float | None = None) -> dict:
    target = f"{server}.{tool}"
    edge_id, access = edge_for(agent, target)
    timeout = timeout or config.TOOL_TIMEOUT_S

    with tracer.start_as_current_span(f"execute_tool {target}") as span:
        span.set_attribute("gen_ai.operation.name", "execute_tool")
        span.set_attribute("gen_ai.tool.name", target)
        span.set_attribute("gen_ai.agent.name", agent)
        span.set_attribute("mcp.server.url", config.mcp_url(server))
        span.set_attribute("wpo.edge_id", edge_id)
        span.set_attribute("wpo.access", access)
        if args and "action" in args:  # multi-action tools (roster.store): lets discovery tell reads from writes
            span.set_attribute("wpo.tool.action", str(args["action"]))

        async def _do():
            async with Client(config.mcp_url(server)) as client:
                return await client.call_tool(tool, args or {})

        try:
            result = await asyncio.wait_for(_do(), timeout=timeout)
        except asyncio.TimeoutError:
            err: ToolCallError = ToolTimeout(target, f"no response in {timeout}s")
            span.set_status(Status(StatusCode.ERROR, str(err)))
            raise err from None
        except Exception as exc:  # transport failure: server down, connection refused
            err = ToolCallError(target, f"transport: {exc!r}")
            span.set_status(Status(StatusCode.ERROR, str(err)))
            raise err from None

        text = result.content[0].text if result.content else "{}"
        if result.is_error:
            err = _parse_error(target, text)
            if err.status:
                span.set_attribute("http.response.status_code", err.status)
            span.set_status(Status(StatusCode.ERROR, str(err)))
            log.debug("%s %s -> error %s", agent, target, err)
            raise err
        return json.loads(text)
