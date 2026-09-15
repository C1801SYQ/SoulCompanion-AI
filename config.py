"""
config.py - 全局配置中心 (Single Source of Truth)

所有运行时参数集中在此处，并支持通过环境变量覆盖，
便于在开发机 / 部署机 / 演示环境之间切换而不改代码。

环境变量一览：
    SOULCOMPANION_DB            情绪数据库路径
    SOULCOMPANION_API_KEY       保留字段（如需外部 API）
    SOULCOMPANION_CORS_ORIGINS  允许跨域来源，逗号分隔；设为 * 表示放开（不携带凭证）
    OLLAMA_URL                  Ollama 接口地址
    OLLAMA_MODEL                使用的模型标签（需与 `ollama list` 一致）
    OLLAMA_TIMEOUT              单次请求超时秒数
    SOULCOMPANION_DASHBOARD_HOST / _PORT  仪表板默认监听地址
"""
from __future__ import annotations

import os
from dataclasses import dataclass

# ─── Paths ────────────────────────────────────────────────────────────
# 用绝对路径，避免因启动时工作目录不同而连到"另一个"数据库
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")

DATABASE_PATH = os.environ.get(
    "SOULCOMPANION_DB",
    os.path.join(DATA_DIR, "emotional_db.sqlite"),
)

# 保留字段：本项目默认不出网，如无需要留空即可
API_KEY = os.environ.get("SOULCOMPANION_API_KEY", "")

# ─── Web / CORS ───────────────────────────────────────────────────────
DASHBOARD_HOST = os.environ.get("SOULCOMPANION_DASHBOARD_HOST", "127.0.0.1")
DASHBOARD_PORT = int(os.environ.get("SOULCOMPANION_DASHBOARD_PORT", "8000"))

# 默认只放行本机来源。设为 "*" 时出于安全考虑会关闭凭证传递。
CORS_ORIGINS = os.environ.get(
    "SOULCOMPANION_CORS_ORIGINS",
    "http://localhost:8000,http://127.0.0.1:8000",
)

# ─── Logging ──────────────────────────────────────────────────────────
LOG_LEVEL = os.environ.get("SOULCOMPANION_LOG_LEVEL", "INFO").upper()


@dataclass(frozen=True)
class Config:
    """运行时配置（供 main.py 等模块以对象形式访问）。"""

    # Ollama LLM 决策后端
    OLLAMA_MODEL: str = os.environ.get("OLLAMA_MODEL", "gemma3n:e4b")
    OLLAMA_URL: str = os.environ.get(
        "OLLAMA_URL", "http://localhost:11434/api/generate"
    )
    OLLAMA_TIMEOUT: float = float(os.environ.get("OLLAMA_TIMEOUT", "60"))

    # ASD 特化阈值 [满足需求3：友好交互]
    ATTENTION_THRESHOLD: float = 8.0
    REINFORCEMENT_INTERVAL: float = 30.0
    SENSORY_FRIENDLY_VOLUME: float = 0.5

    # 对话历史上限：防止长时间运行导致内存无界增长
    MAX_CHAT_HISTORY: int = 200

    # 情绪数据库
    DATABASE_PATH: str = DATABASE_PATH
