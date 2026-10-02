"""Single TTS worker with bounded pending speech and explicit failure state."""
import logging
import threading
import queue

logger = logging.getLogger("AudioPlayer")


class AudioPlayer:
    def __init__(self, *, engine_factory=None):
        self.msg_queue = queue.Queue(maxsize=8)
        self._stop_event = threading.Event()
        self._engine_factory = engine_factory
        self._engine = None
        self.last_error = ""
        self.is_running = True
        # 核心：只启动唯一一个守护线程处理语音，避免多线程冲突
        self.thread = threading.Thread(target=self._worker, daemon=True)
        self.thread.start()

    def speak(self, text):
        """Accept bounded speech work without blocking the robot loop."""
        if not text or self._stop_event.is_set() or not self.thread.is_alive():
            return False
        try:
            self.msg_queue.put_nowait(text)
            return True
        except queue.Full:
            logger.warning("tts_queue_full")
            return False

    def _worker(self):
        """语音工作线程，顺序处理队列中的每一句话"""
        try:
            if self._engine_factory is None:
                import pyttsx3
                self._engine_factory = pyttsx3.init
            engine = self._engine = self._engine_factory()
            engine.setProperty('rate', 160)
            while not self._stop_event.is_set():
                try:
                    text = self.msg_queue.get(timeout=0.1)
                except queue.Empty:
                    continue
                try:
                    engine.say(text)
                    engine.runAndWait()
                    self._stop_event.wait(0.3)
                except Exception as exc:
                    self.last_error = type(exc).__name__
                    logger.warning("tts_playback_failed type=%s", self.last_error)
                    self._stop_event.set()
                finally:
                    self.msg_queue.task_done()
        except Exception as exc:
            self.last_error = type(exc).__name__
            logger.warning("tts_initialize_failed type=%s", self.last_error)
            self._stop_event.set()
        finally:
            self.is_running = False
            if self._engine is not None:
                try:
                    self._engine.stop()
                except Exception as exc:
                    logger.warning("tts_stop_failed type=%s", type(exc).__name__)

    def stop(self):
        self._stop_event.set()
        self.is_running = False
        if self.thread is not threading.current_thread():
            self.thread.join(timeout=2.0)
        if self.thread.is_alive():
            self.last_error = "shutdown_timeout"
            logger.warning("tts_shutdown_timeout")
