"""Start every stub and MCP server in one process tree.

This is the entrypoint of the single `wpo-systems` container, and also works
on a laptop without Docker:  python run_systems.py
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time

from mcp_servers.common import MCP_PORTS, STUB_PORTS

HOST = os.getenv("STUB_HOST", "0.0.0.0")


def main() -> None:
    procs: list[tuple[str, subprocess.Popen]] = []
    for name, port in STUB_PORTS.items():
        cmd = [sys.executable, "-m", "uvicorn", f"stubs.{name}:app", "--host", HOST, "--port", str(port), "--log-level", "warning"]
        procs.append((f"stub-{name}:{port}", subprocess.Popen(cmd)))
    time.sleep(1.5)  # let stubs bind before MCP servers start taking calls
    for name, port in MCP_PORTS.items():
        procs.append((f"mcp-{name}:{port}", subprocess.Popen([sys.executable, "-m", f"mcp_servers.{name}"])))

    print("wpo-systems up:", flush=True)
    for label, _ in procs:
        print(f"  {label}", flush=True)

    def stop(*_):
        for _, p in procs:
            p.terminate()
        for _, p in procs:
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()
        sys.exit(0)

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    while True:
        for label, p in procs:
            if p.poll() is not None:
                print(f"{label} exited with {p.returncode}; shutting down", flush=True)
                stop()
        time.sleep(1)


if __name__ == "__main__":
    main()
