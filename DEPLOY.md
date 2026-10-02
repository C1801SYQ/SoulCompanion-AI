# Deployment / 部署与运行

更新：2026-10-02。

本版为单用户、单儿童的本机产品。**已实际验证的是 Windows + Python 3.12 原生轻量 Web 部署**。完整感知链路使用原生进程；摄像头、麦克风、模型和执行器还需要目标设备验收。无需 Docker 即可部署已验收的软件功能。

## 1. 原生部署

在维护者提交本版后克隆仓库。当前交付改动保留在本地，尚未推送，远程克隆暂时不会包含它们。

```powershell
git clone https://github.com/C1801SYQ/SoulCompanion-AI.git
cd SoulCompanion-AI
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-web.txt
$env:SOULCOMPANION_APP_ENV='production'
$env:SOULCOMPANION_DB=(Join-Path (Get-Location) 'data/emotional_db.sqlite')
.\.venv\Scripts\python.exe -m web.app --host 127.0.0.1 --port 8000
```

访问 http://127.0.0.1:8000 。该实例读取真实 SQLite 历史；未连接 bridge 时没有实时感知数据。首次数据库查询会建立 `data/` 与 SQLite v1 表。服务重启后记录仍保留。

Linux 对应命令为 `.venv/bin/python`。环境变量用 `export NAME=value` 设置。`.env.example` 不会自动读取。不要直接运行多个采集进程或多个 uvicorn worker。

检查：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/healthz
Invoke-RestMethod http://127.0.0.1:8000/readyz
Invoke-RestMethod http://127.0.0.1:8000/api/v1/dashboard/snapshot
```

`healthz=ok` 仅证明 API 活着。`readyz` 无设备时返回 degraded 与具体 reason；数据库失败返回 unavailable/503。设备状态 unknown/disabled/unavailable 不等于 healthy。

关闭前端不会停止另一个真实采集进程。按 Ctrl+C 停止部署进程；启动器关闭 bridge、传感器、TTS、决策 worker 和 Web 服务，第三方阻塞调用超时会明确记录。

## 2. 完整 Edge 模式

在原生 Windows 进程中准备摄像头、麦克风与 [README](readme.md) 的模型路径，再安装可选大型依赖：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe scripts/hardware_smoke_test.py --real
.\.venv\Scripts\python.exe launch.py
```

Web 与 bridge 在同一进程共享快照，主循环另用后台线程调用本地 Ollama。默认 `OLLAMA_TIMEOUT=60` 是每次请求总时限，覆盖连接、响应头和正文；配置 1–120 秒。连接/超时最多重试一次，总等待最多约两倍时限，响应正文最多 64KiB。主循环不等待它；停止时取消当前 socket 并停止发布回复。

大型依赖和实际模型组合未在本轮完整安装；`--real` 结果由部署设备决定，不自动下载模型。物理执行器适配器尚未提供，`--hardware` 会显示 unavailable。默认 smoke 是 FAKE，并返回 `verified_hardware=false`。

## 3. 无硬件演示

```powershell
$env:SOULCOMPANION_DEMO_MODE='true'
.\.venv\Scripts\python.exe launch.py
```

该模式不启动 robot/bridge，不创建或读取真实数据库。恢复真实模式设置 false 并重启。浏览器的 DEMO 按钮只切换视图；如果需要禁止后台采集，必须使用此启动配置。

公开展示仅使用静态合成构建：

```powershell
.\.venv\Scripts\python.exe scripts/build_site.py --out .test-artifacts/site
.\.venv\Scripts\python.exe -m http.server 8080 --bind 127.0.0.1 --directory .test-artifacts/site
```

静态站固定 DEMO-only、零 API 请求，`?nodemo=1` 不能启用真实模式。构建器拒绝非空未标记输出、源目录和链接路径，不删除已有用户文件。

## 4. 持久化与维护

设置 `SOULCOMPANION_DB` 为部署用户独占的本地绝对路径。保护整个数据目录，包括 SQLite、WAL、SHM、备份与导出文件；不要将其放入公开静态目录。Windows 上自行设置目录 ACL，文件模式不提供磁盘加密。

在真实模式的本地终端运行：

```powershell
.\.venv\Scripts\python.exe scripts/data_admin.py info
.\.venv\Scripts\python.exe scripts/data_admin.py backup --output data/backup-20261002.sqlite
.\.venv\Scripts\python.exe scripts/data_admin.py export --output data/export-20261002.json
.\.venv\Scripts\python.exe scripts/data_admin.py retention --days 30 --backup data/pre-retention-20261002.sqlite --confirm-delete
```

输出父目录须存在，文件须为新的文件；每次选择不同名字。使用 SQLite 一致性 backup API，不复制正在写入的 `.sqlite` 而遗漏 WAL。删除/清理持有写锁并验证备份后才删记录。导出默认排除原始文本；`--include-raw` 明确纳入原始数据，CSV 有公式注入防护。

`SOULCOMPANION_RETENTION_DAYS=0` 默认永久保留，非零是手动清理策略，不是自动任务。备份含原始文本，管理员须单独管理与删除；源记录删除不删除备份，也不承诺磁盘残余安全擦除。

恢复时停止所有写入，将已验证备份复制为一个新的私有数据库文件，将 `SOULCOMPANION_DB` 指向它，再启动并检查 history/readyz。不要覆盖仍在运行的数据库。更高 schema_version 会被拒绝，不能用旧程序强行降级打开。

## 5. 可选 Docker 配方（本轮未运行）

仓库提供 `Dockerfile` 与 `compose.yaml` 作为 **Linux Web-only** 配方：

```bash
docker compose up --build -d
docker compose logs dashboard
docker compose down
```

必须在 Linux 主机本机访问 http://127.0.0.1:8000 。采用 host networking 保持严格回环绑定，不发布端口，不挂载设备，不含外网入口。容器非 root，根文件系统只读，SQLite 放在 `companion-data` 卷。单 worker。停止容器不删除数据卷；不要随意使用 `down -v`。

本机没有 Docker，镜像构建、Linux UID/卷权限、host networking、健康检查与 compose 生命周期**尚未实际验证**。Docker Desktop 不属于此配方的已支持环境。执行器及 Windows 摄像头/音频仍采用原生 Edge；本版没有跨容器设备状态中继，容器看板只显示它自身能验证的状态。

## 6. 安全与运维

仅允许本机操作系统用户访问；无远程登录、多用户授权或 TLS 公网模式。应用拒绝远程 bind/client、非法 Host/Origin/转发头。CORS 不是认证。不得使用隧道、端口转发或反向代理公开真实 API。对外只分享 DEMO-only 静态网站。

API 请求每分钟共享默认 180 次限额；多个标签页也共享。错误包含通用 code/message/request_id。日志仅保留模块、类型与故障上下文，不记录原始儿童话语、LLM 提示或生成全文。

## 7. 可重复验收

```powershell
.\.venv\Scripts\python.exe scripts/acceptance_smoke.py
npm ci --ignore-scripts
npx playwright install chromium
$env:SOULCOMPANION_PYTHON=(Resolve-Path .\.venv\Scripts\python.exe).Path
npm run test:e2e
```

两套验收都采用新建临时合成 SQLite 历史，通过真实后端验证启动、分页、报告、数据重启保留与本机边界。浏览器还验证 REAL/DEMO/ERROR/OFFLINE、断线恢复、手机布局和零致命异常。它们不写默认真实数据库，不证明实际硬件或实际儿童会话。

完整测试、已执行证据和未验收项见 `docs/PRODUCT_DELIVERY_REPORT.md`。GitHub Actions 工作流已配置，因未提交/推送，本轮不能确认远程 Actions 全绿。
