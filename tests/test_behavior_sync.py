"""emotion/behavior_sync.py 单元测试。

覆盖：情绪→行为映射、注意力调整、唤醒度调整、置信度兜底、优先级。
"""
from __future__ import annotations

import pytest

from emotion.behavior_sync import BehaviorSync, create_behavior_sync
from emotion.models import BehaviorAction, BehaviorCommand, EmotionCategory, EmotionState


@pytest.fixture()
def sync() -> BehaviorSync:
    return BehaviorSync()


# ─── 基础映射 ──────────────────────────────────────────────────────────

def test_happy_mapping(sync):
    cmd = sync.sync(
        EmotionState(
            category=EmotionCategory.HAPPY,
            confidence=0.8,
            arousal=0.7,
            attention_level=1.0,
        )
    )
    assert BehaviorAction.EAR_WIGGLE in cmd.actions
    assert BehaviorAction.LED_WARM in cmd.actions
    assert BehaviorAction.EXCITED_VOICE in cmd.actions
    assert cmd.led_color == "#FFD700"
    assert cmd.speech_rate == pytest.approx(1.2)
    assert cmd.priority == 0
    assert "happy" in cmd.reason


def test_neutral_mapping(sync):
    cmd = sync.sync(EmotionState(category=EmotionCategory.NEUTRAL))
    assert cmd.actions == [BehaviorAction.BREATHING_LED]
    assert cmd.led_color == "#4CAF50"
    assert cmd.priority == 0


def test_anxious_mapping_is_soothing(sync):
    cmd = sync.sync(EmotionState(category=EmotionCategory.ANXIOUS))
    assert BehaviorAction.HEARTBEAT in cmd.actions
    assert BehaviorAction.SOOTHING_VOICE in cmd.actions
    assert BehaviorAction.LED_COOL in cmd.actions
    assert cmd.led_color == "#64B5F6"
    assert cmd.priority == 0


def test_distressed_has_high_priority(sync):
    cmd = sync.sync(EmotionState(category=EmotionCategory.DISTRESSED))
    assert cmd.priority == 1
    assert BehaviorAction.STILL in cmd.actions
    assert BehaviorAction.LED_DIM in cmd.actions
    assert BehaviorAction.SOOTHING_VOICE in cmd.actions
    assert cmd.led_color == "#E0E0E0"


def test_fearful_has_high_priority(sync):
    cmd = sync.sync(EmotionState(category=EmotionCategory.FEARFUL))
    assert cmd.priority == 1


def test_returns_behavior_command(sync):
    cmd = sync.sync(EmotionState(category=EmotionCategory.CALM))
    assert isinstance(cmd, BehaviorCommand)


# ─── 注意力调整 ────────────────────────────────────────────────────────

def test_low_attention_adds_gentle_attractors(sync):
    cmd = sync.sync(
        EmotionState(category=EmotionCategory.NEUTRAL, attention_level=0.2)
    )
    assert BehaviorAction.HEAD_TILT in cmd.actions
    assert BehaviorAction.EAR_WIGGLE in cmd.actions
    assert cmd.led_color == "#FFEB3B"
    assert cmd.led_brightness == pytest.approx(0.7)
    assert "注意力低" in cmd.reason


def test_normal_attention_no_attractors(sync):
    cmd = sync.sync(
        EmotionState(category=EmotionCategory.NEUTRAL, attention_level=0.9)
    )
    assert BehaviorAction.HEAD_TILT not in cmd.actions


# ─── 唤醒度调整 ────────────────────────────────────────────────────────

def test_high_arousal_reduces_stimuli(sync):
    cmd = sync.sync(
        EmotionState(
            category=EmotionCategory.NEUTRAL,
            arousal=0.9,
            attention_level=1.0,
            confidence=0.5,
        )
    )
    # NEUTRAL 基线亮度 0.6 → 高唤醒 -0.2 = 0.4
    assert cmd.led_brightness == pytest.approx(0.4)
    # 基线伺服速度 0.5 → -0.2 = 0.3
    assert cmd.servo_speed == pytest.approx(0.3)
    assert "高唤醒" in cmd.reason


def test_very_low_arousal_increases_engagement(sync):
    cmd = sync.sync(
        EmotionState(
            category=EmotionCategory.NEUTRAL,
            arousal=0.1,
            attention_level=1.0,
            confidence=0.5,
        )
    )
    # 0.6 + 0.1 = 0.7
    assert cmd.led_brightness == pytest.approx(0.7)


# ─── 置信度兜底 ────────────────────────────────────────────────────────

def test_low_confidence_defaults_to_calming(sync):
    cmd = sync.sync(
        EmotionState(
            category=EmotionCategory.NEUTRAL,
            confidence=0.3,
            arousal=0.5,
            attention_level=1.0,
        )
    )
    assert BehaviorAction.SOOTHING_VOICE in cmd.actions
    assert cmd.speech_rate <= 0.8
    assert "低置信度" in cmd.reason


def test_high_confidence_no_calming_override(sync):
    cmd = sync.sync(
        EmotionState(
            category=EmotionCategory.HAPPY,
            confidence=0.9,
            arousal=0.7,
            attention_level=1.0,
        )
    )
    assert cmd.speech_rate == pytest.approx(1.2)


# ─── 状态缓存 / 工厂 ───────────────────────────────────────────────────

def test_get_last_command_updates(sync):
    assert isinstance(sync.get_last_command(), BehaviorCommand)
    cmd = sync.sync(EmotionState(category=EmotionCategory.HAPPY))
    assert sync.get_last_command() is cmd


def test_factory():
    assert isinstance(create_behavior_sync(), BehaviorSync)
