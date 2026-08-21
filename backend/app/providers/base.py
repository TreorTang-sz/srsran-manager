"""Abstract provider interfaces — the anti-corruption layer of the system.

Business logic (watchdog, API, frontend data) depends ONLY on these
interfaces. Platform differences are resolved once, in
``app.providers.factory.build_providers`` (the composition root).
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from app.models import (
    CoreTraffic,
    EnbMetrics,
    S1Status,
    ServiceName,
    ServiceState,
    ServiceStatus,
    SystemMetrics,
    UsrpStatus,
)


class SystemMetricsProvider(ABC):
    """System resource metrics (CPU, RAM, swap, disk, IO, network, temp)."""

    @abstractmethod
    def get_metrics(self) -> SystemMetrics:
        ...


class ProcessManager(ABC):
    """Lifecycle control for the srsEPC / srsENB services.

    Security contract: implementations expose ONLY the fixed operations
    start/stop/restart/status. No arbitrary command execution is possible
    through this interface.
    """

    @abstractmethod
    def start(self, service: ServiceName) -> ServiceStatus:
        ...

    @abstractmethod
    def stop(self, service: ServiceName) -> ServiceStatus:
        ...

    @abstractmethod
    def restart(self, service: ServiceName) -> ServiceStatus:
        ...

    @abstractmethod
    def status(self, service: ServiceName) -> ServiceStatus:
        ...


class UsrpProvider(ABC):
    """USRP B210 presence / UHD health."""

    @abstractmethod
    def get_status(self) -> UsrpStatus:
        ...


class S1Provider(ABC):
    """eNB <-> EPC S1 link state."""

    @abstractmethod
    def get_status(self) -> S1Status:
        ...


class SrsranMetricsProvider(ABC):
    """srsENB metrics (UE table, air-interface DL/UL bitrates).

    Implementations should prefer srsRAN's own metrics output
    (CSV / JSON) over screen-text scraping; format differences are
    normalised by a SrsranMetricsAdapter.
    """

    @abstractmethod
    def get_enb_metrics(self) -> EnbMetrics:
        ...


class CoreTrafficProvider(ABC):
    """Actual traffic on the core network side (SGi / GTP-U interfaces)."""

    @abstractmethod
    def get_traffic(self) -> CoreTraffic:
        ...


class LogLine:
    """One raw srsRAN log line with its origin and timestamp."""

    __slots__ = ("service", "ts", "message")

    def __init__(self, service: str, ts: float, message: str) -> None:
        self.service = service      # "enb" | "epc"
        self.ts = ts                # epoch seconds
        self.message = message

    def __repr__(self) -> str:  # pragma: no cover — debug helper
        return f"LogLine({self.service}, {self.ts:.3f}, {self.message[:60]!r})"


class LogSource(ABC):
    """Incremental source of srsEPC / srsENB log lines.

    Implementations MUST:
      * return each line exactly once (deduplicated across polls)
      * stamp lines with the source timestamp (journal time), not poll time
      * be safe to call from the watchdog thread

    Linux: journalctl (json output). Mock: scripted world timeline.
    The same LogEventParser consumes lines from either implementation
    (identical-interface principle).
    """

    @abstractmethod
    def poll(self) -> list[LogLine]:
        ...


def service_state_is_running(state: ServiceState) -> bool:
    return state == ServiceState.RUNNING
