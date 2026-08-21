"""State machine unit tests — log-event driven startup pipeline."""
from app.models import WatchdogState
from app.watchdog.state_machine import WatchdogEvent, WatchdogStateMachine


def test_initial_state_is_stopped():
    sm = WatchdogStateMachine()
    assert sm.state == WatchdogState.STOPPED


def test_start_stop_lifecycle():
    sm = WatchdogStateMachine()
    assert sm.fire(WatchdogEvent.START) == WatchdogState.STARTING
    assert sm.fire(WatchdogEvent.STOP) == WatchdogState.STOPPED


def test_stage_sync_drives_startup_path():
    """engine 依据日志聚合器沿启动路径推进（STARTING -> ... -> RUNNING）"""
    sm = WatchdogStateMachine()
    sm.fire(WatchdogEvent.START)
    assert sm.sync_to(WatchdogState.STARTING) == WatchdogState.STARTING
    assert sm.sync_to(WatchdogState.EPC_READY) == WatchdogState.EPC_READY
    assert sm.sync_to(WatchdogState.ENB_RF_INITIALIZING) == WatchdogState.ENB_RF_INITIALIZING
    assert sm.sync_to(WatchdogState.ENB_RUNNING) == WatchdogState.ENB_RUNNING
    assert sm.sync_to(WatchdogState.S1_CONNECTING) == WatchdogState.S1_CONNECTING
    assert sm.sync_to(WatchdogState.RUNNING) == WatchdogState.RUNNING


def test_stage_sync_is_idempotent_and_can_go_backwards():
    """eNB 重启时沿启动路径回退（RUNNING -> EPC_READY）"""
    sm = WatchdogStateMachine()
    sm.fire(WatchdogEvent.START)
    sm.sync_to(WatchdogState.RUNNING)
    assert sm.sync_to(WatchdogState.RUNNING) == WatchdogState.RUNNING  # idempotent
    assert sm.sync_to(WatchdogState.EPC_READY) == WatchdogState.EPC_READY  # eNB restart
    assert sm.sync_to(WatchdogState.RUNNING) == WatchdogState.RUNNING


def test_sync_rejected_in_controlled_states():
    sm = WatchdogStateMachine()
    assert sm.sync_to(WatchdogState.RUNNING) is None  # STOPPED: engine-controlled
    sm.fire(WatchdogEvent.START)
    sm.fire(WatchdogEvent.CRITICAL)
    assert sm.state == WatchdogState.RECOVERING
    assert sm.sync_to(WatchdogState.RUNNING) is None  # RECOVERING: no sync


def test_warning_degraded_side_states():
    sm = WatchdogStateMachine()
    sm.fire(WatchdogEvent.START)
    sm.sync_to(WatchdogState.RUNNING)
    assert sm.sync_to(WatchdogState.WARNING) == WatchdogState.WARNING
    assert sm.sync_to(WatchdogState.RUNNING) == WatchdogState.RUNNING
    assert sm.sync_to(WatchdogState.DEGRADED) == WatchdogState.DEGRADED  # S1_LOST
    assert sm.sync_to(WatchdogState.RUNNING) == WatchdogState.RUNNING


def test_critical_leads_to_recovering_from_every_operating_state():
    for target in (WatchdogState.STARTING, WatchdogState.EPC_READY,
                   WatchdogState.ENB_RF_INITIALIZING, WatchdogState.ENB_RUNNING,
                   WatchdogState.S1_CONNECTING, WatchdogState.RUNNING,
                   WatchdogState.WARNING, WatchdogState.DEGRADED):
        sm = WatchdogStateMachine()
        sm.fire(WatchdogEvent.START)
        sm.sync_to(target)
        assert sm.fire(WatchdogEvent.CRITICAL) == WatchdogState.RECOVERING, target


def test_recovery_outcomes():
    sm = WatchdogStateMachine()
    sm.fire(WatchdogEvent.START)
    sm.fire(WatchdogEvent.CRITICAL)
    # failed recovery keeps RECOVERING (retry after cooldown)
    assert sm.fire(WatchdogEvent.RECOVERY_FAIL) == WatchdogState.RECOVERING
    # successful recovery re-derives from the startup path
    assert sm.fire(WatchdogEvent.RECOVERY_OK) == WatchdogState.STARTING
    sm.sync_to(WatchdogState.RUNNING)


def test_fault_path():
    sm = WatchdogStateMachine()
    sm.fire(WatchdogEvent.START)
    sm.fire(WatchdogEvent.CRITICAL)
    assert sm.fire(WatchdogEvent.FAULT) == WatchdogState.FAULT
    # only manual reset or stop leave FAULT
    assert sm.fire(WatchdogEvent.CRITICAL) is None
    assert sm.fire(WatchdogEvent.RECOVERY_OK) is None
    assert sm.sync_to(WatchdogState.RUNNING) is None
    assert sm.fire(WatchdogEvent.RESET) == WatchdogState.STARTING


def test_ignored_events():
    sm = WatchdogStateMachine()
    assert sm.fire(WatchdogEvent.CRITICAL) is None     # STOPPED + CRITICAL invalid
    assert sm.fire(WatchdogEvent.RECOVERY_OK) is None  # STOPPED + RECOVERY_OK invalid
    assert sm.state == WatchdogState.STOPPED
    sm.fire(WatchdogEvent.START)
    assert sm.fire(WatchdogEvent.RECOVERY_OK) is None  # STARTING + RECOVERY_OK invalid


def test_stop_from_any_state():
    for target in (WatchdogState.STARTING, WatchdogState.RUNNING,
                   WatchdogState.WARNING, WatchdogState.DEGRADED):
        sm = WatchdogStateMachine()
        sm.fire(WatchdogEvent.START)
        sm.sync_to(target)
        assert sm.fire(WatchdogEvent.STOP) == WatchdogState.STOPPED, target


def test_transition_listener_and_history():
    sm = WatchdogStateMachine()
    seen = []
    sm.add_listener(lambda old, new, ev: seen.append((old.value, new.value, ev)))
    sm.fire(WatchdogEvent.START)
    sm.sync_to(WatchdogState.RUNNING)
    assert seen == [("STOPPED", "STARTING", "START"),
                    ("STARTING", "RUNNING", "SYNC")]
    history = sm.history()
    assert [h["to"] for h in history] == ["STARTING", "RUNNING"]
