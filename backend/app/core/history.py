"""In-memory throughput history (ring buffer, 1 Hz, ~1 hour).

Architecture note: history is kept in memory for the first version
(1-minute curves). The interface allows a future Prometheus /
time-series backend without touching API consumers.
"""
from __future__ import annotations

import threading
import time
from collections import deque
from typing import Deque, List

from app.models import ThroughputPoint


class ThroughputHistory:
    def __init__(self, capacity: int = 3600) -> None:
        self._points: Deque[ThroughputPoint] = deque(maxlen=capacity)
        self._lock = threading.Lock()

    def append(self, lte_dl: float, lte_ul: float, core_dl: float, core_ul: float) -> None:
        point = ThroughputPoint(
            ts=time.time(),
            lte_dl=round(lte_dl, 3),
            lte_ul=round(lte_ul, 3),
            core_dl=round(core_dl, 3),
            core_ul=round(core_ul, 3),
        )
        with self._lock:
            self._points.append(point)

    def window(self, seconds: int = 60) -> List[ThroughputPoint]:
        cutoff = time.time() - seconds
        with self._lock:
            return [p for p in self._points if p.ts >= cutoff]
