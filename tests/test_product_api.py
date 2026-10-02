"""Product API integration with real SQLite and injected device/runtime boundaries."""
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from core.memory import database_connection
from emotion.memory_axis import MemoryAxis
from emotion.models import BehaviorCommand, EmotionCategory, EmotionState
from web.contracts import ComponentStatus, DashboardSnapshot, SystemComponents, SystemStatus
from web.product import install_product_api
from web.security import install_security
from web.service import ProductService


def test_ollama_readiness_rejects_redirect_without_contacting_target(monkeypatch):
    visited = []

    class RedirectingServer(BaseHTTPRequestHandler):
        def do_GET(self):
            visited.append(self.path)
            self.send_response(302)
            self.send_header("Location", "/redirect-target")
            self.end_headers()

        def log_message(self, *args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), RedirectingServer)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    monkeypatch.setattr("web.service.config.Config", lambda: SimpleNamespace(
        OLLAMA_URL=f"http://127.0.0.1:{server.server_port}/api/generate", OLLAMA_MODEL="test",
    ))
    try:
        service = ProductService(lambda: None, lambda: None, Mock(), demo_mode=False)
        status = service._probe_ollama(datetime.now().isoformat())
        assert status.status == "unavailable"
        assert visited == ["/api/tags"]
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)


def make_app(service):
    app = FastAPI()
    install_security(app)
    install_product_api(app, service)
    return app


def live_snapshot(**changes):
    now = datetime.now().isoformat()
    fields = dict(
        emotion=EmotionState(category=EmotionCategory.HAPPY, valence=0.7),
        behavior=BehaviorCommand(), intervention_type="none", guidance_text="",
        guidance_style="gentle", parent_alert=False, risk_triggers=[], has_risk=False,
        is_running=True, cycle_count=11, last_update=now, data_available=True,
        risk_checked_at=now,
    )
    fields.update(changes)
    return SimpleNamespace(**fields)


@pytest.fixture
def storage(tmp_path):
    memory = MemoryAxis(str(tmp_path / "api.sqlite"))
    memory.record(EmotionState(category=EmotionCategory.HAPPY, valence=0.7),
                  context="private raw transcript", source_text="private raw transcript")
    memory.record(EmotionState(category=EmotionCategory.SAD, valence=-0.5,
                              timestamp=(datetime.now() - timedelta(days=20)).isoformat()))
    return memory


def test_snapshot_reads_one_snapshot_without_storage_models_or_network():
    bridge = SimpleNamespace(get_snapshot=Mock(return_value=live_snapshot()))
    memory = Mock(side_effect=AssertionError("snapshot must not touch storage"))
    runtime = Mock(side_effect=AssertionError("snapshot must not probe runtime"))
    service = ProductService(lambda: bridge, runtime, memory, demo_mode=False)
    service._probe_ollama = Mock(side_effect=AssertionError("snapshot must not contact Ollama"))
    with TestClient(make_app(service)) as client:
        response = client.get("/api/v1/dashboard/snapshot")
    assert response.status_code == 200
    payload = DashboardSnapshot.model_validate(response.json())
    assert payload.emotion.category == "happy"
    assert payload.risk.status == "known"
    assert payload.system.status == "unknown"
    bridge.get_snapshot.assert_called_once()
    memory.assert_not_called()
    runtime.assert_not_called()
    service._probe_ollama.assert_not_called()


@pytest.mark.parametrize("bridge", [None, SimpleNamespace(get_snapshot=Mock(return_value=live_snapshot(data_available=False)))])
def test_unavailable_sensor_does_not_create_a_neutral_real_emotion(bridge):
    service = ProductService(lambda: bridge, lambda: None, Mock(), demo_mode=False)
    payload = service.snapshot()
    assert payload.emotion is None
    assert payload.behavior is None
    assert payload.data_available is False


def test_unchecked_or_stale_risk_is_unknown():
    bridge = SimpleNamespace(get_snapshot=Mock(return_value=live_snapshot(risk_checked_at=None)))
    service = ProductService(lambda: bridge, lambda: None, Mock(), demo_mode=False)
    assert service.snapshot().risk.has_risk is None
    bridge.get_snapshot.return_value = live_snapshot(
        risk_checked_at=(datetime.now() - timedelta(seconds=30)).isoformat(), has_risk=True,
    )
    assert service.snapshot().risk.status == "unknown"
    bridge.get_snapshot.return_value = live_snapshot(
        last_update=(datetime.now() - timedelta(seconds=30)).isoformat(),
    )
    assert service.snapshot().data_available is False


def test_history_filters_window_pages_stably_and_excludes_raw_text(storage):
    storage.record(EmotionState(category=EmotionCategory.CALM, valence=0.2))
    service = ProductService(lambda: None, lambda: None, lambda: storage, demo_mode=False)
    with TestClient(make_app(service)) as client:
        first = client.get("/api/v1/emotions/history?days=1&limit=1").json()
        second = client.get("/api/v1/emotions/history?days=1&limit=1&offset=1").json()
        monthly = client.get("/api/v1/emotions/history?days=30").json()
    assert first["total"] == 2
    assert first["has_more"] is True
    assert second["has_more"] is False
    assert first["records"][0] != second["records"][0]
    assert monthly["total"] == 3
    assert "source_text" not in str(monthly)
    assert "context" not in str(monthly)
    assert "private raw transcript" not in str(monthly)


def test_history_same_timestamp_uses_insertion_id_for_stable_pages(storage):
    timestamp = datetime.now().isoformat()
    storage.record(EmotionState(timestamp=timestamp, category=EmotionCategory.ANGRY))
    storage.record(EmotionState(timestamp=timestamp, category=EmotionCategory.CALM))
    records, total = storage.get_history_page(days=1, limit=1)
    next_records, _ = storage.get_history_page(days=1, limit=1, offset=1)
    assert total == 3
    assert records[0].category == "calm"
    assert next_records[0].category == "angry"


@pytest.mark.parametrize("path", [
    "/emotions/history?days=2", "/emotions/history?limit=0", "/emotions/history?offset=-1",
    "/emotions/analytics?days=365", "/reports/parent?days=0",
])
def test_invalid_v1_queries_return_typed_errors_before_storage(path):
    memory = Mock(side_effect=AssertionError("must validate before accessing storage"))
    service = ProductService(lambda: None, lambda: None, memory, demo_mode=False)
    with TestClient(make_app(service)) as client:
        response = client.get("/api/v1" + path)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_REQUEST"
    assert response.json()["error"]["request_id"] == response.headers["X-Request-ID"]
    memory.assert_not_called()


def test_analytics_bounds_series_and_preserves_whole_period(storage):
    now = datetime.now()
    samples = [((now - timedelta(minutes=index)).isoformat(),) for index in range(1100)]
    with database_connection(storage.db_path) as connection:
        connection.executemany("INSERT INTO emotion_records(timestamp) VALUES (?)", samples)
    service = ProductService(lambda: None, lambda: None, lambda: storage, demo_mode=False)
    with TestClient(make_app(service)) as client:
        response = client.get("/api/v1/emotions/analytics?days=1")
    assert response.status_code == 200
    payload = response.json()
    assert 2 <= len(payload["series"]) <= 500
    assert payload["total_records"] == 1101
    assert payload["trend"]["period"] == "1d"
    assert payload["series"][0]["timestamp"] == min(row[0] for row in samples)
    assert payload["series"][-1]["timestamp"] == max(row[0] for row in samples)


def test_report_uses_real_history_and_empty_score_is_null(storage):
    service = ProductService(lambda: None, lambda: None, lambda: storage, demo_mode=False)
    with TestClient(make_app(service)) as client:
        report = client.get("/api/v1/reports/parent?days=1").json()
        markdown = client.get("/api/v1/reports/parent.md?days=1")
        with database_connection(storage.db_path) as connection:
            connection.execute("DELETE FROM emotion_records")
        empty = client.get("/api/v1/reports/parent?days=1").json()
    assert report["data_available"] is True
    assert report["interaction_count"] == report["emotion_trend"]["total_records"] == 1
    assert empty["data_available"] is False
    assert empty["health_score"] is None
    assert markdown.status_code == 200
    assert markdown.headers["Content-Type"].startswith("text/markdown")
    assert "\n## " in markdown.text


def test_explicit_demo_never_reads_real_storage_or_probes_ollama():
    memory = Mock(side_effect=AssertionError("demo must not read a real database"))
    bridge = Mock(side_effect=AssertionError("demo must not use real bridge"))
    runtime = Mock(side_effect=AssertionError("demo must not probe hardware"))
    service = ProductService(bridge, runtime, memory, demo_mode=True)
    service._probe_ollama = Mock(side_effect=AssertionError("demo must not contact Ollama"))
    with TestClient(make_app(service)) as client:
        assert client.get("/api/v1/dashboard/snapshot").json()["mode"] == "demo"
        assert client.get("/api/v1/system/status").json()["components"]["database"]["status"] == "disabled"
        assert client.get("/api/v1/system/settings").json()["storage"]["status"] == "disabled"
        for path in ("emotions/history", "emotions/analytics", "reports/parent", "reports/parent.md"):
            response = client.get("/api/v1/" + path)
            assert response.status_code == 409
            assert response.json()["error"]["code"] == "DEMO_MODE"
    memory.assert_not_called()
    bridge.assert_not_called()
    runtime.assert_not_called()
    service._probe_ollama.assert_not_called()


def test_system_status_probes_once_and_readiness_explains_missing_runtime(storage):
    service = ProductService(lambda: None, lambda: None, lambda: storage, demo_mode=False)
    service._probe_ollama = Mock(return_value=ComponentStatus(status="unavailable", reason="test: Ollama stopped"))
    with TestClient(make_app(service)) as client:
        first = client.get("/api/v1/system/status")
        second = client.get("/api/v1/system/readiness")
        snap = client.get("/api/v1/dashboard/snapshot").json()
    assert first.status_code == second.status_code == 200
    assert first.json()["status"] == "degraded"
    assert first.json()["components"]["database"]["status"] == "healthy"
    assert first.json()["components"]["camera"]["status"] == "unknown"
    assert any("No edge runtime" in reason for reason in first.json()["reasons"])
    assert snap["system"]["status"] == "degraded"
    service._probe_ollama.assert_called_once()


def test_readiness_and_storage_errors_are_explicit():
    import sqlite3

    memory = Mock(side_effect=sqlite3.OperationalError("sensitive path must not leak"))
    service = ProductService(lambda: None, lambda: None, memory, demo_mode=False)
    service._probe_ollama = Mock(return_value=ComponentStatus(status="disabled", reason="test"))
    with TestClient(make_app(service)) as client:
        readiness = client.get("/api/v1/system/readiness")
        history = client.get("/api/v1/emotions/history")
    assert readiness.status_code == 503
    assert readiness.json()["status"] == "unavailable"
    assert history.status_code == 503
    assert history.json()["error"]["code"] == "STORAGE_UNAVAILABLE"
    assert "sensitive path" not in history.text


def test_every_v1_json_route_has_a_named_openapi_contract(storage):
    service = ProductService(lambda: None, lambda: None, lambda: storage, demo_mode=False)
    schema = make_app(service).openapi()
    for path, operation in schema["paths"].items():
        if not path.endswith(".md"):
            body = operation["get"]["responses"]["200"]["content"]["application/json"]["schema"]
            assert "$ref" in body
        error = operation["get"]["responses"]["422"]["content"]["application/json"]["schema"]
        assert error["$ref"].endswith("/ErrorResponse")


def test_status_invalidation_and_expiration_do_not_trigger_snapshot_probes(storage):
    service = ProductService(lambda: None, lambda: None, lambda: storage, demo_mode=False)
    service._probe_ollama = Mock(return_value=ComponentStatus(status="disabled", reason="test"))
    service.system_status()
    assert service.snapshot().system.status == "degraded"
    service._status_cached_at -= 6
    assert service.snapshot().system.status == "unknown"
    assert service.settings().storage.status == "unknown"
    service._probe_ollama.assert_called_once()
    service.invalidate_status()
    assert service._cached_status is None


def test_real_application_routes_are_wired_without_liveness_or_snapshot_side_effects(monkeypatch):
    from web import api

    memory = Mock(side_effect=AssertionError("liveness and snapshot must not open storage"))
    network = Mock(side_effect=AssertionError("liveness and snapshot must not probe network"))
    monkeypatch.setattr(api.product_service, "_memory_getter", memory)
    monkeypatch.setattr(api.product_service, "_bridge_getter", lambda: None)
    monkeypatch.setattr(api.product_service, "_probe_ollama", network)
    api.product_service.invalidate_status()
    with TestClient(api.app) as client:
        assert client.get("/healthz").json()["status"] == "ok"
        assert client.get("/api/v1/dashboard/snapshot").json()["data_available"] is False
    memory.assert_not_called()
    network.assert_not_called()
    missing = ComponentStatus(status="unavailable", reason="database missing")
    unknown = ComponentStatus(status="unknown", reason="not checked")
    unavailable = SystemStatus(
        status="unavailable", timestamp=datetime.now().isoformat(), mode="real",
        components=SystemComponents(
            backend=ComponentStatus(status="healthy", reason="running"), database=missing,
            bridge=unknown, camera=unknown, microphone=unknown, vision_model=unknown,
            speech_model=unknown, ser_model=unknown, ollama=unknown, hardware=unknown,
        ), reasons=["database missing"],
    )
    monkeypatch.setattr(api.product_service, "system_status", Mock(return_value=unavailable))
    with TestClient(api.app) as client:
        assert client.get("/readyz").status_code == 503
        assert client.get("/api/v1/system/readiness").json()["reasons"] == ["database missing"]
