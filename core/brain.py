# SoulCompanion_AI/core/brain.py
import random


class RobotBrain:
    def __init__(self):
        # 预设训练场景 (当前默认为：自由社交场景)
        self.current_scenario = "social_interaction"

        self.intents = {
            "greet": ["你好呀！看到你真高兴。", "哈喽！今天想玩点什么？"],
            "praise": ["你做得太棒了！", "我就知道你一定行！"]
        }
        print("🧠 [ASD干预大脑] 自适应策略引擎已激活")

    def think(self, user_context, vision_data):
        v_emotion = vision_data.get("emotion", "neutral")
        v_face = vision_data.get("face_detected", False)
        v_attention_loss = vision_data.get("attention_loss_time", 0.0)

        # --- 🚨 优先级 1：防情绪崩溃干预 (ASD核心痛点) ---
        if v_emotion == "anxious":
            return self._build_resp(
                "我看你好像有点紧张，我们一起来做个深呼吸吧。吸气... 呼气...",
                "calm", "slow_nod", "blue_breathe"  # 蓝色呼吸灯有安抚作用
            )

        # --- 👀 优先级 2：眼神/注意力引导 (ASD核心痛点) ---
        # 如果儿童超过 8 秒没有看着机器人，主动引导
        if not v_face and v_attention_loss > 8.0:
            if not user_context:  # 且没有说话
                return self._build_resp(
                    "小予在这里哦，能看看我的眼睛吗？",
                    "friendly", "head_tilt", "soft_yellow"  # 柔和黄灯吸引注意
                )

        # --- 🗣️ 优先级 3：常规对话与情感共鸣 ---
        if v_emotion == "sad" and ("没事" in user_context or not user_context):
            return self._build_resp("你看起来有点难过，可以跟小予说说吗？我一直在呢。", "sad", "arm_hug", "warm_white")

        if any(word in user_context for word in ["你好", "嘿", "名字"]):
            return self._build_resp(random.choice(self.intents["greet"]), "happy", "nod", "green")

        if any(word in user_context for word in ["好", "开心", "棒"]):
            return self._build_resp(random.choice(self.intents["praise"]), "happy", "spin", "rainbow")

        # --- 兜底回复 ---
        if user_context:
            return self._build_resp("嗯，小予在听。", "neutral", "nod", "soft_white")

        return None

    def _build_resp(self, text, emotion, action, led_mode):
        """统一返回格式，增加专门针对 ASD 的柔和灯光模式"""
        return {
            "reply": text,
            "emotion": emotion,
            "hardware_action": action,
            "led_mode": led_mode
        }