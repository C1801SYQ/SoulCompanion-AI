"""
launch.py - Unified Launcher for SoulCompanion AI

Starts all three systems in a single process:
  1. Robot core loop (main.py's SoulCompanionRobot)
  2. Emotion bridge (background thread)
  3. Web dashboard (FastAPI on port 8000)

Usage:
    python launch.py                    # Start everything (default port 8000)
    python launch.py --port 8080        # Custom port
    python launch.py --no-robot         # Dashboard only (no robot loop)
    python launch.py --no-web           # Robot + bridge only (no dashboard)
    python launch.py --hardware         # Enable hardware mode

Architecture:
    ┌──────────────────────────────────────────────────────────┐
    │  launch.py                                               │
    │                                                          │
    │  Thread 1: robot.run()          ← main.py loop           │
    │  Thread 2: bridge.start()       ← emotion processing     │
    │  Thread 3: uvicorn.run()        ← web dashboard          │
    │                                                          │
    │  Shared: robot.vision ←──── bridge reads ────→ dashboard │
    │          robot.speech ←──── bridge reads ────→ dashboard │
    └──────────────────────────────────────────────────────────┘
"""
from __future__ import annotations

import argparse
import logging
import sys
import os
import threading
import time

# Fix Windows console encoding for emoji support
if sys.platform == "win32":
    os.environ["PYTHONIOENCODING"] = "utf-8"
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

logger = logging.getLogger("Launcher")


def launch(
    port: int = 8000,
    host: str = "127.0.0.1",
    enable_robot: bool = True,
    enable_web: bool = True,
    hardware: bool = False,
):
    """
    Launch the full SoulCompanion AI system.

    Args:
        port: Web dashboard port
        host: Web dashboard host
        enable_robot: Whether to start the robot loop
        enable_web: Whether to start the web dashboard
        hardware: Whether to enable hardware mode
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    logger.info("=" * 60)
    logger.info("💠 SoulCompanion AI - 多模态情绪智能系统")
    logger.info("=" * 60)

    # ── Step 1: Initialize robot ──
    robot = None
    if enable_robot:
        logger.info("🤖 [1/3] 初始化机器人核心...")
        try:
            from main import SoulCompanionRobot
            robot = SoulCompanionRobot()
            logger.info("✅ 机器人核心已就绪")
        except Exception as e:
            logger.error(f"❌ 机器人初始化失败: {e}")
            if not enable_web:
                logger.error("无法继续，退出")
                return
            logger.warning("⚠️ 继续启动（仅Web模式）")
            enable_robot = False

    # ── Step 2: Initialize emotion bridge ──
    bridge = None
    logger.info("🧠 [2/3] 初始化情绪桥接器...")

    try:
        from emotion.bridge import EmotionBridge

        # Define getters that read from the robot's engines
        if robot:
            get_vision = robot.vision.get_latest_state
            get_speech = robot.speech.get_latest_text
        else:
            # No robot: provide dummy getters for standalone dashboard
            def get_vision():
                return {"face_detected": False, "emotion": "neutral", "attention_loss_time": 0.0}
            def get_speech():
                return None

        bridge = EmotionBridge(
            get_vision_state=get_vision,
            get_speech_state=get_speech,
            hardware_available=hardware,
            cycle_interval=0.5,
        )

        # Set intervention callback (log interventions)
        def on_intervention(plan):
            if plan.guidance_text:
                logger.info(f"💬 [干预] {plan.guidance_text}")

        def on_behavior(cmd):
            if cmd.actions:
                action_names = ", ".join(a.value for a in cmd.actions[:3])
                logger.debug(f"🎬 [行为] {action_names}")

        bridge.set_callbacks(
            on_intervention=on_intervention,
            on_behavior=on_behavior,
        )

        bridge.start()
        logger.info("✅ 情绪桥接器已启动")
    except Exception as e:
        logger.error(f"❌ 桥接器初始化失败: {e}")
        if not enable_web:
            return
        logger.warning("⚠️ 继续启动（无桥接器）")

    # ── Step 3: Start web dashboard ──
    if enable_web:
        logger.info(f"🌐 [3/3] 启动Web仪表板 ({host}:{port})...")

        try:
            from web.api import app, set_bridge

            if bridge:
                set_bridge(bridge)

            # Start uvicorn in a background thread so main thread stays responsive
            import uvicorn

            def run_web():
                uvicorn.run(
                    app,
                    host=host,
                    port=port,
                    log_level="warning",  # Reduce noise
                )

            web_thread = threading.Thread(target=run_web, daemon=True, name="WebServer")
            web_thread.start()

            logger.info(f"✅ Web仪表板已启动: http://{host}:{port}")
            logger.info(f"📖 API文档: http://{host}:{port}/docs")
        except ImportError:
            logger.error("❌ FastAPI/uvicorn 未安装。请运行: pip install -r requirements-web.txt")
        except Exception as e:
            logger.error(f"❌ Web启动失败: {e}")
    else:
        logger.info("🌐 [3/3] Web仪表板已禁用")

    # ── Step 4: Start robot loop (blocking on main thread) ──
    if enable_robot and robot:
        logger.info("")
        logger.info("🚀 系统就绪！机器人开始运行...")
        logger.info("   按 Ctrl+C 停止")
        logger.info("")

        try:
            robot.run()  # This blocks until KeyboardInterrupt
        except KeyboardInterrupt:
            logger.info("")
            logger.info("⏹️ 收到停止信号...")
        finally:
            shutdown(robot, bridge)
    else:
        # No robot: keep main thread alive for web dashboard
        logger.info("")
        logger.info(f"🌐 仪表板运行中: http://{host}:{port}")
        logger.info("   按 Ctrl+C 停止")
        logger.info("")

        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("")
            logger.info("⏹️ 收到停止信号...")
            shutdown(None, bridge)


def shutdown(robot, bridge):
    """Graceful shutdown of all systems."""
    logger.info("⚙️ 正在关闭系统...")

    if bridge:
        bridge.stop()
        logger.info("✅ 情绪桥接器已停止")

    if robot:
        robot.shutdown()
        logger.info("✅ 机器人核心已停止")

    logger.info("👋 系统已关闭")


def main():
    parser = argparse.ArgumentParser(
        description="💠 SoulCompanion AI - 多模态情绪智能系统启动器"
    )
    parser.add_argument(
        "--port", type=int, default=8000,
        help="Web仪表板端口 (默认: 8000)"
    )
    parser.add_argument(
        "--host", default="127.0.0.1",
        help="Web仪表板绑定地址 (默认: 127.0.0.1)"
    )
    parser.add_argument(
        "--no-robot", action="store_true",
        help="不启动机器人核心（仅仪表板）"
    )
    parser.add_argument(
        "--no-web", action="store_true",
        help="不启动Web仪表板（仅机器人+桥接器）"
    )
    parser.add_argument(
        "--hardware", action="store_true",
        help="启用硬件模式"
    )

    args = parser.parse_args()

    launch(
        port=args.port,
        host=args.host,
        enable_robot=not args.no_robot,
        enable_web=not args.no_web,
        hardware=args.hardware,
    )


if __name__ == "__main__":
    main()
