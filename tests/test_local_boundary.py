"""Local product boundary must cover legacy APIs, docs and future v1 routes."""
import os
import subprocess
import sys

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from config import ConfigurationError, validate_bind_host
from web.security import install_security


@pytest.mark.parametrize("name,value", [
    ("SOULCOMPANION_CORS_ORIGINS", "http://localhost:abc"),
    ("SOULCOMPANION_CORS_ORIGINS", "http://localhost:0"),
    ("SOULCOMPANION_CORS_ORIGINS", "http://localhost/path"),
    ("SOULCOMPANION_CORS_ORIGINS", "http://[broken"),
    ("OLLAMA_URL", "http://[broken"),
    ("OLLAMA_URL", "http://localhost:0/api/generate"),
])
def test_malformed_local_url_configuration_names_the_variable(name, value):
    result = subprocess.run([sys.executable, "-c", "import config"],
                            env={**os.environ, name: value}, capture_output=True, text=True)
    assert result.returncode != 0
    assert f"ConfigurationError: {name}" in result.stderr


@pytest.fixture
def client():
    app = FastAPI()
    install_security(app)

    @app.get("/api/private")
    def private():
        return {"ok": True}

    @app.get("/api/failure")
    def failure():
        raise RuntimeError("private child text")

    with TestClient(app) as client:
        yield client


@pytest.mark.parametrize("host", ["0.0.0.0", "::", "192.168.1.1", "example.com"])
def test_remote_bind_rejected(host):
    with pytest.raises(ConfigurationError):
        validate_bind_host(host)


@pytest.mark.parametrize("headers", [
    {"host": "evil.example"}, {"origin": "https://evil.example"},
    {"x-forwarded-for": "127.0.0.1"}, {"sec-fetch-site": "cross-site"},
    {"origin": "null"}, {"origin": "http://testserver.evil.example"},
])
def test_cross_origin_and_proxy_requests_rejected(client, headers):
    result = client.get("/api/private", headers=headers)
    assert result.status_code == 403
    assert result.json()["error"]["code"] == "LOCAL_ACCESS_ONLY"


def test_errors_have_request_ids_and_no_private_text(client):
    result = client.get("/api/failure")
    assert result.status_code == 500
    assert result.json()["error"]["request_id"] == result.headers["x-request-id"]
    assert "private child text" not in result.text
    assert client.get("/missing").json()["error"]["code"] == "NOT_FOUND"


def test_non_local_client_is_rejected_even_with_a_local_host():
    app = FastAPI()
    install_security(app)
    with TestClient(app, base_url="http://127.0.0.1", client=("192.0.2.10", 12345)) as remote:
        assert remote.get("/docs").status_code == 403


def test_rate_limit_applies_to_local_api_calls(monkeypatch):
    monkeypatch.setattr("web.security.RATE_LIMIT_PER_MINUTE", 3)
    app = FastAPI()
    install_security(app)

    @app.get("/api/private")
    def private():
        return {"ok": True}

    with TestClient(app) as local:
        for _ in range(3):
            assert local.get("/api/private").status_code == 200
        response = local.get("/api/private")
        assert response.status_code == 429
        assert response.headers["retry-after"] == "60"
        assert response.json()["error"]["code"] == "RATE_LIMITED"


@pytest.mark.parametrize("path", [
    "/api/emotion/current", "/api/emotion/history", "/api/parent/report",
    "/api/parent/report.md", "/api/behavior/command", "/api/risk/triggers",
    "/api/bridge/status",
])
def test_explicit_demo_blocks_legacy_real_data_before_getters(monkeypatch, path):
    from unittest.mock import Mock
    import web.api as api

    monkeypatch.setattr(api, "DEMO_MODE", True)
    memory = Mock(side_effect=AssertionError("real database accessed"))
    bridge = Mock()
    monkeypatch.setattr(api, "_get_memory_axis", memory)
    monkeypatch.setattr(api, "_bridge", bridge)
    with TestClient(api.app) as client:
        result = client.get(path)
    assert result.status_code == 409
    assert result.json()["error"]["code"] == "DEMO_MODE"
    memory.assert_not_called()
    bridge.get_snapshot.assert_not_called()
    bridge.get_memory.assert_not_called()


@pytest.mark.parametrize("name,value", [
    ("SOULCOMPANION_DASHBOARD_PORT", "abc"), ("SOULCOMPANION_DASHBOARD_PORT", "65536"),
    ("OLLAMA_TIMEOUT", "nan"), ("SOULCOMPANION_DEMO_MODE", "maybe"),
    ("SOULCOMPANION_CORS_ORIGINS", "*"),
    ("OLLAMA_URL", "http://example.com/api/generate"),
])
def test_invalid_configuration_names_setting(name, value):
    env = {**os.environ, name: value}
    result = subprocess.run([sys.executable, "-c", "import config"], env=env,
                            capture_output=True, text=True)
    assert result.returncode != 0
    assert name in result.stderr
