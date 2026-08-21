"""Mock 日志源 —— 从 MockWorld 剧本中取日志行。

与 LinuxJournalLogSource 走同一 LogSource 接口：输出行进入同一条
LogEventParser -> LogStateAggregator 管线（相同接口原则）。
"""
from __future__ import annotations

import time

from app.mock.world import MockWorld
from app.providers.base import LogLine, LogSource


class MockLogSource(LogSource):
    def __init__(self, world: MockWorld) -> None:
        self.world = world

    def poll(self) -> list[LogLine]:
        now = time.time()
        due = self.world.collect_due_logs(now)
        return [LogLine(service, now, message) for service, message in due]
