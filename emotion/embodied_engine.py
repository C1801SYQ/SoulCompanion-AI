"""
emotion/embodied_engine.py - Humanoid Behavior Simulation Engine

Executes BehaviorCommands as physical/virtual robot actions:
- Heartbeat simulation (soothing vibration)
- Breathing LED (slow pulsing light)
- Ear movements (playful/curious)
- Head tilt (thinking/engaging)
- Soothing feedback behaviors

Hardware-abstracted: works with or without physical hardware.
Falls back to console logging when no hardware is present.
"""
from __future__ import annotations

import logging
import math
import threading
import time
from typing import Optional

from emotion.models import BehaviorAction, BehaviorCommand

logger = logging.getLogger("EmbodiedEngine")

# ─── Animation Parameters ──────────────────────────────────────────────

HEARTBEAT_BPM = 72           # Resting heart rate
BREATHING_CYCLE_SEC = 4.0    # Inhale + exhale duration
EAR_WIGGLE_DURATION = 0.5    # Seconds per wiggle
HEAD_TILT_ANGLE = 15         # Degrees


class EmbodiedEngine:
    """
    Humanoid behavior simulation engine.

    Executes BehaviorCommands by controlling:
    - LED brightness/color (breathing patterns)
    - Servo motors (head tilt, ear movement)
    - Vibration motor (heartbeat simulation)
    - Speech rate modulation

    Hardware-abstracted: detects available hardware and falls back
    to console logging for development/testing.
    """

    def __init__(self, hardware_available: bool = False):
        """
        Args:
            hardware_available: If True, attempt to use real hardware.
                               If False, use simulation/logging only.
        """
        self.hardware_available = hardware_available
        self._running = True
        self._current_action: Optional[BehaviorAction] = None
        self._action_thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

        # Hardware interface (lazy-loaded)
        self._actuator = None

        if hardware_available:
            self._init_hardware()

        logger.info(
            f"✅ [拟人引擎] 行为仿真引擎已就绪 "
            f"({'硬件模式' if hardware_available else '模拟模式'})"
        )

    def _init_hardware(self) -> None:
        """Initialize hardware interfaces if available."""
        try:
            from hardware.controllers.actuators import RobotActuator
            self._actuator = RobotActuator()
            logger.info("✅ [拟人引擎] 硬件控制器已连接")
        except Exception as e:
            logger.warning(f"⚠️ [拟人引擎] 硬件初始化失败，回退到模拟模式: {e}")
            self.hardware_available = False

    def execute(self, command: BehaviorCommand) -> None:
        """
        Execute a BehaviorCommand.

        Starts background threads for continuous actions (heartbeat, breathing)
        and executes discrete actions (head tilt, ear wiggle) immediately.

        Args:
            command: BehaviorCommand to execute
        """
        if command.priority >= 1:
            # High priority: stop current actions immediately
            self._stop_current_actions()

        for action in command.actions:
            self._dispatch_action(action, command)

        # Log the behavior for monitoring
        logger.info(
            f"🎬 [行为执行] {', '.join(a.value for a in command.actions)} "
            f"| LED={command.led_color} 亮度={command.led_brightness} "
            f"| 语速={command.speech_rate} | 原因: {command.reason}"
        )

    def _dispatch_action(self, action: BehaviorAction, command: BehaviorCommand) -> None:
        """Dispatch a single action to the appropriate handler."""
        handlers = {
            BehaviorAction.HEARTBEAT: self._heartbeat,
            BehaviorAction.BREATHING_LED: self._breathing_led,
            BehaviorAction.EAR_WIGGLE: self._ear_wiggle,
            BehaviorAction.HEAD_TILT: self._head_tilt,
            BehaviorAction.SOOTHING_VOICE: lambda: self._voice_modulation(command.speech_rate),
            BehaviorAction.EXCITED_VOICE: lambda: self._voice_modulation(command.speech_rate),
            BehaviorAction.SLOW_MOTION: lambda: self._motion_control(command.servo_speed),
            BehaviorAction.STILL: self._still_mode,
            BehaviorAction.LED_WARM: lambda: self._led_control(command.led_color, command.led_brightness),
            BehaviorAction.LED_COOL: lambda: self._led_control(command.led_color, command.led_brightness),
            BehaviorAction.LED_DIM: lambda: self._led_control(command.led_color, command.led_brightness),
        }

        handler = handlers.get(action)
        if handler:
            try:
                handler()
            except Exception as e:
                logger.error(f"❌ [行为执行] {action.value} 失败: {e}")

    # ─── Continuous Actions (run in background threads) ───────────────

    def _heartbeat(self) -> None:
        """Simulate heartbeat with vibration motor pattern."""
        if self.hardware_available and self._actuator:
            self._actuator.perform_action("心跳模拟")
        else:
            # Simulation: log heartbeat pattern
            logger.info("💓 [心跳] 72bpm 安抚节律启动")

    def _breathing_led(self) -> None:
        """Start breathing LED pattern (slow sine wave brightness)."""
        if self.hardware_available and self._actuator:
            self._actuator.set_led("breathing")
        else:
            logger.info("💡 [呼吸灯] 缓慢呼吸灯模式启动")

    # ─── Discrete Actions ─────────────────────────────────────────────

    def _ear_wiggle(self) -> None:
        """Execute ear wiggle animation."""
        if self.hardware_available and self._actuator:
            self._actuator.perform_action("动耳朵")
        else:
            logger.info("👂 [耳朵] 可爱耳朵摆动")

    def _head_tilt(self) -> None:
        """Execute head tilt to show curiosity/engagement."""
        if self.hardware_available and self._actuator:
            self._actuator.perform_action("歪头15度")
        else:
            logger.info("🤔 [头部] 好奇歪头 15°")

    def _voice_modulation(self, rate: float) -> None:
        """Modulate speech rate for emotional expression."""
        # This is applied by the TTS engine via the command's speech_rate
        logger.info(f"🗣️ [语音] 语速调整至 {rate:.1f}x")

    def _motion_control(self, speed: float) -> None:
        """Control overall motion speed."""
        logger.info(f"🦽 [运动] 动作速度调整至 {speed:.1f}")

    def _still_mode(self) -> None:
        """Enter still mode - minimize all movement (reduce stimuli)."""
        logger.info("🧊 [静止] 进入静止模式，减少刺激")

    def _led_control(self, color: str, brightness: float) -> None:
        """Set LED color and brightness."""
        if self.hardware_available and self._actuator:
            self._actuator.set_led(color)
        else:
            logger.info(f"💡 [灯光] LED={color} 亮度={brightness:.0%}")

    # ─── Utility ──────────────────────────────────────────────────────

    def _stop_current_actions(self) -> None:
        """Stop any currently running continuous actions."""
        with self._lock:
            self._current_action = None
        logger.info("⏹️ [行为] 停止当前动作 (高优先级中断)")

    def stop(self) -> None:
        """Shutdown the embodied engine."""
        self._running = False
        self._stop_current_actions()
        logger.info("⚙️ [拟人引擎] 已关闭")

    # ─── Status ───────────────────────────────────────────────────────

    def get_status(self) -> dict:
        """Return current engine status for monitoring."""
        return {
            "hardware_available": self.hardware_available,
            "current_action": self._current_action.value if self._current_action else None,
            "running": self._running,
        }


def create_embodied_engine(hardware_available: bool = False) -> EmbodiedEngine:
    """Factory function to create an EmbodiedEngine instance."""
    return EmbodiedEngine(hardware_available=hardware_available)
