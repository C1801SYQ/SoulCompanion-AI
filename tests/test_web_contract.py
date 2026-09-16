from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from web.api import app
from web.app import build_parser


@pytest.mark.parametrize("url", [
    "/api/emotion/history?limit=-1", "/api/emotion/history?limit=501",
    "/api/emotion/history?offset=-1", "/api/emotion/counts?days=0",
    "/api/emotion/valence-series?days=366",
    "/api/emotion/periodicity?lookback_days=-2",
    "/api/parent/report?days=9999", "/api/parent/report.md?days=-1",
])
def test_invalid_queries_rejected_before_accessing_storage(url):
    with patch("web.api._memory") as memory:
        with TestClient(app) as client:
            assert client.get(url).status_code == 422
        memory.assert_not_called()


def test_liveness_has_no_storage_side_effects():
    with patch("web.api._memory") as memory:
        with TestClient(app) as client:
            result = client.get("/healthz")
        assert result.status_code == 200
        assert result.json()["status"] == "ok"
        memory.assert_not_called()


def test_cli_respects_configuration_and_explicit_overrides():
    with patch("config.DASHBOARD_HOST", "127.0.0.2"), patch("config.DASHBOARD_PORT", 8123):
        parser = build_parser()
        assert parser.parse_args([]).port == 8123
        assert parser.parse_args([]).host == "127.0.0.2"
        assert parser.parse_args(["--port", "9000"]).port == 9000
