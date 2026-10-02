"""Bounded local Ollama requests and a single nonblocking decision worker."""
from __future__ import annotations

import logging
import http.client
import json as json_codec
import queue
import socket
import ssl
import threading
import time
from datetime import datetime
from urllib.parse import urlsplit

import requests

from config import validate_bind_host

logger = logging.getLogger("Ollama")
FALLBACK_REPLY = "小予在这里，我们慢慢来。"


class ResponseTooLarge(ValueError):
    """The local generation response exceeded the configured byte limit."""


class _RequestGuard:
    """Interrupt blocking socket operations at an absolute deadline or stop."""

    def __init__(self, connection, deadline, stop_event):
        self.connection = connection
        self.deadline = deadline
        self.stop_event = stop_event
        self.socket = None
        self.expired = False
        self.done = threading.Event()
        self.thread = threading.Thread(target=self._watch, daemon=True, name="OllamaDeadline")
        self.thread.start()

    def _watch(self):
        while not self.done.wait(timeout=min(0.05, max(0.001, self.deadline - time.monotonic()))):
            if time.monotonic() >= self.deadline or (self.stop_event is not None and self.stop_event.is_set()):
                self.expired = True
                # Keep the connected socket even when HTTPConnection detaches it
                # for a server's Connection: close response.
                active = self.socket or self.connection.sock
                if active is not None:
                    try:
                        active.shutdown(socket.SHUT_RDWR)
                    except OSError:
                        logger.debug("ollama_socket_already_closed")
                return

    def check(self):
        if self.expired or time.monotonic() >= self.deadline or (self.stop_event is not None and self.stop_event.is_set()):
            raise requests.Timeout("Local generation deadline or cancellation reached")

    def finish(self):
        self.done.set()
        if self.thread is not threading.current_thread():
            self.thread.join(timeout=0.2)


class _LocalResponse:
    def __init__(self, response, connection, guard, max_bytes, on_close):
        self.response = response
        self.connection = connection
        self.guard = guard
        self.max_bytes = max_bytes
        self.on_close = on_close
        self.status_code = response.status

    def json(self):
        body = bytearray()
        while True:
            self.guard.check()
            try:
                chunk = self.response.read1(min(4096, self.max_bytes - len(body) + 1))
            except (OSError, http.client.HTTPException) as exc:
                self.guard.check()
                raise requests.ConnectionError("Local generation body read failed") from exc
            self.guard.check()
            if not chunk:
                break
            body.extend(chunk)
            if len(body) > self.max_bytes:
                raise ResponseTooLarge("Local generation response too large")
        return json_codec.loads(body)

    def close(self):
        self.guard.finish()
        try:
            self.response.close()
        finally:
            self.connection.close()
            self.on_close(self.connection)


class _LocalTransport:
    """Direct local HTTP with no environment proxy or redirect handling."""

    trust_env = False

    def __init__(self, max_bytes):
        self.max_bytes = max_bytes
        self._connections = set()
        self._lock = threading.Lock()

    def _forget(self, connection):
        with self._lock:
            self._connections.discard(connection)

    def post(self, url, *, json, timeout, allow_redirects, stream, stop_event=None):
        parsed = urlsplit(url)
        connection_type = http.client.HTTPSConnection if parsed.scheme == "https" else http.client.HTTPConnection
        options = {"timeout": min(timeout)}
        if parsed.scheme == "https":
            options["context"] = ssl.create_default_context()
        connection = connection_type(parsed.hostname, parsed.port, **options)
        guard = _RequestGuard(connection, time.monotonic() + timeout[1], stop_event)
        with self._lock:
            self._connections.add(connection)
        try:
            connection.connect()
            guard.socket = connection.sock
            guard.check()
            connection.sock.settimeout(max(0.001, guard.deadline - time.monotonic()))
            path = parsed.path or "/"
            if parsed.query:
                path += "?" + parsed.query
            body = json_codec.dumps(json).encode("utf-8")
            connection.request("POST", path, body=body, headers={"Content-Type": "application/json"})
            response = connection.getresponse()
            guard.check()
            return _LocalResponse(response, connection, guard, self.max_bytes, self._forget)
        except (OSError, http.client.HTTPException, requests.Timeout) as exc:
            guard.finish()
            connection.close()
            self._forget(connection)
            if guard.expired or time.monotonic() >= guard.deadline:
                raise requests.Timeout("Local generation deadline reached") from exc
            raise requests.ConnectionError("Local generation connection failed") from exc

    def close(self):
        with self._lock:
            connections = list(self._connections)
        for connection in connections:
            connection.close()


class OllamaClient:
    def __init__(self, url, model, timeout=10.0, *, session=None, max_response_bytes=65536):
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("Ollama must use a local HTTP(S) endpoint")
        validate_bind_host(parsed.hostname)
        if not 0 < timeout <= 120:
            raise ValueError("Ollama timeout must be between 0 and 120 seconds")
        if not isinstance(max_response_bytes, int) or not 1 <= max_response_bytes <= 1024 * 1024:
            raise ValueError("Ollama response limit must be between 1 byte and 1 MiB")
        self.url, self.model, self.timeout = url, model, timeout
        self.session = session or _LocalTransport(max_response_bytes)
        self.session.trust_env = False
        self.last_error = ""
        self.checked_at = ""

    def generate(self, prompt, stop_event=None):
        for attempt in range(2):
            if stop_event is not None and stop_event.is_set():
                return FALLBACK_REPLY
            response = None
            try:
                response = self.session.post(
                    self.url, json={"model": self.model, "prompt": prompt, "stream": False},
                    timeout=(min(2.0, self.timeout), self.timeout), allow_redirects=False,
                    stream=True, **({"stop_event": stop_event} if isinstance(self.session, _LocalTransport) else {}),
                )
                if response.status_code != 200:
                    self.last_error = "http_" + str(response.status_code)
                    break
                payload = response.json()
                reply = payload.get("response") if isinstance(payload, dict) else None
                if not isinstance(reply, str) or not reply.strip():
                    self.last_error = "empty_or_invalid_response"
                    break
                self.last_error = ""
                return reply.strip()[:200]
            except (requests.Timeout, requests.ConnectionError) as exc:
                self.last_error = type(exc).__name__
                if attempt == 0 and not (stop_event is not None and stop_event.is_set()):
                    continue
            except (requests.RequestException, ValueError, TypeError, OSError, http.client.HTTPException) as exc:
                self.last_error = type(exc).__name__
            finally:
                self.checked_at = datetime.now().isoformat()
                if response is not None:
                    response.close()
            break
        logger.warning("ollama_fallback code=%s", self.last_error)
        return FALLBACK_REPLY

    def close(self):
        self.session.close()

    def get_status(self):
        status = "degraded" if self.last_error else ("healthy" if self.checked_at else "unknown")
        reason = self.last_error or ("Local generation succeeded" if self.checked_at else "No request completed")
        return {"status": status, "reason": reason, "checked_at": self.checked_at}


class DecisionWorker:
    def __init__(self, client):
        self.client = client
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._busy = False
        self._queue = queue.Queue(maxsize=1)
        self.thread = threading.Thread(target=self._run, daemon=True, name="OllamaDecision")
        self.thread.start()

    def submit(self, prompt, callback):
        with self._lock:
            if self._stop_event.is_set() or self._busy or not self.thread.is_alive():
                return False
            self._busy = True
            self._queue.put_nowait((prompt, callback))
            return True

    def _run(self):
        try:
            while not self._stop_event.is_set():
                try:
                    prompt, callback = self._queue.get(timeout=0.1)
                except queue.Empty:
                    continue
                try:
                    reply = self.client.generate(prompt, self._stop_event)
                    if not self._stop_event.is_set():
                        callback(reply)
                except Exception as exc:
                    logger.warning("decision_worker_failed type=%s", type(exc).__name__)
                finally:
                    with self._lock:
                        self._busy = False
                    self._queue.task_done()
        finally:
            self.client.close()

    def stop(self):
        self._stop_event.set()
        if self.thread is not threading.current_thread():
            self.thread.join(timeout=2.0)
        if self.thread.is_alive():
            logger.warning("decision_shutdown_waiting_for_bounded_request")
