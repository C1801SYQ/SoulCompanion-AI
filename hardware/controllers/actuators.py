"""Explicit simulated actuator; it never claims to control physical hardware."""
import logging

logger = logging.getLogger("SimulatedActuator")


class RobotActuator:
    is_real = False

    def __init__(self):
        self.current_angle = 0

    def probe(self):
        return False

    def stop(self):
        logger.debug("simulated_actuator_stop")

    def perform_action(self, action_name):
        """
        执行拟人化动作
        """
        # 功能 5：拟人类反应
        if action_name == "歪头15度":
            self.current_angle = 15
            logger.debug("simulated_head_tilt angle=15")

        elif action_name == "动耳朵":
            logger.debug("simulated_ear_wiggle")

        elif action_name == "心跳模拟":
            logger.debug("simulated_heartbeat")

    def set_led(self, color):
        logger.debug("simulated_led color=%s", color)
