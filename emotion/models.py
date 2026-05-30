"""
emotion/models.py - Shared data models for the emotion system.

All emotion modules use these immutable dataclasses for data exchange.
Designed for minimal coupling and clear data flow.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional


class EmotionCategory(str, Enum):
    """Standardized emotion categories for ASD context."""
    HAPPY = "happy"
    CALM = "calm"
    ANXIOUS = "anxious"
    SAD = "sad"
    ANGRY = "angry"
    FEARFUL = "fearful"
    SURPRISED = "surprised"
    NEUTRAL = "neutral"
    DISTRESSED = "distressed"  # ASD-specific: overload/meltdown


class BehaviorAction(str, Enum):
    """Robot behavior actions mapped from emotions."""
    HEARTBEAT = "heartbeat"       # Soothing vibration pattern
    BREATHING_LED = "breathing_led"  # Slow breathing light
    EAR_WIGGLE = "ear_wiggle"     # Playful ear movement
    HEAD_TILT = "head_tilt"       # Thinking/curious tilt
    SOOTHING_VOICE = "soothing_voice"  # Calm speech pattern
    EXCITED_VOICE = "excited_voice"    # Happy speech pattern
    SLOW_MOTION = "slow_motion"   # Gentle movement
    STILL = "still"               # No movement (reduce stimuli)
    LED_WARM = "led_warm"         # Warm color LED
    LED_COOL = "led_cool"         # Cool/calming LED
    LED_DIM = "led_dim"           # Dim LED (reduce visual load)


class InterventionType(str, Enum):
    """Types of educational intervention."""
    GENTLE_REDIRECT = "gentle_redirect"    # Soft attention redirect
    EMOTION_LABEL = "emotion_label"        # Help name feelings
    BREATHING_GUIDE = "breathing_guide"    # Guide breathing exercise
    POSITIVE_REINFORCE = "positive_reinforce"  # Praise good behavior
    CALMING_ACTIVITY = "calming_activity"  # Suggest calming activity
    SOCIAL_STORY = "social_story"          # Short social narrative
    NONE = "none"                          # No intervention needed


@dataclass(frozen=True)
class EmotionState:
    """
    Immutable snapshot of the fused emotional state.
    Output of fusion_engine, consumed by all other modules.
    """
    # Primary emotion
    category: EmotionCategory = EmotionCategory.NEUTRAL
    confidence: float = 0.5           # 0.0 - 1.0
    valence: float = 0.0              # -1.0 (negative) to 1.0 (positive)
    arousal: float = 0.5              # 0.0 (calm) to 1.0 (excited)

    # Source breakdown
    vision_emotion: str = "neutral"
    speech_emotion: str = "neutral"
    environment_signal: str = "normal"

    # Inferred context
    emotional_cause: str = ""         # Why the child feels this way
    attention_level: float = 1.0      # 0.0 (lost) to 1.0 (focused)

    # Metadata
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    source_weights: Dict[str, float] = field(default_factory=lambda: {
        "vision": 0.4, "speech": 0.4, "environment": 0.2
    })


@dataclass
class BehaviorCommand:
    """
    Command for the embodied engine to execute.
    Output of behavior_sync, input to embodied_engine.
    """
    actions: List[BehaviorAction] = field(default_factory=list)
    speech_rate: float = 1.0          # 0.5 (slow) to 1.5 (fast)
    led_color: str = "#4CAF50"        # Hex color
    led_brightness: float = 0.7       # 0.0 to 1.0
    servo_speed: float = 0.5          # 0.0 (still) to 1.0 (fast)
    priority: int = 0                 # 0 = normal, 1 = high (safety)
    reason: str = ""                  # Why this behavior was chosen


@dataclass
class InterventionPlan:
    """
    Plan for educational intervention.
    Output of intervention engine.
    """
    intervention_type: InterventionType = InterventionType.NONE
    guidance_text: str = ""           # What to say to the child
    guidance_style: str = "gentle"    # gentle, playful, calm
    parent_alert: bool = False        # Should parent be notified?
    parent_note: str = ""             # Note for parent report
    duration_seconds: float = 0.0     # How long to maintain this intervention
    metadata: Dict = field(default_factory=dict)


@dataclass
class EmotionRecord:
    """Single emotion record for long-term memory storage."""
    timestamp: str = ""
    category: str = "neutral"
    valence: float = 0.0
    arousal: float = 0.5
    cause: str = ""
    context: str = ""                 # What was happening
    source_text: str = ""             # What the child said


@dataclass
class EmotionTrend:
    """Aggregated emotion trend analysis."""
    period: str = "daily"             # hourly, daily, weekly
    dominant_emotion: str = "neutral"
    average_valence: float = 0.0
    average_arousal: float = 0.5
    stability_score: float = 1.0      # 0.0 (volatile) to 1.0 (stable)
    risk_periods: List[str] = field(default_factory=list)  # Times of concern
    positive_periods: List[str] = field(default_factory=list)  # Times of joy
    total_records: int = 0


@dataclass
class ParentReport:
    """Weekly report for parents."""
    period_start: str = ""
    period_end: str = ""
    summary: str = ""
    emotion_trend: Optional[EmotionTrend] = None
    highlights: List[str] = field(default_factory=list)
    concerns: List[str] = field(default_factory=list)
    suggestions: List[str] = field(default_factory=list)
    interaction_count: int = 0
    health_score: float = 50.0        # 0-100
