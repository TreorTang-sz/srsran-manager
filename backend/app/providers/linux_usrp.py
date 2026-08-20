"""USRP B210 detection via UHD (production).

DEPLOYMENT STATUS: written for Phase 6, to be verified on the target
(UHD + B210 over USB3 on RK3588).

Uses ``uhd_find_devices`` (fixed command, no shell). The call is
relatively slow, so results are cached for ``check_interval`` seconds.
"""
from __future__ import annotations

import re
import subprocess
import threading
import time

from app.config import AppConfig
from app.models import UsrpStatus


class LinuxUhdUsrpProvider:
    def __init__(self, config: AppConfig) -> None:
        self._cmd = config.linux.usrp.find_cmd
        self._ttl = max(config.linux.usrp.check_interval, 1.0)
        self._lock = threading.Lock()
        self._cached: UsrpStatus | None = None
        self._checked_at = 0.0

    def _probe(self) -> UsrpStatus:
        try:
            proc = subprocess.run(
                [self._cmd],
                capture_output=True,
                text=True,
                timeout=15,
            )
        except (subprocess.TimeoutExpired, OSError) as exc:
            return UsrpStatus(connected=False, detail=f"uhd_find_devices failed: {exc}")
        out = proc.stdout or ""
        if proc.returncode != 0:
            return UsrpStatus(connected=False, detail=(proc.stderr or "uhd_find_devices error").strip()[:300])
        # Example output:
        #   --------------------------------------------------
        #   -- UHD Device 0
        #   --------------------------------------------------
        #   Device Address:
        #       type: b200
        #       product: B210
        #       serial: F5A6B7C
        m = re.search(r"product:\s*(\S+)", out)
        serial = re.search(r"serial:\s*(\S+)", out)
        connected = "Device Address" in out and bool(m)
        device = m.group(1) if m else ("B210" if connected else None)
        return UsrpStatus(
            connected=connected,
            device=device,
            serial=serial.group(1) if serial else None,
            detail="UHD device found" if connected else "no UHD device found",
        )

    def get_status(self) -> UsrpStatus:
        with self._lock:
            now = time.time()
            if self._cached is not None and now - self._checked_at < self._ttl:
                return self._cached.model_copy(update={"ts": now})
            status = self._probe()
            self._cached = status
            self._checked_at = now
            return status
