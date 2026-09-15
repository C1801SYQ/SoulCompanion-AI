"""config.py 单元测试（纯标准库，零重依赖）。

覆盖 R11 修复点：
- Config 关键阈值均为合理正数
- DATABASE_PATH 为绝对路径（避免因工作目录不同而连到"另一个"数据库）
- Config.DATABASE_PATH 与模块级 DATABASE_PATH 保持一致（单一事实来源）
"""
from __future__ import annotations

import dataclasses
import os

import pytest

import config
from config import Config


# ─── 阈值合理性 ────────────────────────────────────────────────────────

def test_thresholds_are_positive():
    """所有关键阈值必须是正数，否则运行时会异常。"""
    cfg = Config()
    assert cfg.ATTENTION_THRESHOLD > 0
    assert cfg.OLLAMA_TIMEOUT > 0
    assert cfg.MAX_CHAT_HISTORY > 0
    assert cfg.REINFORCEMENT_INTERVAL > 0


def test_attention_threshold_default():
    # ASD 特化注意力阈值默认 8.0（秒）
    assert Config().ATTENTION_THRESHOLD == 8.0


def test_ollama_timeout_default():
    # LLM 单次请求超时默认 60s
    assert Config().OLLAMA_TIMEOUT == 60.0


def test_max_chat_history_default():
    # 对话历史上限默认 200，防止长时间运行内存无界增长
    assert Config().MAX_CHAT_HISTORY == 200


def test_sensory_friendly_volume_in_range():
    # 感官友好音量应落在 (0, 1] 合理区间
    volume = Config().SENSORY_FRIENDLY_VOLUME
    assert 0.0 < volume <= 1.0


# ─── 路径 ──────────────────────────────────────────────────────────────

def test_database_path_is_absolute():
    """R11 修复：数据库路径必须是绝对路径。"""
    assert os.path.isabs(Config().DATABASE_PATH)
    assert os.path.isabs(config.DATABASE_PATH)


def test_database_path_consistency():
    """类字段与模块级变量必须一致（单一事实来源）。"""
    assert Config.DATABASE_PATH == config.DATABASE_PATH
    assert Config().DATABASE_PATH == config.DATABASE_PATH


def test_database_path_default_location():
    """在无环境变量覆盖时，默认落在项目 data/ 目录下。"""
    if os.environ.get("SOULCOMPANION_DB"):
        pytest.skip("SOULCOMPANION_DB 覆盖了默认路径")
    assert Config().DATABASE_PATH == os.path.join(
        config.DATA_DIR, "emotional_db.sqlite"
    )
    assert Config().DATABASE_PATH.startswith(config.DATA_DIR)
    assert Config().DATABASE_PATH.endswith(".sqlite")


def test_base_and_data_dir_are_absolute():
    assert os.path.isabs(config.BASE_DIR)
    assert os.path.isabs(config.DATA_DIR)


# ─── 不变性与其它字段 ──────────────────────────────────────────────────

def test_config_is_frozen():
    """Config 是 frozen dataclass，运行时不可被意外修改。"""
    cfg = Config()
    with pytest.raises(dataclasses.FrozenInstanceError):
        cfg.MAX_CHAT_HISTORY = 10  # type: ignore[misc]


def test_ollama_endpoints_nonempty():
    cfg = Config()
    assert cfg.OLLAMA_MODEL
    assert cfg.OLLAMA_URL.startswith("http")


def test_log_level_uppercased():
    assert config.LOG_LEVEL == config.LOG_LEVEL.upper()
