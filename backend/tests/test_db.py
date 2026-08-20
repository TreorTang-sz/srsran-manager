"""Database (SQLite) tests: events, logs, kv_state, watchdog status persistence."""
from __future__ import annotations

from app.database.models import StateStore
from app.models import EventRecord, EventType, LogRecord, Severity


def test_event_roundtrip(runtime):
    record = runtime.bus.publish_event(
        type=EventType.ENB_CRASH, source="ENB", severity=Severity.ERROR,
        message="srsENB crashed", data={"reason": "segfault"})
    assert record.id is None  # bus record has no id; persister assigns one
    stored = runtime.event_store.query_events(limit=10)
    assert any(r.type == EventType.ENB_CRASH and r.message == "srsENB crashed" for r in stored)
    match = [r for r in stored if r.type == EventType.ENB_CRASH][0]
    assert match.id is not None
    assert match.data == {"reason": "segfault"}
    assert match.severity == Severity.ERROR


def test_event_filters(runtime):
    runtime.bus.publish_event(EventType.UE_ATTACHED, "ENB", message="ue1")
    runtime.bus.publish_event(EventType.UE_DETACHED, "ENB", message="ue1 gone")
    only_attach = runtime.event_store.query_events(type=EventType.UE_ATTACHED, limit=10)
    assert only_attach and all(r.type == EventType.UE_ATTACHED for r in only_attach)


def test_log_roundtrip(runtime):
    runtime.bus.publish_log("WARNING", "srsran.watchdog", "eNB unhealthy, starting recovery")
    logs = runtime.log_store.query_logs(limit=10)
    assert any(l.module == "srsran.watchdog" and l.level == "WARNING" for l in logs)
    filtered = runtime.log_store.query_logs(level="WARNING", limit=10)
    assert filtered and all(l.level == "WARNING" for l in filtered)


def test_kv_state_store(runtime):
    store = StateStore(runtime.db)
    store.set_state("desired_running", True)
    assert store.get_state("desired_running") is True
    store.set_state("desired_running", False)
    assert store.get_state("desired_running") is False
    assert store.get_state("missing") is None


def test_watchdog_status_persisted_when_engine_ticks(runtime):
    runtime.control.start_network()
    from tests.conftest import wait_for
    assert wait_for(lambda: runtime.state_store.get_state("watchdog_status") is not None,
                    timeout=3)
    data = runtime.state_store.get_state("watchdog_status")
    assert "state" in data
    assert "consecutive_failures" in data
