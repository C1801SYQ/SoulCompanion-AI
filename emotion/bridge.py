"""
emotion/bridge.py - Non-invasive Integration Bridge

Connects the emotion system to the existing robot loop WITHOUT modifying main.py.
Runs as a background thread, reads from VisionEngine/SpeechEngine via injected
getter functions, and processes through the full emotion pipeline.

Architecture:
    main.py (unchanged)
        │
        ├── vision.get_latest_state() ──┐
        │                                │
        └── speech.get_latest_text() ───┤
                                         ▼
                              ┌──────────────────┐
                              │   EmotionBridge   │ (background thread)
                              │                   │
                              │  fusion_engine    │
                              │  memory_axis      │
                              │  behavior_sync    │
                              │  embodied_engine  │
                              │  intervention     │
                              └────────┬──────────┘
                                       │
                                       ▼
                              Web Dashboard reads state

Usage:
    bridge = EmotionBridge(
        get_vision_state=robot.vision.get_latest_state,
        get_speech_state=robot.speech.get_latest_text,
    )
    bridge.start()  # Runs in background thread

    # Web dashboard reads state:
    state = bridge.get_snapshot()
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Dict, List, Optional

from emotion.behavior_sync import BehaviorSync
from emotion.embodied_engine import EmbodiedEngine
from emotion.fusion_engine import FusionEngine
from emotion.intervention import InterventionEngine, InterventionPlan
from emotion.memory_axis import MemoryAxis
from emotion.models import (
    BehaviorCommand,
    EmotionCategory,
    EmotionState,
    InterventionType,
)

logger = logging.getLogger("EmotionBridge")


@dataclass(frozen=True)
class EmotionSnapshot:
    """
    Immutable snapshot of the entire emotion system state.
    Thread-safe read for web dashboard and other consumers.
    """
    # Emotion state
    emotion: EmotionState = field(default_factory=EmotionState)

    # Behavior
    behavior: BehaviorCommand = field(default_factory=BehaviorCommand)

    # Intervention
    intervention_type: str = "none"
    guidance_text: str = ""
    guidance_style: str = "gentle"
    parent_alert: bool = False

    # Risk
    risk_triggers: List[str] = field(default_factory=list)
    has_risk: bool = False

    # System
    is_running: bool = False
    cycle_count: int = 0
    last_update: str = ""

    # Attention
    attention_level: float = 1.0


# Type aliases for getter functions
VisionGetter = Callable[[], Dict]
SpeechGetter = Callable[[], Optional[Dict]]


class EmotionBridge:
    """
    Non-invasive integration bridge between main.py and the emotion system.

    Reads sensor state from existing engines via injected getter functions,
    processes through the full emotion pipeline, and exposes state for
    the web dashboard.

    Does NOT modify main.py or any existing module.
    """

    def __init__(
        self,
        get_vision_state: VisionGetter,
        get_speech_state: SpeechGetter,
        env_signals: Optional[Dict] = None,
        hardware_available: bool = False,
        db_path: Optional[str] = None,
        cycle_interval: float = 0.5,
    ):
        """
        Args:
            get_vision_state: Callable that returns VisionEngine state dict
            get_speech_state: Callable that returns SpeechEngine state dict
            env_signals: Optional static environment signals
            hardware_available: Whether physical hardware is connected
            db_path: SQLite database path (defaults to config.DATABASE_PATH)
            cycle_interval: Seconds between processing cycles
        """
        self._get_vision = get_vision_state
        self._get_speech = get_speech_state
        self._env_signals = env_signals or {}
        self._cycle_interval = cycle_interval

        # ── Initialize emotion modules ──
        self._memory = MemoryAxis(db_path=db_path)
        self._fusion = FusionEngine(memory_axis=self._memory)
        self._behavior = BehaviorSync()
        self._embodied = EmbodiedEngine(hardware_available=hardware_available)
        self._intervention = InterventionEngine(memory_axis=self._memory)

        # ── State ──
        self._snapshot = EmotionSnapshot()
        self._lock = threading.Lock()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._cycle_count = 0

        # ── Callbacks ──
        self._on_intervention: Optional[Callable[[InterventionPlan], None]] = None
        self._on_behavior: Optional[Callable[[BehaviorCommand], None]] = None

        logger.info("✅ [桥接器] 情绪系统桥接器已初始化")

    def set_callbacks(
        self,
        on_intervention: Optional[Callable[[InterventionPlan], None]] = None,
        on_behavior: Optional[Callable[[BehaviorCommand], None]] = None,
    ):
        """
        Set callback functions for intervention and behavior events.

        Args:
            on_intervention: Called when an intervention is triggered
            on_behavior: Called when a behavior command is generated
        """
        self._on_intervention = on_intervention
        self._on_behavior = on_behavior

    def start(self) -> None:
        """Start the emotion bridge background thread."""
        if self._running:
            logger.warning("⚠️ [桥接器] 已在运行中")
            return

        self._running = True
        self._thread = threading.Thread(
            target=self._run_loop,
            daemon=True,
            name="EmotionBridge",
        )
        self._thread.start()
        logger.info("🚀 [桥接器] 后台情绪处理循环已启动")

    def stop(self) -> None:
        """Stop the emotion bridge."""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5.0)
        self._embodied.stop()
        logger.info("⚙️ [桥接器] 已停止")

    def get_snapshot(self) -> EmotionSnapshot:
        """Get the current emotion system snapshot (thread-safe)."""
        with self._lock:
            return self._snapshot

    def get_memory(self) -> MemoryAxis:
        """Get the memory axis instance (for web API queries)."""
        return self._memory

    def get_fusion_engine(self) -> FusionEngine:
        """Get the fusion engine instance."""
        return self._fusion

    def get_intervention_engine(self) -> InterventionEngine:
        """Get the intervention engine instance."""
        return self._intervention

    def get_behavior_sync(self) -> BehaviorSync:
        """Get the behavior sync instance."""
        return self._behavior

    def get_embodied_engine(self) -> EmbodiedEngine:
        """Get the embodied engine instance."""
        return self._embodied

    @property
    def is_running(self) -> bool:
        """Whether the bridge is currently running."""
        return self._running

    # ─── Main Loop ───────────────────────────────────────────────────

    def _run_loop(self) -> None:
        """Background processing loop."""
        logger.info("🔄 [桥接器] 情绪处理循环开始")

        while self._running:
            try:
                self._process_cycle()
            except Exception as e:
                logger.error(f"❌ [桥接器] 处理周期异常: {e}", exc_info=True)

            time.sleep(self._cycle_interval)

        logger.info("🔄 [桥接器] 情绪处理循环结束")

    def _process_cycle(self) -> None:
        """Single processing cycle: read → fuse → act → record."""
        self._cycle_count += 1

        # ── 1. Read sensor state ──
        vision_state = self._get_vision()
        speech_state = self._get_speech()

        # Merge environment signals with dynamic data
        env = dict(self._env_signals)
        env["hour"] = datetime.now().hour

        # ── 2. Fuse emotions ──
        emotion_state = self._fusion.fuse(
            vision_state=vision_state,
            speech_state=speech_state,
            env_signals=env,
        )

        # ── 3. Record to memory ──
        context = speech_state.get("text", "") if speech_state else ""
        self._memory.record(emotion_state, context=context, source_text=context)

        # ── 4. Generate behavior command ──
        behavior_cmd = self._behavior.sync(emotion_state)

        # ── 5. Execute behavior ──
        self._embodied.execute(behavior_cmd)

        # ── 6. Evaluate intervention ──
        intervention = self._intervention.evaluate(emotion_state)

        # ── 7. Check risk triggers (every 10 cycles to avoid DB spam) ──
        risk_triggers: List[str] = []
        if self._cycle_count % 10 == 0:
            risk_triggers = self._memory.check_risk_triggers(window_minutes=30)

        # ── 8. Fire callbacks ──
        if intervention.intervention_type != InterventionType.NONE and self._on_intervention:
            try:
                self._on_intervention(intervention)
            except Exception as e:
                logger.error(f"❌ [桥接器] 干预回调异常: {e}")

        if self._on_behavior:
            try:
                self._on_behavior(behavior_cmd)
            except Exception as e:
                logger.error(f"❌ [桥接器] 行为回调异常: {e}")

        # ── 9. Update snapshot ──
        snapshot = EmotionSnapshot(
            emotion=emotion_state,
            behavior=behavior_cmd,
            intervention_type=intervention.intervention_type.value
                if hasattr(intervention.intervention_type, 'value')
                else str(intervention.intervention_type),
            guidance_text=intervention.guidance_text,
            guidance_style=intervention.guidance_style,
            parent_alert=intervention.parent_alert,
            risk_triggers=risk_triggers,
            has_risk=len(risk_triggers) > 0,
            is_running=self._running,
            cycle_count=self._cycle_count,
            last_update=datetime.now().isoformat(),
            attention_level=emotion_state.attention_level,
        )

        with self._lock:
            self._snapshot = snapshot


def create_bridge(
    get_vision_state: VisionGetter,
    get_speech_state: SpeechGetter,
    **kwargs,
) -> EmotionBridge:
    """
    Factory function to create an EmotionBridge instance.

    Args:
        get_vision_state: Callable returning vision engine state
        get_speech_state: Callable returning speech engine state
        **kwargs: Additional arguments passed to EmotionBridge

    Returns:
        Configured EmotionBridge instance
    """
    return EmotionBridge(
        get_vision_state=get_vision_state,
        get_speech_state=get_speech_state,
        **kwargs,
    )
