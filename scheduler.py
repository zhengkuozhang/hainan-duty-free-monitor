"""轻量、可持久化的后台采集调度器。"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable


DEFAULT_SETTINGS = {"enabled": True, "interval_hours": 24}


class CrawlScheduler:
    def __init__(self, settings_path: Path, callback: Callable[[], bool]):
        self.settings_path = settings_path
        self.callback = callback
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._next_run: datetime | None = None
        self._settings = self._load()

    def _load(self) -> dict:
        try:
            saved = json.loads(self.settings_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            saved = {}
        return self.validate({**DEFAULT_SETTINGS, **saved})

    @staticmethod
    def validate(settings: dict) -> dict:
        enabled = bool(settings.get("enabled", True))
        hours = int(settings.get("interval_hours", 24))
        if hours not in {6, 12, 24, 48, 72}:
            raise ValueError("采集周期仅支持 6、12、24、48 或 72 小时")
        return {"enabled": enabled, "interval_hours": hours}

    def save(self, settings: dict) -> dict:
        self._settings = self.validate(settings)
        self.settings_path.parent.mkdir(parents=True, exist_ok=True)
        self.settings_path.write_text(
            json.dumps(self._settings, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        self._next_run = self._calculate_next()
        self._wake.set()
        return self.status()

    def _calculate_next(self) -> datetime | None:
        if not self._settings["enabled"]:
            return None
        return datetime.now().astimezone() + timedelta(hours=self._settings["interval_hours"])

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._next_run = self._calculate_next()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="crawl-scheduler")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread:
            self._thread.join(timeout=2)

    def _loop(self) -> None:
        while not self._stop.is_set():
            if not self._settings["enabled"]:
                self._wake.wait()
                self._wake.clear()
                continue
            if self._next_run is None:
                self._next_run = self._calculate_next()
            seconds = max(0.0, (self._next_run - datetime.now().astimezone()).total_seconds())
            if self._wake.wait(timeout=seconds):
                self._wake.clear()
                continue
            self.callback()
            self._next_run = self._calculate_next()

    def status(self) -> dict:
        return {
            **self._settings,
            "next_run_at": self._next_run.isoformat(timespec="seconds") if self._next_run else None,
        }
