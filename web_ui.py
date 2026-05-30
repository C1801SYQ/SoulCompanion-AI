import streamlit as st
import cv2
import time
import threading
from main import SoulCompanionRobot  # 导入你的机器人核心类

# 1. 页面配置与美化样式
st.set_page_config(page_title="小予智能干预终端", layout="wide", initial_sidebar_state="collapsed")

# 自定义 CSS：打造医疗级简洁界面，避免过度刺激
st.markdown("""
    <style>
    .main { background-color: #f0f2f6; }
    .stMetric { background-color: #ffffff; padding: 15px; border-radius: 10px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); }
    .chat-container { border: 1px solid #e6e9ef; border-radius: 10px; background-color: white; padding: 10px; }
    .stChatMessage { margin-bottom: 10px; }
    </style>
    """, unsafe_allow_html=True)

# 2. 初始化单例机器人
if "robot" not in st.session_state:
    st.session_state.robot = SoulCompanionRobot()
    # 记录对话历史
    st.session_state.messages = []
    # 启动后端逻辑线程
    threading.Thread(target=st.session_state.robot.run, daemon=True).start()

# 3. 侧边栏：干预状态监控
with st.sidebar:
    st.header("⚙️ 干预配置")
    current_scene = st.selectbox("当前训练场景", ["自由对话", "打招呼练习", "情绪识别", "社交规则"])
    st.session_state.robot.state.current_scene = current_scene
    st.write(f"当前难度系数: {st.session_state.robot.state.difficulty_level}")
    if st.button("重置对话历史"):
        st.session_state.messages = []

# 4. 主界面布局
st.title("💠 小予 (SoulCompanion) | ASD 辅助干预终端")

col_vid, col_data = st.columns([1.8, 1])

with col_vid:
    st.subheader("📸 实时监测")
    video_placeholder = st.empty()
    # 动态显示视觉提示卡片
    hint_placeholder = st.empty()

with col_data:
    st.subheader("📊 多模态反馈")
    m_col1, m_col2 = st.columns(2)
    with m_col1:
        emo_metric = st.metric("面部情绪", "检测中...")
    with m_col2:
        att_metric = st.metric("注意力丢失", "0s")

    st.divider()
    st.subheader("💬 实时对话干预")
    # 对话显示区域
    chat_placeholder = st.empty()


# 5. UI 刷新与对话同步逻辑
def update_ui():
    last_processed_time = 0

    while True:
        # A. 获取传感器与机器人状态
        v_state = st.session_state.robot.vision.get_latest_state()
        robot_state = st.session_state.robot.state

        # B. 渲染视频流
        frame = st.session_state.robot.vision.get_current_frame()
        if frame is not None:
            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            video_placeholder.image(rgb_frame, use_container_width=True)

        # C. 渲染视觉提示卡片 (Requirement 2)
        if robot_state.active_hint:
            hint_placeholder.info(f"💡 引导提示：{robot_state.active_hint}")
        else:
            hint_placeholder.empty()

        # D. 更新数据指标
        emo_metric.metric("面部情绪", v_state.get("emotion", "neutral"))
        att_metric.metric("注意力丢失", f"{v_state.get('attention_loss_time', 0)}s")

        # E. 实时同步对话历史
        # 这里建议你在 main.py 的 RobotBrain 或交互逻辑里维护一个 history 列表
        # 简单演示：获取机器人最后一次说话的内容
        with chat_placeholder.container():
            for msg in robot_state.chat_history[-10:]:  # 显示最近10条
                with st.chat_message(msg["role"]):
                    st.write(msg["content"])

        if robot_state.active_hint:
            hint_placeholder.warning(f"💡 引导：{robot_state.active_hint}")
        else:
            hint_placeholder.empty()

        time.sleep(0.1)


# 启动更新逻辑（后台线程，避免阻塞 Streamlit 主线程渲染）
threading.Thread(target=update_ui, daemon=True).start()