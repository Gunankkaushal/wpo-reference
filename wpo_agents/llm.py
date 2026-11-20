"""Azure OpenAI chat, with an offline fallback so the demo runs with no keys.

Set AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_API_KEY and AZURE_OPENAI_DEPLOYMENT to
use the real endpoint. To put NaviStorm's model gateway in front, point
AZURE_OPENAI_ENDPOINT at the gateway.
"""

from __future__ import annotations

from opentelemetry.trace import Status, StatusCode

from wpo_agents import config
from wpo_agents.topology import edge_for
from wpo_agents.tracing import tracer

_client = None


def online() -> bool:
    return bool(config.AZURE_OPENAI_ENDPOINT and config.AZURE_OPENAI_API_KEY)


def _get_client():
    global _client
    if _client is None:
        from openai import AsyncAzureOpenAI

        _client = AsyncAzureOpenAI(
            azure_endpoint=config.AZURE_OPENAI_ENDPOINT,
            api_key=config.AZURE_OPENAI_API_KEY,
            api_version=config.AZURE_OPENAI_API_VERSION,
            # SDK-level retries off: each node's own retry config is the one in force.
            max_retries=0,
            timeout=config.TOOL_TIMEOUT_S,
        )
    return _client


async def complete(agent: str, system: str, user: str, *, offline: str, max_tokens: int = 300) -> str:
    edge_id, _ = edge_for(agent, "azure_openai")
    with tracer.start_as_current_span(f"chat {config.AZURE_OPENAI_DEPLOYMENT}") as span:
        span.set_attribute("gen_ai.operation.name", "chat")
        span.set_attribute("gen_ai.system", "az.ai.openai")
        span.set_attribute("gen_ai.request.model", config.AZURE_OPENAI_DEPLOYMENT)
        span.set_attribute("gen_ai.agent.name", agent)
        span.set_attribute("wpo.edge_id", edge_id)
        if not online():
            span.set_attribute("wpo.llm_mode", "offline")
            return offline
        try:
            resp = await _get_client().chat.completions.create(
                model=config.AZURE_OPENAI_DEPLOYMENT,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                max_tokens=max_tokens,
                temperature=0.2,
            )
        except Exception as exc:
            span.set_status(Status(StatusCode.ERROR, str(exc)))
            raise
        if resp.usage:
            span.set_attribute("gen_ai.usage.input_tokens", resp.usage.prompt_tokens)
            span.set_attribute("gen_ai.usage.output_tokens", resp.usage.completion_tokens)
        return resp.choices[0].message.content or ""
