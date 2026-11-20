"""Rebuild the topology screen the way NaviStorm discovery does: from traces and MCP manifests only.

    python -m wpo_agents discover [--out data/discovered_topology.json] [--no-run]

Nothing here reads topology.yaml or wpo_agents/topology.py to build the result.
There are two sources:

  otel_trace    spans emitted while both journeys run (OTel GenAI conventions:
                gen_ai.operation.name, gen_ai.agent.name, gen_ai.tool.name,
                messaging.* for the forecast queue)
  mcp_manifest  tools/list from every MCP server: tool names, annotations
                (readOnlyHint, destructiveHint) and _meta["wpo/backend"],
                which says what sits behind the server

Every node and edge records the sources that classified it in `classified_by`.
The declared map in wpo_agents/topology.py is used only afterwards, as a
cross-check, and never as an input.

Running it executes the nightly journey once (which publishes a roster to the
stubs) and asks Manager Copilot one question. With --no-run, only the MCP
manifests are read.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from mcp import Client
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from wpo_agents import config, tracing

TRACE, MANIFEST = "otel_trace", "mcp_manifest"
READ_ACTIONS = {"latest", "get", "read", "list"}
EXPECTED = {"orchestrators": 1, "agents": 5, "mcp_tools": 11, "systems": 6, "edges": 18}


def _install_exporter() -> InMemorySpanExporter:
    exporter = InMemorySpanExporter()
    provider = trace.get_tracer_provider()
    if not isinstance(provider, TracerProvider):  # no OTLP export configured: install our own provider
        provider = TracerProvider()
        trace.set_tracer_provider(provider)
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    return exporter


async def _run_journeys() -> None:
    from wpo_agents.manager_copilot import graph as copilot
    from wpo_agents.supervisor import graph as nightly

    with tracing.orchestrator_span():
        await nightly.ainvoke({}, {"recursion_limit": 50})
    with tracing.agent_span("manager_copilot"):
        await copilot.ainvoke({"question": "Who is on L1 early?", "site_id": "SITE-01", "ignore_hours": True})


async def _manifests() -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for server in config.MCP_DEFAULT_PORTS:
        async with Client(config.mcp_url(server)) as client:
            res = await client.list_tools()
        out[server] = [t.model_dump(by_alias=True, exclude_none=True) for t in res.tools]
    return out


class Topology:
    def __init__(self) -> None:
        self.nodes: dict[str, dict] = {}
        self.edges: dict[tuple[str, str], dict] = {}

    def node(self, node_id: str, kind: str, source: str, **fields) -> dict:
        n = self.nodes.setdefault(node_id, {"id": node_id, "kind": kind, "classified_by": []})
        if source not in n["classified_by"]:
            n["classified_by"].append(source)
        for k, v in fields.items():
            n.setdefault(k, v)
        return n

    def edge(self, src: str, dst: str, source: str, **fields) -> dict:
        e = self.edges.setdefault((src, dst), {"from": src, "to": dst, "classified_by": [], "calls": 0})
        if source not in e["classified_by"]:
            e["classified_by"].append(source)
        for k, v in fields.items():
            e.setdefault(k, v)
        return e

    # ── source 1: traces ──
    def add_spans(self, spans) -> None:
        for s in spans:
            a = dict(s.attributes or {})
            op = a.get("gen_ai.operation.name")
            agent = a.get("gen_ai.agent.name")
            if op == "invoke_workflow":
                self.node(a.get("wpo.orchestrator") or a.get("gen_ai.workflow.name", "workflow"), "orchestrator", TRACE,
                          workflow=a.get("gen_ai.workflow.name"))
            elif op == "invoke_agent" and agent:
                self.node(agent, "agent", TRACE)
            elif op == "execute_tool" and agent:
                tool = a["gen_ai.tool.name"]
                self.node(agent, "agent", TRACE)
                self.node(tool, "mcp_tool", TRACE)
                e = self.edge(agent, tool, TRACE, edge_id=a.get("wpo.edge_id"), hop="mcp", actions=[])
                e["calls"] += 1
                act = a.get("wpo.tool.action", "default")
                if act not in e["actions"]:
                    e["actions"].append(act)
            elif op == "chat" and agent:
                model_id = "azure_openai" if a.get("gen_ai.system") == "az.ai.openai" else a.get("gen_ai.system", "model")
                self.node(agent, "agent", TRACE)
                self.node(model_id, "model_endpoint", TRACE, model=a.get("gen_ai.request.model"))
                e = self.edge(agent, model_id, TRACE, edge_id=a.get("wpo.edge_id"), hop="model", access="read")
                e["calls"] += 1
            elif a.get("messaging.destination.name") and agent:
                q = a["messaging.destination.name"]
                self.node(agent, "agent", TRACE)
                self.node(q, "queue", TRACE, messaging_system=a.get("messaging.system"))
                access = "write" if a.get("messaging.operation.type") == "send" else "read"
                e = self.edge(agent, q, TRACE, edge_id=a.get("wpo.edge_id"), hop="queue", access=access)
                e["calls"] += 1

    # ── source 2: MCP manifests ──
    def add_manifests(self, manifests: dict[str, list[dict]]) -> None:
        for server, tools in manifests.items():
            for t in tools:
                tool_id = f"{server}.{t['name']}"
                ann = t.get("annotations", {})
                backend = t.get("_meta", {}).get("wpo/backend", {})
                access = "write" if ann.get("destructiveHint") else ("read" if ann.get("readOnlyHint") else "unknown")
                self.node(tool_id, "mcp_tool", MANIFEST, server=server, access=access,
                          destructive=bool(ann.get("destructiveHint")), backend=backend.get("id"))
                if backend:
                    kind = "system" if backend.get("kind") == "external_system" else "internal_service"
                    self.node(backend["id"], kind, MANIFEST, name=backend.get("name"))
        # Tool edges observed in traces are confirmed and typed by the manifest.
        for (src, dst), e in self.edges.items():
            tool = self.nodes.get(dst, {})
            if tool.get("kind") == "mcp_tool" and MANIFEST in tool["classified_by"]:
                e["classified_by"].append(MANIFEST)
                # A destructive tool used only with a read action is a read edge (E17: roster.store action=latest).
                read_only_use = tool["destructive"] and set(e.get("actions", [])) <= READ_ACTIONS
                e.setdefault("access", "read" if read_only_use else tool["access"])
                e["destructive"] = tool["destructive"] and not read_only_use
        # A backend whose tools were called is also seen in traces.
        called = {self.nodes[dst].get("backend") for (_s, dst) in self.edges if self.nodes.get(dst, {}).get("backend")}
        for b in called:
            if b in self.nodes and TRACE not in self.nodes[b]["classified_by"]:
                self.nodes[b]["classified_by"].append(TRACE)

    def summary(self) -> dict:
        kinds = [n["kind"] for n in self.nodes.values()]
        return {"orchestrators": kinds.count("orchestrator"), "agents": kinds.count("agent"),
                "mcp_tools": kinds.count("mcp_tool"), "systems": kinds.count("system"), "edges": len(self.edges)}

    def to_json(self) -> dict:
        edges = sorted(self.edges.values(), key=lambda e: (e.get("edge_id") or "Z", e["from"], e["to"]))
        return {"summary": self.summary(), "nodes": sorted(self.nodes.values(), key=lambda n: (n["kind"], n["id"])),
                "edges": edges}


def _cross_check(topo: Topology) -> list[str]:
    """Compare with the declared map. Reporting only; never an input to the result."""
    from wpo_agents.topology import EDGES

    found = {(e["from"], e["to"]): e.get("edge_id") for e in topo.edges.values()}
    problems = [f"missing {eid} {a} -> {t}" for (a, t), (eid, _acc) in EDGES.items() if (a, t) not in found]
    problems += [f"undeclared edge {a} -> {t}" for (a, t) in found if (a, t) not in EDGES]
    problems += [f"edge id mismatch {a} -> {t}: span says {found[(a, t)]}, declared {EDGES[(a, t)][0]}"
                 for (a, t) in found if (a, t) in EDGES and found[(a, t)] != EDGES[(a, t)][0]]
    return problems


def _print(topo: Topology) -> None:
    data = topo.to_json()
    by_kind: dict[str, list[dict]] = {}
    for n in data["nodes"]:
        by_kind.setdefault(n["kind"], []).append(n)
    print("NODES")
    for kind in ("orchestrator", "agent", "mcp_tool", "system", "internal_service", "queue", "model_endpoint"):
        for n in by_kind.get(kind, []):
            print(f"  {kind:<17} {n['id']:<24} classified_by={'+'.join(n['classified_by'])}")
    print("EDGES")
    for e in data["edges"]:
        extra = " destructive" if e.get("destructive") else ""
        print(f"  {e.get('edge_id') or '???':<4} {e['from']:<17} -> {e['to']:<22} {e.get('access', '?'):<6}"
              f" calls={e['calls']:<3} classified_by={'+'.join(e['classified_by'])}{extra}")


async def _main(args) -> int:
    exporter = _install_exporter()
    if not args.no_run:
        await _run_journeys()
    topo = Topology()
    topo.add_spans(exporter.get_finished_spans())
    topo.add_manifests(await _manifests())

    _print(topo)
    s = topo.summary()
    print("\nSUMMARY  " + "  ".join(f"{k}={v} (expected {EXPECTED[k]})" for k, v in s.items()))
    problems = [] if args.no_run else _cross_check(topo)
    for p in problems:
        print("  cross-check:", p)
    unclassified = [n["id"] for n in topo.nodes.values() if not n["classified_by"]]
    ok = s == EXPECTED and not problems and not unclassified if not args.no_run else s["mcp_tools"] == 11 and s["systems"] == 6

    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(topo.to_json(), indent=1), encoding="utf-8")
        print(f"wrote {out}")
    print("RESULT  " + ("PASS: topology matches the NaviStorm topology screen" if ok else "FAIL"))
    return 0 if ok else 1


def run(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="wpo_agents discover")
    p.add_argument("--out", default="data/discovered_topology.json")
    p.add_argument("--no-run", action="store_true", help="read MCP manifests only; do not run the journeys")
    return asyncio.run(_main(p.parse_args(argv)))
