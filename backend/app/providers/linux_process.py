"""systemd-based process manager (production).

DEPLOYMENT STATUS: written for Phase 6/7, to be verified on the target.
Security: only fixed ``systemctl`` invocations with the configured unit
names are possible — no shell, no arbitrary commands.
"""
from __future__ import annotations

import subprocess

from app.config import AppConfig
from app.models import ServiceName, ServiceState, ServiceStatus

# systemctl show ActiveState -> ServiceState
_STATE_MAP = {
    "active": ServiceState.RUNNING,
    "activating": ServiceState.STARTING,
    "deactivating": ServiceState.STOPPING,
    "failed": ServiceState.FAILED,
    "inactive": ServiceState.STOPPED,
}


class LinuxSystemdProcessManager:
    def __init__(self, config: AppConfig) -> None:
        self._units = {
            ServiceName.EPC: config.linux.services.epc,
            ServiceName.ENB: config.linux.services.enb,
        }

    @staticmethod
    def _systemctl(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["systemctl", *args],
            capture_output=True,
            text=True,
            timeout=30,
        )

    def _unit(self, service: ServiceName) -> str:
        return self._units[service]

    def status(self, service: ServiceName) -> ServiceStatus:
        unit = self._unit(service)
        try:
            proc = self._systemctl("show", unit, "--property=ActiveState,SubState,MainPID")
        except (subprocess.TimeoutExpired, OSError) as exc:
            return ServiceStatus(name=service.value, state=ServiceState.UNKNOWN, detail=str(exc))
        props: dict[str, str] = {}
        for line in proc.stdout.splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                props[k.strip()] = v.strip()
        active = props.get("ActiveState", "unknown")
        state = _STATE_MAP.get(active, ServiceState.UNKNOWN)
        sub = props.get("SubState", "")
        pid = int(props["MainPID"]) if props.get("MainPID", "0").isdigit() and props.get("MainPID") != "0" else None
        detail = f"{active}({sub})" if sub else active
        return ServiceStatus(name=service.value, state=state, pid=pid, detail=detail)

    def start(self, service: ServiceName) -> ServiceStatus:
        self._systemctl("start", self._unit(service))
        return self.status(service)

    def stop(self, service: ServiceName) -> ServiceStatus:
        self._systemctl("stop", self._unit(service))
        return self.status(service)

    def restart(self, service: ServiceName) -> ServiceStatus:
        self._systemctl("restart", self._unit(service))
        return self.status(service)
