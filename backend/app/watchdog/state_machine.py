"""Watchdog state machine — log-event driven startup pipeline.

状态（来自真实 srsRAN 启动流程）：

  STOPPED -> STARTING -> EPC_READY -> ENB_RF_INITIALIZING ->
  ENB_RUNNING -> S1_CONNECTING -> RUNNING
  侧态: WARNING / DEGRADED / RECOVERING / FAULT

两种驱动方式：
  * fire(event)   —— 控制类事件（START/STOP/CRITICAL/RECOVERY/FAULT/RESET），
                     由显式转换表约束。
  * sync_to(state) —— 启动路径的派生推进（engine 依据聚合器的组件阶段
                     计算出应处的状态，幂等，允许沿启动路径前进/回退，
                     例如 eNB 重启时 RUNNING -> EPC_READY）。

                    +---------+
                    | STOPPED |<--------------------------+
                    +----+----+                           |
                         | START                          | STOP
                         v                                |
                    +---------+  stage sync   +---------+  |
                    |STARTING |-------------->|EPC_READY|  |
                    +---------+               +----+----+  |
                         ^                        |       |
                         |              ENB_RF_INITIALIZING|
                         |                        |       |
                         |                   ENB_RUNNING  |
                         |                        |       |
                         |                  S1_CONNECTING |
                         |                        |       |
                         |                     RUNNING <--+ (WARNING side state)
                         |                        |
                         |     CRITICAL           | S1 lost -> DEGRADED
                         +--------+  <-----------+        |
                                  v                     | grace expired
                             +-----------+  FAULT       | -> CRITICAL
                             |RECOVERING |--------+     |
                             +-----+-----+        |     |
                               |   ^              v     |
                    RECOVERY_OK|   |RECOVERY_FAIL +-----+
                               v   (retry)       FAULT --RESET--> STARTING
                             (re-derive)
"""
from __future__ import annotations

import threading
import time
from collections import deque
from enum import Enum
from typing import Callable, Deque, List, Optional, Tuple

from app.models import WatchdogState

# 派生同步允许的目标状态（运行/启动路径 + 侧态）
_SYNCABLE = {
    WatchdogState.STARTING,
    WatchdogState.EPC_READY,
    WatchdogState.ENB_RF_INITIALIZING,
    WatchdogState.ENB_RUNNING,
    WatchdogState.S1_CONNECTING,
    WatchdogState.RUNNING,
    WatchdogState.WARNING,
    WatchdogState.DEGRADED,
}


class WatchdogEvent(str, Enum):
    START = "START"
    STOP = "STOP"
    CRITICAL = "CRITICAL"           # hard failure -> recover
    RECOVERY_OK = "RECOVERY_OK"
    RECOVERY_FAIL = "RECOVERY_FAIL"
    FAULT = "FAULT"
    RESET = "RESET"


# states from which CRITICAL leads to RECOVERING
_OPERATING = _SYNCABLE | {WatchdogState.STARTING}

# (state, event) -> next state
TRANSITIONS: dict[Tuple[WatchdogState, WatchdogEvent], WatchdogState] = {
    (WatchdogState.STOPPED, WatchdogEvent.START): WatchdogState.STARTING,
    (WatchdogState.STOPPED, WatchdogEvent.STOP): WatchdogState.STOPPED,

    (WatchdogState.RECOVERING, WatchdogEvent.RECOVERY_OK): WatchdogState.STARTING,
    (WatchdogState.RECOVERING, WatchdogEvent.RECOVERY_FAIL): WatchdogState.RECOVERING,
    (WatchdogState.RECOVERING, WatchdogEvent.FAULT): WatchdogState.FAULT,
    (WatchdogState.RECOVERING, WatchdogEvent.STOP): WatchdogState.STOPPED,

    (WatchdogState.FAULT, WatchdogEvent.RESET): WatchdogState.STARTING,
    (WatchdogState.FAULT, WatchdogEvent.STOP): WatchdogState.STOPPED,
}

# every operating state: CRITICAL -> RECOVERING, STOP -> STOPPED
for _s in _OPERATING:
    TRANSITIONS[(_s, WatchdogEvent.CRITICAL)] = WatchdogState.RECOVERING
    TRANSITIONS[(_s, WatchdogEvent.STOP)] = WatchdogState.STOPPED


TransitionListener = Callable[[WatchdogState, WatchdogState, str], None]


class WatchdogStateMachine:
    """Thread-safe FSM with transition history and listeners."""

    def __init__(self, initial: WatchdogState = WatchdogState.STOPPED) -> None:
        self._lock = threading.RLock()
        self._state = initial
        self._state_since = time.time()
        self._history: Deque[Tuple[float, WatchdogState, WatchdogState, str]] = deque(maxlen=200)
        self._listeners: List[TransitionListener] = []

    # ------------------------------------------------------------------
    @property
    def state(self) -> WatchdogState:
        with self._lock:
            return self._state

    @property
    def state_since(self) -> float:
        with self._lock:
            return self._state_since

    def add_listener(self, listener: TransitionListener) -> None:
        with self._lock:
            self._listeners.append(listener)

    def can_fire(self, event: WatchdogEvent) -> bool:
        with self._lock:
            return (self._state, event) in TRANSITIONS

    # ------------------------------------------------------------------
    def fire(self, event: WatchdogEvent) -> Optional[WatchdogState]:
        """Apply a control event; returns the new state or None."""
        with self._lock:
            key = (self._state, event)
            if key not in TRANSITIONS:
                return None
            new = TRANSITIONS[key]
            return self._transition(new, event.value)

    def sync_to(self, target: WatchdogState) -> Optional[WatchdogState]:
        """Derive-driven state sync (startup path / WARNING / DEGRADED).

        Only valid while the machine is in a derivable state (not in
        STOPPED / RECOVERING / FAULT). Idempotent; may move backwards
        along the startup path (e.g. eNB restart: RUNNING -> EPC_READY).
        """
        with self._lock:
            if target not in _SYNCABLE:
                return None
            if self._state not in _SYNCABLE and self._state != WatchdogState.STARTING:
                return None  # RECOVERING / FAULT / STOPPED: engine-controlled
            if self._state == target:
                return target
            return self._transition(target, "SYNC")

    # ------------------------------------------------------------------
    def _transition(self, new: WatchdogState, event: str) -> WatchdogState:
        old = self._state
        self._state = new
        self._state_since = time.time()
        self._history.append((time.time(), old, new, event))
        listeners = list(self._listeners)
        for listener in listeners:
            listener(old, new, event)
        return new

    def history(self, limit: int = 20) -> List[dict]:
        with self._lock:
            items = list(self._history)
        return [
            {"ts": ts, "from": old.value, "to": new.value, "event": ev}
            for ts, old, new, ev in items[-limit:]
        ]
