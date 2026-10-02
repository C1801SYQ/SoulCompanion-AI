"""Product-boundary regressions using fake sensors and no model downloads."""
from __future__ import annotations

import importlib.util
import sys
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import config
import launch
from emotion.bridge import EmotionBridge


@pytest.fixture
def speech(monkeypatch):
    """Load the real speech getters without importing native AI dependencies."""
    monkeypatch.setitem(sys.modules, "numpy", SimpleNamespace())
    monkeypatch.setitem(sys.modules, "pyaudio", SimpleNamespace())
    monkeypatch.setitem(
        sys.modules, "vosk", SimpleNamespace(Model=Mock(), KaldiRecognizer=Mock())
    )
    monkeypatch.setitem(sys.modules, "transformers", SimpleNamespace(pipeline=Mock()))
    path = Path(__file__).resolve().parents[1] / "modules" / "speech_engine.py"
    spec = importlib.util.spec_from_file_location("_speech_product_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    engine = module.SpeechEngine.__new__(module.SpeechEngine)
    engine._lock = threading.Lock()
    engine._consumed_seq = 0
    engine.current_state = {"text": "你好", "emotion": "happy", "seq": 1}
    return engine


@pytest.mark.parametrize("main_reads_first", [True, False])
def test_main_and_bridge_receive_same_speech_event(speech, main_reads_first):
    if main_reads_first:
        consumed = speech.get_latest_text()
        observed = speech.peek_latest_text()
    else:
        observed = speech.peek_latest_text()
        consumed = speech.get_latest_text()
    assert consumed == observed == {"text": "你好", "emotion": "happy", "seq": 1}
    assert speech.get_latest_text() is None
    assert speech.peek_latest_text() == observed


def test_speech_consumers_receive_copies_and_new_events(speech):
    consumed = speech.get_latest_text()
    consumed["text"] = "changed by consumer"
    assert speech.peek_latest_text()["text"] == "你好"
    speech.current_state = {"text": "再见", "emotion": "sad", "seq": 2}
    assert speech.get_latest_text()["seq"] == 2
    assert speech.get_latest_text() is None
    assert speech.peek_latest_text()["text"] == "再见"


def _bridge(tmp_path):
    return EmotionBridge(
        get_vision_state=lambda: {"face_detected": True, "emotion": "happy"},
        get_speech_state=lambda: None,
        db_path=str(tmp_path / "edge.sqlite"),
    )


def test_risk_remains_visible_between_checks_and_clears_after_recheck(tmp_path, monkeypatch):
    bridge = _bridge(tmp_path)
    check = Mock(side_effect=[["持续负面情绪"], []])
    monkeypatch.setattr(bridge.get_memory(), "check_risk_triggers", check)
    for _ in range(10):
        bridge._process_cycle()
    assert bridge.get_snapshot().has_risk is True
    for _ in range(9):
        bridge._process_cycle()
        assert bridge.get_snapshot().has_risk is True
        assert bridge.get_snapshot().risk_triggers == ["持续负面情绪"]
    assert check.call_count == 1
    bridge._process_cycle()
    assert bridge.get_snapshot().has_risk is False
    assert check.call_count == 2


def test_failed_memory_write_retries_without_waiting_for_heartbeat(tmp_path, monkeypatch):
    bridge = _bridge(tmp_path)
    memory = bridge.get_memory()
    original_record = memory.record
    record = Mock(side_effect=[OSError("database unavailable"), None])

    def flaky_record(*args, **kwargs):
        record(*args, **kwargs)
        original_record(*args, **kwargs)

    monkeypatch.setattr(memory, "record", flaky_record)
    bridge._process_cycle()
    assert bridge.get_snapshot().last_error == "memory_write_failed"
    assert bridge.get_snapshot().data_available is True
    assert memory.get_records() == []
    bridge._process_cycle()
    assert record.call_count == 2
    assert len(memory.get_records()) == 1
    assert bridge.get_snapshot().cycle_count == 2


@pytest.mark.parametrize("robot_initialization_fails", [False, True])
def test_launcher_without_robot_never_creates_recording_bridge(monkeypatch, robot_initialization_fails):
    bridge_constructor = Mock(side_effect=AssertionError("must not create a dummy bridge"))
    monkeypatch.setattr("emotion.bridge.EmotionBridge", bridge_constructor)
    set_bridge = Mock()
    monkeypatch.setitem(sys.modules, "web.api", SimpleNamespace(app=object(), set_bridge=set_bridge, set_runtime=Mock()))
    server = SimpleNamespace(started=True, run=Mock(), should_exit=False)
    monkeypatch.setitem(sys.modules, "uvicorn", SimpleNamespace(Config=Mock(), Server=Mock(return_value=server)))
    robot_constructor = Mock(side_effect=RuntimeError("sensor dependencies missing"))
    monkeypatch.setitem(sys.modules, "main", SimpleNamespace(SoulCompanionRobot=robot_constructor))
    web_thread = Mock()
    monkeypatch.setattr(launch.threading, "Thread", Mock(return_value=web_thread))
    monkeypatch.setattr(launch.time, "sleep", Mock(side_effect=KeyboardInterrupt))

    launch.launch(enable_robot=robot_initialization_fails)

    bridge_constructor.assert_not_called()
    set_bridge.assert_called_once_with(None)
    web_thread.start.assert_called_once()
    if robot_initialization_fails:
        robot_constructor.assert_called_once()
    else:
        robot_constructor.assert_not_called()


def test_launcher_rejects_unsafe_bind_before_initializing_devices(monkeypatch):
    validator = Mock(side_effect=ValueError("loopback only"))
    monkeypatch.setattr(config, "validate_bind_host", validator)
    robot = Mock()
    monkeypatch.setitem(sys.modules, "main", SimpleNamespace(SoulCompanionRobot=robot))
    with pytest.raises(ValueError, match="loopback only"):
        launch.launch(host="0.0.0.0")
    validator.assert_called_once_with("0.0.0.0")
    robot.assert_not_called()


def test_launcher_cli_reports_bind_validation_error(monkeypatch, capsys):
    monkeypatch.setattr(config, "validate_bind_host", Mock(side_effect=ValueError("loopback only")))
    monkeypatch.setattr(sys, "argv", ["launch.py", "--host", "0.0.0.0"])
    run = Mock()
    monkeypatch.setattr(launch, "launch", run)
    with pytest.raises(SystemExit) as error:
        launch.main()
    assert error.value.code == 2
    assert "loopback only" in capsys.readouterr().err
    run.assert_not_called()
