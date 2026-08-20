"""State machine unit tests."""
from app.models import WatchdogState
from app.watchdog.state_machine import WatchdogEvent, WatchdogStateMachine


def test_initial_state_is_stopped():
    sm = WatchdogStateMachine()
    assert sm.state == WatchdogState.STOPPED


def test_normal_lifecycle():
    sm = WatchdogStateMachine()
    assert sm.fire(WatchdogEvent.START) == WatchdogState.STARTING
    assert sm.fire(WatchdogEvent.HEALTHY) == WatchdogState.RUNNING
    assert sm.fire(WatchdogEvent.WARNING) == WatchdogState.WARNING
    assert sm.fire(WatchdogEvent.HEALTHY) == WatchdogState.RUNNING
    assert sm.fire(WatchdogEvent.CRITICAL) == WatchdogState.RECOVERING
    assert sm.fire(WatchdogEvent.RECOVERY_OK) == WatchdogState.RUNNING
    assert sm.fire(WatchdogEvent.STOP) == WatchdogState.STOPPED


def test_fault_path():
    sm = WatchdogStateMachine()
    sm.fire(WatchdogEvent.START)
    sm.fire(WatchdogEvent.HEALTHY)
    sm.fire(WatchdogEvent.CRITICAL)
    assert sm.state == WatchdogState.RECOVERING
    # failed recovery keeps RECOVERING
    assert sm.fire(WatchdogEvent.RECOVERY_FAIL) == WatchdogState.RECOVERING
    assert sm.fire(WatchdogEvent.RECOVERY_FAIL) == WatchdogState.RECOVERING
    # engine decides fault
    assert sm.fire(WatchdogEvent.FAULT) == WatchdogState.FAULT
    # only manual reset or stop leave FAULT
    assert sm.fire(WatchdogEvent.HEALTHY) is None
    assert sm.fire(WatchdogEvent.CRITICAL) is None
    assert sm.fire(WatchdogEvent.RECOVERY_OK) is None
    assert sm.fire(WatchdogEvent.RESET) == WatchdogState.STARTING


def test_ignored_events():
    sm = WatchdogStateMachine()
    assert sm.fire(WatchdogEvent.HEALTHY) is None      # STOPPED + HEALTHY invalid
    assert sm.fire(WatchdogEvent.CRITICAL) is None     # STOPPED + CRITICAL invalid
    assert sm.state == WatchdogState.STOPPED
    sm.fire(WatchdogEvent.START)
    assert sm.fire(WatchdogEvent.RECOVERY_OK) is None  # STARTING + RECOVERY_OK invalid


def test_stop_from_any_state():
    sm = WatchdogStateMachine()
    for ev in (WatchdogEvent.START, WatchdogEvent.HEALTHY):
        sm.fire(ev)
    assert sm.state == WatchdogState.RUNNING
    assert sm.fire(WatchdogEvent.STOP) == WatchdogState.STOPPED


def test_transition_listener_and_history():
    sm = WatchdogStateMachine()
    seen = []
    sm.add_listener(lambda old, new, ev: seen.append((old.value, new.value, ev.value)))
    sm.fire(WatchdogEvent.START)
    sm.fire(WatchdogEvent.HEALTHY)
    assert seen == [("STOPPED", "STARTING", "START"), ("STARTING", "RUNNING", "HEALTHY")]
    history = sm.history()
    assert [h["to"] for h in history] == ["STARTING", "RUNNING"]
