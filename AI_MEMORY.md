# AI TechLead Memory

## System Baseline (2026-05-30)

**Project**: SoulCompanion_AI - ASD儿童智能陪伴干预机器人
**Language**: Python 3.10-3.12
**Entry**: main.py (SoulCompanionRobot)
**UI**: web_ui.py (Streamlit) + web/api.py (FastAPI) + streamlit_dashboard.py

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
     └── models.py           ← 共享数据模型

web/ (NEW - Web Dashboard)
     ├── api.py              ← FastAPI REST API (20+ endpoints)
     ├── app.py              ← 应用入口
     ├── templates/dashboard.html ← 4-panel dashboard
     └── static/{style.css, app.js} ← 前端资源
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
- [ ] M1: 零测试覆盖

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
- **No main.py modification**: All new code in emotion/ and web/ packages
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
