"""
emotion/memory_axis.py - Long-term Emotion Memory System

Stores emotion records in SQLite, provides:
- Time series recording
- Periodicity detection (e.g., Sunday anxiety)
- Emotion trend analysis
- Behavior trigger mechanism

Extends existing core/memory.py without modifying it.
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

try:
    from config import DATABASE_PATH
except ImportError:
    DATABASE_PATH = "data/emotional_db.sqlite"
from emotion.models import EmotionRecord, EmotionState, EmotionTrend

logger = logging.getLogger("MemoryAxis")

# ─── SQL Schema ────────────────────────────────────────────────────────

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS emotion_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'neutral',
    valence REAL DEFAULT 0.0,
    arousal REAL DEFAULT 0.5,
    cause TEXT DEFAULT '',
    context TEXT DEFAULT '',
    source_text TEXT DEFAULT '',
    confidence REAL DEFAULT 0.5
)
"""

_CREATE_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_er_timestamp ON emotion_records(timestamp)",
    "CREATE INDEX IF NOT EXISTS idx_er_category ON emotion_records(category)",
]


class MemoryAxis:
    """
    Long-term emotion memory system.

    Persists EmotionState snapshots to SQLite and provides analytics:
    - Trend analysis (recent emotional direction)
    - Periodicity detection (recurring patterns by day/hour)
    - Risk period identification
    - Trigger mechanism for behavior system
    """

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or DATABASE_PATH
        self._init_db()
        logger.info(f"✅ [情绪记忆] 记忆轴已就绪 (db: {self.db_path})")

    def _init_db(self) -> None:
        """Initialize SQLite database with emotion_records table."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(_CREATE_TABLE)
            for idx_sql in _CREATE_INDEXES:
                conn.execute(idx_sql)

    # ─── Recording ────────────────────────────────────────────────────

    def record(self, state: EmotionState, context: str = "", source_text: str = "") -> None:
        """
        Persist an EmotionState to the database.

        Args:
            state: The EmotionState to record
            context: What was happening (e.g., "自由对话", "打招呼练习")
            source_text: What the child said (if applicable)
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """INSERT INTO emotion_records
                   (timestamp, category, valence, arousal, cause, context, source_text, confidence)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    state.timestamp,
                    state.category.value if hasattr(state.category, 'value') else str(state.category),
                    state.valence,
                    state.arousal,
                    state.emotional_cause,
                    context,
                    source_text,
                    state.confidence,
                ),
            )

    # ─── Trend Analysis ──────────────────────────────────────────────

    def get_recent_trend(self, limit: int = 10) -> Optional[int]:
        """
        Get recent emotional trend as a signed integer.
        Negative = recent emotions are negative, Positive = recent are positive.

        Compatible with existing core/memory.py interface.
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT valence FROM emotion_records ORDER BY timestamp DESC LIMIT ?",
                (limit,),
            )
            valences = [row[0] for row in cursor.fetchall()]

        if not valences:
            return None

        # Sum of recent valences (positive = good trend, negative = bad trend)
        return round(sum(valences))

    def get_trend_analysis(self, period: str = "daily") -> EmotionTrend:
        """
        Analyze emotion trends for a given period.

        Args:
            period: "hourly", "daily", or "weekly"

        Returns:
            EmotionTrend with aggregated analysis
        """
        now = datetime.now()

        if period == "hourly":
            start = now - timedelta(hours=1)
        elif period == "daily":
            start = now - timedelta(days=1)
        elif period == "weekly":
            start = now - timedelta(days=7)
        else:
            start = now - timedelta(days=1)

        start_str = start.strftime("%Y-%m-%dT%H:%M:%S")

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                """SELECT category, valence, arousal, timestamp
                   FROM emotion_records
                   WHERE timestamp >= ?
                   ORDER BY timestamp""",
                (start_str,),
            )
            records = cursor.fetchall()

        if not records:
            return EmotionTrend(period=period, total_records=0)

        # Aggregate
        categories = [r[0] for r in records]
        valences = [r[1] for r in records]
        arousals = [r[2] for r in records]
        timestamps = [r[3] for r in records]

        # Dominant emotion (most frequent)
        from collections import Counter
        category_counts = Counter(categories)
        dominant = category_counts.most_common(1)[0][0]

        # Stability: inverse of valence standard deviation
        avg_valence = sum(valences) / len(valences)
        if len(valences) > 1:
            variance = sum((v - avg_valence) ** 2 for v in valences) / len(valences)
            stability = max(0.0, 1.0 - (variance ** 0.5))
        else:
            stability = 1.0

        # Risk periods: timestamps where valence < -0.3
        risk_periods = [
            ts for ts, v in zip(timestamps, valences) if v < -0.3
        ]

        # Positive periods: timestamps where valence > 0.3
        positive_periods = [
            ts for ts, v in zip(timestamps, valences) if v > 0.3
        ]

        return EmotionTrend(
            period=period,
            dominant_emotion=dominant,
            average_valence=round(avg_valence, 3),
            average_arousal=round(sum(arousals) / len(arousals), 3),
            stability_score=round(stability, 3),
            risk_periods=risk_periods[-10:],  # Last 10 risk periods
            positive_periods=positive_periods[-10:],
            total_records=len(records),
        )

    # ─── Periodicity Detection ────────────────────────────────────────

    def detect_periodicity(self, lookback_days: int = 30) -> Dict[str, float]:
        """
        Detect recurring emotional patterns by day-of-week and hour.

        Returns:
            Dict with keys like "monday_anxiety", "evening_sadness" etc.
            Values are frequency scores (0.0 - 1.0).
        """
        start = datetime.now() - timedelta(days=lookback_days)
        start_str = start.strftime("%Y-%m-%dT%H:%M:%S")

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                """SELECT timestamp, category, valence
                   FROM emotion_records
                   WHERE timestamp >= ?
                   ORDER BY timestamp""",
                (start_str,),
            )
            records = cursor.fetchall()

        if len(records) < 7:
            return {}  # Not enough data

        # Group by day-of-week
        day_emotions: Dict[int, List[float]] = {i: [] for i in range(7)}
        hour_emotions: Dict[int, List[float]] = {h: [] for h in range(24)}

        for ts_str, category, valence in records:
            try:
                ts = datetime.fromisoformat(ts_str)
                day_emotions[ts.weekday()].append(valence)
                hour_emotions[ts.hour].append(valence)
            except (ValueError, TypeError):
                continue

        patterns: Dict[str, float] = {}
        day_names = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]

        # Detect day-of-week patterns
        for day_idx, valences in day_emotions.items():
            if len(valences) >= 2:
                avg = sum(valences) / len(valences)
                if avg < -0.2:
                    patterns[f"{day_names[day_idx]}_negative"] = round(abs(avg), 2)
                elif avg > 0.3:
                    patterns[f"{day_names[day_idx]}_positive"] = round(avg, 2)

        # Detect time-of-day patterns
        for hour, valences in hour_emotions.items():
            if len(valences) >= 2:
                avg = sum(valences) / len(valences)
                if avg < -0.2:
                    patterns[f"hour_{hour}_negative"] = round(abs(avg), 2)
                elif avg > 0.3:
                    patterns[f"hour_{hour}_positive"] = round(avg, 2)

        return patterns

    # ─── Risk Detection ──────────────────────────────────────────────

    def check_risk_triggers(self, window_minutes: int = 30) -> List[str]:
        """
        Check for risk triggers in recent emotion history.

        Returns list of trigger descriptions (empty if no risks).
        """
        start = datetime.now() - timedelta(minutes=window_minutes)
        start_str = start.strftime("%Y-%m-%dT%H:%M:%S")

        triggers: List[str] = []

        with sqlite3.connect(self.db_path) as conn:
            # Check for sustained negative emotion
            cursor = conn.execute(
                """SELECT COUNT(*), AVG(valence)
                   FROM emotion_records
                   WHERE timestamp >= ? AND valence < -0.3""",
                (start_str,),
            )
            neg_count, avg_valence = cursor.fetchone()

            if neg_count and neg_count >= 3:
                triggers.append(f"持续负面情绪 ({neg_count}次, 均值{avg_valence:.2f})")

            # Check for emotion volatility
            cursor = conn.execute(
                """SELECT valence FROM emotion_records
                   WHERE timestamp >= ? ORDER BY timestamp""",
                (start_str,),
            )
            valences = [r[0] for r in cursor.fetchall()]

            if len(valences) >= 4:
                changes = sum(
                    1 for i in range(1, len(valences))
                    if abs(valences[i] - valences[i - 1]) > 0.5
                )
                if changes >= 3:
                    triggers.append(f"情绪波动剧烈 ({changes}次大幅变化)")

            # Check for distressed state
            cursor = conn.execute(
                """SELECT COUNT(*) FROM emotion_records
                   WHERE timestamp >= ? AND category IN ('distressed', 'fearful')""",
                (start_str,),
            )
            distress_count = cursor.fetchone()[0]
            if distress_count and distress_count >= 2:
                triggers.append(f"出现过载/恐惧状态 ({distress_count}次)")

        return triggers

    # ─── Query ────────────────────────────────────────────────────────

    def get_records(
        self, limit: int = 100, offset: int = 0
    ) -> List[EmotionRecord]:
        """Retrieve emotion records from database."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                """SELECT timestamp, category, valence, arousal, cause, context, source_text
                   FROM emotion_records
                   ORDER BY timestamp DESC
                   LIMIT ? OFFSET ?""",
                (limit, offset),
            )
            rows = cursor.fetchall()

        return [
            EmotionRecord(
                timestamp=r[0],
                category=r[1],
                valence=r[2],
                arousal=r[3],
                cause=r[4],
                context=r[5],
                source_text=r[6],
            )
            for r in rows
        ]

    def get_emotion_counts(self, days: int = 7) -> Dict[str, int]:
        """Get emotion category counts for the last N days."""
        start = datetime.now() - timedelta(days=days)
        start_str = start.strftime("%Y-%m-%dT%H:%M:%S")

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                """SELECT category, COUNT(*) as cnt
                   FROM emotion_records
                   WHERE timestamp >= ?
                   GROUP BY category
                   ORDER BY cnt DESC""",
                (start_str,),
            )
            return {row[0]: row[1] for row in cursor.fetchall()}

    def get_valence_series(self, days: int = 7) -> List[Tuple[str, float]]:
        """Get timestamped valence series for charting."""
        start = datetime.now() - timedelta(days=days)
        start_str = start.strftime("%Y-%m-%dT%H:%M:%S")

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                """SELECT timestamp, valence
                   FROM emotion_records
                   WHERE timestamp >= ?
                   ORDER BY timestamp""",
                (start_str,),
            )
            return [(row[0], row[1]) for row in cursor.fetchall()]


def create_memory_axis(db_path: Optional[str] = None) -> MemoryAxis:
    """Factory function to create a MemoryAxis instance."""
    return MemoryAxis(db_path=db_path)
