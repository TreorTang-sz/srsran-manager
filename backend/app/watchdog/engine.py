"""Watchdog engine — the loop that drives the log-event-driven state machine.

Runs in its own thread and has ZERO dependency on the web layer
(FastAPI is never imported here). In production it can run as a
standalone systemd service (srsran-watchdog.service); in dev/mock mode
it runs inside the manager process.

每个 tick：
  1. pump 日志（journalctl / mock 剧本 -> 解析 -> 聚合器）
  2. STOPPED + desired -> 发起启动（EPC 先、eNB 后）
  3. CONFIG_ERROR -> 直接 FAULT（重启无意义，禁止自动恢复）
  4. CRITICAL（进程死 / 阶段超时 / S1_LOST 超时）-> RECOVERING
  5. 否则按聚合器的组件阶段派生状态（sync_to），S1_LOST -> DEGRADED

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
    EnbStage,
    EpcStage,
    EventType,
    HealthLevel,
    HealthReport,
    Severity,
    S1State,
    WatchdogState,
    WatchdogStatus,
)
from app.watchdog.aggregator import LogStateAggregator
from app.watchdog.health import HealthChecker
from app.watchdog.pipeline import LogPipeline
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
        pipeline: LogPipeline,
        aggregator: LogStateAggregator,
        state_store=None,  # Optional[app.database.models.StateStore]
    ) -> None:
        self.sm = sm
        self.health = health
        self.recovery = recovery
        self.bus = bus
        self.pipeline = pipeline
        self.agg = aggregator
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
        self._fault_reason = ""
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
        """Operator resets a FAULT: clears failure counters and retries.

        强制重启两个服务：FAULT 场景下服务可能还在运行（如 PLMN 配置
        错误），幂等 start 不会产生新的启动 banner —— 必须重启才能让
        聚合器从新日志完整重建状态。
        """
        with self.action_lock:
            self._consecutive_failures = 0
            self._last_error = ""
            self._fault_reason = ""
            self.agg.reset_all()
            self.agg.clear_config_error()
            self.desired_running = True
            self.sm.fire(WatchdogEvent.RESET)
            self.recovery.start_network(force_restart=True)
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
            fault_reason=self._fault_reason,
        )

    # ------------------------------------------------------------------
    # core loop
    # ------------------------------------------------------------------
    def _tick(self) -> None:
        self._sync_from_store()
        self.pipeline.pump()
        self._persist_status()
        state = self.sm.state

        if not self.desired_running:
            if state != WatchdogState.STOPPED:
                self.sm.fire(WatchdogEvent.STOP)
                # 网络被主动停机：丢弃日志推导的旧状态（banner 回滚
                # 依赖新日志，停机期间不会有新证据）
                self.agg.reset_all()
            return

        if state == WatchdogState.STOPPED:
            # desired RUNNING but services are stopped -> start them
            with self.action_lock:
                self._fault_reason = ""
                self.sm.fire(WatchdogEvent.START)
                self.recovery.start_network()
            return

        if state == WatchdogState.FAULT:
            return  # wait for manual reset

        if state == WatchdogState.RECOVERING:
            self._handle_recovering()
            return

        # operating states (STARTING / EPC_READY / ... / RUNNING / WARNING / DEGRADED)
        self._handle_operating()

    # ------------------------------------------------------------------
    def _handle_operating(self) -> None:
        report = self.health.check()
        self._last_report = report

        # 配置错误：重启无意义 —— 直接 FAULT，禁止自动恢复
        if report.config_error:
            self._announce_failures(report)
            self._enter_fault(reason=f"CONFIG_ERROR: {report.config_error}")
            return

        if report.level == HealthLevel.CRITICAL:
            self._announce_failures(report)
            self.sm.fire(WatchdogEvent.CRITICAL)
            return

        self._announced_failures.clear()
        target = self._derive_target(report)
        if target is not None:
            self.sm.sync_to(target)

    def _derive_target(self, report: HealthReport) -> Optional[WatchdogState]:
        """从组件阶段派生看门狗状态（详见 state_machine 模块文档）。"""
        if report.epc_stage != EpcStage.READY:
            return WatchdogState.STARTING
        if report.enb_stage in (EnbStage.DOWN, EnbStage.STARTING, EnbStage.CONFIG_LOADING):
            return WatchdogState.EPC_READY
        if report.enb_stage == EnbStage.RF_READY:
            return WatchdogState.ENB_RF_INITIALIZING
        # enb_stage == RUNNING
        s1 = report.s1_state
        if s1 == S1State.S1_READY:
            if report.level == HealthLevel.WARNING:
                return WatchdogState.WARNING
            return WatchdogState.RUNNING
        if s1 == S1State.S1_LOST:
            return WatchdogState.DEGRADED  # grace 内等待 eNB 自行重连
        if s1 == S1State.S1_CONNECTING:
            return WatchdogState.S1_CONNECTING
        return WatchdogState.ENB_RUNNING  # S1_DOWN: 等 S1 协商日志

    # ------------------------------------------------------------------
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
            self.sm.fire(WatchdogEvent.RECOVERY_OK)  # -> STARTING, 下一 tick 重新派生
        else:
            reason = "configuration error" if (report and report.config_error) \
                else "recovery unsuccessful"
            self._register_failure(reason=reason,
                                   config_error=(report.config_error if report else None))

    # ------------------------------------------------------------------
    def _announce_failures(self, report: HealthReport) -> None:
        """Emit component-failure events once per unhealthy episode."""
        failing: set[str] = set()
        if not report.epc_running:
            failing.add("EPC")
        if not report.enb_running:
            failing.add("ENB")
        snap = self.agg.snapshot()
        if report.epc_running and report.enb_running:
            if snap.s1_state in (S1State.S1_LOST,):
                failing.add("S1_LOST")
            elif snap.s1_state == S1State.S1_CONFIG_ERROR:
                failing.add("S1_CONFIG")
        if report.enb_running and snap.usrp_log_error:
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
            elif comp == "S1_LOST":
                self.bus.publish_event(EventType.S1_DISCONNECTED, source="S1",
                                       severity=Severity.ERROR,
                                       message="S1 link lost after SCTP shutdown")
            elif comp == "S1_CONFIG":
                self.bus.publish_event(EventType.S1_DISCONNECTED, source="S1",
                                       severity=Severity.ERROR,
                                       message="S1 setup failure (config mismatch)")
            elif comp == "USRP":
                self.bus.publish_event(EventType.USRP_DISCONNECTED, source="USRP",
                                       severity=Severity.ERROR,
                                       message=f"USRP B210 problem: {snap.usrp_log_error}")
        self._announced_failures = failing

    def _enter_fault(self, reason: str) -> None:
        if self.sm.state == WatchdogState.FAULT:
            return
        self._fault_reason = reason
        self.bus.publish_event(
            EventType.FAULT_ENTERED, source="Watchdog",
            severity=Severity.CRITICAL,
            message=f"FAULT: {reason} — automatic recovery disabled until manual reset",
            data={"reason": reason},
        )
        if self.sm.state == WatchdogState.RECOVERING:
            self.sm.fire(WatchdogEvent.FAULT)
        else:
            # operating state -> FAULT via RECOVERING (保持转换表合法性)
            self.sm.fire(WatchdogEvent.CRITICAL)
            self.sm.fire(WatchdogEvent.FAULT)

    def _register_failure(self, reason: str, config_error: Optional[str] = None) -> None:
        issues = [f"{i.component}: {i.message}" for i in self._last_report.issues] \
            if self._last_report else []
        if config_error:
            # 配置错误：不消耗自动恢复次数，直接 FAULT（人工修复配置）
            self._enter_fault(reason=f"CONFIG_ERROR: {config_error}")
            return
        self._consecutive_failures += 1
        self.bus.publish_event(
            EventType.AUTO_RECOVERY_FAILED, source="Watchdog",
            severity=Severity.ERROR,
            message=f"recovery failed ({reason}) "
                    f"{self._consecutive_failures}/{self.cfg.max_recovery_attempts}",
            data={"consecutive_failures": self._consecutive_failures,
                  "max": self.cfg.max_recovery_attempts, "issues": issues},
        )
        if self._consecutive_failures >= self.cfg.max_recovery_attempts:
            self._enter_fault(
                reason=f"{self.cfg.max_recovery_attempts} consecutive recovery failures")
        else:
            # stay in RECOVERING; cooldown applies before the next attempt
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
        """Split deployment: pick up commands written by the web manager."""
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
