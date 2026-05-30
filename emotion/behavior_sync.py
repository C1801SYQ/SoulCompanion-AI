"""
emotion/behavior_sync.py - Emotion → Behavior Mapping Engine

Maps EmotionState to BehaviorCommand for the embodied engine.
Controls speech rate, LED color, motion speed, servo behavior, and breathing.

Input:  EmotionState
Output: BehaviorCommand
"""
from __future__ import annotations

import logging
from typing import Dict

from emotion.models import (
    BehaviorAction,
    BehaviorCommand,
    EmotionCategory,
    EmotionState,
)

logger = logging.getLogger("BehaviorSync")

# ─── Emotion → Behavior Mapping Table ──────────────────────────────────
# Each emotion maps to a set of behaviors with parameters

EMOTION_BEHAVIOR_MAP: Dict[EmotionCategory, Dict] = {
    EmotionCategory.HAPPY: {
        "actions": [BehaviorAction.EAR_WIGGLE, BehaviorAction.LED_WARM, BehaviorAction.EXCITED_VOICE],
        "speech_rate": 1.2,
        "led_color": "#FFD700",       # Gold
        "led_brightness": 0.8,
        "servo_speed": 0.7,
    },
    EmotionCategory.CALM: {
        "actions": [BehaviorAction.BREATHING_LED, BehaviorAction.SOOTHING_VOICE],
        "speech_rate": 0.9,
        "led_color": "#87CEEB",       # Sky blue
        "led_brightness": 0.5,
        "servo_speed": 0.3,
    },
    EmotionCategory.NEUTRAL: {
        "actions": [BehaviorAction.BREATHING_LED],
        "speech_rate": 1.0,
        "led_color": "#4CAF50",       # Green
        "led_brightness": 0.6,
        "servo_speed": 0.5,
    },
    EmotionCategory.SURPRISED: {
        "actions": [BehaviorAction.HEAD_TILT, BehaviorAction.EAR_WIGGLE, BehaviorAction.LED_WARM],
        "speech_rate": 1.1,
        "led_color": "#FF9800",       # Orange
        "led_brightness": 0.9,
        "servo_speed": 0.8,
    },
    EmotionCategory.ANXIOUS: {
        "actions": [BehaviorAction.HEARTBEAT, BehaviorAction.BREATHING_LED, BehaviorAction.SOOTHING_VOICE, BehaviorAction.LED_COOL],
        "speech_rate": 0.7,
        "led_color": "#64B5F6",       # Soft blue
        "led_brightness": 0.4,
        "servo_speed": 0.2,
    },
    EmotionCategory.SAD: {
        "actions": [BehaviorAction.HEARTBEAT, BehaviorAction.SOOTHING_VOICE, BehaviorAction.SLOW_MOTION, BehaviorAction.LED_COOL],
        "speech_rate": 0.7,
        "led_color": "#7986CB",       # Lavender
        "led_brightness": 0.3,
        "servo_speed": 0.2,
    },
    EmotionCategory.ANGRY: {
        "actions": [BehaviorAction.STILL, BehaviorAction.LED_DIM, BehaviorAction.SOOTHING_VOICE],
        "speech_rate": 0.6,
        "led_color": "#B0BEC5",       # Cool gray
        "led_brightness": 0.2,
        "servo_speed": 0.1,
    },
    EmotionCategory.FEARFUL: {
        "actions": [BehaviorAction.HEARTBEAT, BehaviorAction.STILL, BehaviorAction.SOOTHING_VOICE, BehaviorAction.LED_DIM],
        "speech_rate": 0.6,
        "led_color": "#B39DDB",       # Soft purple
        "led_brightness": 0.2,
        "servo_speed": 0.1,
    },
    EmotionCategory.DISTRESSED: {
        "actions": [BehaviorAction.STILL, BehaviorAction.LED_DIM, BehaviorAction.SOOTHING_VOICE],
        "speech_rate": 0.5,
        "led_color": "#E0E0E0",       # Dim white
        "led_brightness": 0.1,
        "servo_speed": 0.0,
    },
}

# Attention-based overrides
LOW_ATTENTION_BEHAVIORS = {
    "actions": [BehaviorAction.HEAD_TILT, BehaviorAction.EAR_WIGGLE],
    "led_color": "#FFEB3B",           # Warm yellow to attract attention
    "led_brightness": 0.7,
}


class BehaviorSync:
    """
    Emotion-to-behavior mapping engine.

    Converts an EmotionState into a BehaviorCommand that the
    embodied engine can execute. Applies ASD-specific rules:
    - Low arousal → reduce stimuli (dim LED, slow motion)
    - High anxiety → soothing behaviors (heartbeat, calm voice)
    - Lost attention → gentle attractors (head tilt, ear wiggle)
    """

    def __init__(self):
        self._last_command = BehaviorCommand()
        logger.info("✅ [行为同步] 情绪→行为映射引擎已就绪")

    def sync(self, state: EmotionState) -> BehaviorCommand:
        """
        Generate a BehaviorCommand from the current EmotionState.

        Args:
            state: Current fused emotion state

        Returns:
            BehaviorCommand with actions and parameters
        """
        category = state.category

        # ── 1. Get base behaviors for this emotion ──
        base = EMOTION_BEHAVIOR_MAP.get(category, EMOTION_BEHAVIOR_MAP[EmotionCategory.NEUTRAL])

        actions = list(base["actions"])
        speech_rate = base["speech_rate"]
        led_color = base["led_color"]
        led_brightness = base["led_brightness"]
        servo_speed = base["servo_speed"]

        # ── 2. Apply attention-based adjustments ──
        if state.attention_level < 0.3:
            # Child is not paying attention - add gentle attractors
            for action in LOW_ATTENTION_BEHAVIORS["actions"]:
                if action not in actions:
                    actions.append(action)
            led_color = LOW_ATTENTION_BEHAVIORS["led_color"]
            led_brightness = LOW_ATTENTION_BEHAVIORS["led_brightness"]

        # ── 3. Apply arousal-based adjustments ──
        if state.arousal > 0.8:
            # High arousal: reduce stimuli
            led_brightness = max(0.1, led_brightness - 0.2)
            servo_speed = max(0.0, servo_speed - 0.2)
        elif state.arousal < 0.2:
            # Very low arousal: slightly increase engagement
            led_brightness = min(0.8, led_brightness + 0.1)

        # ── 4. Confidence-based adjustment ──
        if state.confidence < 0.4:
            # Low confidence in emotion reading: default to calming
            if BehaviorAction.SOOTHING_VOICE not in actions:
                actions.append(BehaviorAction.SOOTHING_VOICE)
            speech_rate = min(speech_rate, 0.8)

        # ── 5. Build command ──
        command = BehaviorCommand(
            actions=actions,
            speech_rate=round(speech_rate, 2),
            led_color=led_color,
            led_brightness=round(led_brightness, 2),
            servo_speed=round(servo_speed, 2),
            priority=1 if category in (
                EmotionCategory.DISTRESSED,
                EmotionCategory.FEARFUL,
            ) else 0,
            reason=self._build_reason(category, state),
        )

        self._last_command = command
        return command

    def get_last_command(self) -> BehaviorCommand:
        """Return the most recent BehaviorCommand."""
        return self._last_command

    def _build_reason(self, category: EmotionCategory, state: EmotionState) -> str:
        """Build a human-readable reason for the behavior choice."""
        parts = [f"情绪={category.value}"]

        if state.attention_level < 0.3:
            parts.append("注意力低")
        if state.arousal > 0.8:
            parts.append("高唤醒")
        if state.confidence < 0.4:
            parts.append("低置信度")

        return ", ".join(parts)


def create_behavior_sync() -> BehaviorSync:
    """Factory function to create a BehaviorSync instance."""
    return BehaviorSync()
