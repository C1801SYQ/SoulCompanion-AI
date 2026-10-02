"""Retired research UI: use the shared launcher for a single owned device lifecycle."""
import streamlit as st

st.set_page_config(page_title="SoulCompanion — 本地入口", layout="centered")
st.title("SoulCompanion · 统一本地看板")
st.info("旧研究入口已停用。统一入口提供历史、报告、设备状态和隐私设置，并由启动器管理设备资源。")
st.code("python launch.py --no-robot", language="text")
st.link_button("打开本机看板", "http://127.0.0.1:8000")
st.caption("需要真实感知时配置本地模型与设备，再运行 python launch.py。此页面不会启动采集或访问数据库。")
