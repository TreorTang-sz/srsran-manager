"""健康判定 —— 基于日志证据 + 进程状态 + 分阶段超时。

CRITICAL（触发恢复）：
  * srsEPC / srsENB 进程不在（systemd 非 active）
  * 启动阶段超时：EPC 未就绪 / eNB RF 未打开 / eNodeB 未 started /
    S1 未就绪 —— 每个阶段有独立超时（不再是统一 30s）
  * S1_LOST 超过 reconnect grace（先给 eNB 自行重连的机会）

CONFIG_ERROR（直接 FAULT，禁止自动重启）：
  * Couldn't open / Unrecognised options / unknown-PLMN / USRP 固件缺失
  —— 重启解决不了配置错误。

WARNING（只报警）：
  * CPU / 内存 / 磁盘 / 温度阈值
  注意：CPU 永远不作为 CRITICAL —— 50 PRB 时 eNB 单核 104% 属正常。

USRP 判定：运行期依据 eNB 日志（RF device opened / No UHD Devices
Found），uhd_find_devices 探测只作为辅助信息（eNB 持有设备时探测结果
不可靠）。
"""
from __future__ import annotations

import time

from app.config import AppConfig
from app.models import (
    EnbStage,
    EpcStage,
    HealthIssue,
    HealthLevel,
    HealthReport,
    S1State,
    ServiceName,
    ServiceState,
)
from app.providers.base import ProcessManager, SystemMetricsProvider
from app.watchdog.aggregator import LogStateAggregator


class HealthChecker:
    def __init__(
        self,
        process: ProcessManager,
        system: SystemMetricsProvider,
        aggregator: LogStateAggregator,
        config: AppConfig,
    ) -> None:
        self._process = process
        self._system = system
        self._agg = aggregator
        self._cfg = config

    def check(self) -> HealthReport:
        issues: list[HealthIssue] = []
        stage_timeout: str | None = None
        now = time.time()

        snap = self._agg.snapshot()
        epc = self._process.status(ServiceName.EPC)
        enb = self._process.status(ServiceName.ENB)
        # "Running" here means the service unit is alive: RUNNING (active)
        # or in transition (STARTING=activating / STOPPING=deactivating).
        # A unit in activating is NOT a crash — flagging it CRITICAL would
        # restart-loop during every (slow) srsRAN start.
        alive = (ServiceState.RUNNING, ServiceState.STARTING, ServiceState.STOPPING)
        epc_running = epc.state in alive
        enb_running = enb.state in alive

        # ---- CRITICAL: 进程不在 --------------------------------------
        if not epc_running:
            issues.append(HealthIssue(
                component="EPC", level=HealthLevel.CRITICAL,
                message=f"srsEPC not running (state={epc.state.value}, {epc.detail})"))
        if not enb_running:
            issues.append(HealthIssue(
                component="ENB", level=HealthLevel.CRITICAL,
                message=f"srsENB not running (state={enb.state.value}, {enb.detail})"))

        # ---- CONFIG_ERROR: 重启无意义 ---------------------------------
        config_error = snap.config_error
        if config_error:
            issues.append(HealthIssue(
                component="Config", level=HealthLevel.CRITICAL,
                message=f"configuration error: {config_error}"))

        # ---- RF 设备丢失（日志证据） -----------------------------------
        if enb_running and snap.usrp_log_error:
            issues.append(HealthIssue(
                component="USRP", level=HealthLevel.CRITICAL,
                message=f"USRP B210 problem in eNB logs: {snap.usrp_log_error}"))

        # ---- 启动阶段超时（分阶段，仅当对应进程在跑） -------------------
        st = self._cfg.watchdog.stages
        if epc_running:
            if snap.epc_stage != EpcStage.READY and \
                    now - snap.epc_stage_since > st.epc_ready_timeout:
                stage_timeout = "EPC_READY"
                issues.append(HealthIssue(
                    component="EPC", level=HealthLevel.CRITICAL,
                    message=f"EPC not ready in {st.epc_ready_timeout:.0f}s "
                            f"(stage={snap.epc_stage.value})"))
        if enb_running:
            if snap.enb_stage == EnbStage.DOWN:
                if now - snap.enb_stage_since > st.enb_rf_timeout:
                    stage_timeout = stage_timeout or "ENB_LOG"
                    issues.append(HealthIssue(
                        component="ENB", level=HealthLevel.CRITICAL,
                        message=f"no eNB startup logs in {st.enb_rf_timeout:.0f}s "
                                f"(journal empty or eNB stuck before banner)"))
            elif snap.enb_stage in (EnbStage.STARTING, EnbStage.CONFIG_LOADING):
                if now - snap.enb_stage_since > st.enb_rf_timeout:
                    stage_timeout = stage_timeout or "ENB_RF"
                    issues.append(HealthIssue(
                        component="ENB", level=HealthLevel.CRITICAL,
                        message=f"eNB RF not opened in {st.enb_rf_timeout:.0f}s "
                                f"(stage={snap.enb_stage.value})"))
            elif snap.enb_stage == EnbStage.RF_READY:
                if now - snap.enb_stage_since > st.enb_running_timeout:
                    stage_timeout = stage_timeout or "ENB_RUNNING"
                    issues.append(HealthIssue(
                        component="ENB", level=HealthLevel.CRITICAL,
                        message=f"'eNodeB started' not seen in "
                                f"{st.enb_running_timeout:.0f}s"))

        # ---- S1 状态机 -------------------------------------------------
        if epc_running and enb_running:
            if snap.s1_state == S1State.S1_DOWN and snap.enb_stage == EnbStage.RUNNING:
                # eNB 已 started 但 EPC 从未见过 S1 Setup Request
                if now - snap.enb_stage_since > st.s1_ready_timeout:
                    stage_timeout = stage_timeout or "S1_SETUP"
                    issues.append(HealthIssue(
                        component="S1", level=HealthLevel.CRITICAL,
                        message=f"S1 setup not seen in {st.s1_ready_timeout:.0f}s "
                                f"after eNodeB started"))
            elif snap.s1_state == S1State.S1_CONNECTING:
                if now - snap.s1_state_since > st.s1_ready_timeout:
                    stage_timeout = stage_timeout or "S1_RESPONSE"
                    issues.append(HealthIssue(
                        component="S1", level=HealthLevel.CRITICAL,
                        message=f"S1 Setup Response not sent in "
                                f"{st.s1_ready_timeout:.0f}s"))
            elif snap.s1_state == S1State.S1_LOST:
                # grace: eNB 可能自行重连（SCTP Shutdown != 启动失败）
                if now - snap.s1_state_since > st.s1_reconnect_grace:
                    issues.append(HealthIssue(
                        component="S1", level=HealthLevel.CRITICAL,
                        message=f"S1 lost (SCTP shutdown) and not re-established "
                                f"in {st.s1_reconnect_grace:.0f}s"))
                else:
                    issues.append(HealthIssue(
                        component="S1", level=HealthLevel.WARNING,
                        message="S1 lost (SCTP shutdown) — waiting for eNB "
                                "to re-connect"))
            # S1_READY / S1_CONFIG_ERROR: 后者已由 config_error 覆盖

        # ---- WARNING: 资源阈值（CPU 永远不 CRITICAL） -------------------
        metrics = self._system.get_metrics()
        th = self._cfg.thresholds
        if metrics.cpu_percent >= th.cpu_warning:
            issues.append(HealthIssue(
                component="System", level=HealthLevel.WARNING,
                message=f"CPU usage {metrics.cpu_percent}% >= {th.cpu_warning}%"))
        if metrics.mem_percent >= th.memory_warning:
            issues.append(HealthIssue(
                component="System", level=HealthLevel.WARNING,
                message=f"Memory usage {metrics.mem_percent}% >= {th.memory_warning}%"))
        if metrics.disk_percent >= th.disk_warning:
            issues.append(HealthIssue(
                component="System", level=HealthLevel.WARNING,
                message=f"Disk usage {metrics.disk_percent}% >= {th.disk_warning}%"))
        if metrics.cpu_temp_c is not None and metrics.cpu_temp_c >= th.temperature_warning:
            issues.append(HealthIssue(
                component="System", level=HealthLevel.WARNING,
                message=f"CPU temperature {metrics.cpu_temp_c}C >= "
                        f"{th.temperature_warning}C"))

        if any(i.level == HealthLevel.CRITICAL for i in issues):
            level = HealthLevel.CRITICAL
        elif issues:
            level = HealthLevel.WARNING
        else:
            level = HealthLevel.OK

        return HealthReport(
            level=level,
            issues=issues,
            epc_running=epc_running,
            enb_running=enb_running,
            epc_stage=snap.epc_stage,
            enb_stage=snap.enb_stage,
            s1_state=snap.s1_state,
            config_error=config_error,
            stage_timeout=stage_timeout,
        )
