#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import time
import threading
import subprocess
import urllib.request
import urllib.error


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)).strip())
    except Exception:
        return default


class QwenAutoscaler:
    """
    Startet/stoppt aicore-qwen automatisch.
    - ensure_running(): startet Service wenn nötig, wartet bis /health ok ist
    - touch(): markiert "Qwen wurde gerade benutzt"
    - start_idle_monitor(): stoppt Qwen nach Idle-Zeit
    """

    def __init__(
        self,
        service_name: str = "aicore-qwen",
        health_url: str = "http://127.0.0.1:8102/health",
    ):
        self.service_name = service_name
        self.health_url = health_url

        self.idle_stop_s = _env_int("QWEN_IDLE_STOP_S", 12 * 60)   # 12 min default
        self.start_wait_s = _env_int("QWEN_START_WAIT_S", 45)      # max wait for cold start
        self.poll_ms = _env_int("QWEN_IDLE_POLL_MS", 2000)         # idle monitor tick
        self._lock = threading.Lock()

        self._last_use_ts = 0.0
        self._busy = 0
        self._stop_evt = threading.Event()
        self._thr = None

    # --- low-level ---------------------------------------------------------

    def _http_ok(self, url: str, timeout_s: float = 0.9) -> bool:
        try:
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=timeout_s) as r:
                return 200 <= int(getattr(r, "status", 200)) < 300
        except Exception:
            return False

    def _systemctl(self, args: list[str]) -> None:
        # Must be called as same user that owns --user services
        cmd = ["systemctl", "--user"] + args
        subprocess.run(cmd, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def is_up(self) -> bool:
        return self._http_ok(self.health_url)

    def start(self) -> None:
        self._systemctl(["start", self.service_name])

    def stop(self) -> None:
        self._systemctl(["stop", self.service_name])

    # --- public ------------------------------------------------------------

    def touch(self) -> None:
        self._last_use_ts = time.time()

    def busy_enter(self) -> None:
        self._busy += 1
        self.touch()

    def busy_exit(self) -> None:
        self._busy = max(0, self._busy - 1)
        self.touch()

    def ensure_running(self) -> bool:
        """
        Garantiert, dass Qwen läuft, wenn geroutet werden soll.
        Returns True wenn health ok wurde, sonst False.
        """
        with self._lock:
            self.touch()
            if self.is_up():
                return True

            # Start service
            self.start()

            # Wait for health
            t0 = time.time()
            while time.time() - t0 < float(self.start_wait_s):
                if self.is_up():
                    return True
                time.sleep(0.4)

            return False

    def start_idle_monitor(self) -> None:
        if self._thr and self._thr.is_alive():
            return
        self._stop_evt.clear()
        self._thr = threading.Thread(target=self._idle_loop, daemon=True)
        self._thr.start()

    def shutdown(self) -> None:
        self._stop_evt.set()

    # --- idle loop ---------------------------------------------------------

    def _idle_loop(self) -> None:
        # Conservative: only stop if:
        # - service is up
        # - not busy
        # - idle time exceeded
        while not self._stop_evt.is_set():
            time.sleep(self.poll_ms / 1000.0)

            if self.idle_stop_s <= 0:
                continue

            if self._busy > 0:
                continue

            last = self._last_use_ts
            if last <= 0:
                continue

            idle = time.time() - last
            if idle < float(self.idle_stop_s):
                continue

            # Only stop if it is actually up right now
            if self.is_up():
                self.stop()
