"""srsRAN 日志采集（生产环境，Linux journalctl）。

DEPLOYMENT STATUS: 基于 journalctl JSON 输出编写，ARM64 Ubuntu 20.04/22.04
的 systemd-journald 均支持；首次部署需在实机验证单元名与 MESSAGE 字段。

策略：
  * 首次 poll 拉取最近 boot_history_s 秒的历史日志 —— 看门狗重启后能
    从既有日志恢复 enb_stage / epc_stage / s1_state（无需重启基站）。
  * 之后增量拉取（--since 上次时间 - 2s 重叠窗口），按 (ts, message) 去重。
  * journalctl 调用失败时记录错误并返回空列表 —— 日志不可用会被
    阶段超时兜底（health 判定依赖日志证据）。
"""
from __future__ import annotations

import json
import logging
import subprocess
import threading
import time
from collections import deque
from typing import Optional

from app.config import AppConfig
from app.providers.base import LogLine, LogSource

logger = logging.getLogger("srsran.logs")

_DEDUP_SIZE = 1000


class LinuxJournalLogSource(LogSource):
    def __init__(self, config: AppConfig) -> None:
        self._cfg = config.linux.logs
        self._lock = threading.Lock()
        self._last_ts: Optional[float] = None          # max seen ts
        self._seen: deque[tuple[float, str]] = deque(maxlen=_DEDUP_SIZE)
        self._boot_history_s = self._cfg.boot_history_s
        self._last_error: str = ""

    @property
    def last_error(self) -> str:
        return self._last_error

    # ------------------------------------------------------------------
    def _fetch(self, since_epoch: float) -> list[LogLine]:
        cmd = [
            "journalctl",
            "-u", self._cfg.enb_unit,
            "-u", self._cfg.epc_unit,
            "--since", f"@{since_epoch:.3f}",
            "-o", "json",
            "--no-pager",
            "-n", "4000",
        ]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        except (subprocess.TimeoutExpired, OSError) as exc:
            self._last_error = f"journalctl failed: {exc}"
            return []
        if proc.returncode != 0:
            self._last_error = (proc.stderr or "journalctl error").strip()[:200]
            return []
        self._last_error = ""

        lines: list[LogLine] = []
        for raw in (proc.stdout or "").splitlines():
            raw = raw.strip()
            if not raw:
                continue
            try:
                entry = json.loads(raw)
            except json.JSONDecodeError:
                continue
            msg = entry.get("MESSAGE")
            if not isinstance(msg, str) or not msg.strip():
                continue
            ts_raw = entry.get("__REALTIME_TIMESTAMP")
            try:
                ts = float(ts_raw) / 1_000_000.0 if ts_raw else time.time()
            except (TypeError, ValueError):
                ts = time.time()
            unit = entry.get("_SYSTEMD_UNIT") or ""
            if self._cfg.enb_unit in unit:
                service = "enb"
            elif self._cfg.epc_unit in unit:
                service = "epc"
            else:
                continue
            lines.append(LogLine(service, ts, msg))
        lines.sort(key=lambda l: (l.ts, l.service))
        return lines

    # ------------------------------------------------------------------
    def poll(self) -> list[LogLine]:
        with self._lock:
            if self._last_ts is None:
                since = time.time() - self._boot_history_s
            else:
                # overlap window: journal timestamps have ms resolution, and
                # lines may arrive slightly out of order between polls
                since = self._last_ts - 2.0
            fetched = self._fetch(since)

            out: list[LogLine] = []
            for line in fetched:
                key = (line.ts, line.message)
                if key in self._seen:
                    continue
                # only accept lines at/after our watermark (strictly newer
                # messages at identical ts are allowed via the dedup set)
                if self._last_ts is not None and line.ts < self._last_ts - 2.0:
                    continue
                self._seen.append(key)
                out.append(line)
                if self._last_ts is None or line.ts > self._last_ts:
                    self._last_ts = line.ts
            return out
