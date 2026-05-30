# SoulCompanion_AI/hardware.py

class RobotBody:
    def __init__(self, voice_engine):
        self.voice = voice_engine
        print("💻 [虚拟硬件] ASD低刺激交互模式已开启。")

    def execute(self, brain_json):
        reply_text = brain_json.get("reply", "")
        action = brain_json.get("hardware_action", "standby")
        led_mode = brain_json.get("led_mode", "soft_white")
        emotion = brain_json.get("emotion", "neutral")

        # 针对 ASD 优化的柔和动作映射
        action_map = {
            "slow_nod": "【动作：缓慢而平稳地点头，提供肯定感】",
            "head_tilt": "【动作：微微歪头，发出温和的邀请】",
            "arm_hug": "【动作：双臂微微张开，提供虚拟拥抱】",
            "spin": "【动作：原地慢慢转半圈，表示开心】",
            "nod": "【动作：轻轻点头】",
            "standby": "【动作：静止陪伴】"
        }

        # 针对 ASD 优化的低感官刺激灯光
        led_map = {
            "blue_breathe": "🌀 缓慢的蓝色呼吸灯 (安抚神经)",
            "soft_yellow": "⭐ 柔和的暖黄灯光 (吸引注意力)",
            "warm_white": "☁️ 暖白色常亮 (提供安全感)",
            "soft_green": "🌿 柔和的浅绿色 (表示正确/鼓励)",
            "rainbow": "✨ 缓慢变幻的淡彩虹色 (低刺激奖励)"
        }

        print(f"\n🎬 {action_map.get(action, '【动作：静止】')}")
        print(f"💡 [视觉治疗灯光]：{led_map.get(led_mode, '☁️ 暖白常亮')}")

        if reply_text:
            # 提示：在此处如果可以控制语速，应尽量将语速放慢
            self.voice.speak(reply_text, emotion)

    def emergency_stop(self):
        print("🛑 [硬件系统] 触发感官过载保护，立即停止所有声光动作。")