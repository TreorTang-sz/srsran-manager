"""Control service — the ONLY path for user-initiated service actions.

Wraps ProcessManager operations (start/stop/restart on epc/enb/network),
coordinates with the watchdog (desired state, action lock) and records
MANUAL_ACTION events. The web API calls this; the web layer itself has
no direct access to process control.

Split deployment (manager-only web process): the engine runs in the
separate watchdog service, so coordination happens through the shared
SQLite kv_state table (desired_running / reset_fault_requested keys).
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Optional

from app.core.bus import EventBus
from app.models import EventType, ServiceName, Severity
from app.providers.base import ProcessManager
from app.watchdog.engine import WatchdogEngine

logger = logging.getLogger("srsran.control")


class ControlService:
    def __init__(self, process: ProcessManager, engine: Optional[WatchdogEngine],
                 bus: EventBus, state_store=None) -> None:
        self._process = process
        self._engine = engine
        self._bus = bus
        self._state_store = state_store  # Optional[StateStore] (split mode)
        self._fallback_lock = threading.RLock()
        self.last_action_ts = 0.0

    # ------------------------------------------------------------------
    # coordination helpers (work in both single-process and split mode)
    # ------------------------------------------------------------------
    @property
    def action_lock(self):
        return self._engine.action_lock if self._engine is not None else self._fallback_lock

    def _set_desired(self, running: bool) -> None:
        if self._engine is not None:
            self._engine.set_desired_running(running)  # also persists to kv
        elif self._state_store is not None:
            try:
                self._state_store.set_state("desired_running", running)
            except Exception:  # noqa: BLE001
                logger.exception("persisting desired state failed")

    def _is_fault(self) -> bool:
        if self._engine is not None:
            return self._engine.sm.state.value == "FAULT"
        if self._state_store is not None:
            try:
                status = self._state_store.get_state("watchdog_status")
                return bool(status and status.get("state") == "FAULT")
            except Exception:  # noqa: BLE001
                logger.exception("reading watchdog status failed")
        return False

    def _reset_fault_if_needed(self) -> None:
        if self._engine is not None:
            self._engine.manual_reset_fault()
        elif self._state_store is not None:
            try:
                self._state_store.set_state("reset_fault_requested", True)
            except Exception:  # noqa: BLE001
                logger.exception("requesting fault reset failed")

    # ------------------------------------------------------------------
    def _manual(self, action: str, target: str) -> None:
        self.last_action_ts = time.time()
        self._bus.publish_event(
            EventType.MANUAL_ACTION, source="Manager",
            message=f"manual {action} on {target}",
            data={"action": action, "target": target},
        )

    # ------------------------------------------------------------------
    # whole network
    # ------------------------------------------------------------------
    def start_network(self) -> dict:
        with self.action_lock:
            self._manual("start", "network")
            if self._is_fault():
                self._reset_fault_if_needed()
            else:
                self._process.start(ServiceName.EPC)
                self._bus.publish_event(EventType.EPC_STARTED, source="Manager",
                                        message="srsEPC started (manual)")
                self._process.start(ServiceName.ENB)
                self._bus.publish_event(EventType.ENB_STARTED, source="Manager",
                                        message="srsENB started (manual)")
                self._set_desired(True)
        return {"result": "network start issued"}

    def stop_network(self) -> dict:
        with self.action_lock:
            self._manual("stop", "network")
            self._set_desired(False)
            self._process.stop(ServiceName.ENB)
            self._bus.publish_event(EventType.ENB_STOPPED, source="Manager",
                                    message="srsENB stopped (manual)")
            self._process.stop(ServiceName.EPC)
            self._bus.publish_event(EventType.EPC_STOPPED, source="Manager",
                                    message="srsEPC stopped (manual)")
        return {"result": "network stop issued"}

    def restart_network(self) -> dict:
        with self.action_lock:
            self._manual("restart", "network")
            if self._is_fault():
                self._reset_fault_if_needed()
            else:
                self._process.restart(ServiceName.EPC)
                self._bus.publish_event(EventType.EPC_STARTED, source="Manager",
                                        message="srsEPC restarted (manual)",
                                        data={"action": "restart"})
                self._process.restart(ServiceName.ENB)
                self._bus.publish_event(EventType.ENB_STARTED, source="Manager",
                                        message="srsENB restarted (manual)",
                                        data={"action": "restart"})
                self._set_desired(True)
        return {"result": "network restart issued"}

    # ------------------------------------------------------------------
    # single services
    # ------------------------------------------------------------------
    def start_service(self, service: ServiceName) -> dict:
        with self.action_lock:
            self._manual("start", service.value)
            self._process.start(service)
            self._bus.publish_event(
                EventType.EPC_STARTED if service == ServiceName.EPC else EventType.ENB_STARTED,
                source="Manager", message=f"{service.value} started (manual)")
            self._set_desired(True)
        return {"result": f"{service.value} start issued"}

    def stop_service(self, service: ServiceName) -> dict:
        with self.action_lock:
            self._manual("stop", service.value)
            self._set_desired(False)
            self._process.stop(service)
            self._bus.publish_event(
                EventType.EPC_STOPPED if service == ServiceName.EPC else EventType.ENB_STOPPED,
                source="Manager", message=f"{service.value} stopped (manual)")
        return {"result": f"{service.value} stop issued"}

    def restart_service(self, service: ServiceName) -> dict:
        with self.action_lock:
            self._manual("restart", service.value)
            if self._is_fault():
                self._reset_fault_if_needed()
            else:
                self._process.restart(service)
                self._bus.publish_event(
                    EventType.EPC_STARTED if service == ServiceName.EPC else EventType.ENB_STARTED,
                    source="Manager", message=f"{service.value} restarted (manual)",
                    data={"action": "restart"})
                self._set_desired(True)
        return {"result": f"{service.value} restart issued"}
