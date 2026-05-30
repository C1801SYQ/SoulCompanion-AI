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
    "disgust": EmotionCategory.ANXIOUS,   # Map disgust → anxious for ASD
    "neutral": EmotionCategory.NEUTRAL,
}

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
        v_emotion = self._parse_vision(vision_state)
        s_emotion = self._parse_speech(speech_state)
        e_emotion = self._parse_environment(env_signals)

        # ── 2. Calculate attention level ──
        attention = self._calc_attention(vision_state)

        # ── 3. Weighted fusion ──
        fused_category, confidence = self._weighted_fuse(
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
            vision_emotion=v_emotion.value if isinstance(v_emotion, EmotionCategory) else str(v_emotion),
            speech_emotion=s_emotion.value if isinstance(s_emotion, EmotionCategory) else str(s_emotion),
            environment_signal=e_emotion.value if isinstance(e_emotion, EmotionCategory) else str(e_emotion),
            emotional_cause=cause,
            attention_level=round(attention, 3),
            source_weights=self.weights.copy(),
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

    def _parse_vision(self, v_state: Dict) -> EmotionCategory:
        """Parse vision engine output into EmotionCategory."""
        raw = v_state.get("emotion", "neutral")
        return VISION_EMOTION_MAP.get(raw, EmotionCategory.NEUTRAL)

    def _parse_speech(self, s_state: Dict) -> EmotionCategory:
        """Parse speech engine output into EmotionCategory."""
        raw = s_state.get("emotion", "neutral")
        return SPEECH_EMOTION_MAP.get(raw, EmotionCategory.NEUTRAL)

    def _parse_environment(self, env: Dict) -> EmotionCategory:
        """Parse environment signals into EmotionCategory."""
        # Bio anxiety level
        anxiety = env.get("bio_anxiety", 0.0)
        if anxiety > 0.8:
            return EmotionCategory.DISTRESSED
        if anxiety > 0.6:
            return EmotionCategory.ANXIOUS

        # Noise level
        noise = env.get("noise_level", 0.0)
        if noise > 0.8:
            return EmotionCategory.ANXIOUS

        # Time-of-day heuristics
        hour = env.get("hour", 12)
        if hour >= 21 or hour <= 6:
            return EmotionCategory.CALM

        return EmotionCategory.NEUTRAL

    # ─── Private: Attention ───────────────────────────────────────────

    def _calc_attention(self, v_state: Dict) -> float:
        """
        Calculate attention level from vision state.
        Returns 0.0 (lost) to 1.0 (focused).
        """
        if not v_state.get("face_detected", False):
            loss_time = v_state.get("attention_loss_time", 0.0)
            # Decay: full attention at 0s, lost at 10s
            return max(0.0, 1.0 - (loss_time / 10.0))
        return 1.0

    # ─── Private: Fusion ─────────────────────────────────────────────

    def _weighted_fuse(
        self,
        v_emo: EmotionCategory,
        s_emo: EmotionCategory,
        e_emo: EmotionCategory,
        attention: float,
    ) -> tuple[EmotionCategory, float]:
        """
        Weighted fusion of three modality emotions.

        Returns (category, confidence).
        """
        # Score each category across modalities
        scores: Dict[EmotionCategory, float] = {}
        total_weight = 0.0

        for emo, weight_key in [
            (v_emo, "vision"),
            (s_emo, "speech"),
            (e_emo, "environment"),
        ]:
            w = self.weights[weight_key]
            scores[emo] = scores.get(emo, 0.0) + w
            total_weight += w

        # Find the dominant emotion
        if not scores:
            return EmotionCategory.NEUTRAL, 0.5

        dominant = max(scores, key=scores.get)  # type: ignore[arg-type]
        raw_confidence = scores[dominant] / total_weight if total_weight > 0 else 0.5

        # Agreement bonus: if multiple modalities agree, boost confidence
        agreement_count = sum(
            1 for e in [v_emo, s_emo, e_emo] if e == dominant
        )
        agreement_bonus = (agreement_count - 1) * 0.15  # +0.15 per agreeing modality

        # Attention penalty: low attention reduces confidence
        attention_penalty = (1.0 - attention) * 0.2

        confidence = min(1.0, max(0.0, raw_confidence + agreement_bonus - attention_penalty))

        # Special ASD rule: if vision says anxious/distressed, trust it more
        if v_emo in (EmotionCategory.ANXIOUS, EmotionCategory.DISTRESSED, EmotionCategory.FEARFUL):
            if confidence < 0.6:
                dominant = v_emo
                confidence = max(confidence, 0.6)

        return dominant, confidence

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
            causes.append(f"语音语调分析")

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
