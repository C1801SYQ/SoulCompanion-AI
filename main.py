import time
import logging
import requests
from typing import Dict, List
from dataclasses import dataclass, field

# 核心模块导入
from modules.vision_engine import VisionEngine
from modules.speech_engine import SpeechEngine
from utils.audio_player import AudioPlayer


@dataclass
class RobotState:
    """维护机器人的干预状态与用户表现数据 [满足需求2：自适应干预]"""
    current_scene: str = "自由对话"  # 场景：GREETING(打招呼), SOCIAL(社交)
    difficulty_level: int = 1  # 1-3 级，动态调整
    performance_score: float = 0.0  # 累计表现分数
    active_hint: str = ""  # 当前下发的视觉提示卡内容
    chat_history: List[Dict] = field(default_factory=list)  # 存储对话历史供 UI 渲染


@dataclass(frozen=True)
class Config:
    # 基础配置 [对齐 Ollama 模型]
    OLLAMA_MODEL: str = "gemma4:e4b"
    OLLAMA_URL: str = "http://localhost:11434/api/generate"

    # ASD 特化阈值 [满足需求3：友好交互]
    ATTENTION_THRESHOLD: float = 8.0
    REINFORCEMENT_INTERVAL: float = 30.0
    SENSORY_FRIENDLY_VOLUME: float = 0.5


class SoulCompanionRobot:
    def __init__(self):
        logging.basicConfig(level=logging.INFO)
        self.logger = logging.getLogger("XiaoYu_ASD")
        self.config = Config()
        self.state = RobotState()

        # 初始化传感器引擎
        self.vision = VisionEngine()
        self.speech = SpeechEngine()
        self.speaker = AudioPlayer()

        self.last_interaction_time = time.time()
        self.logger.info("✅ 小予 ASD 多模态干预引擎已就绪")

    def run(self):
        """核心干预循环 [满足需求2]"""
        try:
            while True:
                # 1. 多模态感知融合 (视觉+听觉) [满足需求1]
                v_data = self.vision.get_latest_state()
                a_data = self.speech.get_latest_text()  # 包含 text, emotion, volume

                # 模拟生物传感器数据
                bio_anxiety = 0.2

                # 2. 行为监测与干预触发
                self._check_behavior_logic(v_data, a_data, bio_anxiety)

                # 3. 语音主动交互
                if a_data and a_data.get("text"):
                    text = a_data["text"]
                    self.logger.info(f"👂 听到: {text} (语气: {a_data.get('emotion')})")
                    self._handle_adaptive_interaction(text, v_data)

                time.sleep(0.1)
        except KeyboardInterrupt:
            self.shutdown()

    def _check_behavior_logic(self, v_data, a_data, bio_anxiety):
        """实时行为监测逻辑"""
        now = time.time()

        # A. 注意力流失提醒 [ASD 核心干预行为感知]
        loss_time = v_data.get("attention_loss_time", 0)
        if loss_time > self.config.ATTENTION_THRESHOLD:
            if now - self.last_interaction_time > 12:
                self.state.active_hint = "👀 眼睛看着小予，我们要开始咯"  # 弹出视觉提示卡
                self._trigger_brain("提醒：孩子注意力偏离", v_data, "GENTLE_REMIND")
        else:
            # 如果注意力回来了，清空提示卡
            if loss_time < 1.0:
                self.state.active_hint = ""

        # B. 情绪异常自动调节 [满足需求2：根据情绪调整难度]
        current_emo = v_data.get("emotion", "neutral")
        if current_emo in ["anxious", "sad"] or bio_anxiety > 0.7:
            self.state.difficulty_level = max(1, self.state.difficulty_level - 1)
            self.state.active_hint = "🌟 放松一下，你做得很棒"
            if now - self.last_interaction_time > 15:
                self._trigger_brain(f"孩子感到{current_emo}", v_data, "CALMING")

    def _handle_adaptive_interaction(self, text, v_data):
        """处理自适应交互"""
        v_emo = v_data.get("emotion", "neutral")

        # 表现评分
        if v_emo == "happy":
            self.state.performance_score += 1.0

        # 同步用户话语到 UI 历史
        self.state.chat_history.append({"role": "user", "content": text})

        # 调用大脑决策
        self._trigger_brain(text, v_data, "SOCIAL_PRACTICE")

    def _trigger_brain(self, input_signal, v_data, mode):
        """大模型驱动的自适应干预决策 [连接 Ollama]"""

        # 构建 ASD 专家级 Prompt [满足需求3：简洁友好]
        prompt = (
            f"你叫小予，是专业的ASD(自闭症)干预伙伴。当前环境：\n"
            f"- 场景：{self.state.current_scene}\n"
            f"- 孩子表情：{v_data.get('emotion', '平静')}\n"
            f"- 输入信号：'{input_signal}'\n"
            f"- 干预模式：{mode}\n\n"
            f"要求：使用5岁孩子能听懂的语言，语气极其温和，字数控制在20字内。建议给予正向强化。"
        )

        try:
            payload = {"model": self.config.OLLAMA_MODEL, "prompt": prompt, "stream": False}
            # 增加超时到 60s，解决日志中的 Read Timeout 问题
            res = requests.post(self.config.OLLAMA_URL, json=payload, timeout=60)

            if res.status_code == 200:
                reply = res.json().get("response", "").strip()
                self.logger.info(f"🧠 [决策] {reply}")

                # 同步回复到 UI 历史记录
                self.state.chat_history.append({"role": "assistant", "content": reply})

                # 播报
                self.speaker.speak(reply)
                self.last_interaction_time = time.time()
        except Exception as e:
            self.logger.error(f"决策引擎异常 (请检查Ollama是否启动): {e}")

    def shutdown(self):
        self.logger.info("⚙️ 正在释放资源...")
        self.vision.stop()
        self.speech.stop()


if __name__ == "__main__":
    robot = SoulCompanionRobot()
    robot.run()