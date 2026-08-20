"""In-process event bus.

Publishes EventRecords / LogRecords to subscribers:
  * Database persister (SQLite)
  * WebSocket bridge (snapshot recent_events)
  * log records also go to the python logging root logger

The bus itself is platform-agnostic and has no FastAPI dependency, so
the standalone watchdog service can use it too.
"""
from __future__ import annotations

import logging
import threading
from collections import deque
from datetime import datetime, timezone
from typing import Callable, Deque, List, Optional

from app.models import EventRecord, LogRecord, Severity

logger = logging.getLogger("srsran.bus")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


Subscriber = Callable[[EventRecord], None]
LogSubscriber = Callable[[LogRecord], None]


class EventBus:
    def __init__(self, recent_capacity: int = 200) -> None:
        self._lock = threading.RLock()
        self._subscribers: List[Subscriber] = []
        self._log_subscribers: List[LogSubscriber] = []
        self._recent: Deque[EventRecord] = deque(maxlen=recent_capacity)

    # ------------------------------------------------------------------
    def publish_event(
        self,
        type: str,
        source: str,
        severity: Severity = Severity.INFO,
        message: str = "",
        data: Optional[dict] = None,
    ) -> EventRecord:
        record = EventRecord(
            ts=utc_now_iso(),
            type=type,
            source=source,
            severity=severity,
            message=message,
            data=data or {},
        )
        with self._lock:
            self._recent.append(record)
            subscribers = list(self._subscribers)
        for sub in subscribers:
            try:
                sub(record)
            except Exception:  # noqa: BLE001 - subscriber isolation
                logger.exception("event subscriber failed")
        return record

    def publish_log(self, level: str, module: str, message: str) -> LogRecord:
        record = LogRecord(ts=utc_now_iso(), level=level, module=module, message=message)
        with self._lock:
            subscribers = list(self._log_subscribers)
        for sub in subscribers:
            try:
                sub(record)
            except Exception:  # noqa: BLE001
                logger.exception("log subscriber failed")
        return record

    # ------------------------------------------------------------------
    def subscribe(self, subscriber: Subscriber) -> None:
        with self._lock:
            self._subscribers.append(subscriber)

    def subscribe_logs(self, subscriber: LogSubscriber) -> None:
        with self._lock:
            self._log_subscribers.append(subscriber)

    def recent_events(self, limit: int = 20) -> List[EventRecord]:
        with self._lock:
            items = list(self._recent)
        return items[-limit:]


class BusLogHandler(logging.Handler):
    """Routes python logging records into the unified log system."""

    def __init__(self, bus: EventBus) -> None:
        super().__init__()
        self.bus = bus

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level = record.levelname
            if level not in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
                level = "INFO"
            self.bus.publish_log(level, record.name or "root", record.getMessage())
        except Exception:  # noqa: BLE001
            pass
