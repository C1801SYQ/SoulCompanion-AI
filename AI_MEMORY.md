# AI TechLead Memory

## System Baseline (2026-05-30)

**Project**: SoulCompanion_AI - ASD儿童智能陪伴干预机器人
**Language**: Python 3.10-3.12
**Entry**: main.py (SoulCompanionRobot)
**UI**: web_ui.py (Streamlit)

### Architecture Map

```
main.py ──→ modules/vision_engine.py  (OpenCV+ONNX 人脸/情绪)
     │      modules/speech_engine.py   (Vosk STT + Wav2Vec2 SER)
     │      utils/audio_player.py      (pyttsx3 TTS)
     └──→ Ollama API (gemma4:e4b)      (LLM决策)
```

### Module Status

| Module | Status | Notes |
|--------|--------|-------|
| main.py | ACTIVE | 入口+主循环+决策，含bugs |
| config.py | ACTIVE | 配置，与memory.py不一致 |
| web_ui.py | ACTIVE | Streamlit UI，有阻塞bug |
| modules/vision_engine.py | ACTIVE | 视觉引擎 |
| modules/speech_engine.py | ACTIVE | 语音引擎，线程安全问题 |
| utils/audio_player.py | ACTIVE | TTS播放 |
| core/brain.py | DEAD | RobotBrain从未被导入 |
| core/llm_engine.py | DEAD | 与main._trigger_brain重复 |
| core/prompt_template.py | DEAD | 未被使用 |
| core/memory.py | DEAD | EmotionMemory未被使用 |
| core/hardware.py | DEAD | RobotBody未被使用 |
| modules/voice_engine.py | DEAD | VoiceEngine未被使用 |
| modules/sensor_sim.py | DEAD | get_mock_sensor_data未使用 |
| hardware/controllers/actuators.py | DEAD | RobotActuator未使用 |

### Known Issues

- [x] C1: test1.py 硬编码 Google API Key → 改为环境变量读取 (R1)
- [ ] C1b: ⚠️ 已泄露的 Key 需要用户手动轮换
- [x] C2: main.py _trigger_brain 变量res未定义 → 删除try外重复块 (R2)
- [x] C3: main.py 重复执行res.status_code==200 → 同上修复 (R2)
- [x] C4: reports/report_generator.py SQL注入 → 参数化查询 (R3)
- [ ] H1: 5个死模块未清理
- [ ] H2: config.py vs core/memory.py 配置不一致
- [ ] H3: web_ui.py update_ui() 阻塞主线程
- [x] H4: speech_engine.py 线程安全 → 添加threading.Lock (R5)
- [x] H5: vision_engine.py空except → 改为except Exception (R4)
- [ ] M1: 零测试覆盖

### Risk Zones

- ~~main.py _trigger_brain: 变量作用域bug~~ → 已修复 (R2)
- ~~test1.py: API Key泄露~~ → 已修复 (R1)
- ~~reports/report_generator.py: SQL注入~~ → 已修复 (R3)
- web_ui.py: update_ui阻塞主线程 + 线程安全 → R4目标

### Round History

| Round | Type | Fix | Status |
|-------|------|-----|--------|
| R1 | security | 移除test1.py硬编码API Key+代理 | ✅ DONE |
| R2 | fix | 修复main.py _trigger_brain NameError+重复写入 | ✅ DONE |
| R3 | security | 修复reports/report_generator.py SQL注入 | ✅ DONE |
| R4 | reliability | 修复空except+线程安全问题 | PENDING |
