"""
config.py - 全局配置中心 (Single Source of Truth)

所有运行时参数集中在此处，并支持通过环境变量覆盖，
便于在开发机 / 部署机 / 演示环境之间切换而不改代码。

环境变量一览：
    SOULCOMPANION_DB            情绪数据库路径
    SOULCOMPANION_API_KEY       保留字段（如需外部 API）
    SOULCOMPANION_CORS_ORIGINS  本机来源，逗号分隔；禁止通配和远程来源
    OLLAMA_URL                  Ollama 接口地址
    OLLAMA_MODEL                使用的模型标签（需与 `ollama list` 一致）
    OLLAMA_TIMEOUT              单次请求超时秒数
    SOULCOMPANION_DASHBOARD_HOST / _PORT  仪表板默认监听地址
"""
from __future__ import annotations

import os
import ipaddress
import math
from dataclasses import dataclass
from urllib.parse import urlsplit


class ConfigurationError(ValueError):
    """Invalid deployment settings, with the offending variable named."""


def _number(name: str, default: str, lower: float, upper: float, integer=False):
    value = os.environ.get(name, default)
    try:
        result = int(value) if integer else float(value)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be a number ({lower}..{upper})") from exc
    if not math.isfinite(result) or not lower <= result <= upper:
        raise ConfigurationError(f"{name} must be between {lower} and {upper}")
    return result


def _boolean(name: str, default: str = "false") -> bool:
    value = os.environ.get(name, default).lower()
    if value not in {"true", "false", "1", "0"}:
        raise ConfigurationError(f"{name} must be true/false or 1/0")
    return value in {"true", "1"}


def validate_bind_host(host: str) -> str:
    """This release serves one local operator and has no remote authentication."""
    if host == "localhost":
        return host
    try:
        if ipaddress.ip_address(host).is_loopback:
            return host
    except ValueError:
        pass
    raise ConfigurationError("Dashboard host must be localhost or a loopback IP; remote access is unsupported")


def _local_http_url(name: str, value: str, *, origin: bool = False):
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("Invalid HTTP(S) endpoint")
        validate_bind_host(parsed.hostname)
        if parsed.port is not None and not 1 <= parsed.port <= 65535:
            raise ValueError("Invalid port")
        if origin and (parsed.path or parsed.query or parsed.fragment):
            raise ValueError("Origin must not contain a path, query or fragment")
        return parsed
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be a valid local HTTP(S) {'origin' if origin else 'URL'} without credentials") from exc


def _path(name: str, default: str) -> str:
    value = os.environ.get(name, default).strip()
    if not value:
        raise ConfigurationError(f"{name} must not be empty")
    return os.path.abspath(os.path.join(BASE_DIR, value))

# ─── Paths ────────────────────────────────────────────────────────────
# 用绝对路径，避免因启动时工作目录不同而连到"另一个"数据库
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")

DATABASE_PATH = _path(
    "SOULCOMPANION_DB",
    os.path.join(DATA_DIR, "emotional_db.sqlite"),
)

# 保留字段：本项目默认不出网，如无需要留空即可
API_KEY = os.environ.get("SOULCOMPANION_API_KEY", "")

# ─── Web / CORS ───────────────────────────────────────────────────────
DASHBOARD_HOST = os.environ.get("SOULCOMPANION_DASHBOARD_HOST", "127.0.0.1")
validate_bind_host(DASHBOARD_HOST)
DASHBOARD_PORT = _number("SOULCOMPANION_DASHBOARD_PORT", "8000", 1, 65535, integer=True)

# Origins must be local; the HTTP boundary additionally checks same-origin access.
CORS_ORIGINS = os.environ.get(
    "SOULCOMPANION_CORS_ORIGINS",
    "http://localhost:8000,http://127.0.0.1:8000",
)
for _origin in filter(None, (item.strip() for item in CORS_ORIGINS.split(","))):
    _local_http_url("SOULCOMPANION_CORS_ORIGINS", _origin, origin=True)

# ─── Logging ──────────────────────────────────────────────────────────
LOG_LEVEL = os.environ.get("SOULCOMPANION_LOG_LEVEL", "INFO").upper()
if LOG_LEVEL not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
    raise ConfigurationError("SOULCOMPANION_LOG_LEVEL must be DEBUG/INFO/WARNING/ERROR/CRITICAL")

APP_ENV = os.environ.get("SOULCOMPANION_APP_ENV", "production").lower()
if APP_ENV not in {"development", "test", "production"}:
    raise ConfigurationError("SOULCOMPANION_APP_ENV must be development/test/production")
DEMO_MODE = _boolean("SOULCOMPANION_DEMO_MODE")
RETENTION_DAYS = _number("SOULCOMPANION_RETENTION_DAYS", "0", 0, 3650, integer=True)
RATE_LIMIT_PER_MINUTE = _number("SOULCOMPANION_RATE_LIMIT", "180", 30, 10000, integer=True)
VISION_MODEL_PATH = _path("SOULCOMPANION_VISION_MODEL", "models/onnx_model.onnx")
HAAR_PATH = _path("SOULCOMPANION_HAAR_PATH", "models/haarcascade_frontalface_default.xml")
VOSK_PATH = _path("SOULCOMPANION_VOSK_PATH", "model")
SER_PATH = _path("SOULCOMPANION_SER_PATH", "models/ser_model")
OLLAMA_ENDPOINT = os.environ.get("OLLAMA_URL", "http://localhost:11434/api/generate")
_local_http_url("OLLAMA_URL", OLLAMA_ENDPOINT)


@dataclass(frozen=True)
class Config:
    """运行时配置（供 main.py 等模块以对象形式访问）。"""

    # Ollama LLM 决策后端
    OLLAMA_MODEL: str = os.environ.get("OLLAMA_MODEL", "gemma3n:e4b")
    OLLAMA_URL: str = OLLAMA_ENDPOINT
    OLLAMA_TIMEOUT: float = _number("OLLAMA_TIMEOUT", "60", 1, 120)

    # ASD 特化阈值 [满足需求3：友好交互]
    ATTENTION_THRESHOLD: float = 8.0
    REINFORCEMENT_INTERVAL: float = 30.0
    SENSORY_FRIENDLY_VOLUME: float = 0.5

    # 对话历史上限：防止长时间运行导致内存无界增长
    MAX_CHAT_HISTORY: int = 200

    # 情绪数据库
    DATABASE_PATH: str = DATABASE_PATH
