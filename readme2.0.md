
# 🌟 小予智能陪伴机器人 - 环境配置手册 (2026 )

本手册针对 **2026 三创赛 (SoulCompanion_AI)** 项目编写。项目已实现 **多模态情感感知**（离线视觉表情 + 离线语音情感）、**离线语音转写** 及 **TTS 输出**。

---

## 🛠️ 第一步：基础环境与清理

为了兼容最新的情感模型架构，请确保使用 **Python 3.12**，并清理旧版依赖冲突。

1.  **升级 Pip**（必须）：
    ```powershell
    python.exe -m pip install --upgrade pip
    ```
2.  **NumPy 版本对齐**（关键）：
    由于 `ultralytics` 和 `scipy` 在当前环境下的限制，必须使用 1.x 版本的 NumPy。
    ```powershell
    pip install "numpy<2.0.0"
    ```

---

## 📦 第二步：安装核心依赖（含多模态模型环境）

本项目涉及深度学习框架，请**严格按照顺序**执行，以避开 Torch 安全检查拦截。

### 1. 安装基础外设驱动
```powershell
pip install opencv-python vosk pyaudio pyttsx3
```

### 2. 安装深度学习与情感识别框架
由于 `transformers` 最新的安全策略，我们采用了**版本降级策略**以适配当前稳定版驱动：
```powershell
# 安装特定版本防止安全拦截
pip install transformers==4.44.2 tf-keras

# 安装 PyTorch (根据你的 CUDA 12.1 驱动对齐)
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121
```

---

## 🧠 第三步：离线模型放置 (双模型驱动)

机器人拥有两套离线模型，分别存放于不同目录。

### 1. 语音转文字 (STT) 模型
* **来源**：[Vosk Models](https://alphacephei.com/vosk/models) (`vosk-model-small-cn-0.22`)。
* **位置**：根目录 `/model` 文件夹（包含 `am`, `graph` 等）。

### 2. 音频情感识别 (SER) 模型
* **来源**：通过 `download_ser.py` 自动下载。
* **位置**：根目录 `/models/ser_model` 文件夹。
* **状态检查**：运行以下命令，看到 `退出代码 0` 即表示离线模型就绪：
    ```powershell
    python D:\SoulCompanion_AI\download_ser.py
    ```

**正确的目录结构：**
```text
SoulCompanion_AI/
├── main.py              <-- 主程序入口
├── download_ser.py      <-- 模型维护工具
├── model/               <-- STT 语音模型 (Vosk)
├── models/
│   └── ser_model/       <-- 情感识别模型 (Wav2Vec2)
└── core/                <-- 机器人决策中枢
```

---

## 🚀 第四步：启动与比赛演示建议

1.  **启动阶段**：运行 `python main.py`。程序会加载多套深度学习模型，启动耗时约 **15-20 秒**。
2.  **离线验证**：模型下载成功后，建议**关闭 WiFi** 进行测试。如果程序能正常显示 `✅ [感知融合]`，则说明离线化成功。
3.  **性能优化**：
    * 如果演示电脑有显卡，请在 `main.py` 的 `SpeechEngine` 初始化中加入 `device=0` 参数。
    * 若报错 `ValueError: Due to a serious vulnerability...`，请检查 `transformers` 版本是否为 `4.44.2`。

---

## 📑 最新依赖清单 (requirements.txt)
```text
numpy<2.0.0
opencv-python
vosk
pyaudio
pyttsx3
transformers==4.44.2
tf-keras
torch
torchvision
torchaudio
```

---

**💡 小提醒：**
在比赛前，请确保执行过 `pip install "defusedxml<0.8.0"` 以消除 `supervision` 库的版本冲突警告，让终端日志保持干净，只留下机器人的交互日志！

---

### 主要更新点说明：
1.  **NumPy 限制**：增加了 `numpy<2.0.0` 的明确要求，防止底层数学库冲突。
2.  **Torch 安全避坑**：加入了 `transformers==4.44.2` 和 `tf-keras` 的安装步骤，这是你解决 `ValueError` 和 `ModuleNotFoundError` 的关键记录。
3.  **双路径模型说明**：区分了根目录下的 `model`（语音识别）和 `models/ser_model`（情感识别），防止文件夹混淆。
4.  **离线化确认**：明确了模型下载后的成功标志。