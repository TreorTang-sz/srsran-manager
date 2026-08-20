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


def service_state_is_running(state: ServiceState) -> bool:
    return state == ServiceState.RUNNING
