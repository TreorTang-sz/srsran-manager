"""Recovery strategies — log-aware, minimal-blast-radius.

一次恢复尝试是固定的预定义动作序列（仅 start/stop/restart via
ProcessManager —— 系统中唯一允许的操作，不执行任意命令）。

策略（按序判定，只动真正故障的部分）：
  1. CONFIG_ERROR       -> 不动作（重启无意义），返回失败交由 engine 进 FAULT
  2. EPC 进程不在        -> restart EPC（连带重置 EPC/S1 日志状态），
                            等待 EPC READY
  3. S1_LOST（曾就绪后断开）-> 只 restart eNB（不是启动失败，不动 EPC）
  4. eNB 进程不在 / RF 未打开 / eNodeB 未 started / S1 未建立
                        -> restart eNB
  等待验证改为轮询（verify_delay 为上限）：期间持续 pump 日志，
  eNB 的 RF 初始化 / S1 协商一旦完成即提前返回成功。
"""
from __future__ import annotations

import logging
import time

from app.config import AppConfig
from app.core.bus import EventBus
from app.models import (
    EnbStage,
    EpcStage,
    EventType,
    ServiceName,
    Severity,
    S1State,
)
from app.providers.base import ProcessManager
from app.watchdog.aggregator import LogStateAggregator
from app.watchdog.health import HealthChecker
from app.watchdog.pipeline import LogPipeline

logger = logging.getLogger("srsran.recovery")


class RecoveryManager:
    def __init__(self, process: ProcessManager, health: HealthChecker,
                 bus: EventBus, config: AppConfig,
                 aggregator: LogStateAggregator,
                 pipeline: LogPipeline) -> None:
        self._process = process
        self._health = health
        self._bus = bus
        self._cfg = config
        self._agg = aggregator
        self._pipeline = pipeline

    # ------------------------------------------------------------------
    def start_network(self, force_restart: bool = False) -> None:
        """Idempotent start: EPC first, then eNB.

        不 reset 聚合器：banner 日志事件自带状态回滚（ENB_BANNER /
        EPC_BANNER 会重走启动链），主动 reset 反而会丢掉已消费的日志
        证据（幂等 start 不会重新产生 banner）。

        force_restart=True（FAULT 人工复位）：重启两个单元，强制产生
        新的启动 banner，聚合器从新日志完整重建。
        """
        op = self._process.restart if force_restart else self._process.start
        op(ServiceName.EPC)
        self._bus.publish_event(EventType.EPC_STARTED, source="Watchdog",
                                message="srsEPC start issued", data={"action": "start"})
        op(ServiceName.ENB)
        self._bus.publish_event(EventType.ENB_STARTED, source="Watchdog",
                                message="srsENB start issued", data={"action": "start"})

    # ------------------------------------------------------------------
    def _wait_for(self, predicate, timeout: float, what: str) -> bool:
        """轮询等待条件成立（期间持续 pump 日志推进聚合器）。

        恢复等待期间一旦出现配置错误（如 S1 Setup Failure unknown-PLMN）
        立即中止 —— 继续等待/重启毫无意义，交由 engine 直接进 FAULT。
        """
        deadline = time.time() + timeout
        interval = min(0.5, max(self._cfg.watchdog.check_interval, 0.05))
        while time.time() < deadline:
            self._pipeline.pump()
            if predicate():
                return True
            if self._agg.config_error:
                logger.warning("recovery wait '%s' aborted: config error (%s)",
                               what, self._agg.config_error)
                return False
            time.sleep(interval)
        return predicate()

    def _s1_ready(self) -> bool:
        snap = self._agg.snapshot()
        return (snap.epc_stage == EpcStage.READY
                and snap.enb_stage == EnbStage.RUNNING
                and snap.s1_state == S1State.S1_READY)

    # ------------------------------------------------------------------
    def execute(self) -> tuple[bool, object]:
        """One recovery attempt. Returns (success, final_report)."""
        report = self._health.check()
        st = self._cfg.watchdog.stages
        verify = self._cfg.watchdog.verify_delay

        # 1) 配置错误：不重启，交给 engine 直接 FAULT
        if report.config_error:
            logger.warning("recovery skipped: config error (%s)", report.config_error)
            return False, report

        acted = False

        # 2) EPC down -> restart EPC, wait EPC READY
        if not report.epc_running:
            logger.warning("recovery: restarting srsEPC")
            self._agg.reset_service("epc")
            self._process.restart(ServiceName.EPC)
            self._bus.publish_event(EventType.EPC_STARTED, source="Watchdog",
                                    severity=Severity.WARNING,
                                    message="srsEPC restarted (recovery)",
                                    data={"action": "restart", "reason": "epc_down"})
            acted = True
            self._wait_for(
                lambda: self._agg.epc_stage == EpcStage.READY,
                max(verify, st.epc_ready_timeout), "EPC READY")
            # EPC 重启后 S1 必然断开；真实 srsENB 会自行重跑 S1 setup
            # —— 先等 eNB 自动重连，不要盲目重启 eNB
            self._wait_for(
                self._s1_ready,
                max(verify, st.s1_ready_timeout + st.s1_reconnect_grace),
                "S1 re-established after EPC restart")
            report = self._health.check()

        # 3) S1_LOST（曾就绪后 SCTP Shutdown）-> 只重启 eNB
        s1_lost = self._agg.s1_state == S1State.S1_LOST

        # 4) eNB 侧问题 -> restart eNB
        need_enb = (not report.enb_running
                    or report.enb_stage not in (EnbStage.RUNNING,)
                    or report.s1_state != S1State.S1_READY)
        if need_enb:
            reason = ("enb_down" if not report.enb_running
                      else "s1_lost" if s1_lost
                      else "enb_stage_incomplete" if report.enb_stage != EnbStage.RUNNING
                      else "s1_not_ready")
            logger.warning("recovery: restarting srsENB (stage=%s s1=%s reason=%s)",
                           report.enb_stage.value, report.s1_state.value, reason)
            self._agg.reset_service("enb")
            self._process.restart(ServiceName.ENB)
            self._bus.publish_event(EventType.ENB_STARTED, source="Watchdog",
                                    severity=Severity.WARNING,
                                    message=f"srsENB restarted (recovery, {reason})",
                                    data={"action": "restart", "reason": reason})
            acted = True
            # 等待完整启动链: RF opened -> eNodeB started -> S1 READY
            timeout = max(verify,
                          st.enb_rf_timeout + st.enb_running_timeout + st.s1_ready_timeout)
            self._wait_for(self._s1_ready, timeout, "eNB + S1 ready")
            report = self._health.check()

        if not acted:
            # 已经自行恢复（例如 eNB 自动重连成功）—— 复核一次
            self._wait_for(self._s1_ready, min(verify, 2.0), "self-recovered")
            report = self._health.check()

        return report.is_healthy_for_recovery, report
