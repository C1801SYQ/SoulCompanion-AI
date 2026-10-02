"""Camera adapter with explicit device/model health and fresh observations."""
from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime

from config import HAAR_PATH, VISION_MODEL_PATH

logger = logging.getLogger("VisionEngine")


class VisionEngine:
    def __init__(self, model_path=None, *, haar_path=None, cv_backend=None, camera_factory=None):
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._components = {}
        self._last_warning = 0.0
        self.cap = self.thread = self.last_frame = None
        self.current_state = {}
        self.model_loaded = self.is_running = False
        self.last_face_time = time.time()
        for name in ("camera", "vision_model"):
            self._status(name, "unknown", "Not initialized")
        try:
            if cv_backend is None:
                import cv2
                cv_backend = cv2
            self.cv = cv_backend
        except ImportError as exc:
            self._failure("camera", "Vision dependency unavailable", exc)
            self._status("vision_model", "unavailable", "Vision dependency unavailable")
            return
        try:
            self.face_cascade = self.cv.CascadeClassifier(haar_path or HAAR_PATH)
            self._haar_ready = not self.face_cascade.empty()
        except Exception as exc:
            self._haar_ready = False
            self._warning("face_detector_failed", exc)
        path = model_path or VISION_MODEL_PATH
        try:
            if not os.path.isfile(path):
                raise FileNotFoundError("Vision model missing")
            self.net = self.cv.dnn.readNetFromONNX(path)
            self.model_loaded = True
            self._status("vision_model", "healthy", "ONNX model loaded")
        except Exception as exc:
            self._failure("vision_model", "Vision model missing or invalid", exc)
        if not self._haar_ready:
            self._status("vision_model", "degraded", "Face detector missing or invalid")
        try:
            if camera_factory is None:
                backend = self.cv.CAP_DSHOW if os.name == "nt" else self.cv.CAP_ANY
                self.cap = self.cv.VideoCapture(0, backend)
            else:
                self.cap = camera_factory()
            if not self.cap.isOpened():
                raise OSError("Camera could not be opened")
            self._status("camera", "degraded", "Camera opened; awaiting a frame")
            self.is_running = True
            self.thread = threading.Thread(target=self._process_video, daemon=True, name="VisionEngine")
            self.thread.start()
        except Exception as exc:
            self._failure("camera", "Camera unavailable", exc)
            self.stop()

    def _status(self, component, status, reason):
        with self._lock:
            self._components[component] = {"status": status, "reason": reason, "checked_at": datetime.now().isoformat()}

    def _warning(self, code, exc):
        now = time.monotonic()
        if now - self._last_warning >= 5.0:
            logger.warning("%s type=%s", code, type(exc).__name__)
            self._last_warning = now

    def _failure(self, component, reason, exc):
        self._status(component, "unavailable", reason)
        self._warning(component + "_failed", exc)

    def _process_video(self):
        frame_count = 0
        try:
            while not self._stop_event.is_set():
                try:
                    ret, frame = self.cap.read()
                    if not ret:
                        raise OSError("Frame read failed")
                    captured_at = time.time()
                    with self._lock:
                        self.last_frame = frame
                    self._status("camera", "healthy", "Camera is producing frames")
                    if not self._haar_ready:
                        self._stop_event.wait(0.1)
                        continue
                    frame_count += 1
                    small = self.cv.resize(frame, (0, 0), fx=0.5, fy=0.5)
                    gray = self.cv.cvtColor(small, self.cv.COLOR_BGR2GRAY)
                    faces = self.face_cascade.detectMultiScale(gray, 1.3, 5)
                    with self._lock:
                        state = self.current_state.copy()
                    state.update(captured_at=captured_at, observation_available=True)
                    if len(faces) > 0:
                        state.update(face_detected=True, attention_loss_time=0.0)
                        self.last_face_time = captured_at
                        if self.model_loaded and (frame_count % 3 == 0 or not state.get("emotion")):
                            try:
                                x, y, w, h = max(faces, key=lambda face: face[2] * face[3])
                                roi = self.cv.resize(gray[y:y + h, x:x + w], (48, 48))
                                blob = self.cv.dnn.blobFromImage(roi, 1.0 / 255.0, (48, 48), (0, 0, 0), swapRB=False)
                                self.net.setInput(blob)
                                predictions = self.net.forward()[0]
                                index = max(range(len(predictions)), key=lambda item: predictions[item])
                                raw = ['angry', 'disgust', 'fear', 'happy', 'sad', 'surprise', 'neutral'][index]
                                state["emotion"] = {"happy": "happy", "surprise": "happy", "sad": "sad", "angry": "anxious", "fear": "anxious", "disgust": "anxious", "neutral": "neutral"}[raw]
                                self._status("vision_model", "healthy", "ONNX inference succeeded")
                            except Exception as exc:
                                state["emotion"] = ""
                                state["observation_available"] = False
                                self._status("vision_model", "degraded", "Vision inference failed")
                                self._warning("vision_inference_failed", exc)
                        elif not self.model_loaded:
                            state["emotion"] = ""
                            state["observation_available"] = False
                    else:
                        state.update(face_detected=False, emotion="", attention_loss_time=round(captured_at - self.last_face_time, 1))
                    with self._lock:
                        self.current_state = state
                except Exception as exc:
                    with self._lock:
                        self.current_state = {}
                        self.last_frame = None
                    self._status("camera", "degraded", "Frame capture or processing failed")
                    self._warning("frame_processing_failed", exc)
                    self._stop_event.wait(0.1)
                self._stop_event.wait(0.01)
        finally:
            self.is_running = False

    def get_current_frame(self):
        with self._lock:
            return self.last_frame.copy() if self.last_frame is not None else None

    def get_latest_state(self):
        with self._lock:
            state = self.current_state.copy()
        age = time.time() - state.get("captured_at", 0)
        if not self.is_running or not state.get("observation_available") or not -1 <= age <= 2.0:
            return {}
        return state

    def get_status(self):
        with self._lock:
            result = {key: value.copy() for key, value in self._components.items()}
        if self.thread is not None and not self.thread.is_alive() and self.is_running:
            result["camera"] = {"status": "unavailable", "reason": "Camera worker stopped", "checked_at": datetime.now().isoformat()}
        return {"components": result, "running": bool(self.thread and self.thread.is_alive() and self.is_running)}

    def stop(self):
        self._stop_event.set()
        self.is_running = False
        if self.thread and self.thread is not threading.current_thread():
            self.thread.join(timeout=2.0)
        if self.cap is not None:
            try:
                self.cap.release()
            except Exception as exc:
                self._warning("camera_release_failed", exc)
            self.cap = None
        if self.thread and self.thread.is_alive():
            self._status("camera", "unavailable", "Camera worker did not stop within timeout")
        elif self._components["camera"]["status"] != "unavailable":
            self._status("camera", "disabled", "Camera stopped")
