"""
emotion/cloud_sync.py - Cloud Data Sync for Remote Dashboard

Syncs emotion state to a free cloud service so the
Streamlit Cloud dashboard can display real-time data.

Architecture:
    Local Robot → cloud_sync.py → Cloud JSON API → Streamlit Dashboard
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from typing import Any, Dict, Optional
from urllib import request, error

logger = logging.getLogger("CloudSync")

# ─── Cloud Storage Endpoints ──────────────────────────────────────────
# Using a free public JSON relay service
# The robot POSTs data, the dashboard GETs it

# Primary: Use a simple file-based approach with a free relay
RELAY_URL = os.environ.get("EMOTION_RELAY_URL", "")


class CloudSync:
    """
    Syncs emotion data to cloud for remote dashboard access.

    When RELAY_URL is set, pushes data to that endpoint.
    Otherwise, writes to a local JSON file for same-machine access.
    """

    def __init__(self, sync_interval: float = 3.0):
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
            except Exception as e:
                logger.debug(f"同步异常: {e}")
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
        except Exception:
            pass

    def _push_http(self, data: Dict) -> None:
        try:
            body = json.dumps(data).encode("utf-8")
            req = request.Request(
                self._relay_url,
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with request.urlopen(req, timeout=5):
                pass
        except Exception as e:
            logger.debug(f"HTTP推送失败: {e}")

    def read_file(self) -> Dict[str, Any]:
        try:
            with open(self._data_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}


def create_cloud_sync(interval: float = 3.0) -> CloudSync:
    return CloudSync(sync_interval=interval)
