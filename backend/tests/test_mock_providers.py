"""Mock provider behaviour tests."""
from __future__ import annotations

from app.models import ServiceName, ServiceState
from app.mock.faults import FaultController
from tests.conftest import wait_for


def test_system_metrics_ranges(runtime):
    m = runtime.providers.system.get_metrics()
    assert 0 <= m.cpu_percent <= 100
    assert len(m.cpu_per_core) == 8
    assert all(0 <= c <= 100 for c in m.cpu_per_core)
    assert m.mem_total_mb > 0
    assert 0 < m.mem_percent < 100
    assert m.disk_total_gb > 0
    assert m.cpu_temp_c is not None and 30 < m.cpu_temp_c < 95
    assert m.uptime_s > 0


def test_service_start_stop_lifecycle(runtime):
    pm = runtime.providers.process
    assert pm.status(ServiceName.ENB).state == ServiceState.STOPPED
    pm.start(ServiceName.ENB)
    assert pm.status(ServiceName.ENB).state == ServiceState.STARTING
    assert wait_for(lambda: pm.status(ServiceName.ENB).state == ServiceState.RUNNING, timeout=3)
    pm.stop(ServiceName.ENB)
    assert wait_for(lambda: pm.status(ServiceName.ENB).state == ServiceState.STOPPED, timeout=3)


def test_s1_requires_both_services(runtime):
    w = runtime.providers.mock_world
    pm = runtime.providers.process
    pm.start(ServiceName.EPC)
    pm.start(ServiceName.ENB)
    assert wait_for(lambda: runtime.providers.s1.get_status().connected, timeout=3)
    # stop eNB -> S1 down even though EPC still running
    pm.stop(ServiceName.ENB)
    assert wait_for(lambda: not runtime.providers.s1.get_status().connected, timeout=3)


def test_usrp_fault_and_clear(runtime):
    faults = runtime.faults
    assert runtime.providers.usrp.get_status().connected
    faults.inject("usrp-down")
    assert not runtime.providers.usrp.get_status().connected
    faults.clear()
    assert runtime.providers.usrp.get_status().connected


def test_ue_attach_detach_with_s1(runtime):
    w = runtime.providers.mock_world
    w.config.mock.ue_attach_probability = 1.0  # force attach each tick
    pm = runtime.providers.process
    pm.start(ServiceName.EPC)
    pm.start(ServiceName.ENB)
    assert wait_for(lambda: len(w.ue_snapshot()) > 0, timeout=5)
    ue = w.ue_snapshot()[0]
    assert ue.rnti > 0
    assert ue.cqi is None or 1 <= ue.cqi <= 15
    # S1 down -> UEs detach
    w.s1_fault = True
    assert wait_for(lambda: len(w.ue_snapshot()) == 0, timeout=3)


def test_high_cpu_fault_reflected_in_metrics(runtime):
    runtime.providers.system.get_metrics()  # prime
    runtime.faults.inject("high-cpu")
    m = runtime.providers.system.get_metrics()
    assert m.cpu_percent > 90
    runtime.faults.inject("high-temp")
    m = runtime.providers.system.get_metrics()
    assert m.cpu_temp_c > 80


def test_enb_metrics_shape(runtime):
    m = runtime.providers.srsran.get_enb_metrics()
    assert m.ue_count == len(m.ues)
    assert m.dl_bitrate_mbps == round(sum(u.dl_bitrate_mbps for u in m.ues), 2)
    assert m.source == "mock"
    # no IMSI-like identity fields exist on UE model
    assert not any("imsi" in f for f in type(m.ues[0]).model_fields) if m.ues else True


def test_core_traffic_provider(runtime):
    core = runtime.providers.core_traffic.get_traffic()
    assert core.rx_mbps >= 0 and core.tx_mbps >= 0
    assert core.interfaces
