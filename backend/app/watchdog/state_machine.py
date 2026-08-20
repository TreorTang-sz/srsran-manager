"""Watchdog state machine.

Explicit finite state machine — NOT scattered if/else branches.

States:
  STOPPED     services intentionally down (user stopped the network)
  STARTING    services are being started, not yet healthy
  RUNNING     everything healthy
  WARNING     healthy but a soft threshold is exceeded (CPU/temp/mem/disk)
  RECOVERING  automatic recovery in progress
  FAULT       max recovery attempts exhausted — manual action required

Events (inputs):
  START         user asked the network to run
  STOP          user asked the network to stop
  HEALTHY       health check OK
  WARNING       health check reports soft warnings only
  CRITICAL      health check reports a hard failure
  RECOVERY_OK   recovery attempt succeeded
  RECOVERY_FAIL recovery attempt failed (engine decides retry or FAULT)
  FAULT         engine exhausted recovery attempts
  RESET         manual reset from FAULT (restart attempt)

                    +---------+
                    | STOPPED |<----------------------+
                    +----+----+                        |
                         | START                       | STOP
                         v                             |
                    +---------+  HEALTHY   +---------+  |
             +----->|STARTING |----------->| RUNNING |--+
             |      +----+----+            +----+----+
             |           | CRITICAL            | CRITICAL
             |           v                     v
             |      +-----------+ WARNING +---------+
             |      |RECOVERING |<--------| WARNING |
             |      +-----+-----+         +---------+
             |            | RECOVERY_OK -> RUNNING
             |            | RECOVERY_FAIL (stay, retry)
             |            | FAULT
             |            v
             |      +-------+   RESET   +---------+
             +------| FAULT |---------->|STARTING |
                    +-------+           +---------+
"""
from __future__ import annotations

import threading
import time
from enum import Enum
from typing import Callable, Deque, List, Optional, Tuple

from collections import deque

from app.models import WatchdogState


class WatchdogEvent(str, Enum):
    START = "START"
    STOP = "STOP"
    HEALTHY = "HEALTHY"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"
    RECOVERY_OK = "RECOVERY_OK"
    RECOVERY_FAIL = "RECOVERY_FAIL"
    FAULT = "FAULT"
    RESET = "RESET"


# (state, event) -> next state
TRANSITIONS: dict[Tuple[WatchdogState, WatchdogEvent], WatchdogState] = {
    (WatchdogState.STOPPED, WatchdogEvent.START): WatchdogState.STARTING,
    (WatchdogState.STOPPED, WatchdogEvent.STOP): WatchdogState.STOPPED,

    (WatchdogState.STARTING, WatchdogEvent.HEALTHY): WatchdogState.RUNNING,
    (WatchdogState.STARTING, WatchdogEvent.WARNING): WatchdogState.WARNING,
    (WatchdogState.STARTING, WatchdogEvent.CRITICAL): WatchdogState.RECOVERING,
    (WatchdogState.STARTING, WatchdogEvent.STOP): WatchdogState.STOPPED,

    (WatchdogState.RUNNING, WatchdogEvent.HEALTHY): WatchdogState.RUNNING,
    (WatchdogState.RUNNING, WatchdogEvent.WARNING): WatchdogState.WARNING,
    (WatchdogState.RUNNING, WatchdogEvent.CRITICAL): WatchdogState.RECOVERING,
    (WatchdogState.RUNNING, WatchdogEvent.STOP): WatchdogState.STOPPED,

    (WatchdogState.WARNING, WatchdogEvent.HEALTHY): WatchdogState.RUNNING,
    (WatchdogState.WARNING, WatchdogEvent.WARNING): WatchdogState.WARNING,
    (WatchdogState.WARNING, WatchdogEvent.CRITICAL): WatchdogState.RECOVERING,
    (WatchdogState.WARNING, WatchdogEvent.STOP): WatchdogState.STOPPED,

    (WatchdogState.RECOVERING, WatchdogEvent.RECOVERY_OK): WatchdogState.RUNNING,
    (WatchdogState.RECOVERING, WatchdogEvent.RECOVERY_FAIL): WatchdogState.RECOVERING,
    (WatchdogState.RECOVERING, WatchdogEvent.FAULT): WatchdogState.FAULT,
    (WatchdogState.RECOVERING, WatchdogEvent.STOP): WatchdogState.STOPPED,

    (WatchdogState.FAULT, WatchdogEvent.RESET): WatchdogState.STARTING,
    (WatchdogState.FAULT, WatchdogEvent.STOP): WatchdogState.STOPPED,
}


TransitionListener = Callable[[WatchdogState, WatchdogState, WatchdogEvent], None]


class WatchdogStateMachine:
    """Thread-safe FSM with transition history and listeners."""

    def __init__(self, initial: WatchdogState = WatchdogState.STOPPED) -> None:
        self._lock = threading.RLock()
        self._state = initial
        self._state_since = time.time()
        self._history: Deque[Tuple[float, WatchdogState, WatchdogState, WatchdogEvent]] = deque(maxlen=100)
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

    def fire(self, event: WatchdogEvent) -> Optional[WatchdogState]:
        """Apply an event; returns the new state or None if not applicable."""
        with self._lock:
            key = (self._state, event)
            if key not in TRANSITIONS:
                return None
            old = self._state
            new = TRANSITIONS[key]
            if new == old and event not in (WatchdogEvent.STOP, WatchdogEvent.WARNING):
                return old  # no-op transition (e.g. RUNNING + HEALTHY)
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
            {"ts": ts, "from": old.value, "to": new.value, "event": ev.value}
            for ts, old, new, ev in items[-limit:]
        ]
