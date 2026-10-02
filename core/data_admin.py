"""Explicit local maintenance: protected exports and backups before destructive operations."""
from __future__ import annotations

import csv
import json
import os
import sqlite3
from contextlib import closing, contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterator

from core.memory import SCHEMA_VERSION, SchemaVersionError


class DataAdminError(ValueError):
    """A maintenance command is unsafe or cannot operate on the selected database."""


class DataAdmin:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path).expanduser().resolve()
        if not self.db_path.is_file():
            raise DataAdminError("Source database must already exist; this tool never creates a source database")

    @staticmethod
    def _safe_output_path(output: str | Path) -> Path:
        requested = Path(output).expanduser().absolute()
        reserved = {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"}
        reserved.update(f"{prefix}{index}" for prefix in ("COM", "LPT") for index in range(1, 10))
        reserved.update(f"{prefix}{index}" for prefix in ("COM", "LPT") for index in ("¹", "²", "³"))
        for part in (requested, *requested.parents):
            if part.is_symlink() or getattr(part, "is_junction", lambda: False)():
                raise DataAdminError("Output must not pass through a symbolic link or junction")
            name = part.name
            if not name or name in {".", ".."}:
                continue
            if ":" in name or name != name.rstrip(" .") or name.split(".")[0].upper() in reserved:
                raise DataAdminError("Output contains a reserved or unsafe filename")
        return requested.resolve()

    @contextmanager
    def _connection(self, *, writable: bool = False) -> Iterator[sqlite3.Connection]:
        mode = "rw" if writable else "ro"
        with closing(sqlite3.connect(f"{self.db_path.as_uri()}?mode={mode}", uri=True, timeout=5.0)) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA busy_timeout=5000")
            conn.execute("PRAGMA foreign_keys=ON")
            with conn:
                yield conn

    @staticmethod
    def _tables(conn: sqlite3.Connection) -> set[str]:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if version > SCHEMA_VERSION:
            raise SchemaVersionError(
                f"Database schema {version} is newer than supported version {SCHEMA_VERSION}; upgrade the application"
            )
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not tables.intersection({"emotion_records", "logs"}):
            raise DataAdminError("Selected file does not contain a SoulCompanion emotion database")
        return tables

    def info(self) -> dict:
        with self._connection() as conn:
            conn.execute("BEGIN")
            tables = self._tables(conn)
            scope = "legacy_single_child"
            if "app_metadata" in tables:
                row = conn.execute("SELECT value FROM app_metadata WHERE key='installation_scope'").fetchone()
                if row:
                    scope = row[0]
            return {
                "schema_version": conn.execute("PRAGMA user_version").fetchone()[0],
                "installation_scope": scope,
                "emotion_records": conn.execute("SELECT COUNT(*) FROM emotion_records").fetchone()[0]
                if "emotion_records" in tables else 0,
                "legacy_logs": conn.execute("SELECT COUNT(*) FROM logs").fetchone()[0] if "logs" in tables else 0,
                "retention_policy": "manual",
                "raw_text_present": (
                    bool(conn.execute("SELECT 1 FROM emotion_records WHERE context != '' OR source_text != '' LIMIT 1").fetchone())
                    if "emotion_records" in tables else False
                ) or (
                    bool(conn.execute("SELECT 1 FROM logs WHERE user_input != '' LIMIT 1").fetchone())
                    if "logs" in tables else False
                ),
            }

    def _reserve_output(self, output: str | Path, extensions: set[str]) -> tuple[Path, int]:
        path = self._safe_output_path(output)
        if path == self.db_path:
            raise DataAdminError("Output must differ from the source database")
        if path.suffix.lower() not in extensions:
            raise DataAdminError("Output filename must use one of: " + ", ".join(sorted(extensions)))
        if path.is_symlink() or any(Path(str(path) + suffix).exists() for suffix in ("-wal", "-shm", "-journal")):
            raise DataAdminError("Output or its SQLite sidecar already exists")
        try:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
        except FileExistsError as exc:
            raise DataAdminError("Output already exists; refusing to overwrite") from exc
        try:
            os.chmod(path, 0o600)
        except BaseException:
            os.close(descriptor)
            path.unlink(missing_ok=True)
            raise
        return path, descriptor

    def backup(self, output: str | Path) -> dict:
        with self._connection() as source:
            self._tables(source)
            path, descriptor = self._reserve_output(output, {".sqlite", ".sqlite3", ".db"})
            os.close(descriptor)
            try:
                with closing(sqlite3.connect(f"{path.as_uri()}?mode=rw", uri=True, timeout=5.0)) as destination:
                    source.backup(destination)
                    if destination.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                        raise DataAdminError("Backup verification failed")
            except BaseException:
                path.unlink(missing_ok=True)
                raise
        return {"backup": str(path), "verified": True, "includes_raw_text": True}

    @staticmethod
    def _csv_value(value):
        # CSV is often opened in a spreadsheet; quoted cells can still run formulas.
        if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
            return "'" + value
        return value

    def export(self, output: str | Path, *, include_raw: bool = False) -> dict:
        suffix = Path(output).suffix.lower()
        if suffix not in {".json", ".csv"}:
            raise DataAdminError("Export output must end in .json or .csv")
        with self._connection() as conn:
            conn.execute("BEGIN")
            tables = self._tables(conn)
            columns = ["id", "timestamp", "category", "valence", "arousal", "confidence", "cause"]
            if include_raw:
                columns += ["context", "source_text"]
            legacy_columns = ["rowid AS id", "time", "emotion", "score"]
            if include_raw:
                legacy_columns.append("user_input")
            schema_version = conn.execute("PRAGMA user_version").fetchone()[0]
            queries = {
                "emotion_records": "SELECT " + ", ".join(columns) + " FROM emotion_records ORDER BY timestamp, id",
                "logs": "SELECT " + ", ".join(legacy_columns) + " FROM logs ORDER BY time, rowid",
            }
            counts = {"emotion_records": 0, "logs": 0}
            path, descriptor = self._reserve_output(output, {suffix})
            try:
                with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as stream:
                    if suffix == ".json":
                        metadata = json.dumps({
                            "schema_version": schema_version, "installation_scope": "single_child",
                            "exported_at": datetime.now().isoformat(), "includes_raw_text": include_raw,
                        }, ensure_ascii=False, indent=2, allow_nan=False)
                        stream.write(metadata[:-1])
                        for table, key in (("emotion_records", "emotion_records"), ("logs", "legacy_logs")):
                            stream.write(',\n"' + key + '": [')
                            if table in tables:
                                for record in conn.execute(queries[table]):
                                    if counts[table]:
                                        stream.write(",")
                                    stream.write("\n")
                                    json.dump(dict(record), stream, ensure_ascii=False, allow_nan=False)
                                    counts[table] += 1
                            stream.write("\n]")
                        stream.write("\n}\n")
                    else:
                        headers = ["source_table", "id", "timestamp", "category", "valence", "arousal", "confidence", "cause", "score"]
                        if include_raw:
                            headers += ["context", "source_text", "user_input"]
                        writer = csv.DictWriter(stream, fieldnames=headers)
                        writer.writeheader()
                        for table in ("emotion_records", "logs"):
                            if table not in tables:
                                continue
                            for record in conn.execute(queries[table]):
                                row = {"source_table": table, **dict(record)}
                                if table == "logs":
                                    row["timestamp"] = row.pop("time")
                                    row["category"] = row.pop("emotion")
                                writer.writerow({key: self._csv_value(value) for key, value in row.items()})
                                counts[table] += 1
            except BaseException:
                path.unlink(missing_ok=True)
                raise
        return {"export": str(path), "emotion_records": counts["emotion_records"],
                "legacy_logs": counts["logs"], "includes_raw_text": include_raw}

    def _delete(self, backup_output: str | Path, *, confirm_delete: bool, days: int | None) -> dict:
        if not confirm_delete:
            raise DataAdminError("Deletion requires --confirm-delete and a new backup path")
        with self._connection(writable=True) as conn:
            # Other writers are held until the backup and deletion commit together.
            conn.execute("BEGIN IMMEDIATE")
            tables = self._tables(conn)
            backup = self.backup(backup_output)
            deleted = {}
            cutoff = datetime.now() - timedelta(days=days) if days is not None else None
            for table, column, date_format in (
                ("emotion_records", "timestamp", "%Y-%m-%dT%H:%M:%S"),
                ("logs", "time", "%Y-%m-%d %H:%M:%S"),
            ):
                if table not in tables:
                    deleted[table] = 0
                    continue
                sql = f"DELETE FROM {table}"
                parameters = ()
                if cutoff is not None:
                    sql += f" WHERE {column} < ?"
                    parameters = (cutoff.strftime(date_format),)
                deleted[table] = conn.execute(sql, parameters).rowcount
        return {"deleted": deleted, **backup, "retention_days": days}

    def delete(self, backup_output: str | Path, *, confirm_delete: bool = False) -> dict:
        return self._delete(backup_output, confirm_delete=confirm_delete, days=None)

    def retention(self, days: int, backup_output: str | Path | None = None, *, confirm_delete: bool = False) -> dict:
        if not isinstance(days, int) or isinstance(days, bool) or not 0 <= days <= 3650:
            raise DataAdminError("Retention days must be an integer between 0 and 3650")
        if days == 0:
            return {"retention_days": 0, "retention_policy": "manual", "deleted": {}, "reason": "Retention deletion is disabled"}
        if backup_output is None:
            raise DataAdminError("Retention deletion requires a new --backup path")
        return self._delete(backup_output, confirm_delete=confirm_delete, days=days)
