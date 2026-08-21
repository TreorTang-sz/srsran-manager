"""组件状态聚合器 —— 把日志事件流折叠成 enb_stage / epc_stage / s1_state。

判定依据（全部来自真实日志证据，不依赖进程存在与否）：

  enb_stage: DOWN -> STARTING -> CONFIG_LOADING -> RF_READY -> RUNNING
             (eNB 重启 -> banner 再次出现 -> 自动回滚重走)
  epc_stage: DOWN -> STARTING -> READY (7 条 Initialized 日志全部出现)
  s1_state:  S1_DOWN -> S1_CONNECTING -> S1_READY
             S1_READY --SCTP Association Shutdown--> S1_LOST
             S1 Setup Failure (unknown-PLMN) -> S1_CONFIG_ERROR

配置类错误（Couldn't open / Unrecognised options / unknown-PLMN /
固件缺失）置 config_error —— 看门狗据此直接进 FAULT，不做无意义的重启。
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import List, Optional

from app.core.bus import EventBus
from app.models import (
    EpcStage,
    EventType,
    EnbStage,
    S1State,
    Severity,
)
from app.watchdog.log_events import EPC_INIT_LINES, LogEvent, LogEventName


@dataclass
class AggregatorSnapshot:
    enb_stage: EnbStage = EnbStage.DOWN
    enb_stage_since: float = field(default_factory=time.time)
    epc_stage: EpcStage = EpcStage.DOWN
    epc_stage_since: float = field(default_factory=time.time)
    s1_state: S1State = S1State.S1_DOWN
    s1_state_since: float = field(default_factory=time.time)
    last_rf_ready_time: Optional[float] = None
    last_s1_ready_time: Optional[float] = None
    last_sctp_shutdown_time: Optional[float] = None
    config_error: Optional[str] = None
    usrp_log_error: Optional[str] = None


class LogStateAggregator:
    """Thread-safe. Fed by LogPipeline.pump(); read by health/engine/monitor."""

    def __init__(self, bus: Optional[EventBus] = None,
                 epc_init_lines: tuple = EPC_INIT_LINES) -> None:
        self._bus = bus
        self._lock = threading.RLock()
        self._epc_init_lines = tuple(epc_init_lines)
        self._epc_seen: set = set()
        self._s = AggregatorSnapshot()

    # ------------------------------------------------------------------
    # read accessors
    # ------------------------------------------------------------------
    @property
    def enb_stage(self) -> EnbStage:
        with self._lock:
            return self._s.enb_stage

    @property
    def epc_stage(self) -> EpcStage:
        with self._lock:
            return self._s.epc_stage

    @property
    def s1_state(self) -> S1State:
        with self._lock:
            return self._s.s1_state

    @property
    def config_error(self) -> Optional[str]:
        with self._lock:
            return self._s.config_error

    @property
    def usrp_log_error(self) -> Optional[str]:
        with self._lock:
            return self._s.usrp_log_error

    def snapshot(self) -> AggregatorSnapshot:
        with self._lock:
            # dataclasses.replace-free shallow copy of value fields
            cp = AggregatorSnapshot(
                enb_stage=self._s.enb_stage,
                enb_stage_since=self._s.enb_stage_since,
                epc_stage=self._s.epc_stage,
                epc_stage_since=self._s.epc_stage_since,
                s1_state=self._s.s1_state,
                s1_state_since=self._s.s1_state_since,
                last_rf_ready_time=self._s.last_rf_ready_time,
                last_s1_ready_time=self._s.last_s1_ready_time,
                last_sctp_shutdown_time=self._s.last_sctp_shutdown_time,
                config_error=self._s.config_error,
                usrp_log_error=self._s.usrp_log_error,
            )
            return cp

    # ------------------------------------------------------------------
    # resets (called by the engine on restart / stop / fault reset)
    # ------------------------------------------------------------------
    def reset_service(self, service: str) -> None:
        """Drop the log-derived state of one service (restart issued).

        S1 belongs to both sides: it is always reset together with the eNB
        (the eNB re-runs S1 setup after restart).
        """
        with self._lock:
            if service == "enb":
                self._set_enb_stage(EnbStage.DOWN, quiet=True)
                self._set_s1(S1State.S1_DOWN, quiet=True)
                self._s.usrp_log_error = None
            elif service == "epc":
                self._set_epc_stage(EpcStage.DOWN, quiet=True)
                self._epc_seen.clear()
                self._set_s1(S1State.S1_DOWN, quiet=True)

    def reset_all(self) -> None:
        with self._lock:
            self._s = AggregatorSnapshot()
            self._epc_seen.clear()

    def clear_config_error(self) -> None:
        with self._lock:
            self._s.config_error = None

    # ------------------------------------------------------------------
    # event application
    # ------------------------------------------------------------------
    def apply(self, events: List[LogEvent]) -> None:
        for ev in events:
            self._apply_one(ev)

    def _apply_one(self, ev: LogEvent) -> None:
        with self._lock:
            n = ev.name
            if n == LogEventName.ENB_BANNER:
                # new boot round of the eNB: rewind its pipeline and S1
                if self._s.enb_stage != EnbStage.DOWN:
                    self._set_enb_stage(EnbStage.DOWN, quiet=True)
                self._set_s1(S1State.S1_DOWN, quiet=True)
                self._s.usrp_log_error = None
                self._set_enb_stage(EnbStage.STARTING)
            elif n == LogEventName.ENB_CONFIG_LOADING:
                self._set_enb_stage(EnbStage.CONFIG_LOADING)
            elif n == LogEventName.ENB_RF_OPENED:
                self._s.last_rf_ready_time = ev.ts
                self._set_enb_stage(EnbStage.RF_READY)
                self._publish(EventType.ENB_RF_READY, Severity.INFO,
                              "RF device 'UHD' successfully opened")
            elif n in (LogEventName.ENB_STARTED, LogEventName.ENB_FREQ_SET):
                self._set_enb_stage(EnbStage.RUNNING)
            elif n == LogEventName.EPC_BANNER:
                if self._s.epc_stage != EpcStage.DOWN:
                    self._set_epc_stage(EpcStage.DOWN, quiet=True)
                    self._epc_seen.clear()
                self._set_epc_stage(EpcStage.STARTING)
            elif n == LogEventName.EPC_INIT_LINE:
                self._epc_seen.add(ev.detail)
                missing = [l for l in self._epc_init_lines if l not in self._epc_seen]
                if self._s.epc_stage == EpcStage.STARTING and not missing:
                    self._set_epc_stage(EpcStage.READY)
                    self._publish(EventType.EPC_READY, Severity.INFO,
                                  "srsEPC initialised (HSS/MME/SPGW ready)")
            elif n == LogEventName.EPC_S1_REQUEST:
                if self._s.s1_state in (S1State.S1_DOWN, S1State.S1_LOST):
                    self._set_s1(S1State.S1_CONNECTING)
            elif n == LogEventName.EPC_S1_RESPONSE:
                was = self._s.s1_state
                self._s.last_s1_ready_time = ev.ts
                self._set_s1(S1State.S1_READY)
                if was != S1State.S1_READY:
                    self._publish(EventType.S1_CONNECTED, Severity.INFO,
                                  "S1 Setup Response sent — S1 ready")
            elif n == LogEventName.EPC_SCTP_SHUTDOWN:
                self._s.last_sctp_shutdown_time = ev.ts
                was = self._s.s1_state
                if was == S1State.S1_READY:
                    self._set_s1(S1State.S1_LOST)
                    self._publish(EventType.S1_DISCONNECTED, Severity.ERROR,
                                  "SCTP Association Shutdown — S1 lost")
                    self._publish(EventType.S1_LOST, Severity.ERROR,
                                  "S1 was READY, then SCTP association shut down")
                elif was != S1State.S1_CONFIG_ERROR:
                    # shutdown during setup: not a fault, just retry
                    self._set_s1(S1State.S1_DOWN)
            elif n == LogEventName.EPC_S1_FAILURE:
                cause = ev.detail or "unknown cause"
                self._set_s1(S1State.S1_CONFIG_ERROR)
                self._s.config_error = f"S1 Setup Failure: {cause}"
                self._publish(EventType.CONFIG_ERROR, Severity.CRITICAL,
                              f"S1 Setup Failure — cause: {cause} "
                              f"(config mismatch, restart will not help)")
            elif n == LogEventName.RF_INIT_ERROR:
                # 可恢复的 RF 初始化失败（B210 USB 句柄未释放 / USB 抖动）：
                # 实机表现是 eNB 随即退出（status=255），看门狗按"进程死亡"
                # 走正常恢复（重启 eNB 即可），绝不能进 CONFIG_ERROR/FAULT。
                self._s.usrp_log_error = "RF init failed (uhd_init failed)"
                self._publish(EventType.USRP_DISCONNECTED, Severity.ERROR,
                              "RF init failed — UHD could not open the device; "
                              "eNB will exit, watchdog recovers by restart")
            elif n == LogEventName.UHD_NO_DEVICE:
                self._s.usrp_log_error = "No UHD Devices Found"
                self._publish(EventType.USRP_DISCONNECTED, Severity.ERROR,
                              "No UHD Devices Found (eNB log)")
            elif n == LogEventName.UHD_FW_MISSING:
                self._s.config_error = "USRP firmware missing (usrp_b200_fw.hex)"
                self._publish(EventType.CONFIG_ERROR, Severity.CRITICAL,
                              "Could not find usrp_b200_fw.hex — run "
                              "uhd_images_downloader, restart will not help")
            elif n == LogEventName.RF_TX_ERROR:
                self._publish(EventType.RF_TX_ERROR, Severity.ERROR,
                              f"RF TX error: {ev.raw[:120]}")
            elif n == LogEventName.RF_UNDERFLOW:
                self._publish(EventType.RF_REALTIME_WARNING, Severity.WARNING,
                              "RF underflow detected")
            elif n == LogEventName.CONFIG_FILE_ERROR:
                self._s.config_error = f"Couldn't open {ev.detail or 'config file'}"
                self._publish(EventType.CONFIG_ERROR, Severity.CRITICAL,
                              f"Couldn't open {ev.detail or 'config file'} — "
                              f"fix the file, restart will not help")
            elif n == LogEventName.CONFIG_OPTION_ERROR:
                self._s.config_error = f"Unrecognised options: {ev.detail}"
                self._publish(EventType.CONFIG_ERROR, Severity.CRITICAL,
                              f"Unrecognised options: {ev.detail} — "
                              f"config/srsRAN version mismatch")

    # ------------------------------------------------------------------
    @staticmethod
    def _stage_order(stage: EnbStage) -> int:
        return {EnbStage.DOWN: 0, EnbStage.STARTING: 1, EnbStage.CONFIG_LOADING: 2,
                EnbStage.RF_READY: 3, EnbStage.RUNNING: 4}[stage]

    def _set_enb_stage(self, stage: EnbStage, quiet: bool = False) -> None:
        if self._s.enb_stage == stage:
            return
        old = self._s.enb_stage
        # only forward transitions within one boot round; DOWN resets freely
        if stage != EnbStage.DOWN and self._stage_order(stage) <= self._stage_order(old):
            return
        self._s.enb_stage = stage
        self._s.enb_stage_since = time.time()
        if not quiet and old != EnbStage.DOWN:
            self._publish(EventType.ENB_STAGE_CHANGED, Severity.INFO,
                          f"eNB stage: {old.value} -> {stage.value}")

    def _set_epc_stage(self, stage: EpcStage, quiet: bool = False) -> None:
        if self._s.epc_stage == stage:
            return
        old = self._s.epc_stage
        if stage != EpcStage.DOWN and stage != EpcStage.READY and old == EpcStage.READY:
            return  # no backwards transition without a reset
        self._s.epc_stage = stage
        self._s.epc_stage_since = time.time()
        if not quiet and stage == EpcStage.STARTING:
            pass  # banner event is too chatty to journal twice

    def _set_s1(self, state: S1State, quiet: bool = False) -> None:
        if self._s.s1_state == state:
            return
        self._s.s1_state = state
        self._s.s1_state_since = time.time()

    def _publish(self, type_: str, severity: Severity, message: str) -> None:
        if self._bus is not None:
            self._bus.publish_event(type_, source="Watchdog", severity=severity,
                                    message=message)
