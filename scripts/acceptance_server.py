"""Software acceptance fixture: real API/storage, explicitly seeded test history, no devices."""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def run_until_stopped(run, shutdown, stop_file):
    finished = threading.Event()

    def watch_stop():
        while not finished.wait(0.05):
            if Path(stop_file).is_file():
                shutdown()
                return

    watcher = threading.Thread(target=watch_stop, daemon=True, name="AcceptanceStop") if stop_file else None
    if watcher:
        watcher.start()
    try:
        run()
    finally:
        finished.set()
        if watcher:
            watcher.join(timeout=1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, required=True)
    sources = parser.add_mutually_exclusive_group(required=True)
    sources.add_argument("--db")
    sources.add_argument("--static-dir", help="Serve only the generated synthetic static site")
    parser.add_argument("--seed", action="store_true")
    parser.add_argument("--stop-file", help="Private fixture control file for cross-platform graceful shutdown")
    args = parser.parse_args()
    if args.static_dir:
        from functools import partial
        from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
        directory = Path(args.static_dir).resolve()
        if not directory.is_dir():
            parser.error("Static acceptance directory must already exist")
        with ThreadingHTTPServer(("127.0.0.1", args.port), partial(SimpleHTTPRequestHandler, directory=str(directory))) as server:
            run_until_stopped(server.serve_forever, server.shutdown, args.stop_file)
        return
    os.environ["SOULCOMPANION_DB"] = str(Path(args.db).resolve())
    os.environ["SOULCOMPANION_DEMO_MODE"] = "false"
    os.environ["SOULCOMPANION_DASHBOARD_HOST"] = "127.0.0.1"
    os.environ["SOULCOMPANION_RATE_LIMIT"] = "10000"
    if args.seed:
        from datetime import datetime, timedelta
        from emotion.memory_axis import MemoryAxis
        from emotion.models import EmotionCategory, EmotionState
        memory = MemoryAxis(args.db)
        if not memory.get_records(limit=1):
            for index in range(65):
                memory.record(EmotionState(
                    timestamp=(datetime.now() - timedelta(minutes=index * 5)).isoformat(),
                    category=EmotionCategory.HAPPY if index % 3 else EmotionCategory.CALM,
                    valence=0.7 if index % 3 else 0.2,
                    emotional_cause="SOFTWARE ACCEPTANCE FIXTURE — synthetic history",
                ))
    import uvicorn
    from web.api import app
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=args.port,
                                         proxy_headers=False, log_level="warning"))

    def run_server():
        if sys.platform == "win32":
            # Avoid Proactor socket-reset cleanup leaving the fixture's server
            # transport attached forever during its graceful shutdown.
            with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
                runner.run(server.serve())
        else:
            server.run()

    run_until_stopped(run_server, lambda: setattr(server, "should_exit", True), args.stop_file)


if __name__ == "__main__":
    main()
