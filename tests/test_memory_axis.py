"""emotion/memory_axis.py 单元测试（临时 SQLite，无重依赖）。

覆盖：记录、趋势、计数、风险触发、周期性检测、序列查询、工厂。
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta

import pytest

from emotion.memory_axis import MemoryAxis, create_memory_axis
from emotion.models import EmotionCategory, EmotionState


@pytest.fixture()
def axis(tmp_path) -> MemoryAxis:
    return MemoryAxis(db_path=str(tmp_path / "emotion_test.sqlite"))


def _record(axis: MemoryAxis, category: EmotionCategory, valence: float, **kwargs) -> EmotionState:
    state = EmotionState(category=category, valence=valence, **kwargs)
    axis.record(state)
    return state


# ─── 初始化 ────────────────────────────────────────────────────────────

def test_db_file_created(axis):
    assert os.path.exists(axis.db_path)
    assert axis.db_path.endswith(".sqlite")


def test_factory_creates_memory_axis(tmp_path):
    axis = create_memory_axis(db_path=str(tmp_path / "f.sqlite"))
    assert isinstance(axis, MemoryAxis)


# ─── 记录与查询 ────────────────────────────────────────────────────────

def test_record_and_get_records(axis):
    _record(axis, EmotionCategory.HAPPY, 0.8)
    records = axis.get_records()
    assert len(records) == 1
    assert records[0].category == "happy"
    assert records[0].valence == pytest.approx(0.8)
    assert records[0].arousal == pytest.approx(0.5)


def test_get_records_limit_offset(axis):
    for i in range(5):
        _record(axis, EmotionCategory.HAPPY, 0.1 * i)
    assert len(axis.get_records(limit=2)) == 2
    assert len(axis.get_records(limit=10, offset=4)) == 1


def test_record_stores_context(axis):
    state = EmotionState(category=EmotionCategory.HAPPY, valence=0.8)
    axis.record(state, context="打招呼练习", source_text="你好")
    rec = axis.get_records()[0]
    assert rec.context == "打招呼练习"
    assert rec.source_text == "你好"


# ─── 近期趋势 ──────────────────────────────────────────────────────────

def test_recent_trend_empty_returns_none(axis):
    assert axis.get_recent_trend() is None


def test_recent_trend_positive(axis):
    _record(axis, EmotionCategory.HAPPY, 0.8)
    assert axis.get_recent_trend() == 1


def test_recent_trend_negative(axis):
    _record(axis, EmotionCategory.SAD, -0.7)
    assert axis.get_recent_trend() == -1


def test_recent_trend_sums_recent(axis):
    _record(axis, EmotionCategory.HAPPY, 0.8)
    _record(axis, EmotionCategory.HAPPY, 0.8)
    # 0.8 + 0.8 = 1.6 → round = 2
    assert axis.get_recent_trend() == 2


# ─── 计数 ──────────────────────────────────────────────────────────────

def test_emotion_counts(axis):
    _record(axis, EmotionCategory.HAPPY, 0.8)
    _record(axis, EmotionCategory.HAPPY, 0.7)
    _record(axis, EmotionCategory.SAD, -0.6)
    counts = axis.get_emotion_counts(days=7)
    assert counts["happy"] == 2
    assert counts["sad"] == 1


# ─── 趋势分析 ──────────────────────────────────────────────────────────

def test_trend_analysis_empty(axis):
    trend = axis.get_trend_analysis()
    assert trend.total_records == 0
    assert trend.dominant_emotion == "neutral"


def test_trend_analysis_dominant_and_totals(axis):
    _record(axis, EmotionCategory.HAPPY, 0.8)
    _record(axis, EmotionCategory.HAPPY, 0.7)
    _record(axis, EmotionCategory.SAD, -0.6)
    trend = axis.get_trend_analysis(period="weekly")
    assert trend.total_records == 3
    assert trend.dominant_emotion == "happy"
    assert trend.average_valence == pytest.approx((0.8 + 0.7 - 0.6) / 3, abs=1e-3)
    assert 0.0 <= trend.stability_score <= 1.0


def test_trend_analysis_risk_periods(axis):
    _record(axis, EmotionCategory.SAD, -0.6)
    _record(axis, EmotionCategory.HAPPY, 0.6)
    trend = axis.get_trend_analysis(period="daily")
    assert len(trend.risk_periods) == 1
    assert len(trend.positive_periods) == 1


# ─── 风险触发 ──────────────────────────────────────────────────────────

def test_risk_trigger_sustained_negative(axis):
    for _ in range(3):
        _record(axis, EmotionCategory.SAD, -0.7)
    triggers = axis.check_risk_triggers(window_minutes=30)
    assert any("持续负面情绪" in t for t in triggers)


def test_risk_trigger_distressed(axis):
    _record(axis, EmotionCategory.DISTRESSED, -0.9)
    _record(axis, EmotionCategory.DISTRESSED, -0.9)
    triggers = axis.check_risk_triggers(window_minutes=30)
    assert any("过载" in t for t in triggers)


def test_no_risk_triggers_for_positive(axis):
    _record(axis, EmotionCategory.HAPPY, 0.8)
    _record(axis, EmotionCategory.HAPPY, 0.8)
    assert axis.check_risk_triggers(window_minutes=30) == []


def test_risk_trigger_volatility(axis):
    # 剧烈波动：连续大幅变化 >= 3 次
    vals = [0.9, -0.9, 0.9, -0.9]
    for v in vals:
        _record(axis, EmotionCategory.HAPPY if v > 0 else EmotionCategory.SAD, v)
    triggers = axis.check_risk_triggers(window_minutes=30)
    assert any("波动" in t for t in triggers)


# ─── 序列 / 周期性 ─────────────────────────────────────────────────────

def test_valence_series(axis):
    _record(axis, EmotionCategory.HAPPY, 0.8)
    _record(axis, EmotionCategory.SAD, -0.7)
    series = axis.get_valence_series(days=7)
    assert len(series) == 2
    assert series[0][1] == pytest.approx(0.8)
    assert series[1][1] == pytest.approx(-0.7)


def test_periodicity_insufficient_data(axis):
    _record(axis, EmotionCategory.SAD, -0.7)
    assert axis.detect_periodicity(lookback_days=30) == {}


def test_periodicity_detects_hour_pattern(axis):
    # 同一小时内 >=2 条负向情绪 → 应识别出 hour_x_negative
    base = datetime.now().replace(minute=30, second=0, microsecond=0)
    for i in range(8):
        ts = (base - timedelta(minutes=i)).isoformat()
        _record(axis, EmotionCategory.SAD, -0.6, timestamp=ts)
    patterns = axis.detect_periodicity(lookback_days=30)
    assert patterns, "应至少识别出一个周期性模式"
    assert any(k.endswith("_negative") for k in patterns)
