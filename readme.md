# 💠 小予 (SoulCompanion AI)

## ASD 儿童多模态情绪智能陪伴干预机器人

---

## 📋 项目简介

小予是一个面向 ASD（自闭症谱系障碍）儿童的智能陪伴机器人系统，具备：

- 🧠 **多模态情绪融合** — 视觉 + 语音 + 环境信号实时融合分析
- 💾 **长期情绪记忆** — SQLite 持久化，趋势分析，周期性检测
- 🤖 **情绪驱动行为** — 呼吸灯、心跳模拟、耳朵摆动、头部倾斜
- 💬 **教育型干预** — 温柔引导，不命令不批评
- 👨‍👩‍👦 **家长洞察** — 每周情绪报告，风险预警
- 🌐 **实时仪表板** — Web 可视化，4 面板监控

---

## 🛠️ 环境要求

| 项目 | 要求 |
|------|------|
| 操作系统 | Windows 10/11 |
| Python | 3.10 - 3.12 |
| 摄像头 | USB 或内置摄像头 |
| 麦克风 | 任意可用麦克风 |
| 内存 | ≥ 8GB（模型加载需要） |
| 磁盘 | ≥ 2GB（模型文件） |

---

## 🚀 快速开始

### 第一步：克隆项目

```bash
git clone https://github.com/C1801SYQ/SoulCompanion-AI.git
cd SoulCompanion-AI
```

### 第二步：安装依赖

```bash
# 升级 pip
python -m pip install --upgrade pip

# 安装 NumPy（必须先装，兼容性问题）
pip install "numpy<2.0.0"

# 安装核心依赖
pip install -r requirements.txt

# 安装 Web 仪表板依赖
pip install fastapi uvicorn jinja2 python-multipart
```

> ⚠️ 如果 `pyaudio` 安装失败：
> ```bash
> pip install pipwin
> pipwin install pyaudio
> ```

### 第三步：下载语音模型

1. 下载 [Vosk 中文模型](https://alphacephei.com/vosk/models) — 选择 `vosk-model-small-cn-0.22`
2. 解压到项目目录下的 `model/` 文件夹

```
SoulCompanion-AI/
├── model/           ← Vosk 模型放这里
│   ├── am/
│   ├── conf/
│   ├── graph/
│   └── ivector/
├── models/
│   ├── onnx_model.onnx          ← 情绪识别模型
│   ├── ser_model/               ← 语音情感模型
│   └── haarcascade_frontalface_default.xml
```

### 第四步：启动系统

```bash
# 方式一：完整系统（推荐）
python launch.py

# 方式二：仅 Web 仪表板（无摄像头/麦克风）
python launch.py --no-robot

# 方式三：自定义端口
python launch.py --port 8080
```

启动后访问：**http://localhost:8000**

---

## 📖 操作手册

### 🎮 启动模式

| 命令 | 说明 | 适用场景 |
|------|------|----------|
| `python launch.py` | 完整系统 | 正式使用，有摄像头和麦克风 |
| `python launch.py --no-robot` | 仅仪表板 | 测试/演示，无硬件 |
| `python launch.py --no-web` | 无仪表板 | 嵌入式部署 |
| `python launch.py --port 8080` | 自定义端口 | 端口冲突时 |
| `python launch.py --hardware` | 硬件模式 | 连接实体机器人 |
| `streamlit run streamlit_dashboard.py` | Streamlit 版 | 本地 Streamlit 仪表板 |

### 🖥️ Web 仪表板说明

启动后打开浏览器访问 `http://localhost:8000`

#### 面板 1：🧠 实时情绪状态

| 指标 | 说明 | 范围 |
|------|------|------|
| 情绪图标 | 当前识别到的情绪 | 😊😐😰😢😠 |
| 置信度 | 情绪识别的可信度 | 0.00 - 1.00 |
| 效价 (Valence) | 正面/负面程度 | -1.0 ~ +1.0 |
| 唤醒度 (Arousal) | 兴奋/平静程度 | 0.0 ~ 1.0 |
| 注意力 | 是否注视摄像头 | 0% - 100% |

#### 面板 2：🤖 行为同步状态

机器人根据情绪自动执行的行为：

| 行为 | 触发情绪 | 效果 |
|------|----------|------|
| 💓 心跳模拟 | 焦虑/难过/害怕 | 72bpm 安抚震动 |
| 💡 呼吸灯 | 中性/平静/焦虑 | 缓慢呼吸灯效 |
| 👂 耳朵摆动 | 开心/注意力低 | 可爱耳朵动作 |
| 🤔 好奇歪头 | 惊讶/注意力低 | 15° 头部倾斜 |
| 🗣️ 温柔语音 | 焦虑/难过/害怕 | 降低语速 |
| 🧊 静止模式 | 生气/过载 | 减少刺激 |

#### 面板 3：📈 情绪趋势

- **效价时间线** — 最近 7 天的情绪变化曲线
- **主导情绪** — 出现最多的情绪类别
- **稳定性** — 情绪波动程度（越高越稳定）

#### 面板 4：👨‍👩‍👦 家长洞察

- **情绪健康指数** — 0-100 综合评分
- **本周亮点** — 积极情绪统计
- **需要关注** — 风险时段和异常模式
- **建议** — 针对性的互动建议

### 📡 API 文档

启动后访问 `http://localhost:8000/docs` 查看完整 API 文档

常用端点：

| 端点 | 说明 |
|------|------|
| `GET /api/emotion/current` | 当前情绪状态 |
| `GET /api/emotion/history` | 情绪历史记录 |
| `GET /api/emotion/trends` | 趋势分析 |
| `GET /api/behavior/command` | 当前行为命令 |
| `GET /api/parent/report` | 家长报告 (JSON) |
| `GET /api/parent/report.md` | 家长报告 (Markdown) |
| `GET /api/risk/triggers` | 风险触发器 |
| `GET /api/bridge/status` | 桥接器状态 |
| `GET /api/skill/*` | Skill 驱动 UI 配置 |

### 🌐 公网访问（远程监控）

将仪表板暴露到公网，供远程查看：

```bash
# 安装 localtunnel
npm install -g localtunnel

# 启动完整系统
python launch.py

# 另开终端，启动隧道
lt --port 8000
```

会生成一个公网 URL，如 `https://xxx.loca.lt`

> ⚠️ 公网访问时，首次打开需点击 "Click to Continue"

### ☁️ Streamlit Cloud 部署（演示用）

将演示版仪表板部署到 Streamlit Cloud：

```bash
# 1. 推送到 GitHub
git push origin master

# 2. 访问 https://share.streamlit.io
# 3. 选择仓库 C1801SYQ/SoulCompanion-AI
# 4. Main file: streamlit_dashboard.py
# 5. 点击 Deploy
```

> 注意：Streamlit Cloud 版本使用演示数据，无法连接本地硬件

---

## 📁 项目结构

```
SoulCompanion-AI/
├── main.py                      # 机器人主程序（核心循环）
├── launch.py                    # 统一启动器
├── config.py                    # 全局配置
├── streamlit_dashboard.py       # Streamlit 仪表板
├── requirements.txt             # Python 依赖
│
├── emotion/                     # 情绪智能核心模块
│   ├── __init__.py
│   ├── models.py                # 共享数据模型
│   ├── fusion_engine.py         # 多模态情绪融合
│   ├── memory_axis.py           # 长期情绪记忆
│   ├── behavior_sync.py         # 情绪→行为映射
│   ├── embodied_engine.py       # 拟人行为仿真
│   ├── intervention.py          # 教育型干预系统
│   └── bridge.py                # 非侵入式集成桥
│
├── web/                         # FastAPI Web 仪表板
│   ├── __init__.py
│   ├── api.py                   # REST API (20+ 端点)
│   ├── app.py                   # 应用入口
│   ├── templates/
│   │   └── dashboard.html       # Dashboard 模板
│   └── static/
│       ├── style.css            # 样式表
│       └── app.js               # 前端逻辑
│
├── modules/                     # 原有核心模块
│   ├── vision_engine.py         # 视觉引擎 (OpenCV + ONNX)
│   └── speech_engine.py         # 语音引擎 (Vosk + Wav2Vec2)
│
├── utils/
│   └── audio_player.py          # TTS 语音合成
│
├── hardware/
│   └── controllers/
│       └── actuators.py         # 硬件控制器
│
├── model/                       # Vosk 语音模型
├── models/                      # 情绪识别模型
│   ├── onnx_model.onnx
│   ├── ser_model/
│   └── haarcascade_frontalface_default.xml
│
├── data/
│   └── emotional_db.sqlite      # 情绪数据库
│
├── reports/
│   └── report_generator.py      # 报告生成器
│
├── web_ui.py                    # 原有 Streamlit UI
├── DEPLOY.md                    # 部署指南
└── AI_MEMORY.md                 # AI 开发记忆
```

---

## 🔧 常见问题

### Q: 启动时报错 `ModuleNotFoundError: No module named 'vosk'`
A: 在 PyCharm 的 `File → Settings → Project → Python Interpreter` 中安装 `vosk`

### Q: 摄像头打不开
A: 确保没有其他软件（微信、腾讯会议）占用摄像头

### Q: 麦克风没反应
A: 检查 Windows 隐私设置中是否允许应用访问麦克风

### Q: Ollama 连接失败
A: 确保 Ollama 已启动：
```bash
ollama serve
ollama pull gemma4:e4b
```

### Q: 仪表板显示"演示数据"
A: 说明机器人核心未启动。检查摄像头和麦克风是否可用，或使用 `python launch.py --no-robot`

### Q: Streamlit Cloud 部署失败
A: 确保 `requirements.txt` 只包含 `streamlit`，不要有其他依赖

### Q: 公网隧道断开
A: localtunnel 免费版不稳定，重新运行 `lt --port 8000` 获取新 URL

---

## 📊 系统架构

```
                    ┌─────────────────────────────────┐
                    │         main.py (不变)           │
                    │  ┌──────────┐  ┌──────────┐     │
                    │  │ Vision   │  │ Speech   │     │
                    │  │ Engine   │  │ Engine   │     │
                    │  └────┬─────┘  └────┬─────┘     │
                    └───────┼─────────────┼───────────┘
                            │             │
                            ▼             ▼
                    ┌─────────────────────────────────┐
                    │       EmotionBridge (新增)       │
                    │                                 │
                    │  ┌──────────┐  ┌──────────┐    │
                    │  │ Fusion   │→ │ Memory   │    │
                    │  │ Engine   │  │ Axis     │    │
                    │  └────┬─────┘  └──────────┘    │
                    │       │                         │
                    │  ┌────▼─────┐  ┌──────────┐    │
                    │  │ Behavior │→ │ Embodied │    │
                    │  │ Sync     │  │ Engine   │    │
                    │  └────┬─────┘  └──────────┘    │
                    │       │                         │
                    │  ┌────▼─────┐                   │
                    │  │Interven- │→ 家长报告         │
                    │  │tion      │                   │
                    │  └──────────┘                   │
                    └───────────┬─────────────────────┘
                                │
                                ▼
                    ┌─────────────────────────────────┐
                    │     Web Dashboard (新增)         │
                    │  http://localhost:8000           │
                    │  ┌──────┐ ┌──────┐              │
                    │  │Emotion│ │Behavior│            │
                    │  │Panel  │ │Monitor│             │
                    │  └──────┘ └──────┘              │
                    │  ┌──────┐ ┌──────┐              │
                    │  │Time- │ │Parent│              │
                    │  │line  │ │Insight│             │
                    │  └──────┘ └──────┘              │
                    └─────────────────────────────────┘
```

---

## 📝 开发日志

| 轮次 | 类型 | 内容 | 状态 |
|------|------|------|------|
| R1 | security | 移除硬编码 API Key | ✅ |
| R2 | fix | 修复 NameError | ✅ |
| R3 | security | 修复 SQL 注入 | ✅ |
| R4 | fix | 修复空 except | ✅ |
| R5 | fix | 添加线程锁 | ✅ |
| R6 | fix | 修复 UI 阻塞 | ✅ |
| R7 | refactor | 统一配置 | ✅ |
| R8 | refactor | 删除死代码 | ✅ |
| R9 | refactor | 清理导入 | ✅ |
| R10 | feat | 情绪智能系统 + Web 仪表板 | ✅ |

---

## 📄 许可证

本项目仅供学术研究和教育用途。

---

**💠 小予 — 用科技温暖每一颗星星的孩子**
