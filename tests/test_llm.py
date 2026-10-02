"""Fake and loopback-only Ollama failure, privacy and deadline tests."""
from __future__ import annotations

import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import requests

from core.llm import DecisionWorker, FALLBACK_REPLY, OllamaClient


def response(status=200, payload=None):
    return SimpleNamespace(status_code=status, json=Mock(return_value={"response": "hello"} if payload is None else payload), close=Mock())


def client_with(session):
    return OllamaClient("http://127.0.0.1:11434/api/generate", "fixture", timeout=1.5, session=session)


def test_success_uses_local_transport_without_proxy_or_redirect():
    reply = response()
    session = SimpleNamespace(post=Mock(return_value=reply), close=Mock(), trust_env=True)
    client = client_with(session)
    assert client.generate("private child input") == "hello"
    assert session.trust_env is False
    kwargs = session.post.call_args.kwargs
    assert kwargs["allow_redirects"] is False
    assert kwargs["timeout"] == (1.5, 1.5)
    assert client.get_status()["status"] == "healthy"
    reply.close.assert_called_once()


@pytest.mark.parametrize("status", [301, 401, 500])
def test_http_errors_have_deterministic_fallback_without_retry(status, caplog):
    session = SimpleNamespace(post=Mock(return_value=response(status=status)), close=Mock())
    client = client_with(session)
    assert client.generate("SENSITIVE_INPUT") == FALLBACK_REPLY
    assert session.post.call_count == 1
    assert client.last_error == f"http_{status}"
    assert "SENSITIVE_INPUT" not in caplog.text


@pytest.mark.parametrize("payload", [{"response": ""}, {"response": 1}, {}, ["bad schema"]])
def test_empty_or_malformed_response_is_visible(payload):
    session = SimpleNamespace(post=Mock(return_value=response(payload=payload)), close=Mock())
    client = client_with(session)
    assert client.generate("fixture") == FALLBACK_REPLY
    assert client.get_status()["status"] == "degraded"


def test_bad_json_closes_response_and_falls_back():
    reply = response()
    reply.json.side_effect = ValueError("malformed response SENSITIVE_TEXT")
    client = client_with(SimpleNamespace(post=Mock(return_value=reply), close=Mock()))
    assert client.generate("fixture") == FALLBACK_REPLY
    assert client.last_error == "ValueError"
    reply.close.assert_called_once()


@pytest.mark.parametrize("error", [requests.Timeout, requests.ConnectionError])
def test_network_failure_retries_only_once(error):
    session = SimpleNamespace(post=Mock(side_effect=error("fixture")), close=Mock())
    client = client_with(session)
    assert client.generate("fixture") == FALLBACK_REPLY
    assert session.post.call_count == 2


def test_retry_can_recover_and_stop_prevents_new_requests():
    session = SimpleNamespace(post=Mock(side_effect=[requests.Timeout(), response()]), close=Mock())
    client = client_with(session)
    assert client.generate("fixture") == "hello"
    stopped = threading.Event()
    stopped.set()
    assert client.generate("fixture", stopped) == FALLBACK_REPLY
    assert session.post.call_count == 2


@pytest.mark.parametrize("url", ["https://example.com/api/generate", "http://user:secret@localhost/api/generate", "file:///private"])
def test_remote_or_credentialed_ollama_endpoint_is_rejected(url):
    with pytest.raises(ValueError):
        OllamaClient(url, "fixture")


def test_worker_submission_is_nonblocking_bounded_and_cancellable():
    entered = threading.Event()
    release = threading.Event()
    callback = Mock()

    def generate(prompt, stop_event):
        entered.set()
        release.wait(timeout=3)
        return "fixture reply"

    client = SimpleNamespace(generate=generate, close=Mock())
    worker = DecisionWorker(client)
    try:
        assert worker.submit("fixture", callback) is True
        assert entered.wait(timeout=1)
        assert worker.submit("another fixture", callback) is False
        worker._stop_event.set()
        release.set()
        worker.stop()
        assert not worker.thread.is_alive()
        assert worker.submit("after shutdown", callback) is False
        callback.assert_not_called()
        client.close.assert_called_once()
    finally:
        release.set()
        worker.stop()


@pytest.fixture
def local_endpoint():
    servers = []

    def start(*, trickle=False, large=False, slow_headers=False, header_delay=0.0):
        started = threading.Event()
        finished = threading.Event()

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                started.set()
                self.rfile.read(int(self.headers.get("Content-Length", "0")))
                payload = b'{"response":"' + (b"x" * 1024 if large else b"fixture") + b'"}'
                try:
                    if header_delay:
                        time.sleep(header_delay)
                    if slow_headers:
                        for byte in b"HTTP/1.1 200 OK\r\nContent-Length: 1000\r\n\r\n":
                            self.wfile.write(bytes([byte]))
                            self.wfile.flush()
                            time.sleep(0.03)
                        return
                    self.send_response(200)
                    self.send_header("Content-Length", str(1000 if trickle else len(payload)))
                    self.end_headers()
                    if trickle:
                        for _ in range(100):
                            self.wfile.write(b"x")
                            self.wfile.flush()
                            time.sleep(0.03)
                    else:
                        self.wfile.write(payload)
                except (BrokenPipeError, ConnectionResetError, OSError):
                    finished.set()

            def log_message(self, format, *args):
                return

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        server.daemon_threads = True
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        servers.append((server, thread))
        return f"http://127.0.0.1:{server.server_port}/api/generate", started, finished

    yield start
    for server, thread in servers:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)


@pytest.mark.parametrize("slow_headers", [False, True])
def test_total_deadline_interrupts_trickling_body_and_headers(local_endpoint, slow_headers):
    url, _, _ = local_endpoint(trickle=True, slow_headers=slow_headers)
    client = OllamaClient(url, "fixture", timeout=0.2)
    started_at = time.monotonic()
    try:
        assert client.generate("fixture") == FALLBACK_REPLY
        assert time.monotonic() - started_at < 1.0
        assert client.last_error == "Timeout"
    finally:
        client.close()


def test_streamed_response_has_byte_limit(local_endpoint):
    url, _, _ = local_endpoint(large=True)
    client = OllamaClient(url, "fixture", timeout=1.0, max_response_bytes=64)
    try:
        assert client.generate("fixture") == FALLBACK_REPLY
        assert client.last_error == "ResponseTooLarge"
    finally:
        client.close()


def test_response_wait_can_exceed_connect_timeout_within_total_deadline(local_endpoint):
    url, _, _ = local_endpoint(header_delay=2.2)
    client = OllamaClient(url, "fixture", timeout=4.0)
    try:
        assert client.generate("fixture") == "fixture"
        assert client.last_error == ""
    finally:
        client.close()


def test_shutdown_cancels_live_trickling_socket(local_endpoint):
    url, started, _ = local_endpoint(trickle=True)
    client = OllamaClient(url, "fixture", timeout=5.0)
    worker = DecisionWorker(client)
    callback = Mock()
    try:
        assert worker.submit("fixture", callback)
        assert started.wait(timeout=1)
        stopped_at = time.monotonic()
        worker.stop()
        assert time.monotonic() - stopped_at < 1.0
        assert not worker.thread.is_alive()
        callback.assert_not_called()
    finally:
        worker.stop()
