"""
Legacy local snapshot helper; remote emotion relay is disabled in this release.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from typing import Any, Dict, Optional

logger = logging.getLogger("CloudSync")

# Retained only to reject a previously configured remote relay explicitly.
RELAY_URL = os.environ.get("EMOTION_RELAY_URL", "")


class CloudSync:
    """
    Legacy local JSON snapshot helper, unused by the product launcher.
    Any configured remote relay is rejected before work starts.
    """

    def __init__(self, sync_interval: float = 3.0):
        if RELAY_URL:
            raise ValueError("EMOTION_RELAY_URL is unsupported: real emotion data must remain local")
        self.sync_interval = sync_interval
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._current_data: Dict[str, Any] = {}
        self._lock = threading.Lock()
        self._relay_url = RELAY_URL
        self._data_file = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "emotion_state.json",
        )
        logger.info("✅ [云同步] 数据同步器已初始化")

    def update(self, data: Dict[str, Any]) -> None:
        """Update current emotion data."""
        with self._lock:
            self._current_data = data.copy()
            self._current_data["_ts"] = time.time()

    def get_latest(self) -> Dict[str, Any]:
        """Get latest data."""
        with self._lock:
            return self._current_data.copy()

    def start(self, getter_fn=None) -> None:
        """Start background sync."""
        if self._running:
            return
        self._running = True
        self._getter_fn = getter_fn
        self._thread = threading.Thread(target=self._sync_loop, daemon=True, name="CloudSync")
        self._thread.start()
        logger.info("🚀 [云同步] 同步线程已启动")

    def stop(self) -> None:
        self._running = False

    def _sync_loop(self) -> None:
        while self._running:
            try:
                if self._getter_fn:
                    data = self._getter_fn()
                    if data:
                        self.update(data)
                self._push()
            except Exception as exc:
                logger.warning("legacy_snapshot_failed type=%s", type(exc).__name__)
            time.sleep(self.sync_interval)

    def _push(self) -> None:
        """Push data to cloud or local file."""
        data = self.get_latest()
        if not data:
            return

        # Always write local file
        self._write_file(data)

        # Push to cloud relay if configured
        if self._relay_url:
            self._push_http(data)

    def _write_file(self, data: Dict) -> None:
        try:
            with open(self._data_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
        except Exception as exc:
            logger.warning("legacy_snapshot_write_failed type=%s", type(exc).__name__)

    def _push_http(self, data: Dict) -> None:
        raise RuntimeError("Remote emotion relay is disabled in the local-only product")

    def read_file(self) -> Dict[str, Any]:
        try:
            with open(self._data_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            return {}
        except Exception as exc:
            logger.warning("legacy_snapshot_read_failed type=%s", type(exc).__name__)
            return {}


def create_cloud_sync(interval: float = 3.0) -> CloudSync:
    return CloudSync(sync_interval=interval)
