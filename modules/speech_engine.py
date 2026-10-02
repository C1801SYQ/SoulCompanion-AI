"""Offline speech adapter with bounded audio buffering and visible health."""
from __future__ import annotations

import logging
import json
import os
import queue
import threading
import time
from collections import deque
from datetime import datetime

from config import SER_PATH, VOSK_PATH

logger = logging.getLogger("SpeechEngine")


class SpeechEngine:
    def __init__(self, vosk_path=None, ser_model_path=None, *, audio_backend=None, model_factory=None, recognizer_factory=None, ser_factory=None):
        self.is_running = False
        self.current_state = {"text": "", "emotion": "neutral", "seq": 0}
        self._lock = threading.RLock()
        self._buffer_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._seq = self._consumed_seq = 0
        self._last_warning = 0.0
        self._components = {}
        self.audio_queue = queue.Queue(maxsize=16)
        self.audio_buffer = deque(maxlen=12)
        self.dropped_chunks = 0
        self.process_thread = None
        self.stream = self.p = None
        for name in ("microphone", "speech_model", "ser_model"):
            self._status(name, "unknown", "Not initialized")
        try:
            import numpy as np
            self.np = np
            if audio_backend is None:
                import pyaudio
                audio_backend = pyaudio
            self.audio_backend = audio_backend
            if model_factory is None or recognizer_factory is None:
                from vosk import Model, KaldiRecognizer
                model_factory = model_factory or Model
                recognizer_factory = recognizer_factory or KaldiRecognizer
            if ser_factory is None:
                from transformers import AutoFeatureExtractor, AutoModelForAudioClassification, pipeline

                def ser_factory(task, *, model, device):
                    classifier = AutoModelForAudioClassification.from_pretrained(model, local_files_only=True)
                    extractor = AutoFeatureExtractor.from_pretrained(model, local_files_only=True)
                    return pipeline(task, model=classifier, feature_extractor=extractor, device=device)
        except ImportError as exc:
            for name in self._components:
                self._status(name, "unavailable", "Speech runtime dependency unavailable")
            self._warning("speech_dependency_failed", exc)
            return
        try:
            path = vosk_path or VOSK_PATH
            if not os.path.isdir(path):
                raise FileNotFoundError("Vosk model missing")
            self.vosk_model = model_factory(path)
            self.recognizer = recognizer_factory(self.vosk_model, 16000)
            self._status("speech_model", "healthy", "Vosk model loaded")
        except Exception as exc:
            self._status("speech_model", "unavailable", "Vosk model missing or invalid")
            self._status("microphone", "disabled", "ASR is unavailable")
            self._warning("vosk_load_failed", exc)
            return
        try:
            path = ser_model_path or SER_PATH
            if not os.path.isdir(path):
                raise FileNotFoundError("SER model missing")
            self.ser_classifier = ser_factory("audio-classification", model=path, device=-1)
            self._status("ser_model", "healthy", "Offline SER model loaded")
        except Exception as exc:
            self.ser_classifier = None
            self._status("ser_model", "unavailable", "SER model missing or invalid; ASR remains available")
            self._warning("ser_load_failed", exc)
        try:
            self.p = self.audio_backend.PyAudio()
            self.stream = self.p.open(format=self.audio_backend.paInt16, channels=1, rate=16000, input=True, frames_per_buffer=4000, stream_callback=self._audio_callback)
            self.stream.start_stream()
            self.is_running = True
            self._status("microphone", "degraded", "Microphone opened; awaiting audio")
            self.process_thread = threading.Thread(target=self._process_audio, daemon=True, name="SpeechEngine")
            self.process_thread.start()
        except Exception as exc:
            self._status("microphone", "unavailable", "Microphone could not be opened")
            self._warning("microphone_open_failed", exc)
            self.stop()

    def _status(self, component, status, reason):
        with self._lock:
            self._components[component] = {"status": status, "reason": reason, "checked_at": datetime.now().isoformat()}

    def _warning(self, code, exc):
        now = time.monotonic()
        if now - self._last_warning >= 5:
            logger.warning("%s type=%s", code, type(exc).__name__)
            self._last_warning = now

    def _audio_callback(self, in_data, frame_count, time_info, status):
        if self._stop_event.is_set():
            return None, self.audio_backend.paComplete
        captured_at = time.time()
        chunk = bytes(in_data)
        try:
            self.audio_queue.put_nowait((chunk, captured_at))
        except queue.Full:
            self.dropped_chunks += 1
        with self._buffer_lock:
            self.audio_buffer.append(chunk)
        self._status("microphone", "degraded" if status or self.dropped_chunks else "healthy", "Audio chunks dropped or device overflow" if status or self.dropped_chunks else "Microphone is producing audio")
        return None, self.audio_backend.paContinue

    def _process_audio(self):
        try:
            while not self._stop_event.is_set():
                try:
                    data, captured_at = self.audio_queue.get(timeout=0.1)
                except queue.Empty:
                    continue
                try:
                    if time.time() - captured_at > 4.0:
                        self.dropped_chunks += 1
                        continue
                    if not self.recognizer.AcceptWaveform(data):
                        continue
                    result = json.loads(self.recognizer.Result())
                    text = result.get("text", "")
                    if not isinstance(text, str) or not text:
                        continue
                    emotion = ""
                    if self.ser_classifier is not None:
                        try:
                            with self._buffer_lock:
                                audio_bytes = b"".join(self.audio_buffer)
                            audio_np = self.np.frombuffer(audio_bytes, dtype=self.np.int16).astype(self.np.float32) / 32768.0
                            ser_result = self.ser_classifier({"raw": audio_np, "sampling_rate": 16000})
                            emotion = {"neu": "neutral", "hap": "happy", "ang": "anxious", "sad": "sad"}.get(ser_result[0]["label"], "neutral")
                            self._status("ser_model", "healthy", "SER inference succeeded")
                        except Exception as exc:
                            self._status("ser_model", "degraded", "SER inference failed; transcript is available")
                            self._warning("ser_inference_failed", exc)
                    if self._stop_event.is_set():
                        continue
                    with self._lock:
                        self._seq += 1
                        self.current_state = {"text": text, "emotion": emotion, "seq": self._seq, "captured_at": captured_at}
                    self._status("speech_model", "healthy", "ASR recognition succeeded")
                except Exception as exc:
                    self._status("speech_model", "degraded", "ASR processing failed")
                    self._warning("audio_processing_failed", exc)
                finally:
                    self.audio_queue.task_done()
        finally:
            self.is_running = False

    def get_latest_text(self):
        """Consume one event for the robot, while retaining it for bridge readers."""
        with self._lock:
            if self.current_state["text"] and self.current_state["seq"] != self._consumed_seq:
                self._consumed_seq = self.current_state["seq"]
                return self.current_state.copy()
        return None

    def peek_latest_text(self):
        with self._lock:
            return self.current_state.copy() if self.current_state.get("text") else None

    def get_status(self):
        with self._lock:
            result = {key: value.copy() for key, value in self._components.items()}
        return {"components": result, "running": bool(self.process_thread and self.process_thread.is_alive() and self.is_running), "queue_size": self.audio_queue.qsize(), "dropped_chunks": self.dropped_chunks}

    def stop(self):
        self._stop_event.set()
        self.is_running = False
        stream, self.stream = self.stream, None
        if stream is not None:
            for name in ("stop_stream", "close"):
                try:
                    getattr(stream, name)()
                except Exception as exc:
                    self._warning("audio_" + name + "_failed", exc)
        if self.process_thread and self.process_thread is not threading.current_thread():
            self.process_thread.join(timeout=2.0)
        audio, self.p = self.p, None
        if audio is not None:
            try:
                audio.terminate()
            except Exception as exc:
                self._warning("audio_terminate_failed", exc)
        if self.process_thread and self.process_thread.is_alive():
            self._status("microphone", "unavailable", "Audio worker did not stop within timeout")
        elif self._components["microphone"]["status"] != "unavailable":
            self._status("microphone", "disabled", "Microphone stopped")
