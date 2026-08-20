"""S1 link state and core network traffic (production, Linux).

DEPLOYMENT STATUS: written for Phase 6, to be verified on the target.

S1 detection (config linux.s1.method):
  * sctp (recommended) - kernel SCTP association to the EPC port (36412).
    Not srsRAN text parsing at all: this is kernel state via ``ss``.
  * log (fallback) - srsENB journal messages, e.g. "S1AP Connected".

Core traffic: byte counters on the srsEPC interfaces (SGi / S1-U)
from /proc/net/dev, converted to Mbps with per-call deltas.
"""
from __future__ import annotations

import re
import subprocess
import time

from app.config import AppConfig
from app.models import CoreTraffic, S1Status


class LinuxS1Provider:
    def __init__(self, config: AppConfig) -> None:
        self._cfg = config.linux.s1

    def _sctp_established(self) -> bool:
        try:
            proc = subprocess.run(
                ["ss", "-H", "--sctp", "state", "established"],
                capture_output=True, text=True, timeout=5,
            )
        except (subprocess.TimeoutExpired, OSError):
            return False
        port = str(self._cfg.sctp_port)
        for line in (proc.stdout or "").splitlines():
            if not line.strip():
                continue
            if f":{port}" in line:
                return True
        return False

    def _log_connected(self) -> bool:
        try:
            proc = subprocess.run(
                ["journalctl", "-u", self._cfg.journal_unit, "-n", "50", "--output", "cat"],
                capture_output=True, text=True, timeout=5,
            )
        except (subprocess.TimeoutExpired, OSError):
            return False
        text = proc.stdout or ""
        connected = bool(re.search(r"S1AP[^\n]*Connected", text, re.IGNORECASE))
        down = bool(re.search(r"S1AP[^\n]*(Down|Disconnect|Failed|Error)", text, re.IGNORECASE))
        # last occurrence wins
        c_pos = text.rfind("Connected") if connected else -1
        d_pos = max(text.rfind("Down"), text.rfind("Disconnect"), text.rfind("Failed")) if down else -1
        return c_pos > d_pos

    def get_status(self) -> S1Status:
        if self._cfg.method == "log":
            ok = self._log_connected()
            return S1Status(connected=ok, detail="journal S1AP state")
        ok = self._sctp_established()
        return S1Status(connected=ok, detail=f"SCTP :{self._cfg.sctp_port} established" if ok
                        else f"no SCTP association to :{self._cfg.sctp_port}")


class LinuxCoreTrafficProvider:
    def __init__(self, config: AppConfig) -> None:
        self._ifaces = list(config.linux.core_traffic.interfaces)
        self._last: dict[str, tuple[int, int]] = {}
        self._last_ts = time.time()

    def _read(self) -> dict[str, tuple[int, int]]:
        out: dict[str, tuple[int, int]] = {}
        try:
            with open("/proc/net/dev", "r", encoding="utf-8") as fh:
                lines = fh.readlines()[2:]
        except OSError:
            return out
        for line in lines:
            if ":" not in line:
                continue
            iface, rest = line.split(":", 1)
            iface = iface.strip()
            if iface in self._ifaces:
                cols = rest.split()
                out[iface] = (int(cols[0]), int(cols[8]))
        return out

    def get_traffic(self) -> CoreTraffic:
        now = time.time()
        dt = max(now - self._last_ts, 1e-6)
        cur = self._read()
        rx = tx = 0.0
        active: list[str] = []
        for iface, (rx_bytes, tx_bytes) in cur.items():
            active.append(iface)
            if iface in self._last:
                rx += (rx_bytes - self._last[iface][0]) * 8 / dt / 1024 ** 2
                tx += (tx_bytes - self._last[iface][1]) * 8 / dt / 1024 ** 2
        self._last = cur
        self._last_ts = now
        return CoreTraffic(
            ts=now,
            rx_mbps=round(max(rx, 0.0), 3),
            tx_mbps=round(max(tx, 0.0), 3),
            interfaces=active,
        )
