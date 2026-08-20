"""Health checking.

CRITICAL (hard failures -> watchdog recovery):
  * srsEPC service not RUNNING
  * srsENB service not RUNNING
  * S1 disconnected while eNB+EPC processes are running
    (process-alive does NOT mean healthy — the key requirement)
  * USRP B210 disconnected

WARNING (soft, no restart):
  * CPU / memory / disk / temperature thresholds exceeded
"""
from __future__ import annotations

from app.config import AppConfig
from app.models import (
    HealthIssue,
    HealthLevel,
    HealthReport,
    ServiceName,
    ServiceState,
)
from app.providers.base import (
    ProcessManager,
    S1Provider,
    SystemMetricsProvider,
    UsrpProvider,
)


class HealthChecker:
    def __init__(
        self,
        process: ProcessManager,
        usrp: UsrpProvider,
        s1: S1Provider,
        system: SystemMetricsProvider,
        config: AppConfig,
    ) -> None:
        self._process = process
        self._usrp = usrp
        self._s1 = s1
        self._system = system
        self._cfg = config

    def check(self) -> HealthReport:
        issues: list[HealthIssue] = []

        epc = self._process.status(ServiceName.EPC)
        enb = self._process.status(ServiceName.ENB)
        epc_running = epc.state == ServiceState.RUNNING
        enb_running = enb.state == ServiceState.RUNNING

        if not epc_running:
            issues.append(HealthIssue(
                component="EPC", level=HealthLevel.CRITICAL,
                message=f"srsEPC not running (state={epc.state.value}, {epc.detail})"))
        if not enb_running:
            issues.append(HealthIssue(
                component="ENB", level=HealthLevel.CRITICAL,
                message=f"srsENB not running (state={enb.state.value}, {enb.detail})"))

        usrp = self._usrp.get_status()
        usrp_connected = usrp.connected
        if not usrp_connected:
            issues.append(HealthIssue(
                component="USRP", level=HealthLevel.CRITICAL,
                message=f"USRP B210 disconnected ({usrp.detail})"))

        s1 = self._s1.get_status()
        s1_connected = s1.connected
        if epc_running and enb_running and not s1_connected:
            # processes alive but S1 down => NOT healthy (核心判定)
            issues.append(HealthIssue(
                component="S1", level=HealthLevel.CRITICAL,
                message=f"S1 disconnected while eNB and EPC are running ({s1.detail})"))

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
                message=f"CPU temperature {metrics.cpu_temp_c}C >= {th.temperature_warning}C"))

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
            s1_connected=s1_connected,
            usrp_connected=usrp_connected,
        )
