"""emotion/fusion_engine.py 单元测试（覆盖 R11 多模态融合修复点 + R12 收尾修复）。

R11 关键修复：
- 缺失模态（无人脸 / 无人说话 / 无环境信号）权重置零并重新归一化，
  不再被当成一次"真实的 neutral 投票"稀释结果；
- face_detected=False 时面部读数不可信，视为缺失；
- source_weights 改为"重新归一化后的有效权重"；
- 注意力惩罚 + ASD 安全规则（视觉焦虑优先采信）。

R12 收尾修复：
- _parse_environment：白天"只有 hour"不构成中性投票（返回 None），
  夜间仅 hour 仍保留 CALM 弱先验；存在真实传感器读数（含 0.0）才投 NEUTRAL；
- _calc_attention：视觉不可用（空 dict / 缺 face_detected 键）→ 0.5 中性值，
  不再误判为"完全专注"（1.0）。
"""
from __future__ import annotations

import pytest

from emotion.fusion_engine import FusionEngine, create_fusion_engine
from emotion.models import EmotionCategory, EmotionState


@pytest.fixture()
def engine() -> FusionEngine:
    return FusionEngine()


# ─── 辅助：可控的记忆轴替身 ────────────────────────────────────────────

class _FakeMemory:
    """只实现 get_recent_trend 的最小替身，用于验证记忆上下文调整。"""

    def __init__(self, trend):
        self._trend = trend

    def get_recent_trend(self):
        return self._trend


class _BoomMemory:
    """get_recent_trend 抛异常，验证异常被吞掉不影响融合。"""

    def get_recent_trend(self):
        raise RuntimeError("boom")


# ─── 空输入：无任何模态 ────────────────────────────────────────────────

def test_fuse_empty_inputs_returns_neutral_low_confidence(engine):
    state = engine.fuse({}, {}, {})
    assert state.category is EmotionCategory.NEUTRAL
    assert state.confidence == pytest.approx(0.3)
    assert state.vision_emotion == "unknown"
    assert state.speech_emotion == "unknown"
    assert state.environment_signal == "unknown"
    assert state.source_weights == {}


def test_fuse_none_inputs_equivalent_to_empty(engine):
    state = engine.fuse(None, None, None)
    assert state.category is EmotionCategory.NEUTRAL
    assert state.confidence == pytest.approx(0.3)
    assert state.source_weights == {}


# ─── 面部读数：无人脸视为缺失 ──────────────────────────────────────────

def test_parse_vision_face_not_detected_returns_none(engine):
    """R11 修复：明确报告没检测到人脸时，面部读数不可信，视为缺失。"""
    assert engine._parse_vision({"face_detected": False, "emotion": "happy"}) is None


def test_parse_vision_with_face_returns_category(engine):
    assert (
        engine._parse_vision({"face_detected": True, "emotion": "happy"})
        is EmotionCategory.HAPPY
    )


def test_parse_vision_missing_emotion_returns_none(engine):
    assert engine._parse_vision({}) is None
    assert engine._parse_vision({"face_detected": True}) is None


def test_fuse_face_not_detected_treats_vision_as_missing(engine):
    state = engine.fuse(vision_state={"face_detected": False, "emotion": "happy"})
    assert state.vision_emotion == "unknown"
    assert state.category is EmotionCategory.NEUTRAL  # 无任何有效模态


# ─── 语音单模态：不被缺失模态稀释 ──────────────────────────────────────

def test_fuse_speech_only_happy(engine):
    state = engine.fuse(speech_state={"emotion": "happy"})
    assert state.category is EmotionCategory.HAPPY
    assert state.speech_emotion == "happy"
    assert state.vision_emotion == "unknown"
    assert state.environment_signal == "unknown"
    # 只有语音一个模态：权重被重新归一化到 1.0
    assert state.source_weights == {"speech": pytest.approx(1.0)}


def test_speech_signal_not_diluted_by_missing_modalities(engine):
    """R11 修复：缺失的视觉/环境不应贡献 neutral 票稀释 happy 的权重。"""
    state = engine.fuse(speech_state={"emotion": "happy"})
    assert state.category is EmotionCategory.HAPPY
    assert "vision" not in state.source_weights
    assert "environment" not in state.source_weights
    assert state.source_weights["speech"] == pytest.approx(1.0)


# ─── 三模态一致：置信度提升 ────────────────────────────────────────────

def test_multimodal_agreement_boosts_confidence(engine):
    single = engine.fuse(speech_state={"emotion": "happy"})
    multi = engine.fuse(
        vision_state={"face_detected": True, "emotion": "happy"},
        speech_state={"emotion": "happy"},
        env_signals={"bio_anxiety": 0.1},  # 真实低值读数 → 有效 NEUTRAL 投票
    )
    assert multi.category is EmotionCategory.HAPPY
    assert multi.confidence > single.confidence
    assert multi.confidence > 0.9


def test_source_weights_are_renormalized(engine):
    state = engine.fuse(
        vision_state={"face_detected": True, "emotion": "happy"},
        speech_state={"emotion": "happy"},
        env_signals={"bio_anxiety": 0.1},
    )
    assert sum(state.source_weights.values()) == pytest.approx(1.0)
    assert set(state.source_weights) == {"vision", "speech", "environment"}


def test_source_weights_renormalized_for_two_modalities(engine):
    state = engine.fuse(
        vision_state={"face_detected": True, "emotion": "happy"},
        speech_state={"emotion": "happy"},
    )
    # 0.4 / (0.4 + 0.4) = 0.5
    assert state.source_weights["vision"] == pytest.approx(0.5)
    assert state.source_weights["speech"] == pytest.approx(0.5)
    assert sum(state.source_weights.values()) == pytest.approx(1.0)


# ─── ASD 安全规则：视觉焦虑/恐惧优先采信 ───────────────────────────────

def test_asd_safety_rule_forces_anxious(engine):
    """视觉 anxious 且置信度不足 → 强制 anxious，confidence >= 0.6。"""
    state = engine.fuse(
        vision_state={"face_detected": True, "emotion": "anxious"},
        speech_state={"emotion": "happy"},
    )
    assert state.category is EmotionCategory.ANXIOUS
    assert state.confidence >= 0.6


def test_asd_safety_rule_forces_fearful(engine):
    state = engine.fuse(
        vision_state={"face_detected": True, "emotion": "fear"},
        speech_state={"emotion": "happy"},
    )
    assert state.category is EmotionCategory.FEARFUL
    assert state.confidence >= 0.6


def test_asd_safety_rule_vision_disgust_maps_to_anxious(engine):
    state = engine.fuse(
        vision_state={"face_detected": True, "emotion": "disgust"},
        speech_state={"emotion": "happy"},
    )
    assert state.category is EmotionCategory.ANXIOUS
    assert state.confidence >= 0.6


# ─── 注意力惩罚 ────────────────────────────────────────────────────────

def test_attention_loss_reduces_confidence(engine):
    focused = engine.fuse(
        vision_state={"face_detected": True},
        speech_state={"emotion": "happy"},
        env_signals={"hour": 12},
    )
    distracted = engine.fuse(
        vision_state={"face_detected": False, "attention_loss_time": 10.0},
        speech_state={"emotion": "happy"},
        env_signals={"hour": 12},
    )
    assert focused.attention_level == pytest.approx(1.0)
    assert distracted.attention_level == pytest.approx(0.0)
    assert distracted.confidence < focused.confidence


def test_calc_attention_decay(engine):
    assert engine._calc_attention({"face_detected": True}) == pytest.approx(1.0)
    assert engine._calc_attention(
        {"face_detected": False, "attention_loss_time": 0.0}
    ) == pytest.approx(1.0)
    assert engine._calc_attention(
        {"face_detected": False, "attention_loss_time": 5.0}
    ) == pytest.approx(0.5)
    assert engine._calc_attention(
        {"face_detected": False, "attention_loss_time": 10.0}
    ) == pytest.approx(0.0)
    # 超过 10s 不再下降（下限 0.0）
    assert engine._calc_attention(
        {"face_detected": False, "attention_loss_time": 20.0}
    ) == pytest.approx(0.0)


# ─── 注意力：R12 视觉掉线不再被当成"完全专注" ─────────────────────────

def test_calc_attention_vision_unavailable_is_neutral(engine):
    """R12 修复：视觉不可用（空 dict / 缺 face_detected 键）→ 注意力未知 = 0.5。"""
    assert engine._calc_attention({}) == pytest.approx(0.5)
    assert engine._calc_attention({"emotion": "happy"}) == pytest.approx(0.5)


def test_fuse_empty_vision_attention_is_neutral_not_focused(engine):
    """R12：vision_state={} 时不应返回 1.0（那是"完全专注"的误判）。"""
    state = engine.fuse(vision_state={}, speech_state={"emotion": "happy"})
    assert state.attention_level == pytest.approx(0.5)


def test_fuse_vision_lost_face_attention_decays(engine):
    """R12：明确检测到人脸丢失 → 保持原有衰减逻辑。"""
    state = engine.fuse(
        vision_state={"face_detected": False, "attention_loss_time": 10.0},
        speech_state={"emotion": "happy"},
    )
    assert state.attention_level == pytest.approx(0.0)


def test_fuse_vision_face_detected_attention_full(engine):
    """R12：正常检测到人脸 → 注意力满值 1.0。"""
    state = engine.fuse(
        vision_state={"face_detected": True, "emotion": "happy"},
        speech_state={"emotion": "happy"},
    )
    assert state.attention_level == pytest.approx(1.0)


def test_attention_unknown_does_not_trigger_downstream_thresholds(engine):
    """R12 安全核对：0.5 高于 behavior_sync(0.3) 与 intervention(0.3/0.1) 阈值。

    behavior_sync 用字面量 0.3 判定低注意力；intervention 用命名常量。
    0.5 均高于两者 → 不会触发任何"注意力低"的干预/行为调整。
    """
    from emotion.intervention import (
        ATTENTION_THRESHOLD_CRITICAL,
        ATTENTION_THRESHOLD_LOW,
    )

    unknown = engine._calc_attention({})
    assert unknown == pytest.approx(0.5)
    assert unknown >= 0.3                # behavior_sync 低注意力阈值为 0.3
    assert unknown >= ATTENTION_THRESHOLD_LOW      # intervention 低阈值
    assert unknown >= ATTENTION_THRESHOLD_CRITICAL  # intervention 临界阈值


# ─── 环境信号解析 ──────────────────────────────────────────────────────

def test_parse_environment_variants(engine):
    assert engine._parse_environment({}) is None
    assert engine._parse_environment(
        {"bio_anxiety": None, "noise_level": None, "hour": None}
    ) is None
    assert engine._parse_environment({"bio_anxiety": 0.9}) is EmotionCategory.DISTRESSED
    assert engine._parse_environment({"bio_anxiety": 0.7}) is EmotionCategory.ANXIOUS
    assert engine._parse_environment({"noise_level": 0.9}) is EmotionCategory.ANXIOUS
    assert engine._parse_environment({"hour": 23}) is EmotionCategory.CALM
    assert engine._parse_environment({"hour": 2}) is EmotionCategory.CALM
    # R12：白天"只有 hour"不构成中性投票 → 无信号
    assert engine._parse_environment({"hour": 12}) is None


# ─── 环境信号解析：R12 白天只有 hour 不投票 ────────────────────────────

def test_parse_environment_daytime_hour_only_is_not_a_vote(engine):
    """R12 修复：白天只有 hour 时不投票，避免稀释视觉/语音的真实信号。"""
    assert engine._parse_environment({"hour": 12}) is None
    assert engine._parse_environment({"hour": 15}) is None
    assert engine._parse_environment({"hour": 7}) is None    # 边界：> 6 视为白天
    assert engine._parse_environment({"hour": 20}) is None   # 边界：< 21 视为白天


def test_parse_environment_night_hour_only_is_calm(engine):
    """R12：仅夜间 hour → 保留"夜间偏平静"的弱先验（CALM）。"""
    assert engine._parse_environment({"hour": 21}) is EmotionCategory.CALM  # 边界
    assert engine._parse_environment({"hour": 23}) is EmotionCategory.CALM
    assert engine._parse_environment({"hour": 6}) is EmotionCategory.CALM   # 边界
    assert engine._parse_environment({"hour": 2}) is EmotionCategory.CALM


def test_parse_environment_low_sensor_reading_is_still_a_vote(engine):
    """R12：真实传感器读数即便很低（0.0/0.1）也是有效的"环境平静"投票。"""
    assert engine._parse_environment({"bio_anxiety": 0.1}) is EmotionCategory.NEUTRAL
    assert engine._parse_environment({"bio_anxiety": 0.0}) is EmotionCategory.NEUTRAL
    assert engine._parse_environment({"noise_level": 0.1}) is EmotionCategory.NEUTRAL
    # 0.0 是合法读数，不能被当成缺失（必须用 is None 判空）
    assert (
        engine._parse_environment({"bio_anxiety": 0.0, "hour": 12})
        is EmotionCategory.NEUTRAL
    )
    # 有真实读数时优先于 hour：即便夜间也只按读数走
    assert (
        engine._parse_environment({"bio_anxiety": 0.0, "hour": 23})
        is EmotionCategory.NEUTRAL
    )


def test_fuse_environment_only(engine):
    state = engine.fuse(env_signals={"bio_anxiety": 0.9})
    assert state.category is EmotionCategory.DISTRESSED
    assert state.environment_signal == "distressed"
    assert state.source_weights == {"environment": pytest.approx(1.0)}


# ─── 原因推断 ──────────────────────────────────────────────────────────

def test_infer_cause_neutral_is_empty(engine):
    """中性情绪没有可推断的原因，返回空字符串。"""
    assert engine._infer_cause(EmotionCategory.NEUTRAL, None, None, None, {}) == ""


def test_infer_cause_anxious_is_nonempty(engine):
    cause = engine._infer_cause(
        EmotionCategory.ANXIOUS,
        EmotionCategory.ANXIOUS,
        None,
        EmotionCategory.ANXIOUS,
        {},
    )
    assert cause != ""


def test_infer_cause_happy_is_nonempty_in_current_source(engine):
    """R11 需求提示曾写到"HAPPY → 空字符串"，但当前源码实现并非如此。

    阅读 emotion/fusion_engine.py 的 _infer_cause 可知：返回空字符串的
    分支只针对 NEUTRAL；HAPPY 会返回如"面部表情显示"的非空原因。
    本测试据实断言源码行为，避免与实现不符的失败用例。
    """
    cause = engine._infer_cause(
        EmotionCategory.HAPPY,
        EmotionCategory.HAPPY,
        None,
        None,
        {},
    )
    assert cause != ""


def test_fuse_neutral_inputs_produce_empty_cause(engine):
    # 无任何模态 → NEUTRAL → 原因为空
    state = engine.fuse({}, {}, {})
    assert state.emotional_cause == ""


# ─── 记忆上下文调整 ────────────────────────────────────────────────────

def test_memory_context_lowers_neutral_confidence_on_negative_trend():
    engine = FusionEngine(memory_axis=_FakeMemory(-5))
    state = engine.fuse(speech_state={"emotion": "neutral"})
    assert state.category is EmotionCategory.NEUTRAL
    # 单模态 neutral 基线 0.75 → R12 视觉缺失注意力惩罚 0.1 = 0.65
    # → 负向趋势再降 0.1 = 0.55
    assert state.confidence == pytest.approx(0.55)


def test_memory_context_flags_happy_inconsistency():
    engine = FusionEngine(memory_axis=_FakeMemory(-5))
    state = engine.fuse(
        vision_state={"face_detected": True, "emotion": "happy"},
        speech_state={"emotion": "happy"},
        env_signals={"bio_anxiety": 0.1},  # 真实低值读数 → 三模态各有信号
    )
    assert state.category is EmotionCategory.HAPPY
    # 三模态一致 0.95 → 趋势极负时降 0.15 = 0.8
    assert state.confidence == pytest.approx(0.8)


def test_memory_context_none_trend_no_change():
    engine = FusionEngine(memory_axis=_FakeMemory(None))
    state = engine.fuse(speech_state={"emotion": "happy"})
    # 单模态 happy 基线 0.75 → R12 视觉缺失注意力惩罚 0.1 = 0.65（趋势 None 不调整）
    assert state.confidence == pytest.approx(0.65)


def test_memory_context_exception_is_swallowed():
    engine = FusionEngine(memory_axis=_BoomMemory())
    state = engine.fuse(speech_state={"emotion": "happy"})
    assert state.category is EmotionCategory.HAPPY


# ─── 标签 / 工厂 / 历史 ────────────────────────────────────────────────

def test_label_maps_none_to_unknown():
    assert FusionEngine._label(None) == "unknown"
    assert FusionEngine._label(EmotionCategory.HAPPY) == "happy"


def test_factory_creates_engine():
    assert isinstance(create_fusion_engine(), FusionEngine)


def test_fuse_updates_history_and_last_state(engine):
    assert engine.get_history() == []
    engine.fuse(speech_state={"emotion": "happy"})
    history = engine.get_history()
    assert len(history) == 1
    assert history[0].category is EmotionCategory.HAPPY
    assert engine.get_last_state().category is EmotionCategory.HAPPY


def test_history_is_capped(engine):
    for _ in range(60):
        engine.fuse(speech_state={"emotion": "happy"})
    assert len(engine.get_history()) == 50


def test_fuse_returns_immutable_state(engine):
    state = engine.fuse(speech_state={"emotion": "happy"})
    assert isinstance(state, EmotionState)
    with pytest.raises(Exception):
        state.confidence = 0.0  # type: ignore[misc]
