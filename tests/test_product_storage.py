"""Storage lifecycle and report-window regressions using real temporary SQLite files."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
import sqlite3
import threading

import pytest

from core.memory import EmotionMemory, database_connection
from emotion.intervention import InterventionEngine
from emotion.memory_axis import MemoryAxis
from emotion.models import EmotionCategory, EmotionState
from reports.report_generator import ReportGenerator


def test_every_storage_operation_closes_its_connection(tmp_path, monkeypatch):
    original_connect = sqlite3.connect
    connections = []

    def tracked_connect(*args, **kwargs):
        connection = original_connect(*args, **kwargs)
        connections.append(connection)
        return connection

    monkeypatch.setattr("core.memory.sqlite3.connect", tracked_connect)
    monkeypatch.chdir(tmp_path)
    db_path = str(tmp_path / "storage.sqlite")
    axis = MemoryAxis(db_path)
    legacy = EmotionMemory(db_path)
    report = ReportGenerator(db_path)
    operations = [
        lambda: axis.record(EmotionState(), source_text="sample"),
        axis.get_recent_trend,
        axis.get_records,
        axis.get_trend_analysis,
        axis.detect_periodicity,
        axis.check_risk_triggers,
        axis.get_emotion_counts,
        axis.get_valence_series,
        lambda: legacy.save_log("sample", "happy"),
        legacy.get_recent_trend,
        lambda: report._load_day(datetime.now().strftime("%Y-%m-%d")),
    ]
    for operation in operations:
        operation()
        for connection in connections:
            with pytest.raises(sqlite3.ProgrammingError, match="closed"):
                connection.execute("SELECT 1")


def test_connection_commits_rolls_back_and_enforces_foreign_keys(tmp_path):
    db_path = str(tmp_path / "transactions.sqlite")
    with database_connection(db_path) as connection:
        assert connection.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
        connection.execute("CREATE TABLE parent (id INTEGER PRIMARY KEY)")
        connection.execute(
            "CREATE TABLE child (parent_id INTEGER REFERENCES parent(id))"
        )
        connection.execute("INSERT INTO parent VALUES (1)")
    with pytest.raises(RuntimeError, match="abort"):
        with database_connection(db_path) as connection:
            connection.execute("INSERT INTO parent VALUES (2)")
            raise RuntimeError("abort")
    with pytest.raises(sqlite3.IntegrityError):
        with database_connection(db_path) as connection:
            connection.execute("INSERT INTO child VALUES (999)")
    with database_connection(db_path) as connection:
        assert connection.execute("SELECT id FROM parent").fetchall() == [(1,)]
        assert connection.execute("SELECT * FROM child").fetchall() == []


def test_concurrent_writes_reads_and_reopen_preserve_records(tmp_path):
    db_path = tmp_path / "concurrent.sqlite"
    axis = MemoryAxis(str(db_path))
    barrier = threading.Barrier(6)

    def work(worker):
        barrier.wait(timeout=10)
        for index in range(20):
            if worker < 4:
                axis.record(EmotionState(), source_text=f"{worker}:{index}")
            else:
                axis.get_records(limit=10)
                axis.get_emotion_counts(days=1)

    with ThreadPoolExecutor(max_workers=6) as executor:
        list(executor.map(work, range(6)))
    reopened = MemoryAxis(str(db_path))
    assert reopened.get_emotion_counts(days=1) == {"neutral": 80}
    assert len(reopened.get_records(limit=100)) == 80
    # Windows cannot rename a database while an old connection still owns its handle.
    moved_path = tmp_path / "reopened.sqlite"
    db_path.rename(moved_path)
    assert len(MemoryAxis(str(moved_path)).get_records(limit=100)) == 80


@pytest.mark.parametrize("days, count, average", [(1, 1, 0.8), (30, 3, 0.067)])
def test_report_trend_and_counts_use_the_selected_window(tmp_path, days, count, average):
    axis = MemoryAxis(str(tmp_path / "report.sqlite"))
    now = datetime.now()
    samples = [
        (0.5, EmotionCategory.HAPPY, 0.8),
        (5, EmotionCategory.SAD, -0.8),
        (20, EmotionCategory.CALM, 0.2),
        (40, EmotionCategory.ANGRY, -0.6),
    ]
    for age, category, valence in samples:
        axis.record(EmotionState(
            timestamp=(now - timedelta(days=age)).isoformat(),
            category=category,
            valence=valence,
        ))
    report = InterventionEngine(axis).generate_parent_report(days=days)
    assert report.interaction_count == count
    assert report.emotion_trend.total_records == count
    assert report.emotion_trend.average_valence == average
    assert "所选时段" in report.summary
    assert "本周" not in report.summary


def test_empty_selected_window_does_not_claim_healthy_emotions(tmp_path):
    axis = MemoryAxis(str(tmp_path / "empty.sqlite"))
    axis.record(EmotionState(
        timestamp=(datetime.now() - timedelta(days=5)).isoformat(),
        category=EmotionCategory.SAD,
        valence=-0.8,
    ))
    engine = InterventionEngine(axis)
    report = engine.generate_parent_report(days=1)
    assert report.interaction_count == 0
    assert report.emotion_trend.total_records == 0
    assert report.highlights == []
    assert report.concerns == []
    assert report.health_score is None
    assert "无法评估" in report.summary
    markdown = engine.generate_parent_report_markdown(days=1)
    assert "暂无数据，无法评估" in markdown
    assert "无需特别关注" not in markdown
    assert "None" not in markdown
    assert "\n## " in markdown
    assert "\\n" not in markdown
