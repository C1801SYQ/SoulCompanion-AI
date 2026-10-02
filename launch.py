"""Run the local edge runtime and dashboard with bounded resource cleanup."""
from __future__ import annotations

import argparse
import logging
import threading
import time

logger = logging.getLogger("Launcher")


def launch(port=None, host=None, enable_robot=True, enable_web=True, hardware=False):
    import config

    port = config.DASHBOARD_PORT if port is None else port
    host = config.DASHBOARD_HOST if host is None else host
    if enable_web:
        config.validate_bind_host(host)
        if not isinstance(port, int) or not 1 <= port <= 65535:
            raise config.ConfigurationError("Dashboard port must be between 1 and 65535")
    logging.basicConfig(
        level=getattr(logging, config.LOG_LEVEL),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    if config.DEMO_MODE:
        enable_robot = False
        logger.info("Explicit browser demo: edge capture and real storage disabled")
    if not enable_robot and not enable_web:
        logger.info("No runtime or dashboard requested")
        return

    robot = bridge = server = web_thread = robot_thread = None
    try:
        if enable_robot:
            try:
                from main import SoulCompanionRobot
                robot = SoulCompanionRobot()
                robot.hardware_requested = hardware
            except Exception as exc:
                logger.warning("robot_initialize_failed type=%s", type(exc).__name__)
                if not enable_web:
                    return
        if robot is not None:
            from emotion.bridge import EmotionBridge
            bridge = EmotionBridge(
                get_vision_state=robot.vision.get_latest_state,
                get_speech_state=robot.speech.peek_latest_text,
                hardware_available=hardware,
                cycle_interval=0.5,
            )
            bridge.start()
        else:
            logger.info("No capture bridge attached; live child data is unavailable")

        if enable_web:
            from web.api import app, set_bridge, set_runtime
            import uvicorn

            set_bridge(bridge)
            set_runtime(robot)
            server = uvicorn.Server(uvicorn.Config(
                app, host=host, port=port, log_level=config.LOG_LEVEL.lower(),
                proxy_headers=False,
            ))

            def run_web():
                try:
                    server.run()
                except BaseException as exc:
                    logger.error("web_server_failed type=%s", type(exc).__name__)

            web_thread = threading.Thread(target=run_web, daemon=True, name="WebServer")
            web_thread.start()
            deadline = time.monotonic() + 5.0
            while not server.started:
                if not web_thread.is_alive() or time.monotonic() >= deadline:
                    logger.error("Web server failed to become ready")
                    return
                time.sleep(0.05)
            logger.info("Dashboard ready: http://%s:%s", host, port)

        if robot is not None:
            robot_thread = threading.Thread(target=robot.run, daemon=True, name="RobotCore")
            robot_thread.start()
        while True:
            if web_thread is not None and not web_thread.is_alive():
                return
            if robot_thread is not None and not robot_thread.is_alive():
                return
            time.sleep(0.1)
    except KeyboardInterrupt:
        logger.info("Shutdown requested")
    except Exception as exc:
        logger.error("startup_failed type=%s", type(exc).__name__)
    finally:
        shutdown(robot, bridge, server, web_thread)
        if robot_thread and robot_thread is not threading.current_thread():
            robot_thread.join(timeout=2.0)


def shutdown(robot, bridge, server=None, web_thread=None):
    if server is not None:
        server.should_exit = True
    for name, resource in (("bridge", bridge), ("robot", robot)):
        if resource is not None:
            try:
                resource.stop() if name == "bridge" else resource.shutdown()
            except Exception as exc:
                logger.warning("shutdown_failed module=%s type=%s", name, type(exc).__name__)
    if web_thread and web_thread is not threading.current_thread():
        web_thread.join(timeout=3.0)
        if web_thread.is_alive():
            logger.warning("web_shutdown_timeout")


def main():
    parser = argparse.ArgumentParser(description="SoulCompanion local runtime")
    try:
        import config
    except ValueError as exc:
        parser.error(str(exc))
    parser.add_argument("--port", type=int, default=config.DASHBOARD_PORT)
    parser.add_argument("--host", default=config.DASHBOARD_HOST)
    parser.add_argument("--no-robot", action="store_true", help="Read existing history without collecting observations")
    parser.add_argument("--no-web", action="store_true")
    parser.add_argument("--hardware", action="store_true", help="Request physical hardware (requires a real adapter)")
    args = parser.parse_args()
    try:
        if not args.no_web:
            config.validate_bind_host(args.host)
            if not 1 <= args.port <= 65535:
                raise config.ConfigurationError("Dashboard port must be between 1 and 65535")
    except ValueError as exc:
        parser.error(str(exc))
    launch(port=args.port, host=args.host, enable_robot=not args.no_robot, enable_web=not args.no_web, hardware=args.hardware)


if __name__ == "__main__":
    main()
