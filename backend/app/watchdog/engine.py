"""Watchdog engine — the loop that drives the state machine.

Runs in its own thread and has ZERO dependency on the web layer
(FastAPI is never imported here). In production it can run as a
standalone systemd service (srsran-watchdog.service) using
``python -m app.watchdog_runner``; in dev/mock mode it runs inside the
manager process.

Anti-infinite-restart: max_recovery_attempts (default 3) consecutive
failures lead to FAULT; only a manual reset (web control / operator)
leaves FAULT.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Optional

from app.config import AppConfig
from app.core.bus import EventBus
from app.models import (
    EventType,
    HealthLevel,
    HealthReport,
    Severity,
    WatchdogState,
    WatchdogStatus,
)
from app.watchdog.health import HealthChecker
from app.watchdog.recovery import RecoveryManager
from app.watchdog.state_machine import WatchdogEvent, WatchdogStateMachine

logger = logging.getLogger("srsran.watchdog")


class WatchdogEngine:
    def __init__(
        self,
        sm: WatchdogStateMachine,
        health: HealthChecker,
        recovery: RecoveryManager,
        bus: EventBus,
        config: AppConfig,
        state_store=None,  # Optional[app.database.models.StateStore]
    ) -> None:
        self.sm = sm
        self.health = health
        self.recovery = recovery
        self.bus = bus
        self.cfg = config.watchdog
        self._state_store = state_store

        self.action_lock = threading.RLock()
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        self.desired_running = False
        self._desired_cond = threading.Condition()
        self._recovery_in_progress = False
        self._last_recovery_finished_at = 0.0
        self._consecutive_failures = 0
        self._total_recoveries = 0
        self._last_report: Optional[HealthReport] = None
        self._last_error = ""
        self._announced_failures: set[str] = set()

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name="watchdog", daemon=True)
        self._thread.start()
        logger.info("watchdog engine started (interval=%.2fs, max_attempts=%d)",
                    self.cfg.check_interval, self.cfg.max_recovery_attempts)

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=10)

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._tick()
            except Exception as exc:  # noqa: BLE001 — watchdog must never die
                self._last_error = f"{type(exc).__name__}: {exc}"
                logger.exception("watchdog tick failed")
            self._stop_event.wait(self.cfg.check_interval)

    # ------------------------------------------------------------------
    # public control (used by ControlService / API)
    # ------------------------------------------------------------------
    def set_desired_running(self, running: bool) -> None:
        with self._desired_cond:
            self.desired_running = running
            self._desired_cond.notify_all()
        self._persist_desired()
        self._persist_status()
        logger.info("desired state -> %s", "RUNNING" if running else "STOPPED")

    @property
    def consecutive_failures(self) -> int:
        return self._consecutive_failures

    def manual_reset_fault(self) -> None:
        """Operator resets a FAULT: clears failure counters and retries."""
        with self.action_lock:
            self._consecutive_failures = 0
            self._last_error = ""
            self.desired_running = True
            self.sm.fire(WatchdogEvent.RESET)
            self.recovery.start_network()
        self.bus.publish_event(
            EventType.MANUAL_ACTION, source="Watchdog",
            message="manual fault reset — restarting network")

    def status(self) -> WatchdogStatus:
        report = self._last_report
        return WatchdogStatus(
            state=self.sm.state,
            desired_running=self.desired_running,
            consecutive_failures=self._consecutive_failures,
            max_recovery_attempts=self.cfg.max_recovery_attempts,
            total_recoveries=self._total_recoveries,
            state_since=self.sm.state_since,
            last_health_level=report.level if report else HealthLevel.OK,
            last_issues=[f"{i.component}: {i.message}" for i in report.issues] if report else [],
            last_error=self._last_error,
        )

    # ------------------------------------------------------------------
    # core loop
    # ------------------------------------------------------------------
    def _tick(self) -> None:
        self._sync_from_store()
        self._persist_status()
        state = self.sm.state

        if not self.desired_running:
            if state != WatchdogState.STOPPED:
                self.sm.fire(WatchdogEvent.STOP)
            return

        if state == WatchdogState.STOPPED:
            # desired RUNNING but services are stopped -> start them
            with self.action_lock:
                self.sm.fire(WatchdogEvent.START)
                self.recovery.start_network()
            return

        if state == WatchdogState.STARTING:
            self._handle_starting()
            return

        if state in (WatchdogState.RUNNING, WatchdogState.WARNING):
            self._handle_running(state)
            return

        if state == WatchdogState.RECOVERING:
            self._handle_recovering()
            return

        # FAULT: wait for manual reset
        return

    def _handle_starting(self) -> None:
        report = self.health.check()
        self._last_report = report
        if report.level == HealthLevel.OK:
            self._announced_failures.clear()
            self.sm.fire(WatchdogEvent.HEALTHY)
            return
        if report.level == HealthLevel.WARNING:
            self._announced_failures.clear()
            self.sm.fire(WatchdogEvent.WARNING)
            return
        self._announce_failures(report)
        # CRITICAL: still starting or genuinely failing
        elapsed = time.time() - self.sm.state_since
        if elapsed < self.cfg.start_timeout:
            return  # keep waiting for services to come up
        # start timed out -> counts as failed attempt #1
        logger.warning("start timed out after %.1fs", elapsed)
        self._register_failure(reason="start timeout")

    def _handle_running(self, state: WatchdogState) -> None:
        report = self.health.check()
        self._last_report = report
        if report.level == HealthLevel.OK:
            self._announced_failures.clear()
            if state == WatchdogState.WARNING:
                self.sm.fire(WatchdogEvent.HEALTHY)
        elif report.level == HealthLevel.WARNING:
            self._announced_failures.clear()
            self.sm.fire(WatchdogEvent.WARNING)
        else:
            self._announce_failures(report)
            self.sm.fire(WatchdogEvent.CRITICAL)

    def _handle_recovering(self) -> None:
        if self._recovery_in_progress:
            return
        if time.time() - self._last_recovery_finished_at < self.cfg.recovery_cooldown:
            return
        self._attempt_recovery()

    def _attempt_recovery(self) -> None:
        self._recovery_in_progress = True
        attempt_no = self._consecutive_failures + 1
        try:
            with self.action_lock:
                self.bus.publish_event(
                    EventType.AUTO_RECOVERY_STARTED, source="Watchdog",
                    severity=Severity.WARNING,
                    message=f"automatic recovery attempt {attempt_no}/{self.cfg.max_recovery_attempts}",
                    data={"attempt": attempt_no, "max": self.cfg.max_recovery_attempts},
                )
                ok, report = self.recovery.execute()
                self._last_report = report
                if report is not None and report.is_critical:
                    self._announce_failures(report)
        except Exception as exc:  # noqa: BLE001
            logger.exception("recovery attempt raised")
            self._last_error = f"{type(exc).__name__}: {exc}"
            ok, report = False, None
        finally:
            self._recovery_in_progress = False
            self._last_recovery_finished_at = time.time()

        self._total_recoveries += 1
        if ok:
            self._consecutive_failures = 0
            self.bus.publish_event(EventType.AUTO_RECOVERY_SUCCESS, source="Watchdog",
                                   message="recovery successful")
            self.sm.fire(WatchdogEvent.RECOVERY_OK)
        else:
            self._register_failure(reason="recovery unsuccessful")

    # ------------------------------------------------------------------
    def _announce_failures(self, report: HealthReport) -> None:
        """Emit component-failure events once per unhealthy episode.

        Deterministic announcement (independent of how fast the
        recovery is): ENB_CRASH / EPC_CRASH / S1_DISCONNECTED /
        USRP_DISCONNECTED are emitted by the engine the moment the
        failing condition is observed.
        """
        failing: set[str] = set()
        if not report.epc_running:
            failing.add("EPC")
        if not report.enb_running:
            failing.add("ENB")
        if report.epc_running and report.enb_running and not report.s1_connected:
            failing.add("S1")
        if not report.usrp_connected:
            failing.add("USRP")

        for comp in sorted(failing - self._announced_failures):
            if comp == "EPC":
                self.bus.publish_event(EventType.EPC_CRASH, source="EPC",
                                       severity=Severity.ERROR,
                                       message="srsEPC not running")
            elif comp == "ENB":
                self.bus.publish_event(EventType.ENB_CRASH, source="ENB",
                                       severity=Severity.ERROR,
                                       message="srsENB not running")
            elif comp == "S1":
                self.bus.publish_event(EventType.S1_DISCONNECTED, source="S1",
                                       severity=Severity.ERROR,
                                       message="S1 link lost (eNB and EPC processes running)")
            elif comp == "USRP":
                self.bus.publish_event(EventType.USRP_DISCONNECTED, source="USRP",
                                       severity=Severity.ERROR,
                                       message="USRP B210 disconnected")
        self._announced_failures = failing

    def _register_failure(self, reason: str) -> None:
        self._consecutive_failures += 1
        issues = [f"{i.component}: {i.message}" for i in self._last_report.issues] \
            if self._last_report else []
        self.bus.publish_event(
            EventType.AUTO_RECOVERY_FAILED, source="Watchdog",
            severity=Severity.ERROR,
            message=f"recovery failed ({reason}) "
                    f"{self._consecutive_failures}/{self.cfg.max_recovery_attempts}",
            data={"consecutive_failures": self._consecutive_failures,
                  "max": self.cfg.max_recovery_attempts, "issues": issues},
        )
        if self._consecutive_failures >= self.cfg.max_recovery_attempts:
            self.bus.publish_event(
                EventType.FAULT_ENTERED, source="Watchdog",
                severity=Severity.CRITICAL,
                message=f"FAULT: {self.cfg.max_recovery_attempts} consecutive recovery "
                        f"failures — automatic recovery disabled until manual reset",
            )
            self.sm.fire(WatchdogEvent.FAULT)
        else:
            # stay in RECOVERING; cooldown applies before the next attempt
            if self.sm.state == WatchdogState.STARTING:
                self.sm.fire(WatchdogEvent.CRITICAL)
            else:
                self.sm.fire(WatchdogEvent.RECOVERY_FAIL)

    # ------------------------------------------------------------------
    def _persist_status(self) -> None:
        if self._state_store is None:
            return
        try:
            self._state_store.set_state("watchdog_status", self.status().model_dump(mode="json"))
        except Exception:  # noqa: BLE001
            logger.exception("persisting watchdog status failed")

    def _persist_desired(self) -> None:
        if self._state_store is None:
            return
        try:
            self._state_store.set_state("desired_running", self.desired_running)
        except Exception:  # noqa: BLE001
            logger.exception("persisting desired state failed")

    def _sync_from_store(self) -> None:
        """Split deployment: pick up commands written by the web manager.

        The manager-only process (no engine) coordinates through the
        shared kv_state table: desired_running + reset_fault_requested.
        """
        if self._state_store is None:
            return
        try:
            desired = self._state_store.get_state("desired_running")
            if desired is not None and bool(desired) != self.desired_running:
                self.desired_running = bool(desired)
                logger.info("desired state synced from store -> %s",
                            "RUNNING" if desired else "STOPPED")
            if self._state_store.get_state("reset_fault_requested"):
                self._state_store.set_state("reset_fault_requested", False)
                if self.sm.state == WatchdogState.FAULT:
                    logger.info("fault reset requested via store")
                    self.manual_reset_fault()
        except Exception:  # noqa: BLE001
            logger.exception("syncing state from store failed")

