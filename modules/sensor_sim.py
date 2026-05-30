# 模拟传感器数据
import time

def get_mock_sensor_data():
    # 这里可以根据测试需求手动修改返回值
    return {
        "is_dark": True,           # 模拟光敏电阻：室内变暗
        "heard_thunder": True,     # 模拟音频识别：听到雷声
        "visual_emotion": "fear",  # 模拟摄像头：孩子表情惊恐
        "is_hugging": False        # 模拟触摸传感器：是否被抱住
    }
