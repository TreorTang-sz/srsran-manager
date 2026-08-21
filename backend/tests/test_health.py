"""Health checker tests — log evidence + process state + staged timeouts.

核心判定原则（与真实 srsRAN 行为对齐）：
  * 进程 RUNNING 不等于正常 —— 组件阶段必须来自日志证据
  * S1_LOST（SCTP Shutdown 后）先给 grace 再判 CRITICAL
  * CONFIG_ERROR（unknown-PLMN 等）单列，不触发自动重启
  * CPU 高负载只 WARNING，永不 CRITICAL（50PRB 单核 104% 属正常）
"""
from __future__ import annotations

import time

from app.config import AppConfig
from app.models import (
    EnbStage,
    EpcStage,
    HealthLevel,
    S1State,
    ServiceName,
    ServiceState,
    ServiceStatus,
    SystemMetrics,
)
from app.watchdog.aggregator import LogStateAggregator
from app.watchdog.health import HealthChecker
from app.watchdog.log_events import LogEventParser


# ---------------------------------------------------------------------------
# fakes
# ---------------------------------------------------------------------------
class FakeProcess:
    def __init__(self, epc=ServiceState.RUNNING, enb=ServiceState.RUNNING):
        self.states = {ServiceName.EPC: epc, ServiceName.ENB: enb}

    def set(self, svc, state):
        self.states[svc] = state

    def _status(self, svc):
        return ServiceStatus(name=svc.value, state=self.states[svc])

    start = stop = restart = _status
    status = _status


class FakeSystem:
    def __init__(self, cpu=30.0, temp=50.0, mem=40.0, disk=40.0):
        self.cpu, self.temp, self.mem, self.disk = cpu, temp, mem, disk

    def get_metrics(self):
        return SystemMetrics(cpu_percent=self.cpu, cpu_temp_c=self.temp,
                             mem_percent=self.mem, disk_percent=self.disk)


# ---------------------------------------------------------------------------
# helpers: feed REAL srsRAN log lines through the parser into the aggregator
# ---------------------------------------------------------------------------
ENB_STARTUP = [
    "---  Software Radio Systems LTE eNodeB  ---",
    "Reading configuration file /etc/srsran/enb.conf...",
    "RF device 'UHD' successfully opened",
    "==== eNodeB started ===",
    "Setting frequency: DL=875.0 Mhz, UL=830.0 MHz for cc_idx=0 nof_prb=25",
]

EPC_STARTUP = [
    "---  Software Radio Systems EPC  ---",
    "HSS Initialized.",
    "MME S11 Initialized",
    "MME GTP-C Initialized",
    "MME Initialized.",
    "SPGW GTP-U Initialized.",
    "SPGW S11 Initialized.",
    "SP-GW Initialized.",
]

S1_SETUP = [
    "Received S1 Setup Request.",
    "S1 Setup Request - eNB Name: srsenb01, eNB id: 0x19b",
    "Sending S1 Setup Response",
]


def feed(agg: LogStateAggregator, service: str, lines: list[str]) -> None:
    parser = LogEventParser()
    now = time.time()
    events = [parser.parse(service, now, line) for line in lines]
    agg.apply([ev for ev in events if ev is not None])


def feed_full_startup(agg: LogStateAggregator) -> None:
    feed(agg, "epc", EPC_STARTUP)
    feed(agg, "enb", ENB_STARTUP)
    feed(agg, "epc", S1_SETUP)


def age(agg: LogStateAggregator, **seconds) -> None:
    """Push stage timestamps into the past to simulate a hang."""
    with agg._lock:
        for field, delta in seconds.items():
            setattr(agg._s, field, time.time() - delta)


def build_checker(process=None, system=None, config=None, agg=None):
    return HealthChecker(
        process or FakeProcess(),
        system or FakeSystem(),
        agg or LogStateAggregator(),
        config or AppConfig(),
    )


# ---------------------------------------------------------------------------
# healthy path
# ---------------------------------------------------------------------------
def test_all_healthy_when_full_startup_chain_seen():
    agg = LogStateAggregator()
    feed_full_startup(agg)
    report = build_checker(agg=agg).check()
    assert report.level == HealthLevel.OK
    assert not report.issues
    assert report.enb_stage == EnbStage.RUNNING
    assert report.epc_stage == EpcStage.READY
    assert report.s1_state == S1State.S1_READY


def test_processes_alive_but_no_log_evidence_is_not_ok():
    """进程 RUNNING 不等于正常：日志无证据时由阶段超时兜底。"""
    report = build_checker().check()  # aggregator empty, processes RUNNING
    # fresh timestamps -> no timeout yet, but stages are not ready either;
    # level stays OK only while within grace of each stage timeout
    assert report.enb_stage == EnbStage.DOWN
    assert report.epc_stage == EpcStage.DOWN


# ---------------------------------------------------------------------------
# process failures
# ---------------------------------------------------------------------------
def test_enb_down_is_critical():
    agg = LogStateAggregator()
    feed_full_startup(agg)
    report = build_checker(process=FakeProcess(enb=ServiceState.STOPPED),
                           agg=agg).check()
    assert report.level == HealthLevel.CRITICAL
    assert any(i.component == "ENB" for i in report.issues)


def test_epc_failed_is_critical():
    agg = LogStateAggregator()
    feed_full_startup(agg)
    report = build_checker(process=FakeProcess(epc=ServiceState.FAILED),
                           agg=agg).check()
    assert report.level == HealthLevel.CRITICAL
    assert any(i.component == "EPC" for i in report.issues)


# ---------------------------------------------------------------------------
# staged startup timeouts
# ---------------------------------------------------------------------------
def test_epc_not_ready_timeout_is_critical():
    agg = LogStateAggregator()
    feed(agg, "epc", ["---  Software Radio Systems EPC  ---"])  # banner only
    age(agg, epc_stage_since=46)
    report = build_checker(agg=agg).check()
    assert report.level == HealthLevel.CRITICAL
    assert report.stage_timeout == "EPC_READY"


def test_enb_rf_not_opened_timeout_is_critical():
    agg = LogStateAggregator()
    feed(agg, "epc", EPC_STARTUP)
    feed(agg, "enb", [
        "---  Software Radio Systems LTE eNodeB  ---",
        "Reading configuration file /etc/srsran/enb.conf...",
    ])  # stuck in CONFIG_LOADING
    age(agg, enb_stage_since=181)  # > enb_rf_timeout 默认 180s
    report = build_checker(agg=agg).check()
    assert report.level == HealthLevel.CRITICAL
    assert report.stage_timeout == "ENB_RF"


def test_enb_not_started_timeout_is_critical():
    agg = LogStateAggregator()
    feed(agg, "epc", EPC_STARTUP)
    feed(agg, "enb", [
        "---  Software Radio Systems LTE eNodeB  ---",
        "Reading configuration file /etc/srsran/enb.conf...",
        "RF device 'UHD' successfully opened",
    ])  # RF ready but never "eNodeB started"
    age(agg, enb_stage_since=61)
    report = build_checker(agg=agg).check()
    assert report.level == HealthLevel.CRITICAL
    assert report.stage_timeout == "ENB_RUNNING"


def test_s1_setup_not_seen_timeout_is_critical():
    agg = LogStateAggregator()
    feed(agg, "epc", EPC_STARTUP)
    feed(agg, "enb", ENB_STARTUP)  # eNB started but EPC never saw S1 request
    age(agg, enb_stage_since=31)
    report = build_checker(agg=agg).check()
    assert report.level == HealthLevel.CRITICAL
    assert report.stage_timeout == "S1_SETUP"


def test_s1_connecting_timeout_is_critical():
    agg = LogStateAggregator()
    feed_full_startup(agg)
    feed(agg, "epc", ["SCTP Association Shutdown. Association: 4"])  # LOST
    feed(agg, "epc", ["Received S1 Setup Request."])  # reconnecting
    age(agg, s1_state_since=31)
    report = build_checker(agg=agg).check()
    assert report.level == HealthLevel.CRITICAL
    assert report.stage_timeout == "S1_RESPONSE"


# ---------------------------------------------------------------------------
# S1_LOST semantics (SCTP shutdown after READY != startup failure)
# ---------------------------------------------------------------------------
def test_s1_lost_within_grace_is_warning():
    agg = LogStateAggregator()
    feed_full_startup(agg)
    feed(agg, "epc", ["SCTP Association Shutdown. Association: 4"])
    assert agg.s1_state == S1State.S1_LOST
    report = build_checker(agg=agg).check()
    assert report.level == HealthLevel.WARNING
    assert report.is_healthy_for_recovery  # grace 内不触发恢复


def test_s1_lost_beyond_grace_is_critical():
    agg = LogStateAggregator()
    feed_full_startup(agg)
    feed(agg, "epc", ["SCTP Association Shutdown. Association: 4"])
    age(agg, s1_state_since=11)  # grace default 10s
    report = build_checker(agg=agg).check()
    assert report.level == HealthLevel.CRITICAL
    assert any(i.component == "S1" for i in report.issues)


# ---------------------------------------------------------------------------
# config errors (restart is pointless)
# ---------------------------------------------------------------------------
def test_unknown_plmn_is_config_error():
    agg = LogStateAggregator()
    feed_full_startup(agg)
    feed(agg, "epc", ["S1 Setup Failure cause: misc - unknown-PLMN"])
    report = build_checker(agg=agg).check()
    assert report.config_error
    assert "unknown-PLMN" in report.config_error
    assert report.s1_state == S1State.S1_CONFIG_ERROR


def test_usrp_firmware_missing_is_config_error():
    agg = LogStateAggregator()
    feed(agg, "enb", ["Could not find usrp_b200_fw.hex!"])
    report = build_checker(agg=agg).check()
    assert report.config_error and "usrp_b200_fw.hex" in report.config_error


def test_unrecognised_options_is_config_error():
    agg = LogStateAggregator()
    feed(agg, "enb", ["Unrecognised options: some_new_option"])
    report = build_checker(agg=agg).check()
    assert report.config_error and "Unrecognised" in report.config_error


# ---------------------------------------------------------------------------
# USRP runtime errors (log evidence, not uhd_find_devices)
# ---------------------------------------------------------------------------
def test_no_uhd_devices_in_log_is_critical():
    agg = LogStateAggregator()
    feed_full_startup(agg)
    feed(agg, "enb", ["No UHD Devices Found"])
    report = build_checker(agg=agg).check()
    assert report.level == HealthLevel.CRITICAL
    assert any(i.component == "USRP" for i in report.issues)


# ---------------------------------------------------------------------------
# resource thresholds — CPU never CRITICAL
# ---------------------------------------------------------------------------
def test_high_cpu_is_warning_not_critical():
    agg = LogStateAggregator()
    feed_full_startup(agg)
    report = build_checker(system=FakeSystem(cpu=104.0), agg=agg).check()
    assert report.level == HealthLevel.WARNING
    assert report.is_healthy_for_recovery  # warnings don't block recovery


def test_high_temp_is_warning():
    agg = LogStateAggregator()
    feed_full_startup(agg)
    report = build_checker(system=FakeSystem(temp=90.0), agg=agg).check()
    assert report.level == HealthLevel.WARNING


def test_high_memory_and_disk_are_warnings():
    agg = LogStateAggregator()
    feed_full_startup(agg)
    report = build_checker(system=FakeSystem(mem=92.0, disk=95.0), agg=agg).check()
    assert report.level == HealthLevel.WARNING
    assert len([i for i in report.issues if i.level == HealthLevel.WARNING]) == 2
