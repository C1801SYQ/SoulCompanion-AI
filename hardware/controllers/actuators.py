class RobotActuator:
    def __init__(self):
        self.current_angle = 0

    def perform_action(self, action_name):
        """
        执行拟人化动作
        """
        # 功能 5：拟人类反应
        if action_name == "歪头15度":
            self.current_angle = 15
            print(f"🎬 [执行动作]：伺服电机旋转 15°，机器人正在思考...")

        elif action_name == "动耳朵":
            print(f"🎬 [执行动作]：微型舵机快速摆动，机器人感到害羞/新奇。")

        elif action_name == "心跳模拟":
            print(f"🎬 [执行动作]：震动马达开启 75bpm 节律，提供生理安抚。")

    def set_led(self, color):
        print(f"💡 [灯光反馈]：RGB灯带切换至 {color}")