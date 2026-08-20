"""Health checker tests — including the key requirement: processes alive
but S1 down must be CRITICAL."""
from app.models import HealthLevel, ServiceName, ServiceState, ServiceStatus
from app.watchdog.health import HealthChecker


class FakeProcess:
    def __init__(self, epc=ServiceState.RUNNING, enb=ServiceState.RUNNING):
        self.states = {ServiceName.EPC: epc, ServiceName.ENB: enb}

    def set(self, svc, state):
        self.states[svc] = state

    def _status(self, svc):
        return ServiceStatus(name=svc.value, state=self.states[svc])

    start = stop = restart = _status
    status = _status


class FakeUsrp:
    def __init__(self, connected=True):
        self.connected = connected

    def get_status(self):
        from app.models import UsrpStatus
        return UsrpStatus(connected=self.connected)


class FakeS1:
    def __init__(self, connected=True):
        self.connected = connected

    def get_status(self):
        from app.models import S1Status
        return S1Status(connected=self.connected)


class FakeSystem:
    def __init__(self, cpu=30.0, temp=50.0, mem=40.0, disk=40.0):
        self.cpu, self.temp, self.mem, self.disk = cpu, temp, mem, disk

    def get_metrics(self):
        from app.models import SystemMetrics
        return SystemMetrics(cpu_percent=self.cpu, cpu_temp_c=self.temp,
                             mem_percent=self.mem, disk_percent=self.disk)


def build_checker(process=None, usrp=None, s1=None, system=None, config=None):
    from app.config import AppConfig
    from app.providers.base import (ProcessManager, S1Provider,
                                    SystemMetricsProvider, UsrpProvider)

    class _P(FakeProcess, ProcessManager): pass

    class _U(FakeUsrp, UsrpProvider): pass

    class _S(FakeS1, S1Provider): pass

    class _Y(FakeSystem, SystemMetricsProvider): pass

    return HealthChecker(
        process or _P(), usrp or _U(), s1 or _S(), system or _Y(),
        config or AppConfig(),
    )


def test_all_healthy():
    report = build_checker().check()
    assert report.level == HealthLevel.OK
    assert not report.issues


def test_process_alive_but_s1_down_is_critical():
    """核心需求: 进程都在但 S1 断开 => 异常"""
    checker = build_checker(s1=FakeS1(connected=False))
    report = checker.check()
    assert report.level == HealthLevel.CRITICAL
    assert any(i.component == "S1" for i in report.issues)


def test_enb_down_is_critical():
    checker = build_checker(process=FakeProcess(enb=ServiceState.STOPPED))
    report = checker.check()
    assert report.level == HealthLevel.CRITICAL
    assert any(i.component == "ENB" for i in report.issues)


def test_epc_failed_is_critical():
    checker = build_checker(process=FakeProcess(epc=ServiceState.FAILED))
    report = checker.check()
    assert report.level == HealthLevel.CRITICAL
    assert any(i.component == "EPC" for i in report.issues)


def test_usrp_disconnected_is_critical():
    checker = build_checker(usrp=FakeUsrp(connected=False))
    report = checker.check()
    assert report.level == HealthLevel.CRITICAL
    assert any(i.component == "USRP" for i in report.issues)


def test_s1_down_while_enb_down_reports_both_not_duplicate_s1():
    """S1 down while eNB is down: the S1 issue is not the root cause,
    but critical level still holds."""
    checker = build_checker(process=FakeProcess(enb=ServiceState.STOPPED),
                            s1=FakeS1(connected=False))
    report = checker.check()
    assert report.level == HealthLevel.CRITICAL


def test_high_cpu_is_warning_not_critical():
    checker = build_checker(system=FakeSystem(cpu=95.0))
    report = checker.check()
    assert report.level == HealthLevel.WARNING
    assert report.is_healthy_for_recovery  # warnings don't block recovery


def test_high_temp_is_warning():
    checker = build_checker(system=FakeSystem(temp=90.0))
    report = checker.check()
    assert report.level == HealthLevel.WARNING


def test_high_memory_and_disk_are_warnings():
    checker = build_checker(system=FakeSystem(mem=92.0, disk=95.0))
    report = checker.check()
    assert report.level == HealthLevel.WARNING
    assert len([i for i in report.issues if i.level == HealthLevel.WARNING]) == 2
