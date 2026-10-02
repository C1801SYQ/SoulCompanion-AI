"""Legacy optional entry points cannot become a remote-data shortcut."""
import pytest

from emotion.cloud_sync import CloudSync


def test_remote_relay_configuration_is_rejected(monkeypatch):
    monkeypatch.setattr("emotion.cloud_sync.RELAY_URL", "https://outside.invalid/relay")
    with pytest.raises(ValueError, match="must remain local"):
        CloudSync()


def test_legacy_remote_push_is_disabled_even_if_instance_setting_changes(monkeypatch):
    monkeypatch.setattr("emotion.cloud_sync.RELAY_URL", "")
    sync = CloudSync()
    sync._relay_url = "https://outside.invalid/relay"
    with pytest.raises(RuntimeError, match="disabled"):
        sync._push_http({"text": "synthetic private fixture"})


def test_legacy_file_failures_log_type_without_private_text(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr("emotion.cloud_sync.RELAY_URL", "")
    sync = CloudSync()
    sync._data_file = str(tmp_path / "missing" / "snapshot.json")
    sync._write_file({"text": "synthetic private fixture"})
    assert "legacy_snapshot_write_failed" in caplog.text
    assert "synthetic private fixture" not in caplog.text


def test_legacy_invalid_snapshot_read_is_visible(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr("emotion.cloud_sync.RELAY_URL", "")
    sync = CloudSync()
    path = tmp_path / "broken.json"
    path.write_text("{invalid", encoding="utf-8")
    sync._data_file = str(path)
    assert sync.read_file() == {}
    assert "legacy_snapshot_read_failed" in caplog.text
