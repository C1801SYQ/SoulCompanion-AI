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
        └── speech.peek_latest_text() ──┤  (非破坏性读取, 推荐)
        └── speech.get_latest_text()  ──┘  (破坏性, 会与主循环抢事件)
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
        get_speech_state=robot.speech.peek_latest_text,  # 非破坏性，别用 get_*
    )
    bridge.start()  # Runs in background thread

    # Web dashboard reads state:
    state = bridge.get_snapshot()
"""
from __future__ import annotations

import logging
import copy
import math
import threading
import time
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Callable, Dict, List, Optional

from emotion.behavior_sync import BehaviorSync
from emotion.embodied_engine import EmbodiedEngine
from emotion.fusion_engine import FusionEngine, SPEECH_EMOTION_MAP, VISION_EMOTION_MAP
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
    data_available: bool = False
    risk_checked_at: str = ""
    last_error: str = ""
    last_error_at: str = ""
    error_count: int = 0

    # Attention
    # R12：默认 0.5（注意力"未知"），与 fusion_engine 的约定一致。
    # 桥接器尚未跑完首轮时，看板不应把"未知"渲染成"满注意力"（1.0），
    # 也不应渲染成"注意力丢失"（0.0）——0.5 是既不奖励也不惩罚的中性值。
    attention_level: float = 0.5


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

        # ── 初始化情绪模块 ──
        self._memory = MemoryAxis(db_path=db_path)
        self._fusion = FusionEngine(memory_axis=self._memory)
        self._behavior = BehaviorSync()
        self._embodied = EmbodiedEngine(hardware_available=hardware_available)
        self._intervention = InterventionEngine(memory_axis=self._memory)

        # ── 状态 ──
        self._snapshot = EmotionSnapshot()
        self._lock = threading.Lock()
        self._lifecycle_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._cycle_count = 0
        self._last_risk_triggers: List[str] = []
        self._risk_checked_at = ""
        self._last_error = self._last_error_at = ""
        self._error_count = 0
        self._last_warning = 0.0

        # ── 记忆写入策略（抑制写放大）──
        # 0.5s 一轮 = 每天约 17 万行，几天就能把 SQLite 撑爆。
        # 策略：情绪类别变化 或 valence 跨越一个档位 → 立即记录；
        #       否则每 _record_heartbeat 秒补一条基线，保证时间序列连续。
        self._record_heartbeat = 30.0
        self._valence_bucket = 0.2
        self._last_record_signature: Optional[tuple] = None
        self._last_record_time = 0.0

        # ── 语音新鲜度 ──
        # peek 接口是非破坏性的，同一句话会被反复读到；这里用 seq 去重，
        # 并加一个时间窗，避免几分钟前的一句话持续主导当前情绪判断。
        self._speech_freshness = 10.0
        self._last_speech_seq: Optional[int] = None
        self._last_speech_time = 0.0

        # ── 回调 ──
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
        with self._lifecycle_lock:
            if self._thread and self._thread.is_alive():
                return
            if self._stop_event.is_set():
                raise RuntimeError("Stopped bridges cannot be restarted; create a new bridge")
            self._running = True
            self._thread = threading.Thread(target=self._run_loop, daemon=True, name="EmotionBridge")
            self._thread.start()
        logger.info("🚀 [桥接器] 后台情绪处理循环已启动")

    def stop(self) -> None:
        """Stop the emotion bridge."""
        with self._lifecycle_lock:
            self._running = False
            self._stop_event.set()
        if self._thread and self._thread.is_alive():
            if self._thread is not threading.current_thread():
                self._thread.join(timeout=2.0)
            if self._thread.is_alive():
                self._mark_error("bridge_shutdown_timeout")
        self._embodied.stop()
        with self._lock:
            self._snapshot = replace(self._snapshot, is_running=False, data_available=False, last_error=self._last_error)
        logger.info("⚙️ [桥接器] 已停止")

    def get_snapshot(self) -> EmotionSnapshot:
        """Get the current emotion system snapshot (thread-safe)."""
        with self._lock:
            return copy.deepcopy(self._snapshot)

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
        return bool(self._running and self._thread and self._thread.is_alive())

    # ─── Main Loop ───────────────────────────────────────────────────

    def _run_loop(self) -> None:
        """Background processing loop."""
        logger.info("🔄 [桥接器] 情绪处理循环开始")

        try:
            while not self._stop_event.is_set():
                try:
                    self._process_cycle()
                except Exception as exc:
                    self._mark_error("bridge_cycle_failed", exc)
                    self._publish_unavailable()
                self._stop_event.wait(self._cycle_interval)
        finally:
            self._running = False
            with self._lock:
                self._snapshot = replace(self._snapshot, is_running=False, data_available=False)

    def _mark_error(self, code, exc=None):
        self._last_error = code
        self._last_error_at = datetime.now().isoformat()
        self._error_count += 1
        now = time.monotonic()
        if now - self._last_warning >= 5.0:
            logger.warning("%s type=%s", code, type(exc).__name__ if exc else "runtime")
            self._last_warning = now

    def _publish_unavailable(self):
        with self._lock:
            self._snapshot = EmotionSnapshot(
                emotion=EmotionState(attention_level=0.5), is_running=self.is_running,
                cycle_count=self._cycle_count, last_update=datetime.now().isoformat(),
                risk_triggers=list(self._last_risk_triggers), has_risk=bool(self._last_risk_triggers),
                risk_checked_at=self._risk_checked_at, last_error=self._last_error,
                last_error_at=self._last_error_at, error_count=self._error_count,
            )

    @staticmethod
    def _fresh_capture(state, maximum_age):
        captured = state.get("captured_at")
        if captured is None:
            return True  # Compatibility for injected legacy/Fake adapters.
        try:
            if isinstance(captured, str):
                captured = datetime.fromisoformat(captured).timestamp()
            return -1.0 <= time.time() - float(captured) <= maximum_age
        except (ValueError, TypeError, OverflowError):
            return False

    def _read_vision(self) -> Dict:
        """安全读取视觉状态；getter 抛异常时返回空 dict 而不是中断整个周期。"""
        try:
            state = self._get_vision() or {}
            if state.get("observation_available") is False or not self._fresh_capture(state, 2.0):
                return {}
            return state
        except Exception as e:
            self._mark_error("vision_read_failed", e)
            return {}

    def _read_speech(self) -> Optional[Dict]:
        """
        安全读取语音状态，并过滤掉已经不新鲜的旧语句。

        - 若 getter 返回带 ``seq`` 的 dict（peek_latest_text），用 seq 去重，
          同一句话只在 ``_speech_freshness`` 秒内参与融合；
        - 若返回不带 ``seq`` 的旧格式，则保持原有行为（视为新鲜）。
        """
        try:
            speech_state = self._get_speech()
        except Exception as e:
            self._mark_error("speech_read_failed", e)
            return None

        if not speech_state:
            return None

        if not self._fresh_capture(speech_state, self._speech_freshness):
            return None

        seq = speech_state.get("seq")
        if seq is None:
            # 旧版 getter：无法去重，直接采信
            return speech_state

        now = time.time()
        if seq != self._last_speech_seq:
            self._last_speech_seq = seq
            self._last_speech_time = now
            return speech_state

        if now - self._last_speech_time <= self._speech_freshness:
            return speech_state
        return None

    def _should_record(self, state: EmotionState) -> bool:
        """
        决定本轮是否写入长期记忆。

        去重条件：情绪类别 + valence 档位（默认 0.2 一档）。
        变化时立即写入；无变化时每 ``_record_heartbeat`` 秒补一条基线。
        """
        now = time.time()
        bucket = round(state.valence / self._valence_bucket)
        signature = (state.category, bucket)

        if signature != self._last_record_signature:
            self._last_record_signature = signature
            self._last_record_time = now
            return True

        if now - self._last_record_time >= self._record_heartbeat:
            self._last_record_time = now
            return True

        return False

    def _process_cycle(self) -> None:
        """Single processing cycle: read → fuse → act → record."""
        self._cycle_count += 1
        self._last_error = ""

        # ── 1. Read sensor state ──
        vision_state = self._read_vision()
        speech_state = self._read_speech()

        # Merge environment signals with dynamic data
        env = dict(self._env_signals)
        env["hour"] = datetime.now().hour

        # A time-of-day prior is not a child observation. Empty/expired sensors
        # publish unavailable state and never manufacture real history or actions.
        vision_signal = bool(
            vision_state.get("face_detected") is not False
            and vision_state.get("emotion") in VISION_EMOTION_MAP
        )
        speech_signal = bool(speech_state and speech_state.get("emotion") in SPEECH_EMOTION_MAP)
        environment_signal = any(
            isinstance(env.get(key), (int, float)) and not isinstance(env.get(key), bool)
            and math.isfinite(env[key]) and 0.0 <= env[key] <= 1.0
            for key in ("bio_anxiety", "noise_level")
        )
        observed = vision_signal or speech_signal or environment_signal
        if not observed:
            self._publish_unavailable()
            return

        # ── 2. Fuse emotions ──
        emotion_state = self._fusion.fuse(
            vision_state=vision_state,
            speech_state=speech_state,
            env_signals=env,
        )

        # ── 3. Record to memory (带去重/限频，避免写放大) ──
        context = speech_state.get("text", "") if speech_state else ""
        previous_signature = self._last_record_signature
        previous_record_time = self._last_record_time
        if self._should_record(emotion_state):
            try:
                self._memory.record(emotion_state, context=context, source_text=context)
            except Exception as exc:
                # 去重标记只有在成功持久化后才能生效；失败周期下次仍应重试。
                self._last_record_signature = previous_signature
                self._last_record_time = previous_record_time
                self._mark_error("memory_write_failed", exc)

        # ── 4. Generate behavior command ──
        behavior_cmd = self._behavior.sync(emotion_state)

        # ── 5. Execute behavior ──
        if not self._stop_event.is_set():
            self._embodied.execute(behavior_cmd)

        # ── 6. Evaluate intervention ──
        intervention = self._intervention.evaluate(emotion_state)

        # ── 7. Check risk triggers (every 10 cycles to avoid DB spam) ──
        if self._cycle_count % 10 == 0:
            try:
                self._last_risk_triggers = self._memory.check_risk_triggers(window_minutes=30)
                self._risk_checked_at = datetime.now().isoformat()
            except Exception as exc:
                self._mark_error("risk_check_failed", exc)
        risk_triggers = list(self._last_risk_triggers)

        # ── 8. Fire callbacks ──
        if not self._stop_event.is_set() and intervention.intervention_type != InterventionType.NONE and self._on_intervention:
            try:
                self._on_intervention(intervention)
            except Exception as e:
                self._mark_error("intervention_callback_failed", e)

        if not self._stop_event.is_set() and self._on_behavior:
            try:
                self._on_behavior(behavior_cmd)
            except Exception as e:
                self._mark_error("behavior_callback_failed", e)

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
            is_running=self.is_running,
            cycle_count=self._cycle_count,
            last_update=datetime.now().isoformat(),
            attention_level=emotion_state.attention_level,
            data_available=not self._stop_event.is_set(),
            risk_checked_at=self._risk_checked_at,
            last_error=self._last_error, last_error_at=self._last_error_at,
            error_count=self._error_count,
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
