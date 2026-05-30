"""Minimal test app for Streamlit Cloud deployment."""
import streamlit as st

st.set_page_config(page_title="Test", page_icon="✅")
st.title("✅ Streamlit Cloud 测试成功！")
st.write("如果你能看到这个页面，说明部署正常。")
st.write("接下来我会部署完整的情绪仪表板。")
st.balloons()
