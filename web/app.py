"""
web/app.py - Web Application Entry Point

Launches the FastAPI-based emotion dashboard.
Can be run standalone or imported for deployment.

Usage:
    python -m web.app                  # Run on localhost:8000
    python -m web.app --port 8080      # Custom port
    python -m web.app --host 0.0.0.0   # Bind to all interfaces
"""
from __future__ import annotations

import argparse
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main():
    parser = argparse.ArgumentParser(description="小予情绪智能仪表板")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8000, help="Port (default: 8000)")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload for development")
    args = parser.parse_args()

    try:
        import uvicorn
    except ImportError:
        print("❌ uvicorn 未安装。请运行: pip install uvicorn")
        sys.exit(1)

    print(f"🌐 启动小予情绪智能仪表板: http://{args.host}:{args.port}")
    print(f"📖 API文档: http://{args.host}:{args.port}/docs")
    print(f"📊 仪表板: http://{args.host}:{args.port}/")

    uvicorn.run(
        "web.api:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )


if __name__ == "__main__":
    main()
