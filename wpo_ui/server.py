"""WPO console: the web front end of the WPO product.

It drives the same LangGraph agents as the CLI, so every call to a system is
still an MCP tool call made by an agent, and NaviStorm sees the same edges
(E01-E18) and spans. The console itself only adds:

  POST /api/nightly        run the nightly roster journey, streamed per node (NDJSON)
  POST /api/ask            ask Manager Copilot
  GET  /api/roster         latest approved roster (read through the roster MCP server)
  GET  /api/systems        liveness of the 6 stubs and 8 MCP servers
  GET  /api/stats          per-stub call counts and write counts (demo aid)
  POST /api/stats/reset    clear stub counters and any local fault
  GET  /api/topology       agents, edges and both graphs as Mermaid

Run:  python -m wpo_ui        (http://127.0.0.1:8000)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from mcp import Client
from pydantic import BaseModel

from wpo_agents import config, tracing
from wpo_agents.topology import AGENTS, EDGES

STATIC = Path(__file__).parent / "static"
STUB_PORTS = {"sap": 8101, "workday": 8102, "mes": 8103, "lms": 8104, "cuopt": 8105, "teams": 8106}
STUB_LABELS = {"sap": "SAP S/4", "workday": "Workday", "mes": "MES", "lms": "Learning system",
               "cuopt": "NVIDIA cuOpt", "teams": "Microsoft Teams"}

log = logging.getLogger("wpo.ui")
_run_lock = asyncio.Lock()


def stub_url(system: str) -> str:
    host = os.getenv("STUB_BASE_HOST", os.getenv("MCP_BASE_HOST", "127.0.0.1"))
    return os.getenv(f"STUB_{system.upper()}_URL", f"http://{host}:{STUB_PORTS[system]}")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    tracing.setup("wpo-agents")
    yield
    tracing.shutdown()


app = FastAPI(title="WPO console", lifespan=lifespan)


@app.get("/")
async def index():
    return FileResponse(STATIC / "index.html")


# ── nightly roster journey ────────────────────────────────────────────────

class NightlyRequest(BaseModel):
    plan_date: str | None = None


class _QueueLogHandler(logging.Handler):
    def __init__(self, q: asyncio.Queue):
        super().__init__(logging.INFO)
        self.q = q

    def emit(self, record: logging.LogRecord) -> None:
        self.q.put_nowait({"type": "log", "level": record.levelname, "logger": record.name,
                           "message": record.getMessage(), "t": time.strftime("%H:%M:%S")})


def _node_detail(node: str, upd: dict) -> dict:
    """The few fields worth showing per node, so the UI need not know the full state."""
    d: dict = {}
    if node == "forecast_demand":
        d = {"slots": sum(s.get("headcount", 0) for s in upd.get("demand", [])), "retries": upd.get("forecast_retries", 0),
             "sites": len({s["site_id"] for s in upd.get("demand", []) if "site_id" in s})}
    elif node == "optimize_roster":
        roster = upd.get("candidate_roster", {})
        d = {"iteration": upd.get("optimizer_iterations"), "assignments": sum(len(v) for v in roster.values()),
             "unfilled": len(upd.get("unfilled", [])), "excluded": upd.get("excluded_workers", [])}
    elif node == "compliance":
        c = upd.get("compliance", {})
        d = {"result": c.get("result"), "violations": c.get("violations", [])}
    elif node == "writeback":
        d = {"published_sites": upd.get("published_sites", [])}
    elif node in ("supervisor", "give_up"):
        d = {k: upd.get(k) for k in ("run_id", "plan_date", "status") if upd.get(k)}
    return d


@app.post("/api/nightly")
async def nightly(req: NightlyRequest):
    if _run_lock.locked():
        raise HTTPException(409, "A nightly run is already in progress.")
    from wpo_agents.supervisor import graph

    async def stream():
        async with _run_lock:
            q: asyncio.Queue = asyncio.Queue()
            handler = _QueueLogHandler(q)
            wpo_log = logging.getLogger("wpo")
            wpo_log.addHandler(handler)
            t0 = time.perf_counter()

            async def runner():
                final: dict = {}
                try:
                    init = {"plan_date": req.plan_date} if req.plan_date else {}
                    with tracing.orchestrator_span():
                        async for mode, chunk in graph.astream(init, {"recursion_limit": 50},
                                                               stream_mode=["updates", "values"]):
                            if mode == "values":
                                final = chunk
                                continue
                            for node, upd in chunk.items():
                                upd = upd or {}
                                q.put_nowait({"type": "node", "node": node, "events": upd.get("events", []),
                                              "detail": _node_detail(node, upd), "t": time.strftime("%H:%M:%S")})
                    q.put_nowait({"type": "done", "summary": {
                        "run_id": final.get("run_id"), "plan_date": final.get("plan_date"),
                        "status": final.get("status"), "sites_published": len(final.get("published_sites", [])),
                        "forecast_retries": final.get("forecast_retries", 0),
                        "optimizer_iterations": final.get("optimizer_iterations"),
                        "elapsed_s": round(time.perf_counter() - t0, 1)}})
                except Exception as exc:  # surface agent failures to the UI rather than dropping the stream
                    log.exception("nightly run failed")
                    q.put_nowait({"type": "error", "message": f"{type(exc).__name__}: {exc}",
                                  "elapsed_s": round(time.perf_counter() - t0, 1)})
                finally:
                    q.put_nowait(None)

            task = asyncio.create_task(runner())
            try:
                while (item := await q.get()) is not None:
                    yield json.dumps(item) + "\n"
            finally:
                wpo_log.removeHandler(handler)
                if not task.done():
                    task.cancel()

    return StreamingResponse(stream(), media_type="application/x-ndjson")


@app.get("/api/nightly/status")
async def nightly_status():
    return {"running": _run_lock.locked()}


# ── Manager Copilot ───────────────────────────────────────────────────────

class AskRequest(BaseModel):
    question: str
    site_id: str | None = None
    ignore_hours: bool = False


@app.post("/api/ask")
async def ask(req: AskRequest):
    from wpo_agents.manager_copilot import graph

    t0 = time.perf_counter()
    try:
        with tracing.agent_span("manager_copilot"):
            final = await graph.ainvoke({"question": req.question, "site_id": req.site_id or None,
                                         "ignore_hours": req.ignore_hours})
    except Exception as exc:
        raise HTTPException(502, f"{type(exc).__name__}: {exc}") from None
    return {"answer": final.get("answer", ""), "open": final.get("open", False),
            "elapsed_s": round(time.perf_counter() - t0, 2)}


# ── roster (read for display) ─────────────────────────────────────────────

@app.get("/api/roster")
async def roster(site_id: str | None = None):
    """Read through the roster MCP server, the same server the agents use. Not an agent edge."""
    try:
        async with Client(config.mcp_url("roster")) as client:
            res = await asyncio.wait_for(client.call_tool("store", {"action": "latest", "site_id": site_id}), timeout=config.TOOL_TIMEOUT_S)
    except Exception as exc:
        raise HTTPException(502, f"roster MCP server unavailable: {exc!r}") from None
    text = res.content[0].text if res.content else "{}"
    if res.is_error:
        raise HTTPException(502, text)
    return json.loads(text)


# ── systems and stats ─────────────────────────────────────────────────────

async def _tcp_up(url: str) -> bool:
    u = httpx.URL(url)
    try:
        _r, w = await asyncio.wait_for(asyncio.open_connection(u.host, u.port or 80), timeout=2)
        w.close()
        return True
    except Exception:
        return False


@app.get("/api/systems")
async def systems():
    async with httpx.AsyncClient(timeout=2) as client:
        async def stub(name: str):
            try:
                ok = (await client.get(f"{stub_url(name)}/health")).status_code == 200
            except httpx.HTTPError:
                ok = False
            return {"name": name, "label": STUB_LABELS[name], "url": stub_url(name), "up": ok}

        stubs = await asyncio.gather(*(stub(n) for n in STUB_PORTS))
    mcp_names = list(config.MCP_DEFAULT_PORTS)
    ups = await asyncio.gather(*(_tcp_up(config.mcp_url(n)) for n in mcp_names))
    mcps = [{"name": n, "url": config.mcp_url(n), "up": up} for n, up in zip(mcp_names, ups)]
    llm = "azure-openai" if config.AZURE_OPENAI_ENDPOINT and config.AZURE_OPENAI_API_KEY else "offline responder"
    return {"stubs": stubs, "mcp": mcps, "llm": llm, "otel": bool(os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"))}


@app.get("/api/stats")
async def stats():
    async with httpx.AsyncClient(timeout=3) as client:
        async def one(name: str):
            try:
                s = (await client.get(f"{stub_url(name)}/_stats")).json()
                w = (await client.get(f"{stub_url(name)}/_writes")).json()
                return {"name": name, "label": STUB_LABELS[name], "calls": s.get("calls", {}), "writes": w.get("count", 0)}
            except (httpx.HTTPError, ValueError):
                return {"name": name, "label": STUB_LABELS[name], "calls": {}, "writes": 0, "error": "unreachable"}

        return {"stubs": await asyncio.gather(*(one(n) for n in STUB_PORTS))}


@app.post("/api/stats/reset")
async def stats_reset():
    async with httpx.AsyncClient(timeout=3) as client:
        await asyncio.gather(*(client.post(f"{stub_url(n)}/_reset") for n in STUB_PORTS), return_exceptions=True)
    return {"reset": True}


# ── topology ──────────────────────────────────────────────────────────────

@app.get("/api/topology")
async def topology():
    from wpo_agents.manager_copilot import graph as copilot
    from wpo_agents.supervisor import graph as nightly_graph

    edges = sorted(({"edge_id": e, "agent": a, "target": t, "access": acc} for (a, t), (e, acc) in EDGES.items()),
                   key=lambda r: r["edge_id"])
    return {"agents": AGENTS, "edges": edges,
            "mermaid": {"nightly": nightly_graph.get_graph().draw_mermaid(),
                        "copilot": copilot.get_graph().draw_mermaid()}}
