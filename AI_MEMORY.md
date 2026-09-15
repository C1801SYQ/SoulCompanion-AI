# AI TechLead Memory

## System Baseline (2026-09-13, R11)

**Project**: SoulCompanion_AI - ASD儿童智能陪伴干预机器人
**Language**: Python 3.10-3.12
**Entry**: main.py (SoulCompanionRobot) / launch.py (三合一启动器)
**UI**: web_ui.py (Streamlit) + web/api.py (FastAPI) + streamlit_dashboard.py
**Tests**: tests/ (pytest, **132 passed**, 零重依赖 — 只 import emotion/* 与 config)
**Config**: config.py 为**唯一**配置源（支持环境变量覆盖）

### Architecture Map

```
main.py ──→ modules/vision_engine.py  (OpenCV+ONNX 人脸/情绪)
     │      modules/speech_engine.py   (Vosk STT + Wav2Vec2 SER)
     │      utils/audio_player.py      (pyttsx3 TTS)
     └──→ Ollama API (gemma4:e4b)      (LLM决策)

emotion/ (NEW - 情绪智能核心)
     ├── fusion_engine.py    ← Vision+Speech+Env → EmotionState
     ├── memory_axis.py      ← SQLite长期记忆 + 趋势分析 + 周期检测
     ├── behavior_sync.py    ← EmotionState → BehaviorCommand
     ├── embodied_engine.py  ← BehaviorCommand → 硬件/模拟执行
     ├── intervention.py     ← EmotionState → 干预计划 + 家长报告
     ├── bridge.py           ← 非侵入式集成桥（后台线程跑完整管线）
     └── models.py           ← 共享数据模型

web/ (NEW - Web Dashboard)
     ├── api.py              ← FastAPI REST API (20+ endpoints)
     ├── app.py              ← 应用入口
     ├── templates/dashboard.html ← 4-panel dashboard
     └── static/{style.css, app.js} ← 前端资源

tests/ (R11 - 单元测试)
     ├── conftest.py         ← 项目根加入 sys.path
     ├── test_fusion_engine.py / test_behavior_sync.py / test_intervention.py
     ├── test_memory_axis.py / test_bridge.py / test_config.py
     └── 运行: .venv-test/Scripts/python.exe -m pytest -q
```

### Module Status

| Module | Status | Notes |
|--------|--------|-------|
| main.py | ACTIVE | 入口+主循环+LLM决策 |
| config.py | ACTIVE | 全局配置 |
| web_ui.py | ACTIVE | Streamlit UI (原有) |
| streamlit_dashboard.py | ACTIVE | Streamlit Cloud部署入口 (新增) |
| modules/vision_engine.py | ACTIVE | 视觉引擎 |
| modules/speech_engine.py | ACTIVE | 语音引擎 |
| utils/audio_player.py | ACTIVE | TTS播放 |
| emotion/fusion_engine.py | ACTIVE | 多模态情绪融合 (新增) |
| emotion/memory_axis.py | ACTIVE | 长期情绪记忆 (新增) |
| emotion/behavior_sync.py | ACTIVE | 情绪→行为映射 (新增) |
| emotion/embodied_engine.py | ACTIVE | 拟人行为仿真 (新增) |
| emotion/intervention.py | ACTIVE | 教育型干预系统 (新增) |
| emotion/models.py | ACTIVE | 共享数据模型 (新增) |
| web/api.py | ACTIVE | FastAPI REST API (新增) |
| web/app.py | ACTIVE | Web应用入口 (新增) |
| core/memory.py | UNUSED | 未被导入但保留(有实际功能) |
| hardware/controllers/actuators.py | UNUSED | 未被导入但保留(未来硬件) |
| ~~core/brain.py~~ | REMOVED | 死代码 R8 |
| ~~core/llm_engine.py~~ | REMOVED | 死代码 R8 |
| ~~core/prompt_template.py~~ | REMOVED | 死代码 R8 |
| ~~core/hardware.py~~ | REMOVED | 死代码 R8 |
| ~~modules/voice_engine.py~~ | REMOVED | 死代码 R8 |
| ~~modules/sensor_sim.py~~ | REMOVED | 死代码 R8 |

### Known Issues

- [x] C1: test1.py 硬编码 Google API Key → 改为环境变量读取 (R1)
- [ ] C1b: ⚠️ 已泄露的 Key 需要用户手动轮换
- [x] C2: main.py _trigger_brain 变量res未定义 → 删除try外重复块 (R2)
- [x] C3: main.py 重复执行res.status_code==200 → 同上修复 (R2)
- [x] C4: reports/report_generator.py SQL注入 → 参数化查询 (R3)
- [x] H1: 6个死模块 → 已删除194行 (R8)
- [x] H2: config.py vs core/memory.py 配置不一致 → 统一从config读取 (R7)
- [x] H3: web_ui.py update_ui() 阻塞主线程 → 改为daemon线程 (R6)
  - ⚠️ 已知限制：Streamlit非线程安全，完整修复需后续迭代
- [x] H4: speech_engine.py 线程安全 → 添加threading.Lock (R5)
- [x] H5: vision_engine.py空except → 改为except Exception (R4)
- [x] M1: 零测试覆盖 → tests/ 132 用例全绿 (R11)
- [ ] C1b: ⚠️ 已泄露的 Key 需要用户手动轮换（需用户本人操作）

### R11 遗留技术债（已由 R12 关闭）

- [x] N-1 (P2): `behavior_sync.py` 硬编码注意力阈值 `0.3`，与 `intervention.ATTENTION_THRESHOLD_LOW` 重复 → 已抽为 `emotion/models.py` 公共常量 (R12)
- [x] N-2 (P3): `bridge.EmotionSnapshot.attention_level` 默认 `1.0`，与"视觉未知=0.5"约定自相矛盾 → 已改为 `0.5` (R12)
- [x] N-3 (P3): `intervention._is_in_cooldown` 第 2/3 分支等价（`_last_urgency` 判断形同虚设）；`fusion_engine` ASD 规则里 `DISTRESSED` 分支不可达（`VISION_EMOTION_MAP` 永不产出 DISTRESSED）→ 均已清理 (R12)
- [ ] 未覆盖：cv2/vosk/torch/pyaudio 未安装，视觉/语音/音频模块仅做 AST/语法级验证，未做实机采集验证
- [ ] `readme2.0.md` 的删除尚未提交（工作区内为已删除状态）

### Risk Zones

- ~~main.py _trigger_brain: 变量作用域bug~~ → 已修复 (R2)
- ~~test1.py: API Key泄露~~ → 已修复 (R1)
- ~~reports/report_generator.py: SQL注入~~ → 已修复 (R3)
- ~~web_ui.py: update_ui阻塞~~ → 已修复 (R6)
- web_ui.py: Streamlit线程安全 → 已知限制，需后续迭代

### Emotion System Architecture (R10)

**Phase 1 - Architecture**: ✅ DONE
**Phase 2 - Emotion Core**: ✅ DONE (fusion_engine + memory_axis)
**Phase 3 - Behavior System**: ✅ DONE (behavior_sync + embodied_engine)
**Phase 4 - Intervention System**: ✅ DONE (intervention + parent report)
**Phase 5 - Web Dashboard**: ✅ DONE (FastAPI + Streamlit Cloud)
**Phase 6 - Deployment**: ✅ DONE (4 deployment options)

#### Data Flow
```
Vision/Speech/Bio → FusionEngine → EmotionState
                                    ├── MemoryAxis (persist + trend)
                                    ├── BehaviorSync → EmbodiedEngine (servo/LED)
                                    ├── Intervention → ParentReport
                                    └── WebDashboard (real-time display)
```

#### Key Design Decisions
- **R10 期间不改 main.py**: 新代码全部落在 emotion/ 与 web/ 包内
- **R11 起允许最小化改动 main.py**: 删除重复 Config、对话历史裁剪、超时可配置（消除配置漂移的必要代价）
- **Hardware abstraction**: embodied_engine works with or without physical hardware
- **ASD-specific rules**: Never command, never criticize, always gentle
- **Skill-driven UI**: /api/skill/* endpoints generate UI configuration
- **Dual deployment**: Streamlit Cloud (simple) + FastAPI (production)

### Round History

| Round | Type | Fix | Status |
|-------|------|-----|--------|
| R1 | security | 移除test1.py硬编码API Key+代理 | ✅ DONE |
| R2 | fix | 修复main.py _trigger_brain NameError+重复写入 | ✅ DONE |
| R3 | security | 修复reports/report_generator.py SQL注入 | ✅ DONE |
| R4 | fix | 修复空except→except Exception in vision_engine | ✅ DONE |
| R5 | fix | speech_engine添加threading.Lock | ✅ DONE |
| R6 | fix | web_ui update_ui改为daemon线程 | ✅ DONE |
| R7 | refactor | 统一DATABASE_PATH配置 | ✅ DONE |
| R8 | refactor | 删除6个死代码模块(-194行) | ✅ DONE |
| R9 | refactor | 清理未用导入+修复重复渲染 | ✅ DONE |
| R10 | feat | 情绪智能系统+Web仪表板+部署方案 | ✅ DONE |
| R11 | fix/perf/security | 配置集中化+语音竞态+融合缺失模态+干预冷却安全+SQLite写放大+CORS+日志刷屏+日报回退链路+测试套件(132) | ✅ DONE |
| R12 | refactor/feat | 4项技术债收尾 + 看板静态化(双模式)==>Cloudflare Pages 可部署(测试153) | ✅ DONE |

### R12 交付摘要（供后续轮次参考）

**技术债收尾**
| # | 文件 | 改动 |
|---|------|------|
| 1 | `emotion/models.py` / `behavior_sync.py` / `intervention.py` | 新增唯一阈值源 `ATTENTION_THRESHOLD_LOW=0.3`，两处改为 import（`intervention` 留同名别名），行为不变 |
| 2 | `emotion/bridge.py` | `EmotionSnapshot.attention_level` 默认 `1.0 → 0.5`（"视觉未知"不再被渲染成"满注意力"） |
| 3 | `emotion/intervention.py` | `_is_in_cooldown` 去掉等价死分支（high→8s，其余→30s），语义与 R11 等价 |
| 4 | `emotion/fusion_engine.py` | 抽 `ASD_VISION_PRIORITY={ANXIOUS,FEARFUL}`，移除不可达 `DISTRESSED`；`disgust→ANXIOUS` 仅加注释（**建议后续独立映射为 DISGUST**） |

**看板静态化（一套代码、双模式）**
- `web/static/demo-data.js`（新）：纯前端演示引擎，复刻融合/行为映射管线，预生成 30 天**决定论**合成历史，覆盖 11 个 API URL，暴露 `window.SoulCompanionDemo`
- `web/static/app.js`：`fetchJSON` 失败/非 2xx 且 `demoFallback` → 切一次演示模式 + 醒目徽章 `demo-badge`；支持 `?demo=1` / `?nodemo=1`
- `scripts/build_site.py` → 一键构建 `dist-site/`（幂等、无 Jinja 残留）
  - 单一数据源：`web/templates/dashboard.html` + `web/static/*` → `dist-site/`
- `scripts/verify_demo.js`（演示引擎回归，44 项）、`docs/Cloudflare部署指南.md`
- 部署：`npx wrangler pages deploy dist-site --project-name=soulcompanion-dashboard`

**⚠️ 维护契约（CRITICAL）**：任何 `/api/*` 端点变更**必须同步 `web/static/demo-data.js`**，字段名/类型要与 `web/api.py` 逐项一致，否则静态站白屏。

**部署状态**：沙箱预览 `https://9cb69cfe8a084ac8b8ce754814a9e2c1.app.workbuddy.host`（自动演示模式）；
Cloudflare Pages **待用户提供 `CLOUDFLARE_API_TOKEN` + `CLOUDFLARE_ACCOUNT_ID`**；`wrangler` 已预热 4.131.1。
环境有 `HTTP_PROXY`/`HTTPS_PROXY`，上传失败时用 `HTTP_PROXY= HTTPS_PROXY= npx wrangler ...` 清空重试。


### R11 关键修复摘要（供后续轮次参考）

| # | 问题 | 修复 |
|---|------|------|
| 1 | `main.py` 自带重复 `Config`；`config.py` 只有 2 行 | `config.py` 成为唯一配置源（env 覆盖 + 绝对 DATABASE_PATH） |
| 2 | `RobotState.chat_history` 无界增长 | 新增 `push_history()` 裁剪至 `MAX_CHAT_HISTORY=200` |
| 3 | **语音事件竞态**：`get_latest_text()` 破坏性读取，main 与 bridge 抢事件 | 新增非破坏性 `peek_latest_text()`（带 `seq`）；bridge 按 seq 去重 + 10s 新鲜度窗 |
| 4 | **融合把"没人说话"当成一次真实 NEUTRAL 投票** | 缺失模态返回 `None` → 权重置零并重新归一化；无人脸时视觉视为缺失；单模态降权；白天仅 `hour` 不投票（第 2 轮补） |
| 5 | **干预冷却挡掉安全关键干预** | 先算计划再判冷却；高紧急度（`urgency=high`）走独立 8s 窗口 |
| 6 | **SQLite 写放大**：每 0.5s 写 1 行（约 17 万行/天） | `bridge._should_record()` 按 `(category, valence档位)` 去重 + 30s 心跳基线；WAL + busy_timeout + 自动建目录 |
| 7 | CORS `["*"]` + `allow_credentials=True` 互斥且不安全；默认绑定 `0.0.0.0` | 从 `config.CORS_ORIGINS` 读取，通配模式强制 `credentials=False`；默认只绑 `127.0.0.1` |
| 8 | `embodied_engine` 每 0.5s 刷多条 INFO + docstring 谎称起后台线程；日报只读没人写的 `logs` 表 | 即时派发模型 + 变更去重 + DEBUG 日志；`report_generator` 优先读 `emotion_records` 回退 `logs` |
| 9 | 依赖清单残缺（`requirements.txt` 只有 `streamlit`；`launch.py` 引用的 `requirements-web.txt` 不存在） | 补齐 `requirements.txt` / `requirements-web.txt`（新建）/ `requirements-dev.txt`（新建） |

### Deployment Quick Reference

```bash
# Streamlit Cloud
streamlit run streamlit_dashboard.py

# FastAPI Dashboard
python -m web.app

# With custom port
python -m web.app --port 8080

# Development mode
python -m web.app --reload
```

### API Endpoints Summary

- `/` - Dashboard页面
- `/api/emotion/current` - 当前情绪状态
- `/api/emotion/history` - 情绪历史
- `/api/emotion/trends` - 趋势分析
- `/api/behavior/command` - 行为命令
- `/api/parent/report` - 家长报告
- `/api/risk/triggers` - 风险检测
- `/api/skill/*` - Skill驱动UI配置
- `/docs` - API文档
