"""Mock process manager — simulates systemd start/stop/restart/status
for srsEPC and srsENB on Windows (dev mode).

State transitions mirror real service behaviour:
  STOPPED --start--> STARTING --(start_delay)--> RUNNING
  RUNNING --stop--> STOPPING --(stop_delay)--> STOPPED
  crash (fault injection): RUNNING --> STOPPED instantly
  recover-fail simulation: STARTING --(start_delay)--> FAILED
"""
from __future__ import annotations

from app.mock.world import MockWorld
from app.models import ServiceName, ServiceState, ServiceStatus


class MockProcessManager:
    def __init__(self, world: MockWorld) -> None:
        self.world = world

    def _svc(self, service: ServiceName):
        return self.world.services[service.value]

    def start(self, service: ServiceName) -> ServiceStatus:
        self.world.start_service(service)
        return self.status(service)

    def stop(self, service: ServiceName) -> ServiceStatus:
        self.world.stop_service(service)
        return self.status(service)

    def restart(self, service: ServiceName) -> ServiceStatus:
        self.world.stop_service(service)
        self.world.start_service(service)
        return self.status(service)

    def status(self, service: ServiceName) -> ServiceStatus:
        self.world.tick()
        svc = self._svc(service)
        detail = {
            ServiceState.STARTING: "mock: activation in progress",
            ServiceState.STOPPING: "mock: deactivation in progress",
            ServiceState.FAILED: "mock: start attempt failed",
            ServiceState.RUNNING: "mock: active and running",
        }.get(svc.state, "")
        return ServiceStatus(name=service.value, state=svc.state, pid=svc.pid, detail=detail)
