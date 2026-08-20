"""Fault injection controller (development / mock mode).

Exposes the fault scenarios required for watchdog verification:
  enb-crash, epc-crash, s1-down, usrp-down, high-cpu, high-temp,
  recover-fail. Reachable through the dev API:
      POST /api/dev/fault/{name}
      POST /api/dev/fault/clear
"""
from __future__ import annotations

from typing import Any, Dict

from app.core.bus import EventBus
from app.models import EventType, ServiceName, Severity
from app.mock.world import MockWorld

FAULT_NAMES = ("enb-crash", "epc-crash", "s1-down", "usrp-down",
               "high-cpu", "high-temp", "recover-fail")


class FaultController:
    def __init__(self, world: MockWorld, bus: EventBus) -> None:
        self.world = world
        self.bus = bus

    def inject(self, name: str, times: int = 1) -> Dict[str, Any]:
        w = self.world
        if name == "enb-crash":
            w.crash_service(ServiceName.ENB)
            message = "injected: srsENB crash"
        elif name == "epc-crash":
            w.crash_service(ServiceName.EPC)
            message = "injected: srsEPC crash"
        elif name == "s1-down":
            w.s1_fault = True
            message = "injected: S1 link down"
        elif name == "usrp-down":
            w.usrp_fault = True
            message = "injected: USRP B210 disconnected"
        elif name == "high-cpu":
            w.high_cpu = True
            message = "injected: high CPU load"
        elif name == "high-temp":
            w.high_temp = True
            message = "injected: high CPU temperature"
        elif name == "recover-fail":
            w.recover_fail_pending += max(1, times)
            message = f"injected: next {w.recover_fail_pending} recoveries will fail"
        else:
            raise ValueError(f"unknown fault: {name}")

        self.bus.publish_event(
            type=EventType.FAULT_INJECTED,
            source="Dev",
            severity=Severity.WARNING,
            message=message,
            data={"fault": name, "times": times},
        )
        return {"fault": name, "active": self.active_faults()}

    def clear(self) -> Dict[str, Any]:
        w = self.world
        w.usrp_fault = False
        w.s1_fault = False
        w.high_cpu = False
        w.high_temp = False
        w.recover_fail_pending = 0
        self.bus.publish_event(
            type=EventType.FAULT_CLEARED,
            source="Dev",
            severity=Severity.INFO,
            message="all injected faults cleared",
        )
        return {"active": self.active_faults()}

    def active_faults(self) -> Dict[str, Any]:
        w = self.world
        return {
            "usrp_fault": w.usrp_fault,
            "s1_fault": w.s1_fault,
            "high_cpu": w.high_cpu,
            "high_temp": w.high_temp,
            "recover_fail_pending": w.recover_fail_pending,
        }
