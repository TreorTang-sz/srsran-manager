"""REST API tests (FastAPI TestClient)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import AppConfig
from app.main import create_app
from app.models import EventType, WatchdogState
from tests.conftest import API_TOKEN, find_event, wait_for

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")


@pytest.fixture()
def client(tmp_path):
    from tests.conftest import make_config
    cfg: AppConfig = make_config(tmp_path)
    app = create_app(cfg)
    with TestClient(app) as c:
        yield c


def auth_headers():
    return {"X-API-Token": API_TOKEN}


# ---------------------------------------------------------------------------
# GET endpoints
# ---------------------------------------------------------------------------
def test_get_status(client):
    resp = client.get("/api/status")
    assert resp.status_code == 200
    data = resp.json()
    for key in ("watchdog", "services", "s1", "usrp", "system",
                "enb_metrics", "core_traffic", "recent_events"):
        assert key in data
    assert data["mode"] == "mock"
    assert set(data["services"].keys()) == {"epc", "enb"}


def test_get_system(client):
    resp = client.get("/api/system")
    assert resp.status_code == 200
    data = resp.json()
    assert "cpu_percent" in data
    assert "mem_percent" in data
    assert "cpu_temp_c" in data
    assert 0 <= data["cpu_percent"] <= 100


def test_get_usrp_s1_ue_throughput(client):
    assert client.get("/api/usrp").json()["device"] == "B210"
    s1 = client.get("/api/s1").json()
    assert "connected" in s1
    ue = client.get("/api/ue").json()
    assert "count" in ue and "ues" in ue
    tp = client.get("/api/throughput").json()
    assert "points" in tp


def test_get_events_and_logs(client):
    events = client.get("/api/events").json()
    assert events["count"] >= 1
    types = {e["type"] for e in events["events"]}
    assert EventType.SYSTEM_START in types

    logs = client.get("/api/logs").json()
    assert "logs" in logs


# ---------------------------------------------------------------------------
# auth
# ---------------------------------------------------------------------------
def test_control_without_token_rejected(client):
    for path in ("/api/network/start", "/api/enb/restart", "/api/epc/stop",
                 "/api/dev/fault/enb-crash"):
        resp = client.post(path)
        assert resp.status_code == 401, f"{path} -> {resp.status_code}"


def test_control_with_wrong_token_rejected(client):
    resp = client.post("/api/network/start", headers={"X-API-Token": "wrong"})
    assert resp.status_code == 401


def test_control_with_token_accepted(client):
    resp = client.post("/api/network/start", headers=auth_headers())
    assert resp.status_code == 200
    assert "result" in resp.json()


def test_token_disabled_when_not_configured(tmp_path):
    from tests.conftest import make_config
    cfg = make_config(tmp_path)
    cfg.security.api_token = None
    app = create_app(cfg)
    with TestClient(app) as c:
        resp = c.post("/api/network/start")
        assert resp.status_code == 503  # control disabled, fail closed


# ---------------------------------------------------------------------------
# control + watchdog through the API
# ---------------------------------------------------------------------------
def test_full_cycle_over_api(client):
    # start network
    client.post("/api/network/start", headers=auth_headers())
    assert wait_for(lambda: client.get("/api/status").json()["watchdog"]["state"] == "RUNNING",
                    timeout=8), "watchdog should reach RUNNING"

    status = client.get("/api/status").json()
    assert status["services"]["enb"]["state"] == "RUNNING"
    assert status["s1"]["connected"] is True
    assert status["usrp"]["connected"] is True

    # inject eNB crash -> watchdog recovers
    client.post("/api/dev/fault/enb-crash", headers=auth_headers())
    assert wait_for(
        lambda: client.get("/api/status").json()["watchdog"]["state"] == "RECOVERING",
        timeout=3), "expected RECOVERING after enb crash"
    assert wait_for(lambda: client.get("/api/status").json()["watchdog"]["state"] == "RUNNING",
                    timeout=8), "expected RUNNING after recovery"

    events = client.get("/api/events", params={"limit": 100}).json()["events"]
    types = {e["type"] for e in events}
    assert EventType.ENB_CRASH in types
    assert EventType.AUTO_RECOVERY_SUCCESS in types

    # stop network
    client.post("/api/network/stop", headers=auth_headers())
    assert wait_for(lambda: client.get("/api/status").json()["watchdog"]["state"] == "STOPPED",
                    timeout=5)
    status = client.get("/api/status").json()
    assert status["services"]["epc"]["state"] == "STOPPED"


def test_restart_single_service(client):
    client.post("/api/enb/start", headers=auth_headers())
    assert wait_for(lambda: client.get("/api/status").json()["services"]["enb"]["state"] == "RUNNING",
                    timeout=5)
    resp = client.post("/api/enb/restart", headers=auth_headers())
    assert resp.status_code == 200
    assert wait_for(lambda: client.get("/api/status").json()["services"]["enb"]["state"] == "RUNNING",
                    timeout=5)


def test_unknown_fault_returns_404(client):
    resp = client.post("/api/dev/fault/does-not-exist", headers=auth_headers())
    assert resp.status_code == 404


def test_high_cpu_fault_creates_warning_state(client):
    client.post("/api/network/start", headers=auth_headers())
    assert wait_for(lambda: client.get("/api/status").json()["watchdog"]["state"] == "RUNNING",
                    timeout=8)
    client.post("/api/dev/fault/high-cpu", headers=auth_headers())
    # WARNING state (soft), no restart
    assert wait_for(lambda: client.get("/api/status").json()["watchdog"]["state"] == "WARNING",
                    timeout=5)
    client.post("/api/dev/fault/clear", headers=auth_headers())
    assert wait_for(lambda: client.get("/api/status").json()["watchdog"]["state"] == "RUNNING",
                    timeout=5)
