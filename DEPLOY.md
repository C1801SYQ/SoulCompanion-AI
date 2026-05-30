# 🚀 小予情绪智能仪表板 - 部署指南

## 方案一：Streamlit Cloud（推荐，最简单）

### 前提条件
- GitHub 账号
- 代码已推送到 GitHub 仓库

### 部署步骤

1. **推送到 GitHub**
   ```bash
   git add .
   git commit -m "[deploy] add emotion system + web dashboard"
   git push origin master
   ```

2. **连接 Streamlit Cloud**
   - 访问 https://share.streamlit.io
   - 用 GitHub 账号登录
   - 点击 "New app"

3. **配置部署**
   - Repository: `你的用户名/SoulCompanion_AI`
   - Branch: `master`
   - Main file path: `streamlit_dashboard.py`
   - Python version: 3.10+

4. **设置环境变量**（如需要）
   - 在 Streamlit Cloud 的 "Advanced settings" 中添加
   - `DATABASE_PATH=data/emotional_db.sqlite`

5. **点击 Deploy**
   - 等待 2-3 分钟构建完成
   - 获得访问 URL: `https://你的app名.streamlit.app`

### 注意事项
- Streamlit Cloud 免费版有资源限制
- 数据库为临时存储，重启后可能丢失
- 适合演示和轻量使用

---

## 方案二：FastAPI + Vercel（生产级）

### 前提条件
- GitHub 账号
- Vercel 账号 (https://vercel.com)

### 部署步骤

1. **创建 Vercel 配置文件**
   ```bash
   # vercel.json (已创建)
   ```

2. **推送到 GitHub**
   ```bash
   git add .
   git commit -m "[deploy] add Vercel deployment config"
   git push origin master
   ```

3. **连接 Vercel**
   - 访问 https://vercel.com
   - 点击 "New Project"
   - 导入 GitHub 仓库

4. **配置构建**
   - Framework Preset: Other
   - Build Command: (留空或 `pip install -r requirements-web.txt`)
   - Output Directory: (留空)
   - Install Command: `pip install -r requirements-web.txt`

5. **设置环境变量**
   - `DATABASE_PATH` = `data/emotional_db.sqlite`

6. **部署**
   - 点击 Deploy
   - 等待构建完成
   - 获得访问 URL: `https://你的项目名.vercel.app`

### Vercel 限制
- Serverless 函数有执行时间限制
- 无持久化存储（需外部数据库）
- 适合 API 服务，不适合长时间运行的任务

---

## 方案三：本地部署（开发/测试）

### 安装依赖

```bash
# 基础依赖
pip install -r requirements.txt

# Web Dashboard 依赖
pip install -r requirements-web.txt
```

### 启动 FastAPI Dashboard

```bash
# 默认端口 8000
python -m web.app

# 自定义端口
python -m web.app --port 8080

# 开发模式（自动重载）
python -m web.app --reload
```

### 启动 Streamlit Dashboard

```bash
streamlit run streamlit_dashboard.py
```

### 访问地址
- FastAPI Dashboard: http://localhost:8000
- API 文档: http://localhost:8000/docs
- Streamlit Dashboard: http://localhost:8501

---

## 方案四：Netlify（静态前端 + API 分离）

### 架构
- 前端: 静态 HTML/CSS/JS 部署到 Netlify
- 后端: FastAPI 部署到 Vercel/Railway

### 部署步骤

1. **构建静态前端**
   ```bash
   # 复制静态文件
   mkdir -p dist
   cp -r web/static/* dist/
   cp web/templates/dashboard.html dist/index.html
   # 修改 API 地址为后端 URL
   ```

2. **部署到 Netlify**
   - 访问 https://netlify.com
   - 拖拽 dist 文件夹到部署区域
   - 或连接 GitHub 仓库自动部署

3. **部署后端到 Vercel**
   - 参考方案二

---

## 文件结构

```
SoulCompanion_AI/
├── main.py                    # 原有机器人主程序（未修改）
├── config.py                  # 配置文件
├── requirements.txt           # 基础依赖
├── requirements-web.txt       # Web Dashboard 依赖
├── streamlit_dashboard.py     # Streamlit Cloud 入口
├── DEPLOY.md                  # 本部署指南
│
├── emotion/                   # 情绪智能核心模块（新增）
│   ├── __init__.py
│   ├── models.py              # 数据模型
│   ├── fusion_engine.py       # 多模态融合
│   ├── memory_axis.py         # 长期记忆
│   ├── behavior_sync.py       # 行为同步
│   ├── embodied_engine.py     # 拟人引擎
│   └── intervention.py        # 干预系统
│
├── web/                       # Web Dashboard（新增）
│   ├── __init__.py
│   ├── api.py                 # FastAPI REST API
│   ├── app.py                 # 应用入口
│   ├── templates/
│   │   └── dashboard.html     # Dashboard 模板
│   └── static/
│       ├── style.css          # 样式表
│       └── app.js             # 前端逻辑
│
├── modules/                   # 原有模块（未修改）
├── core/                      # 原有核心（未修改）
├── utils/                     # 原有工具（未修改）
└── data/                      # 数据目录
    └── emotional_db.sqlite    # SQLite 数据库
```

---

## API 端点一览

| 端点 | 方法 | 描述 |
|------|------|------|
| `/` | GET | Dashboard 页面 |
| `/api/emotion/current` | GET | 当前情绪状态 |
| `/api/emotion/history` | GET | 情绪历史记录 |
| `/api/emotion/trends` | GET | 趋势分析 |
| `/api/emotion/periodicity` | GET | 周期性模式 |
| `/api/emotion/counts` | GET | 情绪计数 |
| `/api/emotion/valence-series` | GET | 效价时间序列 |
| `/api/behavior/status` | GET | 行为引擎状态 |
| `/api/behavior/command` | GET | 最新行为命令 |
| `/api/parent/report` | GET | 家长报告 (JSON) |
| `/api/parent/report.md` | GET | 家长报告 (Markdown) |
| `/api/intervention/last` | GET | 最新干预计划 |
| `/api/risk/triggers` | GET | 风险触发器 |
| `/api/system/status` | GET | 系统状态 |
| `/api/skill/dashboard-layout` | GET | Dashboard 布局配置 |
| `/api/skill/emotion-panel` | GET | 情绪面板配置 |
| `/api/skill/emotion-timeline` | GET | 时间线面板配置 |
| `/api/skill/behavior-monitor` | GET | 行为监控面板配置 |
| `/api/skill/parent-insight` | GET | 家长洞察面板配置 |
| `/docs` | GET | API 文档 (Swagger) |
