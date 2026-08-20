"""Runtime — wires providers, database, watchdog, monitor and control.

Composition happens here; the API layer only consumes the runtime.
In mock mode the whole system runs in one process. On Linux the same
Runtime can run inside srsran-watchdog.service (run_web=False) and
srsran-manager.service (run_watchdog=False) — the SQLite kv_state
table then carries the watchdog status between the two processes.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Optional

from app.config import AppConfig
from app.core.bus import BusLogHandler, EventBus
from app.core.control import ControlService
from app.core.history import ThroughputHistory
from app.database.db import Database
from app.database.models import (
    BusPersister,
    EventStore,
    LogStore,
    StateStore,
)
from app.models import (
    EventType,
    HealthLevel,
    ServiceName,
    ServiceState,
    Severity,
    Snapshot,
    WatchdogState,
    WatchdogStatus,
)
from app.mock.faults import FaultController
from app.providers import Providers, build_providers
from app.watchdog.engine import WatchdogEngine
from app.watchdog.health import HealthChecker
from app.watchdog.recovery import RecoveryManager
from app.watchdog.state_machine import WatchdogEvent, WatchdogStateMachine

logger = logging.getLogger("srsran.runtime")


class MonitorLoop:
    """Samples all providers once per interval, detects state changes,
    records events and refreshes the live snapshot."""

    def __init__(self, runtime: "Runtime") -> None:
        self.rt = runtime
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

        self._prev_s1: Optional[bool] = None
        self._prev_usrp: Optional[bool] = None
        self._prev_ues: set[int] = set()
        self._prev_states: dict[str, ServiceState] = {}

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="monitor", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception:  # noqa: BLE001
                logger.exception("monitor tick failed")
            self._stop.wait(self.rt.config.watchdog.monitor_interval)

    # ------------------------------------------------------------------
    def tick(self) -> Snapshot:
        rt = self.rt
        providers: Providers = rt.providers

        system = providers.system.get_metrics()
        enb_metrics = providers.srsran.get_enb_metrics()
        core = providers.core_traffic.get_traffic()
        s1 = providers.s1.get_status()
        usrp = providers.usrp.get_status()
        epc_status = providers.process.status(ServiceName.EPC)
        enb_status = providers.process.status(ServiceName.ENB)

        self._detect_changes(epc_status.state, enb_status.state, s1.connected,
                             usrp.connected, [u.rnti for u in enb_metrics.ues])

        rt.history.append(enb_metrics.dl_bitrate_mbps, enb_metrics.ul_bitrate_mbps,
                          core.rx_mbps, core.tx_mbps)

        snapshot = Snapshot(
            ts=time.time(),
            mode=rt.config.resolved_mode,
            watchdog=rt.watchdog_status(),
            services={"epc": epc_status, "enb": enb_status},
            s1=s1,
            usrp=usrp,
            system=system,
            enb_metrics=enb_metrics,
            core_traffic=core,
            recent_events=rt.bus.recent_events(20),
        )
        rt.latest = snapshot
        return snapshot

    def _detect_changes(self, epc_state: ServiceState, enb_state: ServiceState,
                        s1_connected: bool, usrp_connected: bool, ue_rntis: list[int]) -> None:
        """Recovery-side change detection (connect / attach).

        Failure-side events (ENB_CRASH, S1_DISCONNECTED, ...) are emitted
        deterministically by the watchdog engine, which observes the
        failing condition before acting on it.
        """
        rt = self.rt
        bus = rt.bus

        if self._prev_s1 is not None and self._prev_s1 != s1_connected:
            if s1_connected:
                bus.publish_event(EventType.S1_CONNECTED, source="S1",
                                  message="S1 link established")
        if self._prev_usrp is not None and self._prev_usrp != usrp_connected:
            if usrp_connected:
                bus.publish_event(EventType.USRP_CONNECTED, source="USRP",
                                  message="USRP B210 connected")

        current = set(ue_rntis)
        for rnti in current - self._prev_ues:
            bus.publish_event(EventType.UE_ATTACHED, source="ENB",
                              message=f"UE attached (RNTI=0x{rnti:04x})",
                              data={"rnti": rnti})
        for rnti in self._prev_ues - current:
            bus.publish_event(EventType.UE_DETACHED, source="ENB",
                              message=f"UE detached (RNTI=0x{rnti:04x})",
                              data={"rnti": rnti})

        self._prev_s1 = s1_connected
        self._prev_usrp = usrp_connected
        self._prev_ues = current
        self._prev_states = {"epc": epc_state, "enb": enb_state}


class Runtime:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.bus = EventBus()

        self.providers = build_providers(config)

        self.db = Database(config.database.path)
        self.event_store = EventStore(self.db)
        self.log_store = LogStore(self.db)
        self.state_store = StateStore(self.db)
        self._persister = BusPersister(self.bus, self.event_store, self.log_store)

        self.history = ThroughputHistory()

        # watchdog (optional: absent in manager-only split mode)
        self.engine: Optional[WatchdogEngine] = None
        self.sm = WatchdogStateMachine()
        if config.watchdog.run_watchdog:
            health = HealthChecker(
                self.providers.process, self.providers.usrp,
                self.providers.s1, self.providers.system, config,
            )
            recovery = RecoveryManager(self.providers.process, health, self.bus, config)
            self.engine = WatchdogEngine(self.sm, health, recovery, self.bus,
                                         config, state_store=self.state_store)
            self.sm.add_listener(self._on_state_change)

        self.control = ControlService(self.providers.process, self.engine, self.bus,
                                      state_store=self.state_store)

        self.faults: Optional[FaultController] = None
        if self.providers.mock_world is not None:
            self.faults = FaultController(self.providers.mock_world, self.bus)

        self.monitor = MonitorLoop(self)
        self.latest: Optional[Snapshot] = None

        self._started = False

    # ------------------------------------------------------------------
    def start(self) -> None:
        if self._started:
            return
        self._started = True
        self.bus.publish_event(
            EventType.SYSTEM_START, source="Manager",
            message=f"srsRAN Manager started (mode={self.config.resolved_mode})")
        if self.engine:
            self.engine.start()
            if self.config.watchdog.auto_start:
                # 无人值守运行: 管理器启动即视为期望网络运行 (STOPPED -> STARTING)
                self.engine.set_desired_running(True)
        if self.config.watchdog.run_monitor:
            self.monitor.start()

    def stop(self) -> None:
        if not self._started:
            return
        self.bus.publish_event(EventType.SYSTEM_SHUTDOWN, source="Manager",
                               message="srsRAN Manager stopping")
        self.monitor.stop()
        if self.engine:
            self.engine.stop()
        self.db.close()
        self._started = False

    # ------------------------------------------------------------------
    def watchdog_status(self) -> WatchdogStatus:
        if self.engine is not None:
            return self.engine.status()
        # split deployment: read status written by the watchdog service
        data = self.state_store.get_state("watchdog_status")
        if data:
            try:
                return WatchdogStatus(**data)
            except Exception:  # noqa: BLE001
                logger.exception("invalid watchdog_status in kv_state")
        return WatchdogStatus()

    def snapshot(self) -> Snapshot:
        if self.latest is not None:
            return self.latest
        return self.monitor.tick()

    def _on_state_change(self, old: WatchdogState, new: WatchdogState,
                         event: WatchdogEvent) -> None:
        self.bus.publish_event(
            EventType.WATCHDOG_STATE_CHANGED, source="Watchdog",
            severity=Severity.WARNING if new in (WatchdogState.RECOVERING, WatchdogState.FAULT)
            else Severity.INFO,
            message=f"watchdog state: {old.value} -> {new.value} (event={event.value})",
            data={"from": old.value, "to": new.value, "event": event.value},
        )

    # ------------------------------------------------------------------
    def setup_logging(self) -> None:
        root = logging.getLogger()
        root.setLevel(getattr(logging, self.config.log_level.upper(), logging.INFO))
        if not any(isinstance(h, BusLogHandler) for h in root.handlers):
            root.addHandler(BusLogHandler(self.bus))


def build_runtime(config: Optional[AppConfig] = None) -> Runtime:
    if config is None:
        from app.config import load_config
        config = load_config()
    rt = Runtime(config)
    rt.setup_logging()
    return rt
