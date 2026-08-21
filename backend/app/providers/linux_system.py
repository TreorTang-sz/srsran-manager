"""Linux system metrics provider (production, RK3588 / Ubuntu 20.04).

DEPLOYMENT STATUS: written for Phase 6, to be verified on the real
RK3588 target. All data comes from /proc and /sys — no external
dependencies, works on ARM64.
"""
from __future__ import annotations

import os
import shutil
import time
from pathlib import Path

from app.models import SystemMetrics


def _read(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return ""


def _parse_proc_stat() -> tuple[list[list[int]], float]:
    """Return per-cpu jiffy counters and total jiffies."""
    cpus: list[list[int]] = []
    total = 0.0
    for line in _read("/proc/stat").splitlines():
        if line.startswith("cpu"):
            parts = line.split()
            if parts[0] == "cpu":
                total = sum(float(x) for x in parts[1:])
            else:
                cpus.append([int(x) for x in parts[1:]])
    return cpus, total


class LinuxSystemMetricsProvider:
    def __init__(self) -> None:
        self._last_cpus, self._last_total = _parse_proc_stat()
        self._last_ts = time.time()
        self._last_disk_stats = self._read_diskstats()
        self._last_net = self._read_net_dev()
        self._boot_ts = time.time()

    # -- helpers -----------------------------------------------------------
    @staticmethod
    def _read_diskstats() -> dict[str, tuple[int, int]]:
        """device -> (sectors_read, sectors_written)."""
        out: dict[str, tuple[int, int]] = {}
        for line in _read("/proc/diskstats").splitlines():
            parts = line.split()
            if len(parts) < 7:
                continue
            name = parts[2]
            # whole devices only (no partitions), skip loop/ram
            if not any(name.startswith(p) for p in ("sd", "vd", "nvme", "mmcblk")):
                continue
            if name[-1].isdigit() and name.startswith(("sd", "vd")):
                continue  # sda1 etc.
            out[name] = (int(parts[5]), int(parts[9]))
        return out

    @staticmethod
    def _read_net_dev() -> tuple[int, int]:
        rx = tx = 0
        for line in _read("/proc/net/dev").splitlines()[2:]:
            if ":" not in line:
                continue
            iface, rest = line.split(":", 1)
            iface = iface.strip()
            if iface == "lo":
                continue
            cols = rest.split()
            rx += int(cols[0])
            tx += int(cols[8])
        return rx, tx

    @staticmethod
    def _cpu_temp() -> float | None:
        best: float | None = None
        for zone in sorted(Path("/sys/class/thermal").glob("thermal_zone*")):
            raw = _read(str(zone / "temp")).strip()
            if raw.isdigit():
                t = int(raw) / 1000.0
                best = t if best is None else max(best, t)
        return best

    # -- provider API --------------------------------------------------------
    def get_metrics(self) -> SystemMetrics:
        now = time.time()
        dt = max(now - self._last_ts, 1e-6)

        # CPU (deltas since last call)
        cpus, total = _parse_proc_stat()
        per_core: list[float] = []
        if len(cpus) == len(self._last_cpus):
            for cur, prev in zip(cpus, self._last_cpus):
                idle_cur = cur[3] + (cur[4] if len(cur) > 4 else 0)
                idle_prev = prev[3] + (prev[4] if len(prev) > 4 else 0)
                d_total = sum(cur) - sum(prev)
                d_idle = idle_cur - idle_prev
                per_core.append(max(0.0, min(100.0, (1.0 - d_idle / d_total) * 100.0)) if d_total > 0 else 0.0)
        cpu_percent = sum(per_core) / len(per_core) if per_core else 0.0

        # memory
        meminfo: dict[str, float] = {}
        for line in _read("/proc/meminfo").splitlines():
            if ":" in line:
                key, val = line.split(":", 1)
                meminfo[key.strip()] = float(val.split()[0]) / 1024.0  # MiB

        # disk usage
        disk_total = disk_used = disk_percent = 0.0
        try:
            usage = shutil.disk_usage("/")
            disk_total = usage.total / 1024 ** 3
            disk_used = usage.used / 1024 ** 3
            # shutil.disk_usage 没有 .percent 属性（那是 psutil 的），手动计算
            disk_percent = usage.used / usage.total * 100.0 if usage.total else 0.0
        except OSError:
            pass

        # disk IO rate
        disk_stats = self._read_diskstats()
        dr = dw = 0.0
        if self._last_disk_stats:
            prev_total = [sum(v) for v in zip(*self._last_disk_stats.values())] if self._last_disk_stats else [0, 0]
            cur_total = [sum(v) for v in zip(*disk_stats.values())] if disk_stats else [0, 0]
            dr = (cur_total[0] - prev_total[0]) * 512 / dt / 1024 ** 2
            dw = (cur_total[1] - prev_total[1]) * 512 / dt / 1024 ** 2

        # network rate
        net = self._read_net_dev()
        rx_mbps = (net[0] - self._last_net[0]) * 8 / dt / 1024 ** 2
        tx_mbps = (net[1] - self._last_net[1]) * 8 / dt / 1024 ** 2

        uptime_s = 0.0
        up = _read("/proc/uptime").split()
        if up:
            uptime_s = float(up[0])

        self._last_cpus, self._last_total = cpus, total
        self._last_ts = now
        self._last_disk_stats = disk_stats
        self._last_net = net

        return SystemMetrics(
            ts=now,
            cpu_percent=round(cpu_percent, 1),
            cpu_per_core=[round(x, 1) for x in per_core],
            mem_total_mb=meminfo.get("MemTotal", 0.0),
            mem_used_mb=meminfo.get("MemTotal", 0.0) - meminfo.get("MemAvailable", 0.0),
            mem_percent=round(
                (meminfo.get("MemTotal", 0.0) - meminfo.get("MemAvailable", 0.0))
                / max(meminfo.get("MemTotal", 1.0), 1.0) * 100.0, 1),
            swap_total_mb=meminfo.get("SwapTotal", 0.0),
            swap_used_mb=meminfo.get("SwapTotal", 0.0) - meminfo.get("SwapFree", 0.0),
            disk_total_gb=round(disk_total, 1),
            disk_used_gb=round(disk_used, 1),
            disk_percent=round(disk_percent, 1),
            disk_read_mbps=round(max(dr, 0.0), 2),
            disk_write_mbps=round(max(dw, 0.0), 2),
            net_rx_mbps=round(max(rx_mbps, 0.0), 2),
            net_tx_mbps=round(max(tx_mbps, 0.0), 2),
            cpu_temp_c=self._cpu_temp(),
            uptime_s=uptime_s,
        )
