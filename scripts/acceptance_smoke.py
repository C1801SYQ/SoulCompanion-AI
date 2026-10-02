"""Run the native deployment and persistence acceptance with an isolated temporary database."""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]


def request_json(base, path, headers=None):
    with build_opener(ProxyHandler({})).open(Request(base + path, headers=headers or {}), timeout=3) as response:
        return json.loads(response.read())


def start_server(port, database, log, seed):
    stop_file = database.parent / ("stop-" + uuid.uuid4().hex + ".signal")
    command = [sys.executable, str(ROOT / "scripts/acceptance_server.py"), "--port", str(port),
               "--db", str(database), "--stop-file", str(stop_file)]
    if seed:
        command.append("--seed")
    process = subprocess.Popen(command, cwd=ROOT, stdout=log, stderr=log,
                               env={**os.environ, "PYTHONUTF8": "1"})
    process.acceptance_stop_file = stop_file
    base = f"http://127.0.0.1:{port}"
    for _ in range(100):
        if process.poll() is not None:
            raise RuntimeError("Acceptance backend stopped before readiness")
        try:
            if request_json(base, "/healthz")["status"] == "ok":
                return process, base
        except (URLError, TimeoutError):
            time.sleep(0.1)
    stop(process)
    raise RuntimeError("Acceptance backend did not become live")


def stop(process):
    if process.poll() is None:
        # Signal the actual server, including the child launched by Windows venv.
        with process.acceptance_stop_file.open("x", encoding="utf-8") as signal:
            signal.write("stop")
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            raise RuntimeError("Acceptance backend did not shut down gracefully")


def wait_stopped(base):
    port = urlsplit(base).port
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            # Windows can take about two seconds to report a refused loopback connection.
            remaining = max(0.001, min(3, deadline - time.monotonic()))
            with socket.create_connection(("127.0.0.1", port), timeout=remaining):
                pass
        except ConnectionRefusedError:
            return
        except TimeoutError:
            # A timeout is inconclusive; only an explicit refusal proves closure.
            pass
        time.sleep(0.1)
    raise RuntimeError("Acceptance backend TCP port closure could not be verified")


def run_checks():
    artifacts = ROOT / ".test-artifacts"
    artifacts.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="native-acceptance-", dir=artifacts) as directory:
        directory = Path(directory)
        database = directory / "acceptance.sqlite"
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        evidence = {}
        with (directory / "backend.log").open("w", encoding="utf-8") as log:
            process, base = start_server(port, database, log, seed=True)
            try:
                evidence["health"] = request_json(base, "/healthz")["status"]
                readiness = request_json(base, "/readyz")
                assert readiness["status"] == "degraded"
                assert readiness["components"]["database"]["status"] == "healthy"
                evidence["readiness"] = readiness["status"]
                snapshot = request_json(base, "/api/v1/dashboard/snapshot")
                assert snapshot["emotion"] is None and snapshot["data_available"] is False
                history = request_json(base, "/api/v1/emotions/history?days=1&limit=20")
                assert history["total"] == 65 and len(history["records"]) == 20 and history["has_more"]
                assert "source_text" not in history["records"][0]
                report = request_json(base, "/api/v1/reports/parent?days=1")
                assert report["interaction_count"] == 65 and report["data_available"]
                evidence["history_records"] = history["total"]
                evidence["report_records"] = report["interaction_count"]
                for headers in ({"Origin": "https://example.com"}, {"Host": "evil.example"}):
                    try:
                        request_json(base, "/api/v1/emotions/history", headers)
                        raise AssertionError("Cross-origin request was accepted")
                    except HTTPError as error:
                        assert error.code == 403
                evidence["local_boundary"] = "passed"
            finally:
                stop(process)
                wait_stopped(base)
                evidence["shutdown_port_closed"] = "passed"
            process, base = start_server(port, database, log, seed=False)
            try:
                assert request_json(base, "/api/v1/emotions/history?days=1")["total"] == 65
                evidence["restart_persistence"] = "passed"
            finally:
                stop(process)
                wait_stopped(base)
    return evidence


def main():
    artifacts = ROOT / ".test-artifacts"
    artifacts.mkdir(exist_ok=True)
    target = artifacts / "native-acceptance.json"
    evidence = {"status": "running"}
    target.write_text(json.dumps(evidence) + "\n", encoding="utf-8")
    try:
        evidence.update(run_checks())
        evidence["status"] = "passed"
        print(json.dumps(evidence, ensure_ascii=False))
    except Exception as error:
        evidence.update(status="failed", failure=str(error))
        raise
    finally:
        target.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
