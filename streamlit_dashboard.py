"""
小予情绪智能仪表板 - Streamlit Cloud 版本
https://soulcompanion-ai-nxafastub9ka8r95xwptfy.streamlit.app/
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

# Try importing emotion modules, fall back to demo
@st.cache_resource
def init_modules():
    try:
        import sys, os
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from emotion.memory_axis import MemoryAxis
        from emotion.fusion_engine import FusionEngine
        from emotion.behavior_sync import BehaviorSync
        from emotion.intervention import InterventionEngine
        m = MemoryAxis(); f = FusionEngine(memory_axis=m)
        b = BehaviorSync(); i = InterventionEngine(memory_axis=m)
        return {"memory": m, "fusion": f, "behavior": b, "intervention": i, "mode": "live"}
    except Exception as e:
        return {"mode": "demo", "error": str(e)}

modules = init_modules()
is_demo = modules.get("mode") == "demo"

def get_demo_state():
    cats = ["happy", "neutral", "calm", "anxious", "sad"]
    cat = random.choices(cats, weights=[0.3, 0.3, 0.2, 0.1, 0.1], k=1)[0]
    vm = {"happy": 0.7, "calm": 0.3, "neutral": 0.0, "anxious": -0.4, "sad": -0.7}
    am = {"happy": 0.7, "calm": 0.2, "neutral": 0.3, "anxious": 0.7, "sad": 0.3}
    return {"category": cat, "confidence": round(random.uniform(0.6, 0.95), 2),
            "valence": round(vm[cat] + random.uniform(-0.1, 0.1), 2),
            "arousal": round(am[cat] + random.uniform(-0.1, 0.1), 2),
            "attention_level": round(random.uniform(0.5, 1.0), 2),
            "vision_emotion": cat, "speech_emotion": "neutral", "environment_signal": "normal"}

if is_demo:
    cur = get_demo_state()
else:
    s = modules["fusion"].get_last_state()
    cat_val = s.category.value if hasattr(s.category, 'value') else str(s.category)
    cur = {"category": cat_val, "confidence": s.confidence, "valence": s.valence,
           "arousal": s.arousal, "attention_level": s.attention_level,
           "vision_emotion": s.vision_emotion, "speech_emotion": s.speech_emotion,
           "environment_signal": s.environment_signal}

cat = cur["category"]
icon = EMOTION_ICONS.get(cat, "😐")
label = EMOTION_LABELS.get(cat, "中性")
color = EMOTION_COLORS.get(cat, "#4CAF50")

mode_badge = "🟢 实时数据" if not is_demo else "🟡 演示数据"
st.title("💠 小予情绪智能仪表板")
st.caption(f"SoulCompanion AI - ASD儿童多模态情绪监控 | {mode_badge} | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

c1, c2 = st.columns(2)
c3, c4 = st.columns([2, 1])

# Panel 1: Emotion Live
with c1:
    st.markdown("### 🧠 实时情绪状态")
    st.markdown(f'<div class="emotion-badge">{icon}</div>', unsafe_allow_html=True)
    st.markdown(f'<div style="font-size:1.8rem;font-weight:700;text-align:center;color:{color}">{label}</div>', unsafe_allow_html=True)
    m1, m2, m3 = st.columns(3)
    m1.metric("置信度", f"{cur['confidence']:.2f}")
    m2.metric("效价", f"{cur['valence']:.2f}")
    m3.metric("唤醒度", f"{cur['arousal']:.2f}")
    st.progress(cur["attention_level"], text=f"注意力: {cur['attention_level']:.0%}")

# Panel 2: Behavior Monitor
with c2:
    st.markdown("### 🤖 行为同步状态")
    ACTION_LABELS = {"heartbeat": "💓 心跳", "breathing_led": "💡 呼吸灯", "ear_wiggle": "👂 耳朵",
                     "head_tilt": "🤔 歪头", "soothing_voice": "🗣️ 温柔", "led_warm": "💡 暖灯"}
    beh = {"happy": ["ear_wiggle", "led_warm"], "neutral": ["breathing_led"],
           "calm": ["breathing_led", "soothing_voice"], "anxious": ["heartbeat", "breathing_led"],
           "sad": ["heartbeat", "soothing_voice"]}
    acts = beh.get(cat, ["breathing_led"])
    st.markdown(f"**动作:** {' '.join(ACTION_LABELS.get(a, a) for a in acts)}")
    led = {"happy": "#FFD700", "neutral": "#4CAF50", "calm": "#87CEEB", "anxious": "#64B5F6", "sad": "#7986CB"}
    st.markdown(f"**LED:** {led.get(cat, '#4CAF50')}")
    st.markdown(f"**语速:** {'1.2x' if cat == 'happy' else '0.7x' if cat in ('anxious','sad') else '1.0x'}")

# Panel 3: Emotion Timeline
with c3:
    st.markdown("### 📈 情绪趋势")
    import pandas as pd
    now = datetime.now()
    data = []
    for d in range(7):
        for r in range(8):
            ts = now - timedelta(days=d, hours=random.randint(8, 20))
            c = random.choices(["happy","neutral","calm","anxious","sad"], weights=[0.3,0.3,0.2,0.1,0.1], k=1)[0]
            vm = {"happy":0.7,"calm":0.3,"neutral":0.0,"anxious":-0.4,"sad":-0.7}
            data.append({"timestamp": ts, "valence": vm[c] + random.uniform(-0.1, 0.1), "emotion": c})
    df = pd.DataFrame(data).sort_values("timestamp").set_index("timestamp")
    st.line_chart(df["valence"], height=200)

    t1, t2, t3, t4 = st.columns(4)
    t1.metric("主导情绪", "中性")
    t2.metric("平均效价", "0.05")
    t3.metric("稳定性", "75%")
    t4.metric("记录数", str(len(data)))

# Panel 4: Parent Insight
with c4:
    st.markdown("### 👨‍👩‍👦 家长洞察")
    score = 72.5
    sc = "#66BB6A" if score >= 70 else "#FFB74D"
    st.markdown(f'<div class="health-ring" style="color:{sc}">{score:.0f}</div>', unsafe_allow_html=True)
    st.caption("情绪健康指数 (0-100)")
    st.markdown("**本周评价:** 整体情绪状态良好，注意力有提升空间。")
    st.markdown("**✨ 亮点:**\n- 开心时刻 12 次\n- 情绪稳定性良好")
    st.markdown("**⚠️ 关注:**\n- 下午注意力偏低")
    st.markdown("**💡 建议:**\n- 增加户外活动\n- 下午安排轻松游戏")

st.divider()
st.caption(f"SoulCompanion AI v1.0.0 | {'实时模式' if not is_demo else '演示模式'} | ASD儿童智能陪伴干预机器人")
