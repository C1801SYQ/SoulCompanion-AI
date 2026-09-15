"""R12 收尾测试：技术债修复 + 静态站点构建。

覆盖：
1. 注意力阈值共享常量被 behavior_sync / intervention 正确引用（单一数据源）。
2. EmotionSnapshot 默认 attention_level == 0.5（视觉未知约定）。
3. _is_in_cooldown 语义与 R11 等价（高紧急度走短冷却，其余走完整冷却）。
4. 融合的 ASD 视觉优先集合不再包含不可达的 DISTRESSED。
5. scripts/build_site.py 能构建出结构正确、无 Jinja 残留的 dist-site。
"""
from __future__ import annotations

import importlib.util
import os

import pytest

from emotion.behavior_sync import BehaviorSync
from emotion.bridge import EmotionSnapshot
from emotion.fusion_engine import ASD_VISION_PRIORITY, VISION_EMOTION_MAP, FusionEngine
from emotion.intervention import InterventionEngine
from emotion.models import (
    ATTENTION_THRESHOLD_LOW as MODELS_ATTENTION_THRESHOLD_LOW,
)
from emotion.models import EmotionCategory, EmotionState

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ─── 1. 共享阈值（单一数据源）──────────────────────────────────────────

def test_shared_attention_threshold_is_single_source():
    """behavior_sync 与 intervention 都从 emotion.models 引用同一常量。"""
    from emotion.behavior_sync import ATTENTION_THRESHOLD_LOW as B
    from emotion.intervention import ATTENTION_THRESHOLD_LOW as I

    assert MODELS_ATTENTION_THRESHOLD_LOW == 0.3
    assert B is MODELS_ATTENTION_THRESHOLD_LOW
    assert I is MODELS_ATTENTION_THRESHOLD_LOW


def test_behavior_sync_uses_shared_threshold():
    """阈值确实驱动低注意力行为（< 0.3 触发），而非硬编码失配值。"""
    sync = BehaviorSync()
    from emotion.models import BehaviorAction

    low = sync.sync(EmotionState(category=EmotionCategory.NEUTRAL, attention_level=0.29))
    high = sync.sync(EmotionState(category=EmotionCategory.NEUTRAL, attention_level=0.31))
    assert BehaviorAction.HEAD_TILT in low.actions
    assert BehaviorAction.HEAD_TILT not in high.actions


def test_intervention_uses_shared_threshold():
    eng = InterventionEngine()
    low = eng.evaluate(EmotionState(category=EmotionCategory.NEUTRAL, attention_level=0.25))
    high = eng.evaluate(EmotionState(category=EmotionCategory.NEUTRAL, attention_level=0.5))
    assert low.metadata.get("reason") == "attention_low"
    assert high.intervention_type.value == "none"


# ─── 2. 快照默认注意力 = 0.5（视觉未知约定）────────────────────────────

def test_snapshot_default_attention_is_unknown_neutral():
    snap = EmotionSnapshot()
    assert snap.attention_level == pytest.approx(0.5)
    # 0.5 高于两个注意力阈值，既不奖励也不惩罚
    assert snap.attention_level >= MODELS_ATTENTION_THRESHOLD_LOW


# ─── 3. 冷却语义等价 ──────────────────────────────────────────────────

def _expected_in_cooldown(engine, last_seconds_ago, last_urgency, urgency):
    """独立复刻"文档所述语义"，作为对照实现。"""
    if last_seconds_ago is None:
        return False
    if urgency in ("high",):
        return last_seconds_ago < engine.urgent_cooldown_seconds
    return last_seconds_ago < engine.cooldown_seconds


@pytest.mark.parametrize(
    "elapsed,last_urgency,urgency",
    [
        (3, "low", "high"),
        (10, "low", "high"),
        (3, "low", "medium"),
        (10, "low", "medium"),
        (31, "low", "low"),
        (10, "high", "low"),
        (31, "high", "low"),
        (5, "high", "medium"),
        (35, "medium", "low"),
    ],
)
def test_cooldown_semantics_unchanged(monkeypatch, elapsed, last_urgency, urgency):
    from datetime import datetime, timedelta

    eng = InterventionEngine()
    eng._last_urgency = last_urgency
    eng._last_intervention_time = datetime.now() - timedelta(seconds=elapsed)
    assert eng._is_in_cooldown(urgency) == _expected_in_cooldown(
        eng, elapsed, last_urgency, urgency
    )


def test_cooldown_no_prior_intervention_is_free():
    eng = InterventionEngine()
    assert eng._last_intervention_time is None
    assert eng._is_in_cooldown("high") is False
    assert eng._is_in_cooldown("low") is False


# ─── 4. 融合规则不再含不可达分支 ──────────────────────────────────────

def test_asd_vision_priority_excludes_distressed():
    """DISTRESSED 不来自视觉通道，故不在视觉优先集合里（死分支已移除）。"""
    assert ASD_VISION_PRIORITY == frozenset(
        {EmotionCategory.ANXIOUS, EmotionCategory.FEARFUL}
    )
    assert EmotionCategory.DISTRESSED not in ASD_VISION_PRIORITY


def test_vision_map_never_produces_distressed():
    """VISION_EMOTION_MAP 永不产出 DISTRESSED（佐证上一条）。"""
    assert EmotionCategory.DISTRESSED not in set(VISION_EMOTION_MAP.values())


def test_vision_disgust_maps_to_anxious_documented():
    """现状：disgust → anxious（仅在源码加注释说明，未改语义）。"""
    assert VISION_EMOTION_MAP["disgust"] is EmotionCategory.ANXIOUS
    state = FusionEngine().fuse(
        vision_state={"face_detected": True, "emotion": "disgust"},
        speech_state={"emotion": "happy"},
    )
    assert state.category is EmotionCategory.ANXIOUS
    assert state.confidence >= 0.6


# ─── 5. 静态站点构建 ──────────────────────────────────────────────────

def _load_build_site():
    path = os.path.join(ROOT, "scripts", "build_site.py")
    spec = importlib.util.spec_from_file_location("build_site", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_build_site_produces_expected_structure(tmp_path):
    build_site = _load_build_site()
    out = str(tmp_path / "dist-site")
    report = build_site.build(out_dir=out, project_root=ROOT)

    assert os.path.isfile(os.path.join(out, "index.html"))
    for name in ("style.css", "app.js", "demo-data.js"):
        assert os.path.isfile(os.path.join(out, "static", name)), name
    for name in ("_headers", "robots.txt", "404.html"):
        assert os.path.isfile(os.path.join(out, name)), name
    assert report["out_dir"] == os.path.abspath(out)


def test_build_site_index_has_no_jinja_residue(tmp_path):
    build_site = _load_build_site()
    out = str(tmp_path / "dist-site")
    build_site.build(out_dir=out, project_root=ROOT)

    with open(os.path.join(out, "index.html"), encoding="utf-8") as fh:
        html = fh.read()
    assert "{{" not in html
    assert "{%" not in html
    # 保留 /static/ 绝对路径
    assert "/static/app.js" in html
    assert "/static/demo-data.js" in html
    # demo-data.js 必须在 app.js 之前加载（按脚本标签位置比较）
    assert html.index('<script src="/static/demo-data.js">') < html.index(
        '<script src="/static/app.js">'
    )


def test_build_site_is_idempotent(tmp_path):
    build_site = _load_build_site()
    out = str(tmp_path / "dist-site")
    build_site.build(out_dir=out, project_root=ROOT)
    first = sorted(os.listdir(os.path.join(out, "static")))
    build_site.build(out_dir=out, project_root=ROOT)  # 再跑一次不应报错
    second = sorted(os.listdir(os.path.join(out, "static")))
    assert first == second
    assert os.path.isfile(os.path.join(out, "index.html"))


def test_transform_strips_jinja():
    build_site = _load_build_site()
    out = build_site.transform_dashboard("<h1>{{ title }}</h1>{% if x %}y{% endif %}")
    assert "{{" not in out and "{%" not in out
    assert out == "<h1></h1>y"
