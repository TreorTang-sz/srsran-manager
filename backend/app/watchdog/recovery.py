"""Recovery strategies.

A recovery attempt is a fixed, predefined sequence of service actions —
the ONLY operations the watchdog may perform (start/stop/restart via
ProcessManager). No arbitrary commands.
"""
from __future__ import annotations

import logging
import time

from app.config import AppConfig
from app.core.bus import EventBus
from app.models import EventType, HealthReport, ServiceName, Severity
from app.providers.base import ProcessManager
from app.watchdog.health import HealthChecker

logger = logging.getLogger("srsran.recovery")


class RecoveryManager:
    def __init__(self, process: ProcessManager, health: HealthChecker,
                 bus: EventBus, config: AppConfig) -> None:
        self._process = process
        self._health = health
        self._bus = bus
        self._cfg = config

    # ------------------------------------------------------------------
    def start_network(self) -> None:
        """Idempotent start: EPC first, then eNB."""
        self._process.start(ServiceName.EPC)
        self._bus.publish_event(EventType.EPC_STARTED, source="Watchdog",
                                message="srsEPC start issued", data={"action": "start"})
        self._process.start(ServiceName.ENB)
        self._bus.publish_event(EventType.ENB_STARTED, source="Watchdog",
                                message="srsENB start issued", data={"action": "start"})

    def execute(self) -> tuple[bool, HealthReport]:
        """One recovery attempt. Returns (success, final_report).

        Strategy (ordered):
          1. EPC down                          -> restart EPC, then restart eNB
          2. eNB down / S1 down / USRP down    -> restart eNB
        Then verify health after verify_delay.
        """
        report = self._health.check()
        acted = False

        if not report.epc_running:
            logger.warning("recovery: restarting srsEPC")
            self._process.restart(ServiceName.EPC)
            self._bus.publish_event(EventType.EPC_STARTED, source="Watchdog",
                                    severity=Severity.WARNING,
                                    message="srsEPC restarted (recovery)",
                                    data={"action": "restart", "reason": "epc_down"})
            acted = True
            time.sleep(self._cfg.watchdog.verify_delay)
            report = self._health.check()

        if not report.enb_running or not report.s1_connected or not report.usrp_connected:
            logger.warning("recovery: restarting srsENB (enb=%s s1=%s usrp=%s)",
                           report.enb_running, report.s1_connected, report.usrp_connected)
            self._process.restart(ServiceName.ENB)
            self._bus.publish_event(EventType.ENB_STARTED, source="Watchdog",
                                    severity=Severity.WARNING,
                                    message="srsENB restarted (recovery)",
                                    data={"action": "restart",
                                          "reason": "enb_down" if not report.enb_running
                                          else "s1_down" if not report.s1_connected
                                          else "usrp_down"})
            acted = True
            time.sleep(self._cfg.watchdog.verify_delay)
            report = self._health.check()

        if not acted:
            # Already healthy again on its own (e.g. systemd restarted the
            # process before we acted) — verify once more for stability.
            time.sleep(min(self._cfg.watchdog.verify_delay, 1.0))
            report = self._health.check()

        return report.is_healthy_for_recovery, report
