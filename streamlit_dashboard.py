"""
streamlit_dashboard.py - Streamlit Cloud Deployment Entry Point

A self-contained Streamlit dashboard for the emotion intelligence system.
Works with real robot data OR demo data (cloud deployment).

Deploy to Streamlit Cloud:
    1. Push this repo to GitHub
    2. Connect at https://share.streamlit.io
    3. Set main file: streamlit_dashboard.py
    4. Get public URL: https://你的app名.streamlit.app
"""
from __future__ import annotations

import sys
import os
import random
from datetime import datetime, timedelta

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import streamlit as st

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
    .emotion-badge {
        font-size: 4rem;
        text-align: center;
        padding: 10px;
    }
    .emotion-label {
        font-size: 1.8rem;
        font-weight: 700;
        text-align: center;
    }
    .health-ring {
        text-align: center;
        font-size: 3.5rem;
        font-weight: 700;
    }
    .risk-alert {
        background: #FFF3E0;
        border: 1px solid #FFB74D;
        border-radius: 8px;
        padding: 12px;
    }
    .section-card {
        background: white;
        border-radius: 12px;
        padding: 20px;
        box-shadow: 0 2px 8px rgba(0,0,0,0.08);
        margin-bottom: 16px;
    }
    div[data-testid="stMetricValue"] { font-size: 1.3rem; }
</style>
""", unsafe_allow_html=True)

# ─── Emotion Mappings ─────────────────────────────────────────────────
EMOTION_ICONS = {
    "happy": "😊", "calm": "😌", "neutral": "😐", "surprised": "😮",
    "anxious": "😰", "sad": "😢", "angry": "😠", "fearful": "😨", "distressed": "😵",
}
EMOTION_LABELS = {
    "happy": "开心", "calm": "平静", "neutral": "中性", "surprised": "惊讶",
    "anxious": "焦虑", "sad": "难过", "angry": "生气", "fearful": "害怕", "distressed": "过载",
}
EMOTION_COLORS = {
    "happy": "#FFD700", "calm": "#87CEEB", "neutral": "#4CAF50", "surprised": "#FF9800",
    "anxious": "#FF9800", "sad": "#7986CB", "angry": "#EF5350", "fearful": "#B39DDB", "distressed": "#FF5722",
}

# ─── Initialize Modules (cached) ─────────────────────────────────────
@st.cache_resource
def init_modules():
    """Initialize emotion modules with error handling."""
    try:
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
            "mode": "live",
        }
    except Exception as e:
        st.warning(f"模块初始化警告: {e}")
        return {"mode": "demo", "error": str(e)}

modules = init_modules()
is_demo = modules.get("mode") == "demo"

# ─── Demo Data Generator ─────────────────────────────────────────────
def generate_demo_state():
    """Generate a realistic demo emotion state."""
    import time
    # Use time-based seed for slowly changing emotions
    seed = int(time.time() / 10)  # Changes every 10 seconds
    random.seed(seed)

    categories = ["happy", "neutral", "calm", "anxious", "sad"]
    weights = [0.3, 0.3, 0.2, 0.1, 0.1]
    cat = random.choices(categories, weights=weights, k=1)[0]

    valence_map = {"happy": 0.7, "calm": 0.3, "neutral": 0.0, "anxious": -0.4, "sad": -0.7}
    arousal_map = {"happy": 0.7, "calm": 0.2, "neutral": 0.3, "anxious": 0.7, "sad": 0.3}

    return {
        "category": cat,
        "confidence": round(random.uniform(0.6, 0.95), 2),
        "valence": valence_map.get(cat, 0.0) + random.uniform(-0.1, 0.1),
        "arousal": arousal_map.get(cat, 0.5) + random.uniform(-0.1, 0.1),
        "vision_emotion": cat,
        "speech_emotion": random.choice(["neutral", cat]),
        "environment_signal": "normal",
        "emotional_cause": "",
        "attention_level": round(random.uniform(0.5, 1.0), 2),
    }

def generate_demo_history(days=7, records_per_day=10):
    """Generate demo emotion history data."""
    from emotion.models import EmotionRecord
    records = []
    now = datetime.now()
    categories = ["happy", "neutral", "calm", "anxious", "sad"]

    for d in range(days):
        for r in range(records_per_day):
            ts = now - timedelta(days=d, hours=random.randint(8, 20), minutes=random.randint(0, 59))
            cat = random.choices(categories, weights=[0.3, 0.3, 0.2, 0.1, 0.1], k=1)[0]
            valence_map = {"happy": 0.7, "calm": 0.3, "neutral": 0.0, "anxious": -0.4, "sad": -0.7}
            records.append(EmotionRecord(
                timestamp=ts.isoformat(),
                category=cat,
                valence=valence_map.get(cat, 0.0) + random.uniform(-0.1, 0.1),
                arousal=random.uniform(0.2, 0.8),
                context="demo",
            ))
    return sorted(records, key=lambda r: r.timestamp, reverse=True)

# ─── Get Current State ────────────────────────────────────────────────
if is_demo:
    current = generate_demo_state()
else:
    state = modules["fusion"].get_last_state()
    current = {
        "category": state.category.value if hasattr(state.category, 'value') else str(state.category),
        "confidence": state.confidence,
        "valence": state.valence,
        "arousal": state.arousal,
        "vision_emotion": state.vision_emotion,
        "speech_emotion": state.speech_emotion,
        "environment_signal": state.environment_signal,
        "emotional_cause": state.emotional_cause,
        "attention_level": state.attention_level,
    }

cat = current["category"]
icon = EMOTION_ICONS.get(cat, "😐")
label = EMOTION_LABELS.get(cat, "中性")
color = EMOTION_COLORS.get(cat, "#4CAF50")

# ─── Header ───────────────────────────────────────────────────────────
mode_badge = "🟢 实时数据" if not is_demo else "🟡 演示数据"
st.title("💠 小予情绪智能仪表板")
st.caption(f"SoulCompanion AI - ASD儿童多模态情绪监控 | {mode_badge} | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

# ─── Main Layout ──────────────────────────────────────────────────────
col_top_left, col_top_right = st.columns(2)
col_bottom_left, col_bottom_right = st.columns([2, 1])

# ─── Panel 1: Emotion Live ───────────────────────────────────────────
with col_top_left:
    st.markdown("### 🧠 实时情绪状态")

    st.markdown(f'<div class="emotion-badge">{icon}</div>', unsafe_allow_html=True)
    st.markdown(f'<div class="emotion-label" style="color:{color}">{label}</div>', unsafe_allow_html=True)

    m1, m2, m3 = st.columns(3)
    m1.metric("置信度", f"{current['confidence']:.2f}")
    m2.metric("效价", f"{current['valence']:.2f}")
    m3.metric("唤醒度", f"{current['arousal']:.2f}")

    st.progress(current["attention_level"], text=f"注意力: {current['attention_level']:.0%}")

    st.markdown(f"""
    | 信号源 | 状态 |
    |--------|------|
    | 👁️ 视觉 | {EMOTION_LABELS.get(current['vision_emotion'], '--')} |
    | 🎤 语音 | {EMOTION_LABELS.get(current['speech_emotion'], '--')} |
    | 🌡️ 环境 | {current['environment_signal']} |
    """)

    if current.get("emotional_cause"):
        st.info(f"💭 {current['emotional_cause']}")

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

    if not is_demo:
        cmd = modules["behavior"].sync(modules["fusion"].get_last_state())
        actions = [a.value for a in cmd.actions]
        led_color = cmd.led_color
        led_brightness = cmd.led_brightness
        speech_rate = cmd.speech_rate
        servo_speed = cmd.servo_speed
        reason = cmd.reason
    else:
        # Demo behavior based on current emotion
        behavior_map = {
            "happy": (["ear_wiggle", "led_warm", "excited_voice"], "#FFD700", 0.8, 1.2, 0.7),
            "neutral": (["breathing_led"], "#4CAF50", 0.6, 1.0, 0.5),
            "calm": (["breathing_led", "soothing_voice"], "#87CEEB", 0.5, 0.9, 0.3),
            "anxious": (["heartbeat", "breathing_led", "soothing_voice"], "#64B5F6", 0.4, 0.7, 0.2),
            "sad": (["heartbeat", "soothing_voice", "slow_motion"], "#7986CB", 0.3, 0.7, 0.2),
        }
        b = behavior_map.get(cat, behavior_map["neutral"])
        actions, led_color, led_brightness, speech_rate, servo_speed = b
        reason = f"情绪={label}"

    actions_text = " ".join(ACTION_LABELS.get(a, a) for a in actions)
    st.markdown(f"**当前动作:** {actions_text}")

    st.markdown(f"""
    | 参数 | 值 |
    |------|-----|
    | 💡 LED | {led_color} 亮度 {led_brightness:.0%} |
    | 🗣️ 语速 | {speech_rate:.1f}x |
    | 🦽 动作速度 | {servo_speed:.1f} |
    """)

    if reason:
        st.caption(f"原因: {reason}")

# ─── Panel 3: Emotion Timeline ───────────────────────────────────────
with col_bottom_left:
    st.markdown("### 📈 情绪趋势")

    time_range = st.selectbox("时间范围", ["1天", "7天", "30天"], index=1, key="time_range")
    days_map = {"1天": 1, "7天": 7, "30天": 30}
    days = days_map[time_range]

    if not is_demo:
        trend = modules["memory"].get_trend_analysis(period="daily")
        series = modules["memory"].get_valence_series(days=days)
        counts = modules["memory"].get_emotion_counts(days=days)
    else:
        # Generate demo trend data
        records = generate_demo_history(days=days)
        valences = [r.valence for r in records]
        avg_v = sum(valences) / len(valences) if valences else 0
        from collections import Counter
        counts = Counter(r.category for r in records)
        series = [(r.timestamp, r.valence) for r in records[:50]]

        class DemoTrend:
            dominant_emotion = max(counts, key=counts.get) if counts else "neutral"
            average_valence = avg_v
            stability_score = 0.75
            total_records = len(records)
        trend = DemoTrend()

    # Trend summary
    dom_label = EMOTION_LABELS.get(trend.dominant_emotion, "中性")
    t1, t2, t3, t4 = st.columns(4)
    t1.metric("主导情绪", dom_label)
    t2.metric("平均效价", f"{trend.average_valence:.2f}")
    t3.metric("稳定性", f"{trend.stability_score:.0%}")
    t4.metric("记录数", trend.total_records)

    # Valence chart
    if series:
        import pandas as pd
        df = pd.DataFrame(series, columns=["timestamp", "valence"])
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df = df.set_index("timestamp")
        st.line_chart(df["valence"], height=200)
    else:
        st.info("暂无足够数据绘制趋势图")

    # Emotion distribution
    if counts:
        total = sum(counts.values())
        dist_items = sorted(counts.items(), key=lambda x: -x[1])
        dist_cols = st.columns(min(len(dist_items), 5))
        for i, (emo, cnt) in enumerate(dist_items[:5]):
            with dist_cols[i % len(dist_cols)]:
                pct = cnt / total * 100
                st.metric(
                    f"{EMOTION_ICONS.get(emo, '❓')} {EMOTION_LABELS.get(emo, emo)}",
                    f"{pct:.0f}%",
                )

# ─── Panel 4: Parent Insight ─────────────────────────────────────────
with col_bottom_right:
    st.markdown("### 👨‍👩‍👦 家长洞察")

    if not is_demo:
        report = modules["intervention"].generate_parent_report(days=7)
        score = report.health_score
        summary = report.summary
        highlights = report.highlights
        concerns = report.concerns
        suggestions = report.suggestions
    else:
        # Demo report
        score = 72.5
        summary = "本周整体情绪状态良好，孩子表现出较多积极情绪。注意力水平有提升空间。"
        highlights = ["开心时刻 12 次", "情绪稳定性良好", "社交互动频率增加"]
        concerns = ["下午时段注意力偏低", "偶尔出现焦虑情绪"]
        suggestions = ["建议增加户外活动时间", "下午时段可安排轻松的游戏"]

    # Health score
    score_color = "#66BB6A" if score >= 70 else ("#FFB74D" if score >= 40 else "#EF5350")
    st.markdown(f'<div class="health-ring" style="color:{score_color}">{score:.0f}</div>', unsafe_allow_html=True)
    st.caption("情绪健康指数 (0-100)")

    st.markdown(f"**本周评价:** {summary}")

    if highlights:
        st.markdown("**✨ 亮点:**")
        for h in highlights:
            st.markdown(f"- {h}")

    if concerns:
        st.markdown("**⚠️ 关注:**")
        for c in concerns:
            st.markdown(f"- {c}")

    if suggestions:
        st.markdown("**💡 建议:**")
        for s in suggestions:
            st.markdown(f"- {s}")

    # Risk alerts
    if not is_demo:
        triggers = modules["memory"].check_risk_triggers(window_minutes=60)
    else:
        triggers = []

    if triggers:
        st.markdown('<div class="risk-alert">🚨 <b>风险提醒</b></div>', unsafe_allow_html=True)
        for t in triggers:
            st.warning(t)

# ─── Footer ───────────────────────────────────────────────────────────
st.divider()
col1, col2 = st.columns(2)
col1.caption("SoulCompanion AI v1.0.0 | ASD儿童智能陪伴干预机器人")
col2.caption(f"模式: {'实时' if not is_demo else '演示'} | 数据仅在本地存储")
