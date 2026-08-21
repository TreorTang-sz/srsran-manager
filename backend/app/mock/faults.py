"""Fault injection controller (development / mock mode).

Exposes the fault scenarios required for watchdog verification:
  enb-crash, epc-crash, s1-down, usrp-down, plmn-error, high-cpu,
  high-temp, recover-fail. Reachable through the dev API:
      POST /api/dev/fault/{name}
      POST /api/dev/fault/clear

plmn-error: EPC 侧立即产生一条真实的
  "S1 Setup Failure cause: misc - unknown-PLMN" 日志 —— 看门狗据此进入
  CONFIG_ERROR -> FAULT，不做任何自动重启（配置错误，重启无效）。
"""
from __future__ import annotations

import time
from typing import Any, Dict

from app.core.bus import EventBus
from app.models import EventType, ServiceName, ServiceState, Severity
from app.mock.world import MockWorld

FAULT_NAMES = ("enb-crash", "epc-crash", "s1-down", "usrp-down",
               "plmn-error", "high-cpu", "high-temp", "recover-fail")

_L_S1_FAILURE = "S1 Setup Failure cause: misc - unknown-PLMN"


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
            # SCTP Association Shutdown 日志将在下一次 poll 产生 (S1_LOST)
            w.s1_fault = True
            message = "injected: S1 link down (SCTP shutdown)"
        elif name == "usrp-down":
            # B210 拔出 -> eNB 进程随之崩溃; 重启后日志输出 No UHD Devices Found
            w.usrp_fault = True
            if w.services[ServiceName.ENB.value].state == ServiceState.RUNNING:
                w.crash_service(ServiceName.ENB)
            message = "injected: USRP B210 disconnected"
        elif name == "plmn-error":
            # EPC 侧立即回 S1 Setup Failure (unknown-PLMN) -> CONFIG_ERROR
            w.plmn_error = True
            with w.lock:
                w._pending_logs.append((time.time(), "epc", _L_S1_FAILURE))
            message = "injected: PLMN mismatch (S1 Setup Failure)"
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
        w.plmn_error = False
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
            "plmn_error": w.plmn_error,
            "high_cpu": w.high_cpu,
            "high_temp": w.high_temp,
            "recover_fail_pending": w.recover_fail_pending,
        }
