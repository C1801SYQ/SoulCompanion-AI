"""Maintenance is exercised only against synthetic databases under pytest's workspace temp."""
import csv
import json
import os
import sqlite3
from datetime import datetime, timedelta

import pytest

import config
from core.data_admin import DataAdmin, DataAdminError
from core.memory import EmotionMemory, SCHEMA_VERSION, SchemaVersionError, database_connection
from emotion.memory_axis import MemoryAxis
from emotion.models import EmotionCategory, EmotionState
from scripts.data_admin import build_parser, main


@pytest.fixture
def database(tmp_path):
    path = tmp_path / "records.sqlite"
    memory = MemoryAxis(str(path))
    memory.record(EmotionState(category=EmotionCategory.HAPPY, valence=0.8),
                  context="private context", source_text="private speech")
    memory.record(EmotionState(category=EmotionCategory.SAD, valence=-0.7,
                              timestamp=(datetime.now() - timedelta(days=40)).isoformat()))
    legacy = EmotionMemory(str(path))
    legacy.save_log("private legacy speech", "happy")
    with database_connection(str(path)) as conn:
        conn.execute("INSERT INTO logs VALUES (?, ?, ?, ?)", (
            (datetime.now() - timedelta(days=40)).strftime("%Y-%m-%d %H:%M:%S"),
            "private old legacy speech", "sad", -1,
        ))
    return path


def test_version_zero_migration_preserves_both_tables_and_custom_indexes(tmp_path):
    path = tmp_path / "old.sqlite"
    with database_connection(str(path)) as conn:
        conn.execute("""CREATE TABLE emotion_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT NOT NULL,
            category TEXT NOT NULL DEFAULT 'neutral', valence REAL DEFAULT 0.0,
            arousal REAL DEFAULT 0.5, cause TEXT DEFAULT '', context TEXT DEFAULT '',
            source_text TEXT DEFAULT '', confidence REAL DEFAULT 0.5)""")
        conn.execute("CREATE TABLE logs (time TEXT, user_input TEXT, emotion TEXT, score INTEGER)")
        conn.execute("CREATE INDEX custom_confidence ON emotion_records(confidence)")
        conn.execute("INSERT INTO emotion_records(timestamp, source_text) VALUES (?, ?)",
                     (datetime.now().isoformat(), "original"))
        conn.execute("INSERT INTO logs VALUES ('old', 'original legacy', 'neutral', 0)")
    MemoryAxis(str(path))
    MemoryAxis(str(path))
    with database_connection(str(path)) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        assert conn.execute("SELECT id, source_text FROM emotion_records").fetchall() == [(1, "original")]
        assert conn.execute("SELECT user_input FROM logs").fetchall() == [("original legacy",)]
        assert conn.execute("SELECT value FROM app_metadata WHERE key='installation_scope'").fetchone() == ("single_child",)
        indexes = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")}
        assert {"custom_confidence", "idx_er_timestamp", "idx_er_category"} <= indexes


def test_future_schema_is_rejected_before_schema_or_journal_mutation(tmp_path):
    path = tmp_path / "future.sqlite"
    with database_connection(str(path)) as conn:
        conn.execute("CREATE TABLE future_table (value TEXT)")
        conn.execute("INSERT INTO future_table VALUES ('keep')")
        conn.execute("PRAGMA user_version=999")
    with pytest.raises(SchemaVersionError, match="upgrade the application"):
        MemoryAxis(str(path))
    with database_connection(str(path)) as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 999
        assert conn.execute("SELECT * FROM future_table").fetchall() == [("keep",)]


def test_failed_migration_rolls_back_schema_version_and_new_objects(tmp_path):
    path = tmp_path / "malformed.sqlite"
    with database_connection(str(path)) as conn:
        conn.execute("CREATE TABLE emotion_records (id INTEGER PRIMARY KEY)")
        conn.execute("INSERT INTO emotion_records VALUES (17)")
    with pytest.raises(sqlite3.OperationalError):
        MemoryAxis(str(path))
    with database_connection(str(path)) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 0
        assert conn.execute("SELECT * FROM emotion_records").fetchall() == [(17,)]
        assert conn.execute("SELECT name FROM sqlite_master WHERE name='app_metadata'").fetchall() == []


def test_legacy_memory_rejects_future_schema_without_creating_logs(tmp_path):
    path = tmp_path / "future-legacy.sqlite"
    with database_connection(str(path)) as conn:
        conn.execute("CREATE TABLE future_only (value TEXT)")
        conn.execute("PRAGMA user_version=999")
    with pytest.raises(SchemaVersionError, match="upgrade the application"):
        EmotionMemory(str(path))
    with database_connection(str(path)) as conn:
        assert conn.execute("SELECT name FROM sqlite_master WHERE name='logs'").fetchall() == []


def test_legacy_memory_rejects_schema_updated_after_initialization(tmp_path):
    path = tmp_path / "upgraded.sqlite"
    memory = EmotionMemory(str(path))
    with database_connection(str(path)) as conn:
        conn.execute("PRAGMA user_version=999")
    with pytest.raises(SchemaVersionError):
        memory.save_log("must not be stored", "happy")
    with pytest.raises(SchemaVersionError):
        memory.get_recent_trend()
    with database_connection(str(path)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM logs").fetchone()[0] == 0


def test_backup_is_a_verified_reopenable_snapshot(database, tmp_path):
    output = tmp_path / "backup.sqlite"
    result = DataAdmin(database).backup(output)
    assert result["verified"] is True
    assert result["includes_raw_text"] is True
    reopened = DataAdmin(output).info()
    assert reopened["emotion_records"] == reopened["legacy_logs"] == 2
    assert reopened["raw_text_present"] is True
    assert MemoryAxis(str(output)).get_records()[0].source_text == "private speech"


@pytest.mark.parametrize("suffix", ["json", "csv"])
@pytest.mark.parametrize("include_raw", [False, True])
def test_exports_are_valid_and_raw_text_requires_explicit_opt_in(database, tmp_path, suffix, include_raw):
    output = tmp_path / f"export.{suffix}"
    result = DataAdmin(database).export(output, include_raw=include_raw)
    assert result["emotion_records"] == result["legacy_logs"] == 2
    text = output.read_text(encoding="utf-8")
    if suffix == "json":
        payload = json.loads(text)
        assert payload["includes_raw_text"] is include_raw
        assert len(payload["emotion_records"]) == len(payload["legacy_logs"]) == 2
    else:
        with output.open(encoding="utf-8", newline="") as stream:
            rows = list(csv.DictReader(stream))
        assert len(rows) == 4
        assert {row["source_table"] for row in rows} == {"emotion_records", "logs"}
    assert ("private speech" in text) is include_raw
    assert ("private legacy speech" in text) is include_raw
    assert ("source_text" in text) is include_raw
    assert ("user_input" in text) is include_raw
    if os.name != "nt":
        assert output.stat().st_mode & 0o777 == 0o600


def test_csv_export_neutralizes_string_formulas_without_changing_numeric_values(database, tmp_path):
    with database_connection(str(database)) as conn:
        conn.execute("UPDATE emotion_records SET cause='=1+1', source_text=' @SUM(A1:A2)'")
    output = tmp_path / "safe.csv"
    DataAdmin(database).export(output, include_raw=True)
    with output.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert rows[0]["cause"] == "'=1+1"
    assert rows[0]["source_text"] == "' @SUM(A1:A2)"
    assert rows[0]["valence"] == "-0.7"


def test_delete_requires_confirmation_and_backup_can_restore_every_record(database, tmp_path):
    admin = DataAdmin(database)
    backup = tmp_path / "before-delete.sqlite"
    with pytest.raises(DataAdminError, match="confirm-delete"):
        admin.delete(backup)
    assert not backup.exists()
    assert admin.info()["emotion_records"] == 2
    result = admin.delete(backup, confirm_delete=True)
    assert result["deleted"] == {"emotion_records": 2, "logs": 2}
    assert admin.info()["emotion_records"] == admin.info()["legacy_logs"] == 0
    assert DataAdmin(backup).info()["emotion_records"] == DataAdmin(backup).info()["legacy_logs"] == 2
    assert DataAdmin(backup).info()["raw_text_present"] is True
    assert admin.info()["installation_scope"] == "single_child"


def test_backup_failure_blocks_deletion(database, tmp_path):
    admin = DataAdmin(database)
    output = tmp_path / "existing.sqlite"
    output.write_text("do not replace", encoding="utf-8")
    with pytest.raises(DataAdminError, match="overwrite"):
        admin.delete(output, confirm_delete=True)
    assert admin.info()["emotion_records"] == admin.info()["legacy_logs"] == 2
    assert output.read_text(encoding="utf-8") == "do not replace"


def test_destructive_transaction_blocks_new_writes_until_backup_and_delete_complete(database, tmp_path, monkeypatch):
    admin = DataAdmin(database)
    original_backup = admin.backup

    def backup_while_locked(output):
        with sqlite3.connect(str(database), timeout=0) as writer:
            with pytest.raises(sqlite3.OperationalError, match="locked"):
                writer.execute("INSERT INTO logs VALUES ('new', 'private', 'happy', 1)")
        writer.close()
        return original_backup(output)

    monkeypatch.setattr(admin, "backup", backup_while_locked)
    backup = tmp_path / "locked.sqlite"
    result = admin.delete(backup, confirm_delete=True)
    assert result["deleted"] == {"emotion_records": 2, "logs": 2}
    assert DataAdmin(backup).info()["legacy_logs"] == 2


def test_legacy_only_database_can_be_exported_without_implicit_migration(tmp_path):
    path = tmp_path / "legacy.sqlite"
    EmotionMemory(str(path)).save_log("raw legacy", "happy")
    info = DataAdmin(path).info()
    assert info["schema_version"] == 0
    assert info["emotion_records"] == 0
    output = tmp_path / "legacy.json"
    DataAdmin(path).export(output)
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["emotion_records"] == []
    assert len(payload["legacy_logs"]) == 1
    assert "raw legacy" not in output.read_text(encoding="utf-8")
    with database_connection(str(path)) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 0


def test_retention_keeps_recent_new_and_legacy_records_after_backup(database, tmp_path):
    admin = DataAdmin(database)
    backup = tmp_path / "before-retention.sqlite"
    result = admin.retention(30, backup, confirm_delete=True)
    assert result["deleted"] == {"emotion_records": 1, "logs": 1}
    assert admin.info()["emotion_records"] == admin.info()["legacy_logs"] == 1
    assert DataAdmin(backup).info()["emotion_records"] == DataAdmin(backup).info()["legacy_logs"] == 2


def test_retention_zero_is_disabled_and_cli_defaults_to_configured_days(database, tmp_path, monkeypatch):
    admin = DataAdmin(database)
    output = tmp_path / "unused.sqlite"
    result = admin.retention(0, output)
    assert result["deleted"] == {}
    assert not output.exists()
    assert admin.info()["emotion_records"] == 2
    monkeypatch.setattr(config, "RETENTION_DAYS", 30)
    assert build_parser().parse_args(["retention"]).days == 30
    assert build_parser().parse_args(["retention", "--days", "0"]).days == 0


def test_positive_retention_requires_both_a_new_backup_and_confirmation(database, tmp_path):
    admin = DataAdmin(database)
    with pytest.raises(DataAdminError, match="backup"):
        admin.retention(30, confirm_delete=True)
    output = tmp_path / "not-confirmed.sqlite"
    with pytest.raises(DataAdminError, match="confirm-delete"):
        admin.retention(30, output)
    assert not output.exists()
    assert admin.info()["emotion_records"] == 2


@pytest.mark.parametrize("days", [-1, 3651, 1.2, True])
def test_invalid_retention_cannot_modify_data(database, tmp_path, days):
    admin = DataAdmin(database)
    with pytest.raises(DataAdminError, match="integer"):
        admin.retention(days, tmp_path / "bad.sqlite", confirm_delete=True)
    assert admin.info()["emotion_records"] == 2


def test_outputs_never_overwrite_database_existing_exports_or_source_code(database, tmp_path):
    admin = DataAdmin(database)
    with pytest.raises(DataAdminError, match="differ"):
        admin.backup(database)
    output = tmp_path / "export.json"
    admin.export(output)
    original = output.read_bytes()
    with pytest.raises(DataAdminError, match="overwrite"):
        admin.export(output, include_raw=True)
    assert output.read_bytes() == original
    code = tmp_path / "source.py"
    code.write_text("original", encoding="utf-8")
    with pytest.raises(DataAdminError):
        admin.backup(code)
    assert code.read_text(encoding="utf-8") == "original"


@pytest.mark.parametrize("name", ["CON.json", "NUL.sqlite", "COM1.sqlite", "export:private.sqlite", "out.sqlite "])
def test_windows_reserved_or_stream_outputs_are_rejected(database, tmp_path, name):
    with pytest.raises(DataAdminError):
        DataAdmin(database).backup(tmp_path / name)


def test_linked_output_parent_is_rejected(database, tmp_path, monkeypatch):
    target = tmp_path / "linked-parent"
    target.mkdir()
    original = type(target).is_symlink
    monkeypatch.setattr(type(target), "is_symlink", lambda path: path == target or original(path))
    with pytest.raises(DataAdminError, match="symbolic link"):
        DataAdmin(database).export(target / "private.json")
    assert not (target / "private.json").exists()


def test_missing_source_is_not_created_and_demo_cli_blocks_real_database(tmp_path, database, monkeypatch):
    missing = tmp_path / "missing.sqlite"
    with pytest.raises(DataAdminError, match="already exist"):
        DataAdmin(missing)
    assert not missing.exists()
    monkeypatch.setattr(config, "DEMO_MODE", True)
    with pytest.raises(SystemExit) as failure:
        main(["--db", str(database), "info"])
    assert failure.value.code == 2


def test_cli_info_and_redacted_export_work_without_starting_models(database, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(config, "DEMO_MODE", False)
    assert main(["--db", str(database), "info"]) == 0
    assert json.loads(capsys.readouterr().out)["schema_version"] == SCHEMA_VERSION
    output = tmp_path / "cli.json"
    assert main(["--db", str(database), "export", "--output", str(output)]) == 0
    assert "private speech" not in output.read_text(encoding="utf-8")
