"""Watchdog end-to-end tests in the mock environment.

Covers: normal startup, eNB crash recovery, EPC crash recovery,
S1 disconnect recovery, USRP disconnect -> FAULT (max attempts),
recover-fail then success, manual reset from FAULT.
"""
from __future__ import annotations

from app.models import EventType, ServiceName, WatchdogState
from tests.conftest import find_event, wait_for


def start_and_wait_running(runtime):
    runtime.control.start_network()
    assert wait_for(lambda: runtime.sm.state == WatchdogState.RUNNING, timeout=6), \
        f"expected RUNNING, got {runtime.sm.state}"
    assert wait_for(lambda: runtime.snapshot().s1.connected, timeout=3)


def test_normal_startup_reaches_running(runtime):
    start_and_wait_running(runtime)
    snap = runtime.snapshot()
    assert snap.services["epc"].state.value == "RUNNING"
    assert snap.services["enb"].state.value == "RUNNING"
    assert snap.s1.connected
    assert snap.usrp.connected
    assert find_event(runtime, EventType.SYSTEM_START)


def test_auto_start_on_boot(tmp_path):
    """无人值守: auto_start=True 时启动即自动拉起网络, 无需人工干预"""
    from app.runtime import Runtime
    from tests.conftest import make_config

    cfg = make_config(tmp_path)
    cfg.watchdog.auto_start = True
    rt = Runtime(cfg)
    try:
        rt.start()  # no explicit start_network() call
        assert wait_for(lambda: rt.sm.state == WatchdogState.RUNNING, timeout=6), \
            f"expected RUNNING via auto-start, got {rt.sm.state}"
        # snapshot 由 monitor 周期采样, 滞后于状态机 — 等待快照追上
        assert wait_for(lambda: rt.snapshot().s1.connected, timeout=3)
    finally:
        rt.stop()


def test_enb_crash_triggers_recovery(runtime):
    start_and_wait_running(runtime)
    runtime.faults.inject("enb-crash")
    # watchdog: CRITICAL -> RECOVERING -> restart -> RUNNING
    assert wait_for(lambda: runtime.sm.state == WatchdogState.RECOVERING, timeout=3), \
        f"expected RECOVERING, got {runtime.sm.state}"
    assert wait_for(lambda: runtime.sm.state == WatchdogState.RUNNING, timeout=6), \
        f"expected RUNNING after recovery, got {runtime.sm.state}"
    assert find_event(runtime, EventType.ENB_CRASH)
    assert find_event(runtime, EventType.AUTO_RECOVERY_SUCCESS)
    assert runtime.engine.consecutive_failures == 0


def test_epc_crash_triggers_recovery(runtime):
    start_and_wait_running(runtime)
    runtime.faults.inject("epc-crash")
    assert wait_for(lambda: runtime.sm.state == WatchdogState.RECOVERING, timeout=3)
    assert wait_for(lambda: runtime.sm.state == WatchdogState.RUNNING, timeout=6)
    assert find_event(runtime, EventType.EPC_CRASH)
    assert find_event(runtime, EventType.AUTO_RECOVERY_SUCCESS)


def test_s1_disconnect_with_processes_alive_is_recovered(runtime):
    """关键场景: eNB/EPC 进程都在, S1 断开 -> 看门狗恢复"""
    start_and_wait_running(runtime)
    runtime.faults.inject("s1-down")
    snap = runtime.snapshot()
    assert snap.services["enb"].state.value == "RUNNING"
    assert snap.services["epc"].state.value == "RUNNING"
    assert wait_for(lambda: not runtime.snapshot().s1.connected, timeout=3)
    assert wait_for(lambda: runtime.sm.state == WatchdogState.RECOVERING, timeout=3)
    # restarting eNB re-establishes S1 (mock semantics)
    assert wait_for(lambda: runtime.sm.state == WatchdogState.RUNNING, timeout=6)
    assert find_event(runtime, EventType.S1_DISCONNECTED)
    assert find_event(runtime, EventType.AUTO_RECOVERY_SUCCESS)


def test_usrp_disconnect_leads_to_fault_after_max_attempts(runtime):
    """B210 拔出 (sticky fault): 3 次恢复失败后进入 FAULT, 禁止无限重启"""
    start_and_wait_running(runtime)
    runtime.faults.inject("usrp-down")

    assert wait_for(lambda: runtime.sm.state == WatchdogState.FAULT, timeout=15), \
        f"expected FAULT, got {runtime.sm.state}"
    assert runtime.engine.consecutive_failures >= runtime.engine.cfg.max_recovery_attempts
    assert find_event(runtime, EventType.USRP_DISCONNECTED)
    assert find_event(runtime, EventType.AUTO_RECOVERY_FAILED)
    assert find_event(runtime, EventType.FAULT_ENTERED)

    # FAULT is terminal: watchdog stops recovering
    failures = runtime.engine.consecutive_failures
    import time as _t
    _t.sleep(0.5)
    assert runtime.sm.state == WatchdogState.FAULT
    assert runtime.engine.consecutive_failures == failures

    # manual reset: clear fault + restart network
    runtime.faults.clear()
    runtime.control.start_network()
    assert wait_for(lambda: runtime.sm.state == WatchdogState.RUNNING, timeout=8), \
        f"expected RUNNING after manual reset, got {runtime.sm.state}"
    assert runtime.engine.consecutive_failures == 0


def test_recover_fail_then_success(runtime):
    """前 2 次恢复失败, 第 3 次成功 -> RUNNING (未超过最大次数)"""
    start_and_wait_running(runtime)
    runtime.faults.inject("recover-fail", times=2)
    runtime.faults.inject("enb-crash")

    assert wait_for(lambda: runtime.sm.state == WatchdogState.RECOVERING, timeout=3)
    # first two attempts fail (service goes FAILED)
    assert wait_for(lambda: runtime.engine.consecutive_failures >= 2, timeout=15)
    # third attempt succeeds
    assert wait_for(lambda: runtime.sm.state == WatchdogState.RUNNING, timeout=15), \
        f"expected RUNNING after 3rd attempt, got {runtime.sm.state}"
    assert runtime.engine.consecutive_failures == 0
    assert find_event(runtime, EventType.AUTO_RECOVERY_FAILED)
    assert find_event(runtime, EventType.AUTO_RECOVERY_SUCCESS)


def test_manual_stop_disables_watchdog_recovery(runtime):
    start_and_wait_running(runtime)
    runtime.control.stop_network()
    assert wait_for(lambda: runtime.sm.state == WatchdogState.STOPPED, timeout=3)
    # fault while stopped: watchdog must NOT restart services
    runtime.faults.inject("enb-crash")
    import time as _t
    _t.sleep(1.0)
    assert runtime.sm.state == WatchdogState.STOPPED
    assert runtime.snapshot().services["enb"].state.value != "RUNNING"


def test_events_persisted_to_sqlite(runtime):
    start_and_wait_running(runtime)
    records = runtime.event_store.query_events(limit=50)
    types = {r.type for r in records}
    assert EventType.SYSTEM_START in types
    assert EventType.EPC_STARTED in types
    assert EventType.ENB_STARTED in types
    assert EventType.S1_CONNECTED in types
