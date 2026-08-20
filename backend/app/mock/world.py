"""MockWorld — the simulated srsRAN server used in Windows dev mode.

Holds all simulated state (services, S1, USRP, UEs, system load) and
advances it lazily whenever any provider reads it. Fault injection
mutates this world; the watchdog then observes the injected fault
exactly as it would observe a real fault on Linux.

Fault semantics:
  * enb/epc crash  - one-shot: the process dies; a restart fixes it.
  * s1 disconnect  - sticky until the eNB restarts (link re-establishes).
  * usrp disconnect- sticky until explicitly cleared (physical unplug).
  * high cpu/temp  - sticky until cleared (resource anomaly).
  * recover-fail N - the next N start/restart attempts end in FAILED,
                     then the system recovers normally. Used to test the
                     RECOVERING -> FAULT path and multi-attempt recovery.
"""
from __future__ import annotations

import random
import threading
import time

from app.config import AppConfig
from app.models import ServiceName, ServiceState, UEInfo


class MockService:
    def __init__(self, name: str) -> None:
        self.name = name
        self.state = ServiceState.STOPPED
        self.pid: int | None = None
        self.ready_at = 0.0
        self.stop_at = 0.0
        self.will_fail = False
        self.running_since = 0.0
        self._pid_seq = random.randint(800, 1600)


class MockUE:
    def __init__(self, rnti: int, rng: random.Random) -> None:
        self.rnti = rnti
        self.cqi = rng.randint(8, 15)
        self.mcs_dl = rng.randint(12, 27)
        self.mcs_ul = rng.randint(8, 20)
        self.dl = rng.uniform(6.0, 14.0)   # Mbps
        self.ul = rng.uniform(0.5, 1.6)    # Mbps
        self.last_seen = time.time()


class MockWorld:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.lock = threading.RLock()
        self.services: dict[str, MockService] = {
            ServiceName.EPC.value: MockService(ServiceName.EPC.value),
            ServiceName.ENB.value: MockService(ServiceName.ENB.value),
        }

        # fault injection state
        self.usrp_fault = False
        self.s1_fault = False
        self.high_cpu = False
        self.high_temp = False
        self.recover_fail_pending = 0

        # UE simulation
        self.ues: dict[int, MockUE] = {}
        self._next_rnti = 0x4601

        self._rng = random.Random()
        self._last_tick = 0.0
        self._process_start = time.time()

    # ------------------------------------------------------------------
    # simulation core
    # ------------------------------------------------------------------
    def tick(self, now: float | None = None) -> None:
        now = now if now is not None else time.time()
        with self.lock:
            if now - self._last_tick < 0.05:
                return
            self._last_tick = now

            for svc in self.services.values():
                if svc.state == ServiceState.STARTING and now >= svc.ready_at:
                    if svc.will_fail:
                        svc.state = ServiceState.FAILED
                        svc.pid = None
                        svc.will_fail = False
                    else:
                        svc.state = ServiceState.RUNNING
                        svc._pid_seq += 1
                        svc.pid = svc._pid_seq
                        svc.running_since = now
                elif svc.state == ServiceState.STOPPING and now >= svc.stop_at:
                    svc.state = ServiceState.STOPPED
                    svc.pid = None

            if self.s1_connected(now):
                self._simulate_ues(now)
            elif self.ues:
                self.ues.clear()

    def _simulate_ues(self, now: float) -> None:
        cfg = self.config.mock
        rng = self._rng
        if len(self.ues) < cfg.max_ues and rng.random() < cfg.ue_attach_probability:
            rnti = self._next_rnti
            self._next_rnti += 1
            self.ues[rnti] = MockUE(rnti, rng)
        if self.ues and rng.random() < cfg.ue_detach_probability:
            self.ues.pop(rng.choice(list(self.ues.keys())))
        for ue in self.ues.values():
            ue.cqi = max(4, min(15, ue.cqi + rng.choice((-1, 0, 0, 1))))
            ue.mcs_dl = max(5, min(28, ue.mcs_dl + rng.choice((-2, -1, 0, 1, 2))))
            ue.mcs_ul = max(4, min(22, ue.mcs_ul + rng.choice((-1, 0, 0, 1))))
            ue.dl = max(0.2, min(30.0, ue.dl + rng.uniform(-1.2, 1.2)))
            ue.ul = max(0.1, min(5.0, ue.ul + rng.uniform(-0.2, 0.2)))
            ue.last_seen = now

    # ------------------------------------------------------------------
    # derived state
    # ------------------------------------------------------------------
    def service_state(self, name: ServiceName) -> ServiceState:
        self.tick()
        with self.lock:
            return self.services[name.value].state

    def s1_connected(self, now: float | None = None) -> bool:
        now = now if now is not None else time.time()
        self.tick(now)
        with self.lock:
            if self.s1_fault:
                return False
            epc = self.services[ServiceName.EPC.value]
            enb = self.services[ServiceName.ENB.value]
            if epc.state != ServiceState.RUNNING or enb.state != ServiceState.RUNNING:
                return False
            # S1 comes up shortly after the eNB is running
            return now >= enb.running_since + self.config.mock.s1_connect_delay

    def usrp_connected(self) -> bool:
        return not self.usrp_fault

    def ue_snapshot(self) -> list[UEInfo]:
        self.tick()
        with self.lock:
            return [
                UEInfo(
                    rnti=ue.rnti,
                    cqi=ue.cqi,
                    mcs_dl=ue.mcs_dl,
                    mcs_ul=ue.mcs_ul,
                    dl_bitrate_mbps=round(ue.dl, 2),
                    ul_bitrate_mbps=round(ue.ul, 2),
                    last_seen=ue.last_seen,
                    state="CONNECTED",
                )
                for ue in self.ues.values()
            ]

    # ------------------------------------------------------------------
    # process manager operations
    # ------------------------------------------------------------------
    def start_service(self, name: ServiceName) -> None:
        with self.lock:
            svc = self.services[name.value]
            now = time.time()
            if svc.state in (ServiceState.RUNNING, ServiceState.STARTING):
                return
            svc.will_fail = self._consume_recover_fail(name)
            svc.state = ServiceState.STARTING
            svc.ready_at = now + self.config.mock.start_delay
            if name == ServiceName.ENB:
                # restarting the eNB re-establishes the S1 link
                self.s1_fault = False

    def stop_service(self, name: ServiceName) -> None:
        with self.lock:
            svc = self.services[name.value]
            now = time.time()
            svc.will_fail = False
            if svc.state == ServiceState.STOPPED:
                return
            svc.state = ServiceState.STOPPING
            svc.stop_at = now + self.config.mock.stop_delay

    def crash_service(self, name: ServiceName) -> None:
        """Unexpected process death (fault injection)."""
        with self.lock:
            svc = self.services[name.value]
            svc.state = ServiceState.STOPPED
            svc.pid = None
            svc.will_fail = False

    def _consume_recover_fail(self, name: ServiceName) -> bool:
        if self.recover_fail_pending > 0:
            self.recover_fail_pending -= 1
            return True
        return False
