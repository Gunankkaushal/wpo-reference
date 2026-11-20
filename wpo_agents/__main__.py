"""CLI.

  python -m wpo_agents nightly [--plan-date YYYY-MM-DD]      run the nightly roster journey
  python -m wpo_agents ask "who is on L1 early?" [--site SITE-01] [--ignore-hours]
  python -m wpo_agents graph                                 print both graphs as Mermaid
  python -m wpo_agents discover [--no-run] [--out FILE]      rebuild the topology from traces + MCP manifests
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import time

from wpo_agents import tracing


async def _nightly(args) -> int:
    from wpo_agents.supervisor import graph

    t0 = time.perf_counter()
    init = {"plan_date": args.plan_date} if args.plan_date else {}
    with tracing.orchestrator_span():
        final = await graph.ainvoke(init, {"recursion_limit": 50})
    elapsed = time.perf_counter() - t0
    for e in final.get("events", []):
        print(" -", e)
    summary = {
        "run_id": final.get("run_id"),
        "plan_date": final.get("plan_date"),
        "status": final.get("status"),
        "sites_published": len(final.get("published_sites", [])),
        "forecast_retries": final.get("forecast_retries", 0),
        "optimizer_iterations": final.get("optimizer_iterations"),
        "elapsed_s": round(elapsed, 1),
    }
    print(json.dumps(summary, indent=2))
    return 0 if final.get("status") == "published" else 1


async def _ask(args) -> int:
    from wpo_agents.manager_copilot import graph

    with tracing.agent_span("manager_copilot"):
        final = await graph.ainvoke({"question": args.question, "site_id": args.site, "ignore_hours": args.ignore_hours})
    print(final["answer"])
    return 0


def _graph(_args) -> int:
    from wpo_agents.manager_copilot import graph as copilot
    from wpo_agents.supervisor import graph as nightly

    print("%% nightly roster (supervisor)\n" + nightly.get_graph().draw_mermaid())
    print("%% manager copilot\n" + copilot.get_graph().draw_mermaid())
    return 0


def main() -> None:
    p = argparse.ArgumentParser(prog="wpo_agents")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)
    n = sub.add_parser("nightly", help="run the nightly roster journey")
    n.add_argument("--plan-date")
    a = sub.add_parser("ask", help="ask Manager Copilot")
    a.add_argument("question")
    a.add_argument("--site")
    a.add_argument("--ignore-hours", action="store_true", help="bypass the business-hours gate (demo only)")
    sub.add_parser("graph", help="print graphs as Mermaid")
    d = sub.add_parser("discover", help="rebuild the NaviStorm topology from traces and MCP manifests")
    d.add_argument("--out", default="data/discovered_topology.json")
    d.add_argument("--no-run", action="store_true", help="read MCP manifests only")
    args = p.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)-7s %(name)s  %(message)s", datefmt="%H:%M:%S")
    for noisy in ("httpx", "httpx2", "mcp", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    tracing.setup()
    try:
        if args.cmd == "graph":
            rc = _graph(args)
        elif args.cmd == "discover":
            from wpo_agents import discover
            rc = discover.run(["--out", args.out] + (["--no-run"] if args.no_run else []))
        else:
            rc = asyncio.run(_nightly(args) if args.cmd == "nightly" else _ask(args))
    finally:
        tracing.shutdown()
    raise SystemExit(rc)


if __name__ == "__main__":
    main()
