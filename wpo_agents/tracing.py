"""OpenTelemetry with GenAI semantic-convention attributes.

NaviStorm's discovery treats OTel GenAI spans as authoritative for call kind,
model and parent span. Export is on only when OTEL_EXPORTER_OTLP_ENDPOINT is
set; otherwise the tracer is a no-op.
"""

from __future__ import annotations

import os

from opentelemetry import trace

_configured = False


def setup(service_name: str = "wpo-agents") -> None:
    global _configured
    if _configured or not os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"):
        return
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    provider = TracerProvider(resource=Resource.create({"service.name": service_name, "wpo.product": "workforce-optimization"}))
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(provider)
    _configured = True


def shutdown() -> None:
    provider = trace.get_tracer_provider()
    if hasattr(provider, "shutdown"):
        provider.shutdown()


tracer = trace.get_tracer("wpo_agents")


# ── Spans that let discovery classify nodes from traces alone ──────────────

def orchestrator_span(workflow: str = "wpo_nightly_roster"):
    """Root span of the nightly journey. The LangGraph supervisor is the one orchestrator.

    It carries no gen_ai.agent.name, so it is never counted as an agent.
    """
    span = tracer.start_as_current_span(f"invoke_workflow {workflow}")
    return _with_attrs(span, {"gen_ai.operation.name": "invoke_workflow", "gen_ai.workflow.name": workflow,
                              "wpo.node_role": "orchestrator", "wpo.orchestrator": "supervisor"})


def agent_span(agent: str):
    """Root span for an agent that runs as its own graph (Manager Copilot)."""
    span = tracer.start_as_current_span(f"invoke_agent {agent}")
    return _with_attrs(span, {"gen_ai.operation.name": "invoke_agent", "gen_ai.agent.name": agent,
                              "wpo.node_role": "agent"})


def queue_span(agent: str, operation: str, destination: str = "forecast-queue"):
    """E05 (send) / E06 (receive). In production this is Azure Service Bus; in this repo
    the hand-off rides LangGraph state, and the span marks where the queue sits."""
    from opentelemetry.trace import SpanKind

    from wpo_agents.topology import edge_for

    edge_id, access = edge_for(agent, destination)
    kind = SpanKind.PRODUCER if operation == "send" else SpanKind.CONSUMER
    span = tracer.start_as_current_span(f"{operation} {destination}", kind=kind)
    return _with_attrs(span, {"messaging.system": "servicebus", "messaging.destination.name": destination,
                              "messaging.operation.type": operation, "gen_ai.agent.name": agent,
                              "wpo.edge_id": edge_id, "wpo.access": access, "wpo.transport": "graph_state"})


class _with_attrs:
    def __init__(self, cm, attrs: dict):
        self._cm, self._attrs = cm, attrs

    def __enter__(self):
        span = self._cm.__enter__()
        for k, v in self._attrs.items():
            span.set_attribute(k, v)
        return span

    def __exit__(self, *exc):
        return self._cm.__exit__(*exc)
