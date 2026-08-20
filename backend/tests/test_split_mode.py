"""Split-deployment (manager-only web process) coordination tests.

In split mode the watchdog runs in a separate process; the web manager
coordinates through the shared SQLite kv_state table.
"""
from __future__ import annotations

from app.models import ServiceName, ServiceState, WatchdogState
from app.runtime import Runtime
from tests.conftest import make_config, wait_for


def make_manager_only_config(tmp_path):
    cfg = make_config(tmp_path)
    cfg.watchdog.run_watchdog = False   # manager-only: no in-process engine
    cfg.watchdog.auto_start = False
    return cfg


def test_control_works_without_engine(tmp_path):
    """Web control must not crash when the engine runs in another process."""
    rt = Runtime(make_manager_only_config(tmp_path))
    try:
        rt.start()
        assert rt.engine is None

        result = rt.control.start_network()
        assert "issued" in result["result"]
        assert rt.state_store.get_state("desired_running") is True
        assert wait_for(
            lambda: rt.providers.process.status(ServiceName.ENB).state == ServiceState.RUNNING,
            timeout=3)

        rt.control.stop_network()
        assert rt.state_store.get_state("desired_running") is False
        assert wait_for(
            lambda: rt.providers.process.status(ServiceName.ENB).state == ServiceState.STOPPED,
            timeout=3)
    finally:
        rt.stop()


def test_watchdog_adopts_desired_state_from_store(tmp_path):
    """The watchdog engine picks up desired_running written by the manager."""
    # 1. manager-only process writes desired_running=True
    mgr = Runtime(make_manager_only_config(tmp_path))
    mgr.start()
    try:
        mgr.control.start_network()
    finally:
        mgr.stop()  # keep kv_state + running mock services

    # 2. full runtime (watchdog present) must adopt the stored desired state
    cfg = make_config(tmp_path)
    cfg.watchdog.auto_start = False
    rt = Runtime(cfg)
    try:
        rt.start()
        assert rt.engine is not None
        assert rt.engine.desired_running is True, "engine should sync from store"
        assert wait_for(lambda: rt.sm.state == WatchdogState.RUNNING, timeout=6), \
            f"expected RUNNING, got {rt.sm.state}"
    finally:
        rt.stop()
