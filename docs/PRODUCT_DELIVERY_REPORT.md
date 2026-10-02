# SOULCOMPANION PRODUCT DELIVERY REPORT

日期：2026-10-02。基准：`09a9fe0cd455a810a04c48ac7226e4989266ee75`。

本轮完成单用户、单儿童、本机访问的软件交付：正式 API、实时看板、历史分页、报告导出、组件状态、隐私与数据维护、故障处理、测试和原生部署。FusionEngine、BehaviorSync 和情绪规则数值保留。软件验收通过；远程 GitHub Actions、Docker 和真实硬件仍未执行验收，不计作通过。

## 1. GitHub vs Local

修改前首先完成用户要求的 Git 差异审计，未提前修改源码。

```text
LOCAL_REMOTE_AUDIT
current_branch: master
local_head_before_sync: 354abd7ef29c18ca5ad9695869a879983e70ae54
origin_master: 09a9fe0cd455a810a04c48ac7226e4989266ee75
ahead: 0
behind: 1
modified: none
staged: none
untracked: none
local_only_commits: none
remote_only_commits: 09a9fe0 Improve runtime reliability, engineering documentation and automated checks
conclusion: clean checkout; fast-forwarded to the verified origin/master baseline
```

原八项差异属于远程提交，不是用户本地修改。快进后 HEAD 与本轮已获取的 origin/master 都为上述基准；交付改动留在工作区，未暂存、未提交、未推送。没有 reset、clean 或丢弃用户代码。

最终 `git status`、`git diff --stat`、原始 `git diff` 及含新文件的完整补丁保存在本聊天交付目录，供逐文件审阅。`git diff` 本身不包含 untracked，新文件另合并进完整补丁。

## 2. Original Architecture

实际调用链已从源码重建，详情与生命周期图在 [PRODUCT_AUDIT](PRODUCT_AUDIT.md)。

```text
launch.py → robot(main.py)
              ├─ VisionEngine / camera+ONNX thread
              ├─ SpeechEngine / microphone callback+ASR/SER thread
              ├─ TTS queue
              └─ blocking Ollama call in original main loop

Vision/Speech → EmotionBridge(0.5s)
  → FusionEngine → MemoryAxis(record)
  → BehaviorSync → EmbodiedEngine
  → InterventionEngine → risk check(every10cycles)
  → locked in-process snapshot → FastAPI → Vanilla JS

SQLite → separate history/report API reads
Original frontend: eight requests/second; errors silently switched to DEMO
```

数据库连接原来未显式关闭；Web 拥有多个懒初始化全局模块。模型在设备构造时加载，bridge/Web/robot 共用一个进程而非多进程共享状态。旧 Streamlit 是另一个机器人生命周期；静态演示没有 Python 后端。

## 3. Problems Found

| 等级 | 主要问题 |
| --- | --- |
| P0 | 无认证真实数据可远程绑定、文档推荐隧道；动态字符串进入 HTML；断线偷偷 Demo；无机器人仍写默认状态；报告区间错误；构建可删除任意输出 |
| P1 | 缺具名 v1 契约、统一错误与请求编号、历史分页、报告导出、真实组件状态、设置与维护 |
| P2 | 每秒八个请求与历史扫描、刷新重叠、连接未关、语音消费竞争、风险缓存丢失、设备失败不透明、Ollama 与停止不受控 |
| P3 | 空数据/加载/断线/键盘/手机布局不完整，模型与配置、部署说明互相矛盾 |

选择 Local-only Product、Vanilla JS、REST snapshot、SQLite 和单 worker。没有引入空的用户/多租户表、React 迁移、Alembic、Redis 或微服务。

## 4. Security Fixes

- 配置仅允许 localhost/回环绑定；所有路由拒绝远程客户端、非法 Host、跨站 Origin 和代理转发头。
- CORS 只接受合法本机来源，不承担认证。API 共享每分钟限额，429 有 Retry-After。
- 统一 `error.code/message/request_id`，异常不返回内部路径或原始儿童文本。
- 动态 UI 字符串全部采用 DOM/textContent；LED 颜色白名单。测试恶意报告、行为、历史和隐私字符串。
- REAL/DEMO/OFFLINE/ERROR 明确分开。后台显式 DEMO 禁用采集及真实历史；静态产物固定 DEMO-only。
- 旧 Streamlit 采集入口改为无采集的导航页。旧 CloudSync 的远程 relay 被明确拒绝，不能作为远程捷径。
- 真实数据库、备份、导出和测试产物不进入 Git；日志不记录原始话语、提示词或生成全文。

本机操作系统登录用户是管理员；无远程会话、家长账户、密码服务或多租户。正式 v1 历史与默认导出不含原文；兼容旧接口可能含原文，仍受本机边界保护。

## 5. Backend Changes

`web/contracts.py` 定义具名 Pydantic 模型；`web/product.py` 注册正式路由；`web/service.py` 处理快照、历史、报告、状态和设置；`web/security.py` 提供访问边界。

| 正式接口 | 用途 |
| --- | --- |
| GET /api/v1/dashboard/snapshot | 一次读取已发布的实时快照，不扫描数据库或调用模型 |
| GET /api/v1/emotions/history | 1/7/30 天筛选、稳定排序与分页，默认隐藏原始文本 |
| GET /api/v1/emotions/analytics | 趋势、类别分布、最多 500 个 SQL 采样点 |
| GET /api/v1/reports/parent | 区间一致的家长报告，空数据分数为 null |
| GET /api/v1/reports/parent.md | Markdown 导出 |
| GET /api/v1/system/status | 十项组件状态与原因，5 秒检查缓存 |
| GET /api/v1/system/readiness | 就绪结果及 HTTP 状态 |
| GET /api/v1/system/settings | 单档案范围、隐私、存储及手动保留策略 |
| GET /healthz、/readyz | 无副作用存活、就绪别名 |

同步数据库工作由 Web 线程池执行，懒初始化加锁。旧 GET 接口保留兼容，DEMO 在调用旧 getter 前拦截。组件区分 healthy/degraded/unavailable/disabled/unknown；没有运行时不会把设备标为正常。

## 6. Frontend Changes

单一 Vanilla JS 看板提供实时情绪、confidence/valence/arousal/来源/原因、最新行为与风险；1/7/30 天趋势和历史分页；独立日期范围的报告与 Markdown；十项设备状态；设置与隐私。

每个数据通道独立处理超时、进行中的请求、重试与版本。改变模式或日期会取消并丢弃旧响应，避免旧报告被下载成新日期。范围失败清空旧范围的评分与趋势，明确显示失败。没有感知数据时不制造“中性、50%置信度”。

| 轮询 | 频率 |
| --- | --- |
| 快照 | 每秒一次 |
| 系统 | 每 7 秒 |
| 历史/趋势 | 每 30 秒或交互 |
| 报告 | 每 60 秒或手动 |
| 设置 | 初始化/手动；数据库检查完成同步显示，无额外请求 |

DOM 定量测试：首次 6 请求，稳定一分钟 73 请求（原 480，约减少 84.8%）。真实浏览器 5.2 秒测得 5 次快照、0 次历史/报告请求，快照最大同时进行数 1。不是 CPU 性能基准，不宣称 CPU 降幅。

提供语义表格、按钮与范围状态、键盘焦点、图表文字替代和 reduced-motion；手机表格在卡片内滚动，页面不横向溢出。浏览器 DEMO 明确提醒后台可能仍按真实配置采集；彻底禁止采集须使用启动配置。

## 7. Database Changes

SQLite v1 事务迁移保留原记录、legacy logs 与索引，写入 single_child 范围元数据；未知更高版本拒绝打开/写入。连接显式关闭，启用 busy timeout/foreign_keys，保持原情绪算法。

`core/data_admin.py` 与 `scripts/data_admin.py` 提供 info、SQLite 一致性备份、流式 JSON/CSV 导出、删除与手动 retention。维护只打开已存在数据库，不误建空源库。输出独占创建，拒绝覆盖现有文件、数据库、源码后缀和链接/特殊 Windows 路径；CSV 防公式注入。

删除必须 `--confirm-delete` 并先生成验证通过的完整备份；清理持有写锁。保留默认 0 天不删，非零不会自动运行。原始文本需 `--include-raw` 才导出，但备份完整包含原文。源数据删除不删除备份，也不承诺磁盘残余法证级擦除。

全部维护验证针对临时合成数据库；没有清理用户真实数据。

## 8. AI/Edge Changes

Vision/Speech 分别检查设备打开、模型缺失/损坏、采集及推理失败，发布状态与时间戳；限频日志、有界音频队列和窗口、独立语音消费游标、幂等停止与资源释放。SER 使用本地 model/feature extractor 对象，明确 local_files_only。

bridge 只在有效视觉情绪、SER 情绪或合法传入环境读数存在时记录/执行；纯转写、无人脸、缺失/过期模型观测不伪造真实情绪。风险结果缓存带检查时间，快照深复制；存储失败可见并下轮重试。

Ollama 使用直连本地 HTTP、单后台任务、整体截止时间、64KiB 正文上限，禁止代理/重定向。连接/超时最多重试一次；非 200、坏 JSON、空回复与异常有确定性回复。停止取消 socket 与回调。真实延迟响应、持续缓慢响应头/正文、超量正文和取消均有回归。

启动器拥有 uvicorn.Server 生命周期，连接 runtime 状态并有界关闭。TTS 队列有限，初始化和系统驱动停止超时可见。实体执行器仍未实现，模拟器明确标识；--hardware 不冒充已连接。

## 9. Tests

已验证 Windows、Python 3.12.4、Node 24.15.0、Playwright Chromium。原 163 项 Python 基线保留，最终 **327 passed**；有一条 Starlette 关于测试客户端 httpx 的弃用提示，不影响结果。

| 检查 | 最终结果 |
| --- | --- |
| 全量 pytest | 327 passed，0 failed |
| 前端 DOM | 38 passed |
| 原合成引擎自测 | 44 passed |
| 浏览器 | 8 项流程通过；0 致命脚本异常 |
| Python compileall / Ruff / JS syntax | 通过 |
| 静态 frontend build | 通过，强制 DEMO-only |
| 实际原生 API/SQLite smoke | health ok，readiness degraded 有原因，65 记录分页/报告/重启保留，本机边界通过 |
| Fake hardware smoke | software_contract_passed=true；verified_hardware=false |
| pip check | 无破损轻量依赖 |
| pip-audit / npm audit | 本轮锁定轻量运行时/前端依赖无已知漏洞 |
| git diff --check | 通过 |

浏览器覆盖实际后端、REAL 空感知、分页、报告下载、显式 DEMO 零 API、错误恢复、停止/重启、静态 DEMO 禁止真实连接、375/768/1440 像素与键盘操作。通过真实 SQLite/HTTP 的合成 fixture 证明软件集成与持久化，不代表实际儿童或物理设备。

Windows 验收使用私有停止文件关闭实际服务，等待进程退出并以 TCP 明确拒绝连接证明端口已关闭；重启不重新播种，浏览器核对新 HTTP 历史响应而非残留页面文本。启动即覆盖旧结果，清理或检查失败写入本轮 failed 证据并返回失败。最终原生与浏览器验收均通过，相关失败路径经隔离验证。

Python/TypeScript 专项及代码复核发现并修复了旧 DEMO 绕过、旧库版本绕过、就绪重定向、报告导出竞态、范围残留、ASR 默认情绪记录和 Ollama 总时限/连接超时回归。最后复核没有剩余阻断项。

## 10. CI

`.github/workflows/checks.yml` 包含 backend-tests、frontend-build、frontend-tests、lint、dependency-checks。使用 Python 3.12 / Node 24；安装轻量依赖，Fake 模型/设备，浏览器安装不下载感知模型。构建与浏览器结果作为 Actions artifacts 保存。

这些检查的本地对应流程已通过；**远程 Actions 未执行本版**。未推送意味着远程仍是基准提交，不能声称 GitHub Actions 已全绿。维护者提交后须实际运行并确认五个 job。

## 11. Deployment

新建 Python 3.12 虚拟环境，仅安装 `requirements-web.txt`，锁定 16 个运行时包并 pip check 通过。使用不含原模型、数据、虚拟环境或 node_modules 的干净源码副本启动实际后端，完成静态构建及 65 条记录的报告/重启验收。陌生开发者安装流程写在 README 与 DEPLOY。

最终干净副本包含 87 个源码文件，六项复测依次为原生 API/重启、静态构建、327 项 pytest、38 项 DOM、44 项合成演示、Fake hardware，全部通过。开发测试使用已声明开发依赖；运行与构建使用只安装轻量 Web 依赖的新环境。

实际验证方案为 Windows 原生轻量 Web。本地 Web-only 正确降级，不假装设备可用。完整 Edge 使用原生 Windows，模型/驱动组合仍需实机。

另外提供非 root、只读根文件系统、持久化卷、回环 host networking 的 Linux Web-only Dockerfile/compose 配方。YAML 结构检查通过；**无 Docker 可执行程序，因此未构建或运行镜像**。不提供公网真实 Dashboard 或跨容器设备中继。

## 12. Remaining Limitations

1. 真实摄像头、麦克风、ONNX/Vosk/SER、Ollama 模型生成、TTS 与实体执行器未实机验收；Fake 不算实机通过。
2. 无远程用户认证、多儿童、多租户、云数据库或公网访问。未来远程版须新增会话/授权/CSRF/HTTPS 与数据归属。
3. GitHub Actions 远程执行和 Docker 生命周期仍待验证。
4. 大型可选感知依赖不在轻量依赖锁/漏洞验收范围；目标设备需安装和适配。
5. 第三方模型/音频驱动阻塞只能有界等待并报告超时，不能强制安全中断驱动。Ollama HTTP 已有总时限和取消。
6. 无数据静态/软件验收不提供临床效果、推断准确率或执行器可用性证明。

## 13. Commands to Run

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-web.txt
.\.venv\Scripts\python.exe -m web.app
# http://127.0.0.1:8000

# 完全禁用真实采集与数据库的显式演示，在新终端执行
$env:SOULCOMPANION_DEMO_MODE='true'
.\.venv\Scripts\python.exe launch.py

# 软件验收，在真实模式终端
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
New-Item -ItemType Directory -Force .test-artifacts
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp .test-artifacts/pytest-local
.\.venv\Scripts\python.exe scripts/acceptance_smoke.py
.\.venv\Scripts\python.exe scripts/hardware_smoke_test.py
npm ci --ignore-scripts
npm test
npm run test:demo
npm run build
npm run lint
npx playwright install chromium
$env:SOULCOMPANION_PYTHON=(Resolve-Path .\.venv\Scripts\python.exe).Path
npm run test:e2e
```

配置、模型、备份/导出/删除/恢复命令和故障排查均在 README / DEPLOY；.env.example 不自动读取。用户真实维护需明确确认和备份；验收脚本只用临时合成数据库。

建议后续按审阅单元提交（本轮不自动提交）：

```text
fix: enforce local data and runtime boundaries
feat: add typed product API and SQLite maintenance
feat: productize dashboard and snapshot polling
fix: harden edge lifecycle and bounded Ollama transport
test: add integration, frontend and browser acceptance
deploy: add native deployment and optional container recipe
docs: finalize product audit and handoff
```

## 14. Product Acceptance Checklist

| 要求 | 状态与证据 |
| --- | --- |
| 初始 Git 审计/保护本地代码 | 通过；清洁基线快进，改动未提交/推送 |
| Clone / 按 README 安装 | 干净源码副本 + 新轻量环境通过；远程新克隆须待维护者提交本版 |
| Backend | 通过；health=ok，readiness=degraded 且原因明确 |
| Frontend | 通过；浏览器 0 致命脚本异常，桌面/手机可交互 |
| Integration | 通过；实际 API 返回实际临时 SQLite 记录 |
| Demo | 通过；显式 DEMO DATA，无静态真实 API 请求 |
| Offline | 通过；Backend disconnected，保持真实模式并可恢复 |
| Database / Report | 通过；65 条测试记录实际写入、重启保留、历史报告/下载 |
| Security | 通过本机边界；不提供远程真实模式 |
| Tests | 327 Python + 38 DOM + 44 demo + 8 browser 全通过 |
| CI | 工作流已完成，本地对应流程通过；远程执行待提交后验证 |
| Deployment | 原生实际验证通过；Docker 配方待验证 |
| Documentation | 启动/模型/维护/范围/故障命令交叉核对通过 |
| Physical devices / accuracy | 未验收，明确未计入通过 |

阶段顺序与主要文件在 PRODUCT_AUDIT；P0、产品 API、前端/轮询、维护、Edge、CI、部署、文档和最终验收均有回归检查。期间审查发现的问题已修复后重跑全量检查，没有用删除失败测试或伪造设备状态取得通过。
