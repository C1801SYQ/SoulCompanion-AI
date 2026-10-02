"""Explicit FAKE software smoke by default; --real probes local devices only."""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def fake_smoke():
    from emotion.bridge import EmotionBridge

    artifacts = ROOT / ".test-artifacts"
    artifacts.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="hardware-fake-", dir=artifacts) as directory:
        bridge = EmotionBridge(
            get_vision_state=lambda: {
                "face_detected": True, "emotion": "happy",
                "captured_at": time.time(), "observation_available": True,
            },
            get_speech_state=lambda: {
                "text": "fake fixture", "emotion": "happy", "seq": 1,
                "captured_at": time.time(),
            },
            db_path=str(Path(directory) / "fake-only.sqlite"),
        )
        try:
            bridge._process_cycle()
            snapshot = bridge.get_snapshot()
            passed = bool(
                snapshot.data_available and snapshot.emotion.category.value == "happy"
                and len(bridge.get_memory().get_records()) == 1
            )
            return {
                "test_mode": "FAKE", "verified_hardware": False,
                "software_contract_passed": passed,
                "reason": "Injected fixtures verify bridge interfaces and temporary storage only; no physical devices were tested",
            }, 0 if passed else 1
        finally:
            bridge.stop()


def real_smoke(duration):
    from modules.vision_engine import VisionEngine
    from modules.speech_engine import SpeechEngine

    resources = []
    try:
        vision = VisionEngine()
        resources.append(vision)
        speech = SpeechEngine()
        resources.append(speech)
        time.sleep(duration)
        components = {
            **vision.get_status()["components"],
            **speech.get_status()["components"],
            "hardware": {
                "status": "disabled", "reason": "No physical actuator adapter is supplied",
                "checked_at": datetime.now().isoformat(),
            },
        }
        required = ("camera", "microphone", "vision_model", "speech_model", "ser_model")
        verified = all(components[name]["status"] == "healthy" for name in required)
        return {
            "test_mode": "REAL", "verified_hardware": verified,
            "components": components,
            "vision_observation_available": bool(vision.get_latest_state()),
            "reason": "Only installed local models are used. Speak during the probe to exercise ASR/SER inference; model loading alone does not prove recognition accuracy",
        }, 0 if verified else 1
    finally:
        for resource in reversed(resources):
            resource.stop()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--real", action="store_true", help="Open actual camera/microphone; never downloads models")
    parser.add_argument("--duration", type=float, default=2.0)
    args = parser.parse_args()
    if not 0 <= args.duration <= 10:
        parser.error("duration must be between 0 and 10 seconds")
    try:
        result, code = real_smoke(args.duration) if args.real else fake_smoke()
    except Exception as exc:
        result, code = {"test_mode": "REAL" if args.real else "FAKE", "verified_hardware": False, "error_type": type(exc).__name__}, 1
    print(json.dumps(result, ensure_ascii=False))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
