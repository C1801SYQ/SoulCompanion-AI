import requests
import json

OLLAMA_MODEL = "gemma4:e4b"
OLLAMA_API_URL = "http://localhost:11434/api/generate"


def ask_xiaoyu(user_text, visual_emotion):
    """接入 Ollama 离线大模型"""
    system_prompt = (
        f"你叫小予，是一个温暖的智能机器人。当前感知到用户情绪为：{visual_emotion}。"
        "请根据情绪和话语进行不超过50字的自然回复，不要输出任何代码或标签。"
    )

    payload = {
        "model": OLLAMA_MODEL,
        "prompt": f"{system_prompt}\n用户：{user_text}\n小予：",
        "stream": False
    }

    try:
        response = requests.post(OLLAMA_API_URL, json=payload, timeout=10)
        return response.json().get("response", "（思绪断了...）").strip()
    except:
        return "我的大脑连接似乎有些延迟，请确保 Ollama 正在运行。"