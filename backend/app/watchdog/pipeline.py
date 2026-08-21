"""LogPipeline —— 日志采集 -> 解析 -> 聚合 的共用管线。

engine 的每个 tick 与 recovery 的验证轮询都调用 pump()，
保证阻塞在恢复期间聚合器状态也能随日志推进。
"""
from __future__ import annotations

import logging
from typing import List

from app.providers.base import LogSource
from app.watchdog.aggregator import LogStateAggregator
from app.watchdog.log_events import LogEvent, LogEventParser

logger = logging.getLogger("srsran.pipeline")


class LogPipeline:
    def __init__(self, source: LogSource, aggregator: LogStateAggregator,
                 parser: LogEventParser | None = None) -> None:
        self.source = source
        self.aggregator = aggregator
        self.parser = parser or LogEventParser()

    def pump(self) -> List[LogEvent]:
        """拉取新日志行 -> 解析 -> 应用到聚合器。返回本轮产生的事件。"""
        events: List[LogEvent] = []
        try:
            lines = self.source.poll()
        except Exception as exc:  # noqa: BLE001 — pipeline must never kill the watchdog
            logger.exception("log source poll failed")
            self.last_error = f"{type(exc).__name__}: {exc}"
            return events
        self.last_error = ""
        for line in lines:
            ev = self.parser.parse(line.service, line.ts, line.message)
            if ev is not None:
                events.append(ev)
        if events:
            self.aggregator.apply(events)
        return events

    last_error: str = ""
