

---

# 🌟 小予智能陪伴机器人 - 环境配置手册 (2026版)

本手册旨在帮助你在 **Windows 10/11** 环境下，从零开始搭建“小星”机器人的本地运行环境。本项目已实现 **离线视觉识别**、**离线语音转写** 及 **离线语音合成**，无需 API Key 即可演示核心功能。

---

## 🛠️ 第一步：环境清理与准备

为了防止 Python 版本冲突，请确保你使用的是 **Python 3.10 - 3.12** 版本。

1.  **打开 PyCharm 终端 (Terminal)**。
2.  **强制升级 Pip**（防止安装旧版库失败）：
    ```bash
    python.exe -m pip install --upgrade pip
    ```
2.  **由于项目依赖的 scipy 和 ultralytics 尚未全面适配 NumPy 2.x，必须回退至 1.x 版本。**
    ```bash
    pip install "numpy<2.0.0"
    ```
---

## 📦 第二步：安装核心依赖库

请**依次执行**以下命令。注意：`sqlite3` 是 Python 自带的，**千万不要执行** `pip install sqlite3`。

```bash
# 1. 安装视觉引擎
pip install opencv-python

# 2. 安装语音转文字 (STT) 引擎
pip install vosk

# 3. 安装麦克风驱动
pip install pyaudio

# 4. 安装语音合成 (TTS) 引擎
pip install pyttsx3
```

> **常见坑点：** 如果 `pyaudio` 安装失败，请通过 `pip install pipwin` 然后执行 `pipwin install pyaudio`。

---

## 🧠 第三步：下载并放置语音模型 (核心)

没有模型，机器人的“耳朵”无法工作。

1.  **下载模型**：访问 [Vosk Models](https://alphacephei.com/vosk/models)。
2.  **选择版本**：下载 **`vosk-model-small-cn-0.22`** (约 42MB)。
3.  **解压并重命名**：
    * 在项目目录 `SoulCompanion_AI/` 下新建一个文件夹，命名为 **`model`**。
    * 将下载的压缩包解压，把里面的所有内容（文件夹 `am`, `graph`, `conf` 等）**直接**放入 `model` 文件夹内。

**正确的路径结构：**
```text
SoulCompanion_AI/
├── main.py
├── model/           <-- 必须叫这个名字
│   ├── am/
│   ├── conf/
│   ├── graph/
│   └── ... (其他模型文件)
├── modules/
└── core/
```

---

## 🚀 第四步：启动机器人

1.  确保你的电脑**摄像头已打开**，且**默认麦克风已开启**。
2.  在 PyCharm 中运行 `main.py`。
3.  **启动阶段**：程序会卡住约 10-15 秒（正在加载语音模型），这是正常现象。
4.  **交互**：
    * 当终端显示 `🎙️ 离线实时听觉已准备就绪` 时，机器人正式上线。
    * **视觉**：在摄像头前晃动，确保光线充足，让它看到你的脸。
    * **语音**：对着麦克风说：“我不开心” 或 “你好”。

---

## ❓ 常见问题排查 (FAQ)

* **报错 `ModuleNotFoundError: No module named 'vosk'`**：
    说明库没装进虚拟环境。请在 PyCharm 的 `File -> Settings -> Project -> Python Interpreter` 中点 `+` 号搜索并安装 `vosk`。
* **报错 `Invalid device` 或麦克风没反应**：
    请检查 Windows 隐私设置中是否允许应用访问麦克风。
* **看不到摄像头画面**：
    确保没有其他软件（如微信、腾讯会议）正在占用摄像头。

---

## 📑 依赖清单 (requirements.txt)
你可以直接创建 `requirements.txt` 文件并写入以下内容：
```text
opencv-python
vosk
pyaudio
pyttsx3
```

---

**配置完成后，你可以尝试对着它笑一下再说话，看看多模态融合逻辑是否能识别出你的“开心”！**