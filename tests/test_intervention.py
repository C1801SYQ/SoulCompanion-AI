"""emotion/intervention.py 单元测试（覆盖 R11 冷却/插队修复点）。

R11 关键修复：
- 冷却判定移到"生成计划之后"，按本次干预的 urgency 决定是否插队；
- 高紧急度干预（过载/恐惧）拥有独立的 8s 短冷却窗口，可插队普通 30s 冷却；
- 若上一次是高紧急度干预，低优先级干预需等完整 30s，避免打断安抚。
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from emotion.intervention import InterventionEngine, create_intervention_engine
from emotion.memory_axis import MemoryAxis
from emotion.models import EmotionCategory, EmotionState, InterventionType


@pytest.fixture()
def engine() -> InterventionEngine:
    return InterventionEngine()


def _state(category: EmotionCategory, **kwargs) -> EmotionState:
    return EmotionState(category=category, **kwargs)


# ─── 干预路由 ──────────────────────────────────────────────────────────

def test_distressed_triggers_calming_activity(engine):
    plan = engine.evaluate(_state(EmotionCategory.DISTRESSED))
    assert plan.intervention_type is InterventionType.CALMING_ACTIVITY
    assert plan.parent_alert is True
    assert plan.metadata["urgency"] == "high"
    assert plan.guidance_text


def test_fearful_triggers_breathing_guide(engine):
    plan = engine.evaluate(_state(EmotionCategory.FEARFUL))
    assert plan.intervention_type is InterventionType.BREATHING_GUIDE
    assert plan.parent_alert is True
    assert plan.metadata["urgency"] == "high"


def test_anxious_triggers_breathing_guide(engine):
    plan = engine.evaluate(_state(EmotionCategory.ANXIOUS))
    assert plan.intervention_type is InterventionType.BREATHING_GUIDE
    assert plan.parent_alert is False
    assert plan.metadata["urgency"] == "medium"


def test_sad_triggers_emotion_label(engine):
    plan = engine.evaluate(_state(EmotionCategory.SAD))
    assert plan.intervention_type is InterventionType.EMOTION_LABEL


def test_angry_triggers_emotion_label(engine):
    plan = engine.evaluate(_state(EmotionCategory.ANGRY))
    assert plan.intervention_type is InterventionType.EMOTION_LABEL


def test_happy_triggers_positive_reinforce(engine):
    plan = engine.evaluate(_state(EmotionCategory.HAPPY))
    assert plan.intervention_type is InterventionType.POSITIVE_REINFORCE
    assert plan.metadata["urgency"] == "low"


def test_surprised_triggers_positive_reinforce(engine):
    plan = engine.evaluate(_state(EmotionCategory.SURPRISED))
    assert plan.intervention_type is InterventionType.POSITIVE_REINFORCE


def test_critical_attention_triggers_redirect(engine):
    plan = engine.evaluate(_state(EmotionCategory.NEUTRAL, attention_level=0.05))
    assert plan.intervention_type is InterventionType.GENTLE_REDIRECT
    assert plan.metadata["reason"] == "attention_critical"


def test_mild_low_attention_triggers_redirect(engine):
    plan = engine.evaluate(_state(EmotionCategory.NEUTRAL, attention_level=0.2))
    assert plan.intervention_type is InterventionType.GENTLE_REDIRECT
    assert plan.metadata["reason"] == "attention_low"


def test_neutral_focused_no_intervention(engine):
    plan = engine.evaluate(_state(EmotionCategory.NEUTRAL, attention_level=1.0))
    assert plan.intervention_type is InterventionType.NONE


# ─── 冷却 / 插队逻辑 ───────────────────────────────────────────────────

def test_first_intervention_allowed_and_updates_state(engine):
    plan = engine.evaluate(_state(EmotionCategory.FEARFUL))
    assert plan.intervention_type is not InterventionType.NONE
    assert engine.get_last_plan() is plan
    assert engine._last_urgency == "high"
    assert engine._intervention_count == 1


def test_immediate_repeat_high_urgency_suppressed(engine):
    engine.evaluate(_state(EmotionCategory.FEARFUL))
    second = engine.evaluate(_state(EmotionCategory.FEARFUL))
    assert second.intervention_type is InterventionType.NONE


def test_urgent_bypasses_normal_cooldown(engine):
    """上一次是普通干预且已过 10s（>= 8s）→ 高紧急度可插队。"""
    engine._last_intervention_time = datetime.now() - timedelta(seconds=10)
    engine._last_urgency = "low"
    plan = engine.evaluate(_state(EmotionCategory.DISTRESSED))
    assert plan.intervention_type is InterventionType.CALMING_ACTIVITY


def test_urgent_still_subject_to_short_cooldown(engine):
    """高紧急度也受 8s 短冷却保护，避免过载时疯狂刷屏。"""
    engine._last_intervention_time = datetime.now() - timedelta(seconds=3)
    engine._last_urgency = "low"
    plan = engine.evaluate(_state(EmotionCategory.DISTRESSED))
    assert plan.intervention_type is InterventionType.NONE


def test_normal_intervention_blocked_within_cooldown(engine):
    engine._last_intervention_time = datetime.now() - timedelta(seconds=10)
    engine._last_urgency = "low"
    plan = engine.evaluate(_state(EmotionCategory.HAPPY))
    assert plan.intervention_type is InterventionType.NONE


def test_low_priority_after_urgent_needs_full_cooldown(engine):
    engine._last_intervention_time = datetime.now() - timedelta(seconds=10)
    engine._last_urgency = "high"
    plan = engine.evaluate(_state(EmotionCategory.HAPPY))
    assert plan.intervention_type is InterventionType.NONE


def test_normal_intervention_allowed_after_cooldown(engine):
    engine._last_intervention_time = datetime.now() - timedelta(seconds=31)
    engine._last_urgency = "low"
    plan = engine.evaluate(_state(EmotionCategory.HAPPY))
    assert plan.intervention_type is InterventionType.POSITIVE_REINFORCE


def test_none_plan_does_not_start_cooldown(engine):
    plan = engine.evaluate(_state(EmotionCategory.NEUTRAL))
    assert plan.intervention_type is InterventionType.NONE
    assert engine._last_intervention_time is None


def test_cooldown_constants(engine):
    assert engine.cooldown_seconds == 30
    assert engine.urgent_cooldown_seconds == 8


# ─── 工厂 ──────────────────────────────────────────────────────────────

def test_factory():
    assert isinstance(create_intervention_engine(), InterventionEngine)


def test_factory_with_memory(tmp_path):
    axis = MemoryAxis(db_path=str(tmp_path / "m.sqlite"))
    eng = create_intervention_engine(memory_axis=axis)
    assert isinstance(eng, InterventionEngine)
    assert eng.memory_axis is axis


# ─── 家长报告 ──────────────────────────────────────────────────────────

def test_parent_report_without_memory_axis(engine):
    report = engine.generate_parent_report()
    assert "暂无" in report.summary
    assert report.interaction_count == 0


def test_parent_report_with_memory(tmp_path):
    axis = MemoryAxis(db_path=str(tmp_path / "mem.sqlite"))
    for _ in range(3):
        axis.record(
            EmotionState(category=EmotionCategory.HAPPY, valence=0.8, arousal=0.7)
        )
    axis.record(
        EmotionState(category=EmotionCategory.DISTRESSED, valence=-0.9, arousal=1.0)
    )
    eng = InterventionEngine(memory_axis=axis)

    report = eng.generate_parent_report(days=7)
    assert report.interaction_count == 4
    assert report.period_start and report.period_end
    assert 0.0 <= report.health_score <= 100.0
    # 出现 happy → highlights 有"开心时刻"
    assert any("开心" in h for h in report.highlights)
    # 出现 distressed → concerns 非空
    assert report.concerns


def test_parent_report_markdown(tmp_path):
    axis = MemoryAxis(db_path=str(tmp_path / "mem2.sqlite"))
    axis.record(EmotionState(category=EmotionCategory.HAPPY, valence=0.8))
    eng = InterventionEngine(memory_axis=axis)

    md = eng.generate_parent_report_markdown(days=7)
    assert "# 🌟" in md
    assert "本周" in md
    assert "报告周期" in md
