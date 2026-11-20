"""python -m wpo_ui [--host 127.0.0.1] [--port 8000]"""

from __future__ import annotations

import argparse
import logging
import os

import uvicorn


def main() -> None:
    p = argparse.ArgumentParser(prog="wpo_ui")
    p.add_argument("--host", default=os.getenv("WPO_UI_HOST", "127.0.0.1"))
    p.add_argument("--port", type=int, default=int(os.getenv("WPO_UI_PORT", "8000")))
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s  %(message)s", datefmt="%H:%M:%S")
    for noisy in ("httpx", "httpx2", "mcp", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    uvicorn.run("wpo_ui.server:app", host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
