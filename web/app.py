"""
web/app.py - Web Application Entry Point

Launches the FastAPI-based emotion dashboard.
Can be run standalone or imported for deployment.

Usage:
    python -m web.app                  # Run on localhost:8000
    python -m web.app --port 8080      # Custom port
    This single-operator release only supports loopback interfaces.
"""
from __future__ import annotations

import argparse
import sys
import os
import logging

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def build_parser():
    from config import DASHBOARD_HOST, DASHBOARD_PORT

    parser = argparse.ArgumentParser(description="小予情绪智能仪表板")
    parser.add_argument("--host", default=DASHBOARD_HOST, help="Bind host (default: configured host)")
    parser.add_argument("--port", type=int, default=DASHBOARD_PORT, help="Port (default: configured port)")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload for development")
    return parser


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    try:
        parser = build_parser()
    except ValueError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    args = parser.parse_args()
    from config import LOG_LEVEL, validate_bind_host
    logging.basicConfig(level=LOG_LEVEL, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
    try:
        validate_bind_host(args.host)
    except ValueError as exc:
        parser.error(str(exc))
    if not 1 <= args.port <= 65535:
        parser.error("port must be between 1 and 65535")

    try:
        import uvicorn
    except ImportError:
        print("uvicorn is missing. Run: python -m pip install -r requirements-web.txt")
        sys.exit(1)

    print(f"Dashboard: http://{args.host}:{args.port}/")
    print(f"API documentation: http://{args.host}:{args.port}/docs")

    uvicorn.run(
        "web.api:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level=LOG_LEVEL.lower(),
        proxy_headers=False,
    )


if __name__ == "__main__":
    main()
