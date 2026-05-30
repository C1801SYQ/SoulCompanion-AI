import time


class VoiceEngine:
    def __init__(self):
        # 未来这里会初始化真实的 TTS 引擎（如 pyttsx3 或 阿里云 TTS）
        print("语音引擎已就绪")

    def speak(self, text, emotion_label):
        """
        根据情绪标签调整说话方式
        """
        speed = 1.0
        pitch = "normal"

        # 功能 3：情绪跟随逻辑
        if emotion_label == "兴奋":
            speed = 1.5  # 说快点
            print(f"【系统信号：灯光变绿快闪】")
        elif emotion_label == "沮丧":
            speed = 0.8  # 说慢点
            print(f"【系统信号：灯光变蓝呼吸】")

        print(f"🎙️ 机器人({emotion_label}, 速度{speed}): {text}")
        # 在真实硬件上，这里会调用声音播放函数