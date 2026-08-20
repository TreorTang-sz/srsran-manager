"""Database schema + data access objects.

Tables:
  events   - important system events (SYSTEM_START, ENB_CRASH, ...)
  logs     - unified log stream (srsENB/srsEPC/Watchdog/Manager/System)
  kv_state - small key/value state store, used for cross-process
             watchdog status sharing in the split systemd deployment
"""
from __future__ import annotations

import json
from typing import Any, Optional

from app.core.bus import EventBus, utc_now_iso
from app.database.db import Database
from app.models import EventRecord, LogRecord, Severity

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    ts       TEXT    NOT NULL,
    type     TEXT    NOT NULL,
    source   TEXT    NOT NULL,
    severity TEXT    NOT NULL,
    message  TEXT    NOT NULL,
    data     TEXT    NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_events_ts   ON events(ts);
CREATE INDEX IF NOT EXISTS idx_events_type ON events(type);

CREATE TABLE IF NOT EXISTS logs (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    ts      TEXT    NOT NULL,
    level   TEXT    NOT NULL,
    module  TEXT    NOT NULL,
    message TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_logs_ts     ON logs(ts);
CREATE INDEX IF NOT EXISTS idx_logs_module ON logs(module);

CREATE TABLE IF NOT EXISTS kv_state (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


class EventStore:
    def __init__(self, db: Database) -> None:
        self.db = db
        with db.lock:
            db.conn.executescript(SCHEMA)
            db.conn.commit()

    def insert_event(self, record: EventRecord) -> int:
        cur = self.db.execute(
            "INSERT INTO events (ts, type, source, severity, message, data) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (record.ts or utc_now_iso(), record.type, record.source,
             record.severity.value if isinstance(record.severity, Severity) else str(record.severity),
             record.message, json.dumps(record.data, ensure_ascii=False)),
        )
        return cur.lastrowid or 0

    def query_events(
        self,
        limit: int = 50,
        offset: int = 0,
        type: Optional[str] = None,
        severity: Optional[str] = None,
        source: Optional[str] = None,
    ) -> list[EventRecord]:
        sql = "SELECT * FROM events"
        conds: list[str] = []
        params: list[Any] = []
        if type:
            conds.append("type = ?")
            params.append(type)
        if severity:
            conds.append("severity = ?")
            params.append(severity)
        if source:
            conds.append("source = ?")
            params.append(source)
        if conds:
            sql += " WHERE " + " AND ".join(conds)
        sql += " ORDER BY id DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        rows = self.db.query(sql, tuple(params))
        return [
            EventRecord(
                id=r["id"], ts=r["ts"], type=r["type"], source=r["source"],
                severity=r["severity"], message=r["message"],
                data=json.loads(r["data"] or "{}"),
            )
            for r in rows
        ]

    def event_count(self, type: Optional[str] = None) -> int:
        if type:
            rows = self.db.query("SELECT COUNT(*) AS c FROM events WHERE type = ?", (type,))
        else:
            rows = self.db.query("SELECT COUNT(*) AS c FROM events")
        return int(rows[0]["c"])


class LogStore:
    def __init__(self, db: Database) -> None:
        self.db = db

    def insert_log(self, record: LogRecord) -> int:
        cur = self.db.execute(
            "INSERT INTO logs (ts, level, module, message) VALUES (?, ?, ?, ?)",
            (record.ts or utc_now_iso(), record.level, record.module, record.message),
        )
        return cur.lastrowid or 0

    def query_logs(
        self,
        limit: int = 100,
        offset: int = 0,
        level: Optional[str] = None,
        module: Optional[str] = None,
    ) -> list[LogRecord]:
        sql = "SELECT * FROM logs"
        conds: list[str] = []
        params: list[Any] = []
        if level:
            conds.append("level = ?")
            params.append(level)
        if module:
            conds.append("module LIKE ?")
            params.append(f"{module}%")
        if conds:
            sql += " WHERE " + " AND ".join(conds)
        sql += " ORDER BY id DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        return [
            LogRecord(id=r["id"], ts=r["ts"], level=r["level"],
                      module=r["module"], message=r["message"])
            for r in self.db.query(sql, tuple(params))
        ]


class StateStore:
    """Small kv store for cross-process state (watchdog status)."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def set_state(self, key: str, value: Any) -> None:
        self.db.execute(
            "INSERT INTO kv_state (key, value, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value, "
            "updated_at = excluded.updated_at",
            (key, json.dumps(value, ensure_ascii=False), utc_now_iso()),
        )

    def get_state(self, key: str) -> Optional[Any]:
        rows = self.db.query("SELECT value FROM kv_state WHERE key = ?", (key,))
        if not rows:
            return None
        try:
            return json.loads(rows[0]["value"])
        except json.JSONDecodeError:
            return None


class BusPersister:
    """Subscribes to the EventBus and persists events/logs to SQLite."""

    def __init__(self, bus: EventBus, events: EventStore, logs: LogStore) -> None:
        self._events = events
        self._logs = logs
        bus.subscribe(self._on_event)
        bus.subscribe_logs(self._on_log)

    def _on_event(self, record: EventRecord) -> None:
        try:
            self._events.insert_event(record)
        except Exception:  # noqa: BLE001
            pass

    def _on_log(self, record: LogRecord) -> None:
        try:
            self._logs.insert_log(record)
        except Exception:  # noqa: BLE001
            pass
