"""
emotion/fusion_engine.py - Multi-modal Emotion Fusion Engine

Fuses vision, speech, and environment signals into a unified EmotionState.
Uses weighted confidence scoring with memory-informed context.

Input:  vision_state, speech_state, env_signals, memory_context
Output: EmotionState (immutable snapshot)
"""
from __future__ import annotations

import logging
import time
from typing import Dict, Optional

from emotion.models import EmotionCategory, EmotionState

logger = logging.getLogger("FusionEngine")

# ─── Emotion Mapping Tables ────────────────────────────────────────────
# Maps raw engine outputs to standardized EmotionCategory

VISION_EMOTION_MAP: Dict[str, EmotionCategory] = {
    "happy": EmotionCategory.HAPPY,
    "surprise": EmotionCategory.SURPRISED,
    "sad": EmotionCategory.SAD,
    "anxious": EmotionCategory.ANXIOUS,
    "angry": EmotionCategory.ANGRY,
    "fear": EmotionCategory.FEARFUL,
    # 现状说明（R12 评估，未改变语义）：目前把"厌恶"并入"焦虑"。
    # 严格来说 disgust（厌恶）与 anxious（焦虑）语义并不完全一致，
    # 但人脸"厌恶"表情在 ASD 儿童交互场景中常表现为回避/不适，
    # 归入"焦虑"可复用现有的安抚行为与干预路径，且避免新增触发面。
    # 若后续有独立干预策略，建议改为独立映射（如 DISGUST）并单独处理；
    # 本次仅加注释记录现状，不改变映射。
    "disgust": EmotionCategory.ANXIOUS,
    "neutral": EmotionCategory.NEUTRAL,
}

# ASD 安全规则：视觉读到"焦虑/恐惧"时优先采信（无需高置信度背书）。
# R12 修复：移除不可达的 DISTRESSED——VISION_EMOTION_MAP 永不产出 DISTRESSED，
# 该类别由环境通道 bio_anxiety（>0.8）产生，因此把它写进视觉优先集合是死分支。
ASD_VISION_PRIORITY: frozenset = frozenset({
    EmotionCategory.ANXIOUS,
    EmotionCategory.FEARFUL,
})

SPEECH_EMOTION_MAP: Dict[str, EmotionCategory] = {
    "happy": EmotionCategory.HAPPY,
    "sad": EmotionCategory.SAD,
    "anxious": EmotionCategory.ANXIOUS,
    "angry": EmotionCategory.ANGRY,
    "neutral": EmotionCategory.NEUTRAL,
}

# Valence and arousal presets per emotion category
EMOTION_VALENCE: Dict[EmotionCategory, float] = {
    EmotionCategory.HAPPY: 0.8,
    EmotionCategory.CALM: 0.3,
    EmotionCategory.SURPRISED: 0.2,
    EmotionCategory.NEUTRAL: 0.0,
    EmotionCategory.ANXIOUS: -0.4,
    EmotionCategory.SAD: -0.7,
    EmotionCategory.ANGRY: -0.6,
    EmotionCategory.FEARFUL: -0.8,
    EmotionCategory.DISTRESSED: -0.9,
}

EMOTION_AROUSAL: Dict[EmotionCategory, float] = {
    EmotionCategory.HAPPY: 0.7,
    EmotionCategory.CALM: 0.2,
    EmotionCategory.SURPRISED: 0.9,
    EmotionCategory.NEUTRAL: 0.3,
    EmotionCategory.ANXIOUS: 0.7,
    EmotionCategory.SAD: 0.3,
    EmotionCategory.ANGRY: 0.8,
    EmotionCategory.FEARFUL: 0.9,
    EmotionCategory.DISTRESSED: 1.0,
}


class FusionEngine:
    """
    Multi-modal emotion fusion engine.

    Combines signals from vision (face emotion), speech (tone emotion),
    and environment (bio sensors, context) into a single EmotionState.

    Features:
    - Weighted confidence fusion
    - Memory-informed context (recent trends bias current reading)
    - Attention level tracking
    - Emotional cause inference
    """

    def __init__(self, memory_axis=None):
        """
        Args:
            memory_axis: Optional MemoryAxis instance for trend-informed fusion.
        """
        self.memory_axis = memory_axis
        self._last_state = EmotionState()
        self._state_history: list[EmotionState] = []
        self._max_history = 50

        # Default fusion weights (adjustable at runtime)
        self.weights = {
            "vision": 0.4,
            "speech": 0.4,
            "environment": 0.2,
        }

        logger.info("✅ [融合引擎] 多模态情绪融合引擎已就绪")

    def fuse(
        self,
        vision_state: Optional[Dict] = None,
        speech_state: Optional[Dict] = None,
        env_signals: Optional[Dict] = None,
    ) -> EmotionState:
        """
        Fuse multi-modal inputs into a unified EmotionState.

        Args:
            vision_state: Output from VisionEngine.get_latest_state()
            speech_state: Output from SpeechEngine.get_latest_text()
            env_signals:  Environment/bio signals dict

        Returns:
            EmotionState: Immutable fused emotional state snapshot
        """
        vision_state = vision_state or {}
        speech_state = speech_state or {}
        env_signals = env_signals or {}

        # ── 1. Parse individual modality signals ──
        # 返回 None 表示该模态本轮"无有效信号"（不是"中性"！），
        # 后续融合会将其权重置零并重新归一化。
        v_emotion = self._parse_vision(vision_state)
        s_emotion = self._parse_speech(speech_state)
        e_emotion = self._parse_environment(env_signals)

        # ── 2. Calculate attention level ──
        attention = self._calc_attention(vision_state)

        # ── 3. Weighted fusion ──
        fused_category, confidence, effective_weights = self._weighted_fuse(
            v_emotion, s_emotion, e_emotion, attention
        )

        # ── 4. Apply memory-informed adjustment ──
        if self.memory_axis:
            fused_category, confidence = self._apply_memory_context(
                fused_category, confidence
            )

        # ── 5. Compute valence & arousal ──
        valence = EMOTION_VALENCE.get(fused_category, 0.0)
        arousal = EMOTION_AROUSAL.get(fused_category, 0.5)

        # ── 6. Infer emotional cause ──
        cause = self._infer_cause(
            fused_category, v_emotion, s_emotion, e_emotion, speech_state
        )

        # ── 7. Build immutable state ──
        state = EmotionState(
            category=fused_category,
            confidence=round(confidence, 3),
            valence=round(valence, 3),
            arousal=round(arousal, 3),
            vision_emotion=self._label(v_emotion),
            speech_emotion=self._label(s_emotion),
            environment_signal=self._label(e_emotion),
            emotional_cause=cause,
            attention_level=round(attention, 3),
            source_weights=effective_weights,
        )

        # ── 8. Update history ──
        self._last_state = state
        self._state_history.append(state)
        if len(self._state_history) > self._max_history:
            self._state_history = self._state_history[-self._max_history:]

        return state

    def get_last_state(self) -> EmotionState:
        """Return the most recent fused EmotionState."""
        return self._last_state

    def get_history(self) -> list[EmotionState]:
        """Return recent fusion history (up to 50 states)."""
        return list(self._state_history)

    # ─── Private: Parsing ─────────────────────────────────────────────

    @staticmethod
    def _label(emo: Optional[EmotionCategory]) -> str:
        """把模态结果转成可展示的字符串；None 表示本轮无有效信号。"""
        if emo is None:
            return "unknown"
        if isinstance(emo, EmotionCategory):
            return emo.value
        return str(emo)

    def _parse_vision(self, v_state: Dict) -> Optional[EmotionCategory]:
        """Parse vision engine output into EmotionCategory (None = 无有效信号)。"""
        if not v_state:
            return None
        # 明确报告"没检测到人脸"时，面部情绪读数不可信，视为缺失
        if v_state.get("face_detected") is False:
            return None
        raw = v_state.get("emotion")
        if not raw:
            return None
        return VISION_EMOTION_MAP.get(raw, EmotionCategory.NEUTRAL)

    def _parse_speech(self, s_state: Optional[Dict]) -> Optional[EmotionCategory]:
        """Parse speech engine output into EmotionCategory (None = 无人说话)。"""
        if not s_state:
            return None
        raw = s_state.get("emotion")
        if not raw:
            return None
        return SPEECH_EMOTION_MAP.get(raw, EmotionCategory.NEUTRAL)

    def _parse_environment(self, env: Optional[Dict]) -> Optional[EmotionCategory]:
        """Parse environment signals into EmotionCategory (None = 无环境信号)。

        R12 修复：白天"只有 hour"不构成中性投票。
        bridge._process_cycle() 每轮都会注入 env["hour"]，若白天 hour 也返回
        NEUTRAL，则 environment 通道会每轮投一个低权重 NEUTRAL，稀释视觉/语音
        的真实信号，使"缺失模态权重置零并归一化"对 environment 形同虚设。

        判定优先级：
        1) bio_anxiety / noise_level / hour 全为 None → 无信号（None）；
        2) 真实传感器优先：bio_anxiety > 0.8 → DISTRESSED，> 0.6 → ANXIOUS，
           noise_level > 0.8 → ANXIOUS；
        3) 只要存在 bio_anxiety 或 noise_level 读数（哪怕 0.0 这种低值，0.0 仍是
           合法读数）→ 真实的"环境平静"读数，返回 NEUTRAL（保留投票）；
        4) 只有 hour：夜间 → CALM（保留"夜间偏平静"弱先验），白天 → None（不投票）。

        注意：一律用 ``is None`` 判断缺失，避免把合法的 0.0 读数当成缺失。
        """
        if not env:
            return None

        # 分别取值；缺键与显式 None 等价，均为"无此读数"
        bio = env.get("bio_anxiety")
        noise = env.get("noise_level")
        hour = env.get("hour")

        # 三个可能的环境维度都没有 → 视为无信号
        if bio is None and noise is None and hour is None:
            return None

        # 真实传感器优先：生物焦虑读数
        if bio is not None:
            if bio > 0.8:
                return EmotionCategory.DISTRESSED
            if bio > 0.6:
                return EmotionCategory.ANXIOUS

        # 噪声读数
        if noise is not None and noise > 0.8:
            return EmotionCategory.ANXIOUS

        # 存在真实传感器读数（即便值很低，如 0.0/0.1）→ 有效的"环境平静"投票
        if bio is not None or noise is not None:
            return EmotionCategory.NEUTRAL

        # 只有 hour → 时间启发式（弱先验：夜间默认偏平静；白天不投票）
        if hour is not None and (hour >= 21 or hour <= 6):
            return EmotionCategory.CALM

        return None

    # ─── Private: Attention ───────────────────────────────────────────

    def _calc_attention(self, v_state: Dict) -> float:
        """
        Calculate attention level from vision state.
        Returns 0.0 (lost) to 1.0 (focused).

        R12 修复：视觉不可用时注意力"未知"，取中性值 0.5。
        此前 vision_state == {}（视觉引擎尚未出数据/掉线，连 face_detected 键都
        没有）会走 `not v_state.get("face_detected", False)` 分支，attention_loss_time
        取默认 0.0 后返回 1.0，把"没有视觉数据"误判成"孩子完全专注"。

        安全核对：0.5 高于所有注意力相关阈值——
        - behavior_sync 的低注意力阈值 0.3（``attention_level < 0.3``）；
        - intervention 的注意力阈值 0.3（LOW）/ 0.1（CRITICAL）；
        因此 0.5 既不惩罚也不奖励，且不会触发注意力干预。
        """
        # 视觉不可用：既没有数据，也没有 face_detected 键 → 注意力未知
        if not v_state or "face_detected" not in v_state:
            return 0.5

        # 明确检测到人脸丢失：按丢失时长线性衰减（0s 满注意力，10s 归零）
        if not v_state["face_detected"]:
            loss_time = v_state.get("attention_loss_time", 0.0)
            return max(0.0, 1.0 - (loss_time / 10.0))

        return 1.0

    # ─── Private: Fusion ─────────────────────────────────────────────

    def _weighted_fuse(
        self,
        v_emo: Optional[EmotionCategory],
        s_emo: Optional[EmotionCategory],
        e_emo: Optional[EmotionCategory],
        attention: float,
    ) -> tuple[EmotionCategory, float, Dict[str, float]]:
        """
        Weighted fusion of the modalities that actually produced a signal.

        缺失的模态（None）权重直接置零，剩余权重重新归一化，
        避免"没人说话"被当作一个真实的 neutral 投票。

        Returns:
            (category, confidence, effective_weights)
        """
        modalities = [
            (v_emo, "vision"),
            (s_emo, "speech"),
            (e_emo, "environment"),
        ]

        # 只保留本轮有信号的模态
        present = [
            (emo, self.weights.get(key, 0.0))
            for emo, key in modalities
            if emo is not None
        ]

        total_weight = sum(w for _, w in present)
        if not present or total_weight <= 0:
            # 没有任何模态有信号 → 只能给出中性的低置信度猜测
            return EmotionCategory.NEUTRAL, 0.3, {}

        # 各情绪类别的加权得分
        scores: Dict[EmotionCategory, float] = {}
        for emo, w in present:
            scores[emo] = scores.get(emo, 0.0) + w

        # 得分最高者胜出（并列时保持插入顺序，即视觉优先）
        dominant = max(scores, key=lambda k: scores[k])
        raw_confidence = scores[dominant] / total_weight

        # 一致度加成：多个模态指向同一情绪时更可信
        agreement_count = sum(1 for emo, _ in present if emo == dominant)
        agreement_bonus = (agreement_count - 1) * 0.15

        # 证据数量校正：仅 1 个模态时天然证据不足
        evidence_factor = {1: 0.75, 2: 0.90}.get(len(present), 1.0)

        # 注意力惩罚：孩子没在看，读数可信度下降
        attention_penalty = (1.0 - attention) * 0.2

        confidence = raw_confidence * evidence_factor + agreement_bonus - attention_penalty
        confidence = min(1.0, max(0.0, confidence))

        # 特殊 ASD 安全规则：视觉读到焦虑/恐惧时优先采信
        # （DISTRESSED 由环境通道 bio_anxiety 产生，不来自视觉，故不在此列）
        if v_emo in ASD_VISION_PRIORITY:
            if confidence < 0.6:
                dominant = v_emo
                confidence = max(confidence, 0.6)

        effective_weights = {
            key: self.weights.get(key, 0.0) / total_weight
            for emo, key in modalities
            if emo is not None
        }

        return dominant, confidence, effective_weights

    # ─── Private: Memory Context ─────────────────────────────────────

    def _apply_memory_context(
        self, category: EmotionCategory, confidence: float
    ) -> tuple[EmotionCategory, float]:
        """
        Adjust fused result based on memory trends.

        If recent trend is negative and current reading is ambiguous (neutral),
        bias toward the trend emotion (momentum effect).
        """
        try:
            trend = self.memory_axis.get_recent_trend()
            if trend is None:
                return category, confidence

            # If current is neutral but recent trend is negative, slight bias
            if category == EmotionCategory.NEUTRAL and trend < -2:
                # Don't override, but lower confidence in "neutral"
                confidence = max(0.3, confidence - 0.1)

            # If current is positive but trend is very negative, flag inconsistency
            if category == EmotionCategory.HAPPY and trend < -4:
                confidence = max(0.4, confidence - 0.15)

        except Exception as e:
            logger.warning(f"Memory context adjustment failed: {e}")

        return category, confidence

    # ─── Private: Cause Inference ─────────────────────────────────────

    def _infer_cause(
        self,
        fused: EmotionCategory,
        v_emo: EmotionCategory,
        s_emo: EmotionCategory,
        e_emo: EmotionCategory,
        speech_state: Dict,
    ) -> str:
        """
        Infer a simple emotional cause from available signals.
        Returns a human-readable cause string.
        """
        if fused == EmotionCategory.NEUTRAL:
            return ""

        causes = []

        # Vision-based cause
        if v_emo == fused:
            causes.append("面部表情显示")

        # Speech-based cause
        text = speech_state.get("text", "")
        if s_emo == fused and text:
            causes.append("语音语调分析")

        # Environment-based cause
        if e_emo in (EmotionCategory.ANXIOUS, EmotionCategory.DISTRESSED):
            causes.append("环境压力信号")

        # Attention-based cause
        if fused in (EmotionCategory.ANXIOUS, EmotionCategory.SAD):
            causes.append("可能需要关注")

        if not causes:
            return "多模态信号综合判断"

        return " + ".join(causes[:2])  # Keep it concise


def create_fusion_engine(memory_axis=None) -> FusionEngine:
    """Factory function to create a FusionEngine instance."""
    return FusionEngine(memory_axis=memory_axis)
