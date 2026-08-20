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
    STOPPED = "STOPPED"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    WARNING = "WARNING"
    RECOVERING = "RECOVERING"
    FAULT = "FAULT"


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
    UE_ATTACHED = "UE_ATTACHED"
    UE_DETACHED = "UE_DETACHED"
    USRP_CONNECTED = "USRP_CONNECTED"
    USRP_DISCONNECTED = "USRP_DISCONNECTED"
    ENB_CRASH = "ENB_CRASH"
    EPC_CRASH = "EPC_CRASH"
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
    connected: bool = False
    detail: str = ""


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
    s1_connected: bool = False
    usrp_connected: bool = False

    @property
    def is_critical(self) -> bool:
        return self.level == HealthLevel.CRITICAL

    @property
    def is_healthy_for_recovery(self) -> bool:
        """Recovery succeeds when no CRITICAL issue remains.

        WARNING-level issues (high CPU / temperature) do not fail a recovery.
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
    watchdog: WatchdogStatus = Field(default_factory=WatchdogStatus)
    services: Dict[str, ServiceStatus] = Field(default_factory=dict)
    s1: S1Status = Field(default_factory=S1Status)
    usrp: UsrpStatus = Field(default_factory=UsrpStatus)
    system: SystemMetrics = Field(default_factory=SystemMetrics)
    enb_metrics: EnbMetrics = Field(default_factory=EnbMetrics)
    core_traffic: CoreTraffic = Field(default_factory=CoreTraffic)
    recent_events: List[EventRecord] = Field(default_factory=list)
