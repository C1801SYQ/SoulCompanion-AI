"""emotion/bridge.py 单元测试（完整管线，零重依赖）。

覆盖 R11 修复点：
- 传感器读取容错（getter 抛异常 / 返回 None 不中断周期）
- 语音新鲜度去重（seq 去重 + 时间窗）
- 记忆写入去重/限频（_should_record）
- 完整周期后的 snapshot 更新、回调、启动/停止
"""
from __future__ import annotations

import time

import pytest

from emotion.bridge import EmotionBridge, EmotionSnapshot, create_bridge
from emotion.models import EmotionCategory, EmotionState, InterventionType


def _bridge(tmp_path, vision=None, speech=None, env=None, **kwargs) -> EmotionBridge:
    db = str(tmp_path / "bridge.sqlite")
    return EmotionBridge(
        get_vision_state=vision
        or (lambda: {"face_detected": True, "emotion": "happy"}),
        get_speech_state=speech
        or (lambda: {"emotion": "happy", "text": "你好", "seq": 1}),
        env_signals={"hour": 12} if env is None else env,
        db_path=db,
        cycle_interval=0.01,
        **kwargs,
    )


# ─── 单周期处理 & 快照 ─────────────────────────────────────────────────

def test_single_cycle_updates_snapshot(tmp_path):
    b = _bridge(tmp_path)
    b._process_cycle()
    snap = b.get_snapshot()
    assert isinstance(snap, EmotionSnapshot)
    assert snap.cycle_count == 1
    assert snap.emotion.category is EmotionCategory.HAPPY
    assert snap.emotion.attention_level == pytest.approx(1.0)
    assert snap.behavior.actions
    assert snap.last_update


def test_cycles_accumulate(tmp_path):
    b = _bridge(tmp_path)
    for _ in range(3):
        b._process_cycle()
    assert b.get_snapshot().cycle_count == 3


def test_snapshot_default_shape():
    snap = EmotionSnapshot()
    assert snap.emotion.category is EmotionCategory.NEUTRAL
    assert snap.intervention_type == "none"
    assert snap.has_risk is False
    assert snap.risk_triggers == []
    # R12：桥接器尚未出首轮数据时，注意力"未知"= 0.5（既不奖励也不惩罚），
    # 不再默认 1.0（那会把"未知"渲染成"满注意力"）。
    assert snap.attention_level == pytest.approx(0.5)


# ─── 传感器读取容错 ────────────────────────────────────────────────────

def test_read_vision_handles_exception(tmp_path):
    def boom():
        raise RuntimeError("sensor down")

    b = _bridge(tmp_path, vision=boom)
    assert b._read_vision() == {}


def test_read_vision_none_returns_empty(tmp_path):
    b = _bridge(tmp_path, vision=lambda: None)
    assert b._read_vision() == {}


def test_read_speech_handles_exception(tmp_path):
    def boom():
        raise RuntimeError("mic down")

    b = _bridge(tmp_path, speech=boom)
    assert b._read_speech() is None


def test_read_speech_none_returns_none(tmp_path):
    b = _bridge(tmp_path, speech=lambda: None)
    assert b._read_speech() is None


def test_cycle_survives_failing_getters(tmp_path):
    def boom():
        raise RuntimeError("down")

    b = _bridge(tmp_path, vision=boom, speech=boom)
    b._process_cycle()  # 不应抛异常
    assert b.get_snapshot().cycle_count == 1


# ─── 语音新鲜度去重 ────────────────────────────────────────────────────

def test_read_speech_seq_dedup_fresh(tmp_path):
    b = _bridge(tmp_path, speech=lambda: {"emotion": "happy", "seq": 7})
    assert b._read_speech() is not None
    assert b._read_speech() is not None  # 同一句在新鲜期内仍有效


def test_read_speech_stale_seq_dropped(tmp_path):
    b = _bridge(tmp_path, speech=lambda: {"emotion": "happy", "seq": 7})
    b._read_speech()
    b._last_speech_time = time.time() - (b._speech_freshness + 5)
    assert b._read_speech() is None


def test_read_speech_new_seq_refreshes(tmp_path):
    holder = {"seq": 1}
    b = _bridge(tmp_path, speech=lambda: {"emotion": "happy", "seq": holder["seq"]})
    b._read_speech()
    b._last_speech_time = time.time() - (b._speech_freshness + 5)
    holder["seq"] = 2  # 新语句应被重新采信
    assert b._read_speech() is not None


def test_read_speech_without_seq_always_fresh(tmp_path):
    b = _bridge(tmp_path, speech=lambda: {"emotion": "happy"})
    assert b._read_speech() is not None
    assert b._read_speech() is not None


# ─── 记忆写入去重 / 限频 ───────────────────────────────────────────────

def test_should_record_dedup_and_change(tmp_path):
    b = _bridge(tmp_path)
    s1 = EmotionState(category=EmotionCategory.HAPPY, valence=0.8)
    assert b._should_record(s1) is True   # 首次必写
    assert b._should_record(s1) is False  # 无变化且未到心跳
    s2 = EmotionState(category=EmotionCategory.HAPPY, valence=-0.6)  # 档位变化
    assert b._should_record(s2) is True
    s3 = EmotionState(category=EmotionCategory.SAD, valence=-0.6)  # 类别变化
    assert b._should_record(s3) is True


def test_should_record_heartbeat(tmp_path):
    b = _bridge(tmp_path)
    s = EmotionState(category=EmotionCategory.HAPPY, valence=0.8)
    assert b._should_record(s) is True
    b._last_record_time = time.time() - (b._record_heartbeat + 1)
    assert b._should_record(s) is True  # 越过心跳窗口补记基线


def test_record_writes_to_memory(tmp_path):
    b = _bridge(tmp_path)
    b._process_cycle()
    # 首个周期 signature 变化 → 至少写入 1 条
    records = b.get_memory().get_records()
    assert len(records) >= 1


# ─── 回调 ──────────────────────────────────────────────────────────────

def test_callbacks_fire(tmp_path):
    b = _bridge(tmp_path)
    fired = {"intervention": [], "behavior": []}
    b.set_callbacks(
        on_intervention=lambda p: fired["intervention"].append(p),
        on_behavior=lambda c: fired["behavior"].append(c),
    )
    b._process_cycle()
    assert len(fired["behavior"]) == 1
    assert len(fired["intervention"]) == 1
    assert (
        fired["intervention"][0].intervention_type
        is InterventionType.POSITIVE_REINFORCE
    )


def test_callback_exception_does_not_break_cycle(tmp_path):
    b = _bridge(tmp_path)

    def boom(_):
        raise RuntimeError("callback down")

    b.set_callbacks(on_behavior=boom)
    b._process_cycle()  # 回调异常被捕获，周期仍完成
    assert b.get_snapshot().cycle_count == 1


def test_distressed_cycle_marks_parent_alert(tmp_path):
    b = _bridge(
        tmp_path,
        vision=lambda: {},
        speech=lambda: None,
        env={"bio_anxiety": 0.95},
    )
    b._process_cycle()
    snap = b.get_snapshot()
    assert snap.emotion.category is EmotionCategory.DISTRESSED
    assert snap.parent_alert is True
    assert snap.guidance_text


def test_attention_propagates_to_snapshot(tmp_path):
    def vision():
        return {"face_detected": False, "attention_loss_time": 10.0}

    b = _bridge(tmp_path, vision=vision, speech=lambda: {"emotion": "happy", "seq": 1})
    b._process_cycle()
    assert b.get_snapshot().attention_level == pytest.approx(0.0)


# ─── 引擎访问器 / 线程生命周期 ─────────────────────────────────────────

def test_engine_accessors(tmp_path):
    b = _bridge(tmp_path)
    assert b.get_memory() is not None
    assert b.get_fusion_engine() is not None
    assert b.get_intervention_engine() is not None
    assert b.get_behavior_sync() is not None
    assert b.get_embodied_engine() is not None


def test_start_stop_thread(tmp_path):
    b = _bridge(tmp_path)
    b.start()
    time.sleep(0.1)
    assert b.is_running is True
    assert b.get_snapshot().cycle_count >= 1
    b.stop()
    assert b.is_running is False


def test_start_twice_is_safe(tmp_path):
    b = _bridge(tmp_path)
    b.start()
    b.start()  # 第二次应被忽略而非重复启动
    assert b.is_running is True
    b.stop()


def test_factory(tmp_path):
    b = create_bridge(
        get_vision_state=lambda: {},
        get_speech_state=lambda: None,
        db_path=str(tmp_path / "f.sqlite"),
    )
    assert isinstance(b, EmotionBridge)
