"""
streamlit_dashboard.py - Streamlit Cloud Deployment Entry Point

A lightweight Streamlit version of the emotion dashboard.
Deployable to Streamlit Cloud with zero configuration.

Usage:
    streamlit run streamlit_dashboard.py

Deployment:
    1. Push to GitHub
    2. Connect to https://share.streamlit.io
    3. Set main file: streamlit_dashboard.py
"""
from __future__ import annotations

import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import streamlit as st
from datetime import datetime

# Page config
st.set_page_config(
    page_title="小予情绪智能仪表板",
    page_icon="💠",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ─── Custom CSS ───────────────────────────────────────────────────────
st.markdown("""
<style>
    .main { background-color: #f5f7fa; }
    .stMetric {
        background-color: #ffffff;
        padding: 15px;
        border-radius: 10px;
        box-shadow: 0 2px 4px rgba(0,0,0,0.05);
    }
    .panel-card {
        background: white;
        border-radius: 12px;
        padding: 20px;
        box-shadow: 0 2px 8px rgba(0,0,0,0.08);
        margin-bottom: 16px;
    }
    .emotion-badge {
        font-size: 3rem;
        text-align: center;
        padding: 20px;
    }
    .emotion-label {
        font-size: 1.5rem;
        font-weight: 700;
        text-align: center;
    }
    .health-ring {
        text-align: center;
        font-size: 3rem;
        font-weight: 700;
        color: #4CAF50;
    }
    .risk-alert {
        background: #FFF3E0;
        border: 1px solid #FFB74D;
        border-radius: 8px;
        padding: 12px;
        margin-top: 12px;
    }
</style>
""", unsafe_allow_html=True)

# ─── Initialize Modules ──────────────────────────────────────────────
@st.cache_resource
def init_modules():
    """Initialize emotion modules (cached for performance)."""
    from emotion.memory_axis import MemoryAxis
    from emotion.fusion_engine import FusionEngine
    from emotion.behavior_sync import BehaviorSync
    from emotion.intervention import InterventionEngine

    memory = MemoryAxis()
    fusion = FusionEngine(memory_axis=memory)
    behavior = BehaviorSync()
    intervention = InterventionEngine(memory_axis=memory)

    return {
        "memory": memory,
        "fusion": fusion,
        "behavior": behavior,
        "intervention": intervention,
    }

modules = init_modules()

# ─── Header ───────────────────────────────────────────────────────────
st.title("💠 小予情绪智能仪表板")
st.caption(f"SoulCompanion AI - ASD儿童多模态情绪监控 | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

# ─── Main Layout ──────────────────────────────────────────────────────
col_top_left, col_top_right = st.columns(2)
col_bottom_left, col_bottom_right = st.columns([2, 1])

# ─── Panel 1: Emotion Live ───────────────────────────────────────────
with col_top_left:
    st.markdown("### 🧠 实时情绪状态")

    EMOTION_ICONS = {
        "happy": "😊", "calm": "😌", "neutral": "😐", "surprised": "😮",
        "anxious": "😰", "sad": "😢", "angry": "😠", "fearful": "😨", "distressed": "😵",
    }
    EMOTION_LABELS = {
        "happy": "开心", "calm": "平静", "neutral": "中性", "surprised": "惊讶",
        "anxious": "焦虑", "sad": "难过", "angry": "生气", "fearful": "害怕", "distressed": "过载",
    }

    # Get current state from fusion engine
    state = modules["fusion"].get_last_state()
    cat = state.category.value if hasattr(state.category, 'value') else str(state.category)

    icon = EMOTION_ICONS.get(cat, "😐")
    label = EMOTION_LABELS.get(cat, "中性")

    st.markdown(f'<div class="emotion-badge">{icon}</div>', unsafe_allow_html=True)
    st.markdown(f'<div class="emotion-label">{label}</div>', unsafe_allow_html=True)

    m1, m2, m3 = st.columns(3)
    m1.metric("置信度", f"{state.confidence:.2f}")
    m2.metric("效价", f"{state.valence:.2f}")
    m3.metric("唤醒度", f"{state.arousal:.2f}")

    if state.emotional_cause:
        st.info(f"💭 {state.emotional_cause}")

# ─── Panel 2: Behavior Monitor ───────────────────────────────────────
with col_top_right:
    st.markdown("### 🤖 行为同步状态")

    ACTION_LABELS = {
        "heartbeat": "💓 心跳模拟", "breathing_led": "💡 呼吸灯",
        "ear_wiggle": "👂 耳朵摆动", "head_tilt": "🤔 好奇歪头",
        "soothing_voice": "🗣️ 温柔语音", "excited_voice": "🗣️ 欢快语音",
        "slow_motion": "🦽 缓慢运动", "still": "🧊 静止模式",
        "led_warm": "💡 暖色灯", "led_cool": "💡 冷色灯", "led_dim": "💡 柔光灯",
    }

    cmd = modules["behavior"].sync(state)
    actions_text = ", ".join(ACTION_LABELS.get(a.value, a.value) for a in cmd.actions)

    st.markdown(f"**当前动作:** {actions_text}")
    st.markdown(f"**LED:** {cmd.led_color} 亮度 {cmd.led_brightness:.0%}")
    st.markdown(f"**语速:** {cmd.speech_rate:.1f}x | **动作速度:** {cmd.servo_speed:.1f}")

    if cmd.reason:
        st.caption(f"原因: {cmd.reason}")

# ─── Panel 3: Emotion Timeline ───────────────────────────────────────
with col_bottom_left:
    st.markdown("### 📈 情绪趋势")

    trend = modules["memory"].get_trend_analysis(period="daily")
    dom_label = EMOTION_LABELS.get(trend.dominant_emotion, "中性")

    t1, t2, t3, t4 = st.columns(4)
    t1.metric("主导情绪", dom_label)
    t2.metric("平均效价", f"{trend.average_valence:.2f}")
    t3.metric("稳定性", f"{trend.stability_score:.0%}")
    t4.metric("记录数", trend.total_records)

    # Valence series chart
    series = modules["memory"].get_valence_series(days=7)
    if series:
        import pandas as pd
        df = pd.DataFrame(series, columns=["timestamp", "valence"])
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df = df.set_index("timestamp")
        st.line_chart(df["valence"], height=200)
    else:
        st.info("暂无足够数据绘制趋势图")

    # Emotion distribution
    counts = modules["memory"].get_emotion_counts(days=7)
    if counts:
        dist_text = " | ".join(
            f"{EMOTION_ICONS.get(cat, '❓')} {EMOTION_LABELS.get(cat, cat)}: {cnt}"
            for cat, cnt in sorted(counts.items(), key=lambda x: -x[1])
        )
        st.markdown(f"**情绪分布:** {dist_text}")

# ─── Panel 4: Parent Insight ─────────────────────────────────────────
with col_bottom_right:
    st.markdown("### 👨‍👩‍👦 家长洞察")

    report = modules["intervention"].generate_parent_report(days=7)

    # Health score
    score = report.health_score
    score_color = "#66BB6A" if score >= 70 else ("#FFB74D" if score >= 40 else "#EF5350")
    st.markdown(
        f'<div class="health-ring" style="color:{score_color}">{score:.0f}</div>',
        unsafe_allow_html=True,
    )
    st.caption("情绪健康指数 (0-100)")

    st.markdown(f"**本周评价:** {report.summary}")

    if report.highlights:
        st.markdown("**✨ 亮点:**")
        for h in report.highlights:
            st.markdown(f"- {h}")

    if report.concerns:
        st.markdown("**⚠️ 关注:**")
        for c in report.concerns:
            st.markdown(f"- {c}")

    if report.suggestions:
        st.markdown("**💡 建议:**")
        for s in report.suggestions:
            st.markdown(f"- {s}")

    # Risk alerts
    triggers = modules["memory"].check_risk_triggers(window_minutes=60)
    if triggers:
        st.markdown('<div class="risk-alert">🚨 <b>风险提醒:</b></div>', unsafe_allow_html=True)
        for t in triggers:
            st.warning(t)

# ─── Footer ───────────────────────────────────────────────────────────
st.divider()
st.caption("SoulCompanion AI v1.0.0 | ASD儿童智能陪伴干预机器人 | 数据仅在本地存储")
