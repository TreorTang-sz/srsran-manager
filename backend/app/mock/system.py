"""Mock system metrics provider (Windows dev mode)."""
from __future__ import annotations

import random
import time

from app.mock.world import MockWorld
from app.models import SystemMetrics


class MockSystemMetricsProvider:
    def __init__(self, world: MockWorld) -> None:
        self.world = world
        self._rng = random.Random(42)
        self._mem_used_percent = 42.0
        self._cpu_base = 24.0

    def get_metrics(self) -> SystemMetrics:
        self.world.tick()
        w = self.world
        rng = self._rng

        if w.high_cpu:
            cpu = round(rng.uniform(94.0, 98.0), 1)
        else:
            self._cpu_base = max(8.0, min(70.0, self._cpu_base + rng.uniform(-4.0, 4.0)))
            cpu = round(max(3.0, min(99.0, self._cpu_base + rng.uniform(-6.0, 6.0))), 1)

        per_core = [round(max(2.0, min(100.0, cpu + rng.uniform(-15.0, 15.0))), 1) for _ in range(8)]

        self._mem_used_percent = max(30.0, min(88.0, self._mem_used_percent + rng.uniform(-0.4, 0.4)))
        mem_total = 16384.0
        mem_used = mem_total * self._mem_used_percent / 100.0

        disk_total = 238.5
        disk_used = 96.4

        if w.high_temp:
            temp = round(rng.uniform(86.0, 90.0), 1)
        else:
            temp = round(rng.uniform(55.0, 61.0), 1)

        # network traffic tracks (simulated) core traffic plus management overhead
        ues = w.ue_snapshot()
        lte_dl = sum(u.dl_bitrate_mbps for u in ues)
        lte_ul = sum(u.ul_bitrate_mbps for u in ues)

        return SystemMetrics(
            ts=time.time(),
            cpu_percent=cpu,
            cpu_per_core=per_core,
            mem_total_mb=mem_total,
            mem_used_mb=round(mem_used, 1),
            mem_percent=round(self._mem_used_percent, 1),
            swap_total_mb=8192.0,
            swap_used_mb=round(rng.uniform(380.0, 520.0), 1),
            disk_total_gb=disk_total,
            disk_used_gb=disk_used,
            disk_percent=round(disk_used / disk_total * 100.0, 1),
            disk_read_mbps=round(rng.uniform(0.0, 3.5), 2),
            disk_write_mbps=round(rng.uniform(0.0, 2.0), 2),
            net_rx_mbps=round(lte_dl * 0.95 + rng.uniform(0.1, 0.5), 2),
            net_tx_mbps=round(lte_ul * 0.95 + rng.uniform(0.1, 0.5), 2),
            cpu_temp_c=temp,
            uptime_s=3 * 86400 + (time.time() - w._process_start),
        )
