"""Shared data models used across providers, watchdog and API layers.

These models are the *internal contract*: both Mock providers (Windows dev)
and Linux providers (production) must produce instances of these types,
so business logic never cares about the platform.
"""
from __future__ import annotations

import time
from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, Field

from app import __version__


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------
class ServiceName(str, Enum):
    EPC = "epc"
    ENB = "enb"


class ServiceState(str, Enum):
    STOPPED = "STOPPED"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    STOPPING = "STOPPING"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"


class WatchdogState(str, Enum):
    """Watchdog top-level states (log-event driven startup pipeline).

    Startup path (derived from real srsRAN logs):
      STOPPED -> STARTING -> EPC_READY -> ENB_RF_INITIALIZING ->
      ENB_RUNNING -> S1_CONNECTING -> RUNNING
    Side states:
      WARNING     ready but a soft threshold is exceeded (CPU/temp/...)
      DEGRADED    was S1_READY, then S1 lost (SCTP Association Shutdown)
      RECOVERING  automatic recovery in progress
      FAULT       manual action required (config error / attempts exhausted)
    """
    STOPPED = "STOPPED"
    STARTING = "STARTING"
    EPC_READY = "EPC_READY"
    ENB_RF_INITIALIZING = "ENB_RF_INITIALIZING"
    ENB_RUNNING = "ENB_RUNNING"
    S1_CONNECTING = "S1_CONNECTING"
    RUNNING = "RUNNING"
    WARNING = "WARNING"
    DEGRADED = "DEGRADED"
    RECOVERING = "RECOVERING"
    FAULT = "FAULT"


# Startup-path states, in order (used to derive the watchdog state from
# the component stages observed in the logs).
STARTUP_PATH: list["WatchdogState"] = [
    WatchdogState.STOPPED,
    WatchdogState.STARTING,
    WatchdogState.EPC_READY,
    WatchdogState.ENB_RF_INITIALIZING,
    WatchdogState.ENB_RUNNING,
    WatchdogState.S1_CONNECTING,
    WatchdogState.RUNNING,
]


class EnbStage(str, Enum):
    """srsENB lifecycle stage, derived from real srsENB journal logs.

    DOWN            process not running / no recent log evidence
    STARTING        banner seen: "---  Software Radio Systems LTE eNodeB  ---"
    CONFIG_LOADING  "Reading configuration file ..."
    RF_READY        "RF device 'UHD' successfully opened" (UHD + USRP OK)
    RUNNING         "==== eNodeB started ==="
    """
    DOWN = "DOWN"
    STARTING = "STARTING"
    CONFIG_LOADING = "CONFIG_LOADING"
    RF_READY = "RF_READY"
    RUNNING = "RUNNING"


class EpcStage(str, Enum):
    """srsEPC lifecycle stage, derived from real srsEPC journal logs.

    READY requires ALL initialisation lines (HSS/MME/SPGW ... Initialized).
    """
    DOWN = "DOWN"
    STARTING = "STARTING"
    READY = "READY"


class S1State(str, Enum):
    """S1 link state machine (log-event driven, replaces a bare bool).

    S1_DOWN           no S1AP activity yet (eNB not ready / just started)
    S1_CONNECTING     EPC log: "Received S1 Setup Request."
    S1_READY          EPC log: "Sending S1 Setup Response"
    S1_LOST           was READY, then "SCTP Association Shutdown"
    S1_CONFIG_ERROR   "S1 Setup Failure cause: misc - unknown-PLMN" (or
                      similar) — restarting is pointless, config fix needed
    """
    S1_DOWN = "S1_DOWN"
    S1_CONNECTING = "S1_CONNECTING"
    S1_READY = "S1_READY"
    S1_LOST = "S1_LOST"
    S1_CONFIG_ERROR = "S1_CONFIG_ERROR"


class HealthLevel(str, Enum):
    OK = "OK"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class Severity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class LogLevel(str, Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


# ---------------------------------------------------------------------------
# Event types (persisted in SQLite + pushed via WebSocket)
# ---------------------------------------------------------------------------
class EventType:
    SYSTEM_START = "SYSTEM_START"
    SYSTEM_SHUTDOWN = "SYSTEM_SHUTDOWN"
    EPC_STARTED = "EPC_STARTED"
    ENB_STARTED = "ENB_STARTED"
    EPC_STOPPED = "EPC_STOPPED"
    ENB_STOPPED = "ENB_STOPPED"
    S1_CONNECTED = "S1_CONNECTED"
    S1_DISCONNECTED = "S1_DISCONNECTED"
    S1_LOST = "S1_LOST"
    UE_ATTACHED = "UE_ATTACHED"
    UE_DETACHED = "UE_DETACHED"
    USRP_CONNECTED = "USRP_CONNECTED"
    USRP_DISCONNECTED = "USRP_DISCONNECTED"
    ENB_CRASH = "ENB_CRASH"
    EPC_CRASH = "EPC_CRASH"
    # log-event driven component stages (real srsRAN journal evidence)
    ENB_RF_READY = "ENB_RF_READY"
    EPC_READY = "EPC_READY"
    ENB_STAGE_CHANGED = "ENB_STAGE_CHANGED"
    RF_TX_ERROR = "RF_TX_ERROR"
    RF_REALTIME_WARNING = "RF_REALTIME_WARNING"
    CONFIG_ERROR = "CONFIG_ERROR"
    AUTO_RECOVERY_STARTED = "AUTO_RECOVERY_STARTED"
    AUTO_RECOVERY_SUCCESS = "AUTO_RECOVERY_SUCCESS"
    AUTO_RECOVERY_FAILED = "AUTO_RECOVERY_FAILED"
    FAULT_ENTERED = "FAULT_ENTERED"
    WATCHDOG_STATE_CHANGED = "WATCHDOG_STATE_CHANGED"
    MANUAL_ACTION = "MANUAL_ACTION"
    FAULT_INJECTED = "FAULT_INJECTED"
    FAULT_CLEARED = "FAULT_CLEARED"


# ---------------------------------------------------------------------------
# Provider data models
# ---------------------------------------------------------------------------
class ServiceStatus(BaseModel):
    name: str
    state: ServiceState = ServiceState.UNKNOWN
    pid: Optional[int] = None
    detail: str = ""
    # Log-derived lifecycle stage (EnbStage for enb, EpcStage for epc).
    # Evidence-based, independent of the systemd process state.
    stage: Optional[str] = None
    stage_since: Optional[float] = None


class SystemMetrics(BaseModel):
    ts: float = Field(default_factory=time.time)
    cpu_percent: float = 0.0
    cpu_per_core: List[float] = Field(default_factory=list)
    mem_total_mb: float = 0.0
    mem_used_mb: float = 0.0
    mem_percent: float = 0.0
    swap_total_mb: float = 0.0
    swap_used_mb: float = 0.0
    disk_total_gb: float = 0.0
    disk_used_gb: float = 0.0
    disk_percent: float = 0.0
    disk_read_mbps: float = 0.0
    disk_write_mbps: float = 0.0
    net_rx_mbps: float = 0.0
    net_tx_mbps: float = 0.0
    cpu_temp_c: Optional[float] = None
    uptime_s: float = 0.0


class UsrpStatus(BaseModel):
    ts: float = Field(default_factory=time.time)
    connected: bool = False
    device: Optional[str] = None
    serial: Optional[str] = None
    detail: str = ""


class S1Status(BaseModel):
    ts: float = Field(default_factory=time.time)
    # Log-event driven S1 state machine (primary source of truth).
    state: S1State = S1State.S1_DOWN
    # Convenience view for clients: True only when state == S1_READY.
    connected: bool = False
    detail: str = ""
    # timestamps (epoch seconds) from the log aggregator
    last_s1_ready_time: Optional[float] = None
    last_sctp_shutdown_time: Optional[float] = None


class UEInfo(BaseModel):
    """One attached UE.

    NOTE: IMSI is intentionally NOT part of the default model. If IMSI
    display is required later, extend this model with an optional field
    populated only from a trusted source (e.g. srsEPC HSS/Subscriber DB).
    Never fabricate identity data.
    """
    rnti: int
    cqi: Optional[int] = None
    mcs_dl: Optional[int] = None
    mcs_ul: Optional[int] = None
    dl_bitrate_mbps: float = 0.0
    ul_bitrate_mbps: float = 0.0
    last_seen: float = Field(default_factory=time.time)
    state: str = "CONNECTED"


class EnbMetrics(BaseModel):
    ts: float = Field(default_factory=time.time)
    ue_count: int = 0
    ues: List[UEInfo] = Field(default_factory=list)
    dl_bitrate_mbps: float = 0.0
    ul_bitrate_mbps: float = 0.0
    source: str = "unknown"


class CoreTraffic(BaseModel):
    ts: float = Field(default_factory=time.time)
    rx_mbps: float = 0.0
    tx_mbps: float = 0.0
    interfaces: List[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Watchdog / snapshot models
# ---------------------------------------------------------------------------
class WatchdogStatus(BaseModel):
    state: WatchdogState = WatchdogState.STOPPED
    desired_running: bool = False
    consecutive_failures: int = 0
    max_recovery_attempts: int = 3
    total_recoveries: int = 0
    state_since: float = Field(default_factory=time.time)
    last_health_level: HealthLevel = HealthLevel.OK
    last_issues: List[str] = Field(default_factory=list)
    last_error: str = ""
    # Why we are in FAULT ("" when not in FAULT): CONFIG_ERROR / e.g.
    # "unknown-PLMN", or "recovery attempts exhausted".
    fault_reason: str = ""


class HealthIssue(BaseModel):
    component: str
    level: HealthLevel
    message: str


class HealthReport(BaseModel):
    ts: float = Field(default_factory=time.time)
    level: HealthLevel = HealthLevel.OK
    issues: List[HealthIssue] = Field(default_factory=list)
    epc_running: bool = False
    enb_running: bool = False
    # log-derived component view (authoritative for health)
    epc_stage: EpcStage = EpcStage.DOWN
    enb_stage: EnbStage = EnbStage.DOWN
    s1_state: S1State = S1State.S1_DOWN
    # True when a configuration error was observed in the logs — restarting
    # cannot help; the watchdog must enter FAULT without recovery attempts.
    config_error: Optional[str] = None
    # stage that timed out, if any (e.g. "ENB_RF"), for diagnostics
    stage_timeout: Optional[str] = None

    @property
    def s1_connected(self) -> bool:
        return self.s1_state == S1State.S1_READY

    @property
    def rf_ready(self) -> bool:
        return self.enb_stage in (EnbStage.RF_READY, EnbStage.RUNNING)

    @property
    def is_critical(self) -> bool:
        return self.level == HealthLevel.CRITICAL

    @property
    def is_healthy_for_recovery(self) -> bool:
        """Recovery succeeds when no CRITICAL issue remains.

        WARNING-level issues (high CPU / temperature / underflow) do not
        fail a recovery.
        """
        return self.level != HealthLevel.CRITICAL


class EventRecord(BaseModel):
    id: Optional[int] = None
    ts: str = ""
    type: str = ""
    source: str = ""
    severity: Severity = Severity.INFO
    message: str = ""
    data: Dict = Field(default_factory=dict)


class LogRecord(BaseModel):
    id: Optional[int] = None
    ts: str = ""
    level: str = "INFO"
    module: str = ""
    message: str = ""


class ThroughputPoint(BaseModel):
    ts: float
    lte_dl: float = 0.0
    lte_ul: float = 0.0
    core_dl: float = 0.0
    core_ul: float = 0.0


class Snapshot(BaseModel):
    """Combined live status pushed via WebSocket and served by /api/status."""
    ts: float = Field(default_factory=time.time)
    mode: str = "mock"
    version: str = __version__  # deployment identification (matches git tag)
    watchdog: WatchdogStatus = Field(default_factory=WatchdogStatus)
    services: Dict[str, ServiceStatus] = Field(default_factory=dict)
    s1: S1Status = Field(default_factory=S1Status)
    usrp: UsrpStatus = Field(default_factory=UsrpStatus)
    system: SystemMetrics = Field(default_factory=SystemMetrics)
    enb_metrics: EnbMetrics = Field(default_factory=EnbMetrics)
    core_traffic: CoreTraffic = Field(default_factory=CoreTraffic)
    recent_events: List[EventRecord] = Field(default_factory=list)
