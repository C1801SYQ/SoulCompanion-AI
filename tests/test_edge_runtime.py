"""Device failures and lifecycle tests without native hardware or model files."""
from __future__ import annotations

import sys
import threading
import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from emotion.bridge import EmotionBridge
from emotion.embodied_engine import EmbodiedEngine
from modules.speech_engine import SpeechEngine
from modules.vision_engine import VisionEngine
from utils.audio_player import AudioPlayer


def eventually(predicate, timeout=1.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    assert predicate()


class Frame:
    def __getitem__(self, item):
        return self

    def copy(self):
        return Frame()


@pytest.fixture
def vision_factory(tmp_path):
    resources = []

    def make(*, opened=True, frame_failure=False, inference_failure=False, haar_failure=False, model_missing=False):
        camera = SimpleNamespace(isOpened=Mock(return_value=opened), read=Mock(return_value=(not frame_failure, Frame())), release=Mock())
        cascade = SimpleNamespace(empty=Mock(return_value=haar_failure), detectMultiScale=Mock(return_value=[(0, 0, 10, 10)]))
        model = SimpleNamespace(setInput=Mock(), forward=Mock(return_value=[[0, 0, 0, 1, 0, 0, 0]]))
        if inference_failure:
            model.forward.side_effect = RuntimeError("fixture inference error")
        backend = SimpleNamespace(CascadeClassifier=Mock(return_value=cascade), dnn=SimpleNamespace(readNetFromONNX=Mock(return_value=model), blobFromImage=Mock()), resize=Mock(return_value=Frame()), cvtColor=Mock(return_value=Frame()), COLOR_BGR2GRAY=0)
        model_path = tmp_path / "fake.onnx"
        if not model_missing:
            model_path.touch()
        engine = VisionEngine(str(model_path), cv_backend=backend, camera_factory=lambda: camera)
        resources.append(engine)
        return engine, camera, model

    yield make
    for resource in resources:
        resource.stop()


def test_camera_open_failure_is_visible_and_releases_resource(vision_factory):
    engine, camera, _ = vision_factory(opened=False)
    assert engine.get_latest_state() == {}
    assert engine.get_status()["components"]["camera"]["status"] == "unavailable"
    camera.release.assert_called_once()
    engine.stop()
    camera.release.assert_called_once()


def test_camera_frames_are_fresh_and_shutdown_joins_worker(vision_factory):
    engine, camera, _ = vision_factory()
    eventually(lambda: engine.get_latest_state().get("emotion") == "happy")
    state = engine.get_latest_state()
    assert state["captured_at"] <= time.time()
    assert engine.get_status()["components"]["camera"]["status"] == "healthy"
    engine.stop()
    assert not engine.thread.is_alive()
    assert engine.get_latest_state() == {}
    camera.release.assert_called_once()


@pytest.mark.parametrize("failure", ["frame_failure", "inference_failure", "haar_failure", "model_missing"])
def test_vision_failure_never_publishes_valid_emotion(vision_factory, failure):
    engine, _, _ = vision_factory(**{failure: True})
    eventually(lambda: engine.get_status()["components"]["camera"]["status"] != "unknown")
    assert engine.get_latest_state() == {}
    components = engine.get_status()["components"]
    assert any(component["status"] in {"unavailable", "degraded"} for component in components.values())


@pytest.fixture
def speech_factory(tmp_path, monkeypatch):
    resources = []
    array = SimpleNamespace(astype=lambda dtype: FloatArray())
    monkeypatch.setitem(sys.modules, "numpy", SimpleNamespace(frombuffer=Mock(return_value=array), int16=object(), float32=object()))
    vosk = tmp_path / "vosk"
    ser = tmp_path / "ser"
    vosk.mkdir()
    ser.mkdir()

    def make(*, vosk_missing=False, ser_missing=False, microphone_failure=False, stream_stop_failure=False, default_ser=False):
        stream = SimpleNamespace(start_stream=Mock(), stop_stream=Mock(), close=Mock())
        if stream_stop_failure:
            stream.stop_stream.side_effect = OSError("fixture stop error")
        audio = SimpleNamespace(open=Mock(return_value=stream), terminate=Mock())
        if microphone_failure:
            audio.open.side_effect = OSError("fixture microphone error")
        backend = SimpleNamespace(PyAudio=lambda: audio, paInt16=1, paContinue=0, paComplete=1)
        recognizer = SimpleNamespace(AcceptWaveform=Mock(return_value=False), Result=Mock(return_value='{"text":"fixture"}'))
        classifier = Mock(return_value=[{"label": "hap", "score": 0.9}])
        factory = None if default_ser else Mock(return_value=classifier)
        engine = SpeechEngine(
            str(tmp_path / "missing" if vosk_missing else vosk), str(tmp_path / "missing-ser" if ser_missing else ser),
            audio_backend=backend, model_factory=Mock(), recognizer_factory=Mock(return_value=recognizer), ser_factory=factory,
        )
        resources.append(engine)
        return engine, audio, stream, recognizer, classifier

    yield make
    for resource in resources:
        resource.stop()


class FloatArray:
    def __truediv__(self, value):
        return self


@pytest.mark.parametrize("failure,component,status", [
    ("vosk_missing", "speech_model", "unavailable"),
    ("ser_missing", "ser_model", "unavailable"),
    ("microphone_failure", "microphone", "unavailable"),
])
def test_speech_initialization_failure_is_explicit(speech_factory, failure, component, status):
    engine, audio, _, _, _ = speech_factory(**{failure: True})
    assert engine.get_status()["components"][component]["status"] == status
    assert engine.peek_latest_text() is None
    if failure == "microphone_failure":
        audio.terminate.assert_called_once()


def test_speech_shutdown_continues_after_stream_stop_error(speech_factory):
    engine, audio, stream, _, _ = speech_factory(stream_stop_failure=True)
    engine.stop()
    stream.close.assert_called_once()
    audio.terminate.assert_called_once()
    assert not engine.process_thread.is_alive()
    engine.stop()
    audio.terminate.assert_called_once()


def test_audio_queue_and_three_second_window_are_bounded(speech_factory):
    engine, _, _, recognizer, _ = speech_factory()
    blocked = threading.Event()
    release = threading.Event()

    def slow_asr(data):
        blocked.set()
        release.wait(timeout=2)
        return False

    recognizer.AcceptWaveform.side_effect = slow_asr
    try:
        engine._audio_callback(b"\x00" * 8000, 4000, {}, 0)
        assert blocked.wait(timeout=1)
        for _ in range(50):
            engine._audio_callback(b"\x00" * 8000, 4000, {}, 0)
        assert engine.audio_queue.qsize() <= 16
        assert len(engine.audio_buffer) == 12
        assert engine.dropped_chunks > 0
        assert engine.get_status()["components"]["microphone"]["status"] == "degraded"
    finally:
        release.set()


def test_ser_failure_keeps_transcript_but_marks_emotion_unavailable(speech_factory):
    engine, _, _, recognizer, classifier = speech_factory()
    recognizer.AcceptWaveform.return_value = True
    classifier.side_effect = RuntimeError("fixture sensitive error")
    engine._audio_callback(b"\x00" * 8000, 4000, {}, 0)
    eventually(lambda: engine.peek_latest_text() is not None)
    state = engine.peek_latest_text()
    assert state["text"] == "fixture"
    assert state["emotion"] == ""
    assert "captured_at" in state
    assert engine.get_status()["components"]["ser_model"]["status"] == "degraded"


def test_default_ser_loads_only_local_model_and_extractor(speech_factory, monkeypatch):
    model = object()
    extractor = object()
    load_model = Mock(return_value=model)
    load_extractor = Mock(return_value=extractor)
    pipeline = Mock(return_value=Mock())
    monkeypatch.setitem(sys.modules, "transformers", SimpleNamespace(
        AutoModelForAudioClassification=SimpleNamespace(from_pretrained=load_model),
        AutoFeatureExtractor=SimpleNamespace(from_pretrained=load_extractor), pipeline=pipeline,
    ))
    engine, _, _, _, _ = speech_factory(default_ser=True)
    assert engine.get_status()["components"]["ser_model"]["status"] == "healthy"
    assert load_model.call_args.kwargs == {"local_files_only": True}
    assert load_extractor.call_args.kwargs == {"local_files_only": True}
    assert pipeline.call_args.kwargs == {"model": model, "feature_extractor": extractor, "device": -1}


def make_bridge(tmp_path, vision=None, speech=None):
    return EmotionBridge(get_vision_state=vision or (lambda: {}), get_speech_state=speech or (lambda: None), db_path=str(tmp_path / "bridge.sqlite"))


def test_no_observation_never_records_or_executes_intervention(tmp_path, monkeypatch):
    bridge = make_bridge(tmp_path)
    execute = Mock()
    intervene = Mock()
    monkeypatch.setattr(bridge.get_embodied_engine(), "execute", execute)
    monkeypatch.setattr(bridge.get_intervention_engine(), "evaluate", intervene)
    bridge._process_cycle()
    assert bridge.get_snapshot().data_available is False
    assert bridge.get_memory().get_records() == []
    execute.assert_not_called()
    intervene.assert_not_called()


def test_captured_time_prevents_old_speech_from_becoming_fresh_on_first_read(tmp_path):
    bridge = make_bridge(tmp_path, speech=lambda: {"text": "old fixture", "emotion": "happy", "seq": 1, "captured_at": time.time() - 60})
    bridge._process_cycle()
    assert bridge.get_snapshot().data_available is False
    assert bridge.get_memory().get_records() == []


@pytest.mark.parametrize("vision, speech", [
    ({}, {"text": "fixture transcript", "emotion": "", "seq": 1}),
    ({"face_detected": False, "emotion": "", "attention_loss_time": 10.0}, None),
    ({"face_detected": True, "emotion": "", "observation_available": False}, None),
    ({"face_detected": False, "emotion": "happy", "attention_loss_time": 10.0}, None),
])
def test_missing_emotion_evidence_has_no_history_or_actions_until_recovery(tmp_path, monkeypatch, vision, speech):
    holder = {
        "vision": {**vision, "captured_at": time.time()},
        "speech": {**speech, "captured_at": time.time()} if speech else None,
    }
    bridge = make_bridge(tmp_path, vision=lambda: holder["vision"], speech=lambda: holder["speech"])
    execute = Mock()
    intervene = Mock(wraps=bridge.get_intervention_engine().evaluate)
    monkeypatch.setattr(bridge.get_embodied_engine(), "execute", execute)
    monkeypatch.setattr(bridge.get_intervention_engine(), "evaluate", intervene)
    bridge._process_cycle()
    assert bridge.get_snapshot().data_available is False
    assert bridge.get_memory().get_records() == []
    execute.assert_not_called()
    intervene.assert_not_called()

    holder["speech"] = {"text": "recovered fixture", "emotion": "happy", "seq": 2, "captured_at": time.time()}
    bridge._process_cycle()
    assert bridge.get_snapshot().data_available is True
    assert bridge.get_snapshot().emotion.category.value == "happy"
    assert len(bridge.get_memory().get_records()) == 1
    execute.assert_called_once()
    intervene.assert_called_once()


def test_stale_or_failed_vision_is_not_observation(tmp_path):
    bridge = make_bridge(tmp_path, vision=lambda: {"face_detected": True, "emotion": "happy", "captured_at": time.time() - 5})
    bridge._process_cycle()
    assert bridge.get_snapshot().data_available is False


def test_bridge_snapshot_is_independent_and_stop_publishes_stopped(tmp_path):
    bridge = make_bridge(tmp_path, vision=lambda: {"face_detected": True, "emotion": "happy"})
    bridge.start()
    try:
        eventually(lambda: bridge.get_snapshot().cycle_count > 0)
        snapshot = bridge.get_snapshot()
        snapshot.behavior.actions.clear()
        snapshot.emotion.source_weights.clear()
        assert bridge.get_snapshot().behavior.actions
        assert bridge.get_snapshot().emotion.source_weights
    finally:
        bridge.stop()
    assert not bridge._thread.is_alive()
    assert bridge.get_snapshot().is_running is False
    assert bridge.get_snapshot().data_available is False
    bridge.stop()


def test_risk_check_failure_keeps_timestamp_and_visible_error(tmp_path, monkeypatch):
    bridge = make_bridge(tmp_path, vision=lambda: {"face_detected": True, "emotion": "happy"})
    check = Mock(side_effect=[["fixture risk"], OSError("fixture storage error")])
    monkeypatch.setattr(bridge.get_memory(), "check_risk_triggers", check)
    for _ in range(10):
        bridge._process_cycle()
    checked = bridge.get_snapshot().risk_checked_at
    assert checked
    for _ in range(10):
        bridge._process_cycle()
    snapshot = bridge.get_snapshot()
    assert snapshot.risk_checked_at == checked
    assert snapshot.risk_triggers == ["fixture risk"]
    assert snapshot.last_error == "risk_check_failed"


def test_tts_initialization_error_stops_worker_and_rejects_new_speech():
    player = AudioPlayer(engine_factory=Mock(side_effect=OSError("fixture private input")))
    player.thread.join(timeout=1)
    assert player.last_error == "OSError"
    assert player.is_running is False
    assert player.speak("fixture") is False
    player.stop()


def test_tts_queue_is_bounded_and_stop_joins_worker():
    started = threading.Event()
    release = threading.Event()
    engine = SimpleNamespace(setProperty=Mock(), say=Mock(), runAndWait=lambda: (started.set(), release.wait(timeout=2)), stop=Mock())
    player = AudioPlayer(engine_factory=lambda: engine)
    try:
        assert player.speak("fixture") is True
        assert started.wait(timeout=1)
        accepted = [player.speak("pending fixture") for _ in range(20)]
        assert sum(accepted) <= 8
        release.set()
        player.stop()
        assert not player.thread.is_alive()
        assert player.speak("after stop") is False
    finally:
        release.set()
        player.stop()


def test_requested_hardware_never_claims_print_stub_is_real():
    engine = EmbodiedEngine(hardware_available=True)
    assert engine.get_status()["hardware_available"] is False
    assert engine.get_status()["status"] == "unavailable"
    engine.stop()


def test_robot_partial_initialization_releases_already_opened_devices(monkeypatch):
    import main

    vision = SimpleNamespace(stop=Mock())
    monkeypatch.setattr(main, "VisionEngine", Mock(return_value=vision))
    monkeypatch.setattr(main, "SpeechEngine", Mock(side_effect=OSError("fixture failure")))
    with pytest.raises(OSError, match="fixture failure"):
        main.SoulCompanionRobot()
    vision.stop.assert_called_once()


def test_robot_shutdown_attempts_every_resource_after_one_failure():
    import logging
    from main import SoulCompanionRobot

    robot = SoulCompanionRobot.__new__(SoulCompanionRobot)
    robot.logger = logging.getLogger("robot-shutdown-test")
    robot._stop_event = threading.Event()
    robot.brain = SimpleNamespace(stop=Mock(side_effect=OSError("fixture stop failure")))
    robot.vision = SimpleNamespace(stop=Mock())
    robot.speech = SimpleNamespace(stop=Mock())
    robot.speaker = SimpleNamespace(stop=Mock())
    robot.shutdown()
    assert robot._stop_event.is_set()
    for name in ("brain", "vision", "speech", "speaker"):
        getattr(robot, name).stop.assert_called_once()


def test_launcher_without_web_or_robot_returns_without_opening_storage(monkeypatch):
    import launch

    factory = Mock(side_effect=AssertionError("no devices should open"))
    monkeypatch.setitem(sys.modules, "main", SimpleNamespace(SoulCompanionRobot=factory))
    launch.launch(enable_robot=False, enable_web=False)
    factory.assert_not_called()
