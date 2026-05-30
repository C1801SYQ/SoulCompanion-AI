"""
小予情绪智能仪表板 - Streamlit Cloud 版本
仅依赖 streamlit（零外部依赖）
"""
import streamlit as st
import random
from datetime import datetime, timedelta

st.set_page_config(page_title="小予情绪智能仪表板", page_icon="💠", layout="wide")

st.markdown("""
<style>
    .main { background-color: #f5f7fa; }
    .stMetric { background-color: #ffffff; padding: 15px; border-radius: 10px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); }
    .emotion-badge { font-size: 4rem; text-align: center; }
    .health-ring { text-align: center; font-size: 3.5rem; font-weight: 700; }
    div[data-testid="stMetricValue"] { font-size: 1.3rem; }
</style>
""", unsafe_allow_html=True)

EMOTION_ICONS = {"happy": "😊", "calm": "😌", "neutral": "😐", "anxious": "😰", "sad": "😢"}
EMOTION_LABELS = {"happy": "开心", "calm": "平静", "neutral": "中性", "anxious": "焦虑", "sad": "难过"}
EMOTION_COLORS = {"happy": "#FFD700", "calm": "#87CEEB", "neutral": "#4CAF50", "anxious": "#FF9800", "sad": "#7986CB"}

# ─── Generate Demo Data ───────────────────────────────────────────────
def get_demo_state():
    cats = ["happy", "neutral", "calm", "anxious", "sad"]
    cat = random.choices(cats, weights=[0.3, 0.3, 0.2, 0.1, 0.1], k=1)[0]
    vm = {"happy": 0.7, "calm": 0.3, "neutral": 0.0, "anxious": -0.4, "sad": -0.7}
    am = {"happy": 0.7, "calm": 0.2, "neutral": 0.3, "anxious": 0.7, "sad": 0.3}
    return {
        "category": cat,
        "confidence": round(random.uniform(0.6, 0.95), 2),
        "valence": round(vm[cat] + random.uniform(-0.1, 0.1), 2),
        "arousal": round(am[cat] + random.uniform(-0.1, 0.1), 2),
        "attention_level": round(random.uniform(0.5, 1.0), 2),
    }

def generate_timeline(days=7):
    """Generate demo timeline data as dict of lists."""
    now = datetime.now()
    timestamps = []
    valences = []
    for d in range(days):
        for r in range(8):
            ts = now - timedelta(days=d, hours=random.randint(8, 20), minutes=random.randint(0, 59))
            cat = random.choices(["happy", "neutral", "calm", "anxious", "sad"],
                                 weights=[0.3, 0.3, 0.2, 0.1, 0.1], k=1)[0]
            vm = {"happy": 0.7, "calm": 0.3, "neutral": 0.0, "anxious": -0.4, "sad": -0.7}
            timestamps.append(ts)
            valences.append(round(vm[cat] + random.uniform(-0.15, 0.15), 2))
    # Sort by time
    paired = sorted(zip(timestamps, valences), key=lambda x: x[0])
    return {
        "timestamp": [p[0].strftime("%m-%d %H:%M") for p in paired],
        "valence": [p[1] for p in paired],
    }

# ─── Current State ────────────────────────────────────────────────────
cur = get_demo_state()
cat = cur["category"]
icon = EMOTION_ICONS.get(cat, "😐")
label = EMOTION_LABELS.get(cat, "中性")
color = EMOTION_COLORS.get(cat, "#4CAF50")

# ─── Header ───────────────────────────────────────────────────────────
st.title("💠 小予情绪智能仪表板")
st.caption(f"SoulCompanion AI - ASD儿童多模态情绪监控 | 🟡 演示数据 | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

c1, c2 = st.columns(2)
c3, c4 = st.columns([2, 1])

# ─── Panel 1: Emotion Live ───────────────────────────────────────────
with c1:
    st.markdown("### 🧠 实时情绪状态")
    st.markdown(f'<div class="emotion-badge">{icon}</div>', unsafe_allow_html=True)
    st.markdown(f'<div style="font-size:1.8rem;font-weight:700;text-align:center;color:{color}">{label}</div>',
                unsafe_allow_html=True)
    m1, m2, m3 = st.columns(3)
    m1.metric("置信度", f"{cur['confidence']:.2f}")
    m2.metric("效价", f"{cur['valence']:.2f}")
    m3.metric("唤醒度", f"{cur['arousal']:.2f}")
    st.progress(cur["attention_level"], text=f"注意力: {cur['attention_level']:.0%}")
    st.markdown(f"""
    | 信号源 | 状态 |
    |--------|------|
    | 👁️ 视觉 | {label} |
    | 🎤 语音 | 中性 |
    | 🌡️ 环境 | 正常 |
    """)

# ─── Panel 2: Behavior Monitor ───────────────────────────────────────
with c2:
    st.markdown("### 🤖 行为同步状态")
    ACTION_LABELS = {
        "heartbeat": "💓 心跳模拟", "breathing_led": "💡 呼吸灯",
        "ear_wiggle": "👂 耳朵摆动", "head_tilt": "🤔 好奇歪头",
        "soothing_voice": "🗣️ 温柔语音", "led_warm": "💡 暖色灯",
    }
    beh = {
        "happy": ["ear_wiggle", "led_warm"],
        "neutral": ["breathing_led"],
        "calm": ["breathing_led", "soothing_voice"],
        "anxious": ["heartbeat", "breathing_led", "soothing_voice"],
        "sad": ["heartbeat", "soothing_voice"],
    }
    acts = beh.get(cat, ["breathing_led"])
    st.markdown(f"**当前动作:** {' '.join(ACTION_LABELS.get(a, a) for a in acts)}")

    led = {"happy": "#FFD700", "neutral": "#4CAF50", "calm": "#87CEEB", "anxious": "#64B5F6", "sad": "#7986CB"}
    sr = "1.2x" if cat == "happy" else "0.7x" if cat in ("anxious", "sad") else "1.0x"
    ss = "0.7" if cat == "happy" else "0.2" if cat in ("anxious", "sad") else "0.5"

    st.markdown(f"""
    | 参数 | 值 |
    |------|-----|
    | 💡 LED | {led.get(cat, '#4CAF50')} |
    | 🗣️ 语速 | {sr} |
    | 🦽 动作速度 | {ss} |
    """)

# ─── Panel 3: Emotion Timeline ───────────────────────────────────────
with c3:
    st.markdown("### 📈 情绪趋势")

    timeline = generate_timeline(7)

    # Simple line chart using st.line_chart with dict
    st.line_chart(timeline["valence"], height=200)

    t1, t2, t3, t4 = st.columns(4)
    t1.metric("主导情绪", "中性")
    t2.metric("平均效价", "0.05")
    t3.metric("稳定性", "75%")
    t4.metric("记录数", str(len(timeline["valence"])))

    # Emotion distribution
    dist = {"😊 开心": "30%", "😐 中性": "30%", "😌 平静": "20%", "😰 焦虑": "10%", "😢 难过": "10%"}
    dist_cols = st.columns(5)
    for i, (k, v) in enumerate(dist.items()):
        with dist_cols[i]:
            st.metric(k, v)

# ─── Panel 4: Parent Insight ─────────────────────────────────────────
with c4:
    st.markdown("### 👨‍👩‍👦 家长洞察")

    score = 72.5
    sc = "#66BB6A" if score >= 70 else "#FFB74D"
    st.markdown(f'<div class="health-ring" style="color:{sc}">{score:.0f}</div>', unsafe_allow_html=True)
    st.caption("情绪健康指数 (0-100)")

    st.markdown("**本周评价:** 整体情绪状态良好，注意力有提升空间。")

    st.markdown("**✨ 亮点:**")
    st.markdown("- 开心时刻 12 次\n- 情绪稳定性良好\n- 社交互动增加")

    st.markdown("**⚠️ 关注:**")
    st.markdown("- 下午注意力偏低\n- 偶尔出现焦虑情绪")

    st.markdown("**💡 建议:**")
    st.markdown("- 增加户外活动时间\n- 下午安排轻松游戏\n- 保持规律作息")

# ─── Footer ───────────────────────────────────────────────────────────
st.divider()
st.caption("SoulCompanion AI v1.0.0 | 演示模式 | ASD儿童智能陪伴干预机器人 | 数据仅在本地存储")
