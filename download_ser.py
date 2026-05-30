# download_ser.py
import os
from transformers import pipeline

# 创建本地存放路径
save_path = os.path.join("models", "ser_model")
os.makedirs(save_path, exist_ok=True)

print("⏳ 正在从 Hugging Face 下载 Wav2Vec2 情感模型，这可能需要几分钟（视网速而定）...")

# 加载在线模型
pipe = pipeline("audio-classification", model="superb/wav2vec2-base-superb-er")

# 保存到本地文件夹
pipe.save_pretrained(save_path)

print(f"✅ 模型下载并保存成功！已存放至: {save_path}")
print("你可以拔掉网线测试离线运行了！")