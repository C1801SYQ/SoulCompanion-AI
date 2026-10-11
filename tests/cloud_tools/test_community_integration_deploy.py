"""PC04 deployment authorization and fixed rollback, strictly local Fake transport."""

from pathlib import Path

import pytest

from scripts import cloud_community_deploy as transport
from scripts import cloud_community_integration_deploy as pc04
from tests.cloud_tools.test_community_deploy import package, setup  # noqa: F401


def test_pc03_pin_is_independent_from_pc02():
    assert pc04.PC03_SHA256 == "835348e8c775cade98a6a263cce8990088c76c37019f61ebab2eecd2574246fe"
    assert pc04.PC03_SHA256 != transport.PC02_SHA256


def test_custom_baseline_checksum_is_required(tmp_path):
    previous = tmp_path / "pc03.zip"
    previous.write_bytes(package(b"pc03"))
    with pytest.raises(transport.AdminError):
        transport.historical_package(previous, baseline_sha256=pc04.PC03_SHA256)
    verified, _ = transport.historical_package(previous, baseline_sha256=transport.digest(previous.read_bytes()))
    assert verified == previous.read_bytes()


def test_pc04_cli_never_constructs_admin_without_dual_gate(monkeypatch, capsys):
    monkeypatch.setattr(transport, "CloudAdmin", lambda: pytest.fail("No cloud calls before PC04 approval"))
    assert pc04.main(["--apply"]) == 1
    assert "PC04_CLOUD_WRITE_AUTHORIZATION_REQUIRED" in capsys.readouterr().out


def test_pc04_offline_plan_and_rollback_keep_all_resources(setup, monkeypatch):  # noqa: F811
    candidate, historical, _, _, _ = setup
    monkeypatch.setattr(pc04, "PC03_SHA256", transport.digest(historical.read_bytes()))
    monkeypatch.setattr(transport, "CloudAdmin", lambda: pytest.fail("Plan must be offline"))
    result = pc04.plan(candidate, historical)
    assert result["real_calls"] is False
    assert result["new_resources"] == result["schema_changes"] == result["gateway_changes"] == []
    assert result["operation"] == "update_pc04_read_compatibility"
    rollback = pc04.plan(Path("missing-candidate"), historical, rollback=True)
    assert rollback["operation"] == "restore_pc03_code"
    assert rollback["zip_sha256"] == transport.digest(historical.read_bytes())


def test_custom_baseline_apply_and_restore_reuse_owned_verified_transport(setup):  # noqa: F811
    candidate, historical, admin, client, _ = setup
    pin = transport.digest(historical.read_bytes())
    result = transport.apply_deployment(admin, client, candidate, historical, cloud_write_authorized=True, baseline_sha256=pin)
    assert result["status"] == "code_verified"
    result = transport.apply_deployment(admin, client, Path("missing-candidate"), historical,
                                        cloud_write_authorized=True, rollback=True, baseline_sha256=pin)
    assert result["status"] == "code_verified"
    assert admin.current == historical.read_bytes()
