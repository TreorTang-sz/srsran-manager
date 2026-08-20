"""Mock srsRAN providers: S1 link, eNB metrics, core traffic (dev mode)."""
from __future__ import annotations

import random
import time

from app.mock.world import MockWorld
from app.models import CoreTraffic, EnbMetrics, S1Status


class MockS1Provider:
    def __init__(self, world: MockWorld) -> None:
        self.world = world

    def get_status(self) -> S1Status:
        connected = self.world.s1_connected()
        if connected:
            detail = "SCTP association to EPC :36412 established"
        elif self.world.s1_fault:
            detail = "S1 link down (injected fault)"
        else:
            detail = "S1 not established (eNB or EPC not running)"
        return S1Status(ts=time.time(), connected=connected, detail=detail)


class MockSrsranMetricsProvider:
    def __init__(self, world: MockWorld) -> None:
        self.world = world

    def get_enb_metrics(self) -> EnbMetrics:
        ues = self.world.ue_snapshot()
        now = time.time()
        return EnbMetrics(
            ts=now,
            ue_count=len(ues),
            ues=ues,
            dl_bitrate_mbps=round(sum(u.dl_bitrate_mbps for u in ues), 2),
            ul_bitrate_mbps=round(sum(u.ul_bitrate_mbps for u in ues), 2),
            source="mock",
        )


class MockCoreTrafficProvider:
    """Simulates SGi traffic: slightly below air-interface bitrates
    (protocol overhead / idle periods)."""

    def __init__(self, world: MockWorld) -> None:
        self.world = world
        self._rng = random.Random(7)

    def get_traffic(self) -> CoreTraffic:
        ues = self.world.ue_snapshot()
        lte_dl = sum(u.dl_bitrate_mbps for u in ues)
        lte_ul = sum(u.ul_bitrate_mbps for u in ues)
        return CoreTraffic(
            ts=time.time(),
            rx_mbps=round(max(0.0, lte_dl * self._rng.uniform(0.85, 0.95)), 2),
            tx_mbps=round(max(0.0, lte_ul * self._rng.uniform(0.82, 0.93)), 2),
            interfaces=["srs_spgw_sgi(mock)"],
        )
