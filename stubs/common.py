"""Shared FastAPI factory for the stubs.

Every stub gets:
  GET  /health        liveness
  GET  /_stats        call counts per endpoint (shows retry amplification)
  GET  /_writes       payloads received on write endpoints
  POST /_fault        local fault hook (demo aid only, see below)
  DELETE /_fault      clear it
  POST /_reset        clear stats, writes and fault

The /_fault hook lets you rehearse the demo without NaviStorm attached. In the
real demo NaviStorm injects faults at its MCP proxy, egress proxy or model
gateway; the stubs stay untouched.
"""

from __future__ import annotations

import asyncio
import random
import time
from collections import Counter
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field


class FaultSpec(BaseModel):
    status: int | None = Field(429, description="HTTP status to return, or null for latency-only")
    rate: float = Field(0.3, ge=0.0, le=1.0, description="Share of matching calls faulted")
    duration_s: float = Field(240, gt=0, description="How long the fault stays armed")
    retry_after: int | None = Field(5, description="Retry-After header value in seconds, or null to omit")
    latency_ms: int = Field(0, ge=0, description="Added latency before responding")
    paths: list[str] = Field(default_factory=list, description="Paths to target; empty = all")


def make_app(name: str, stands_for: str) -> FastAPI:
    app = FastAPI(title=f"stub-{name}", description=f"Canned stand-in for {stands_for}. Not a real system.")
    state: dict[str, Any] = {"fault": None, "armed_until": 0.0, "calls": Counter(), "writes": []}
    app.state.stub = state

    @app.middleware("http")
    async def _fault_and_count(request: Request, call_next):
        path = request.url.path
        if path.startswith("/_") or path in ("/health", "/docs", "/openapi.json"):
            return await call_next(request)

        state["calls"][f"{request.method} {path}"] += 1
        fault: FaultSpec | None = state["fault"]
        if fault and time.time() < state["armed_until"]:
            if (not fault.paths or path in fault.paths) and random.random() < fault.rate:
                state["calls"][f"FAULTED {request.method} {path}"] += 1
                if fault.latency_ms:
                    await asyncio.sleep(fault.latency_ms / 1000)
                if fault.status:
                    headers = {"Retry-After": str(fault.retry_after)} if fault.retry_after is not None else {}
                    return JSONResponse(
                        {"error": "injected", "status": fault.status, "system": name},
                        status_code=fault.status,
                        headers=headers,
                    )
        return await call_next(request)

    @app.get("/health")
    async def health():
        return {"status": "ok", "stub": name}

    @app.get("/_stats")
    async def stats():
        return {"stub": name, "calls": dict(state["calls"])}

    @app.get("/_writes")
    async def writes():
        return {"stub": name, "count": len(state["writes"]), "writes": state["writes"][-50:]}

    @app.post("/_fault")
    async def arm_fault(spec: FaultSpec):
        state["fault"] = spec
        state["armed_until"] = time.time() + spec.duration_s
        return {"armed": True, "stub": name, "fault": spec.model_dump(), "expires_in_s": spec.duration_s}

    @app.delete("/_fault")
    async def clear_fault():
        state["fault"] = None
        state["armed_until"] = 0.0
        return {"armed": False, "stub": name}

    @app.post("/_reset")
    async def reset():
        state["fault"] = None
        state["armed_until"] = 0.0
        state["calls"].clear()
        state["writes"].clear()
        return {"reset": True, "stub": name}

    return app


def record_write(app: FastAPI, endpoint: str, body: Any) -> None:
    app.state.stub["writes"].append({"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "endpoint": endpoint, "body": body})
