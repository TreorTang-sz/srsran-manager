"""Provider abstractions.

Every subsystem of srsRAN Manager talks to these interfaces only:

  SystemMetricsProvider   - CPU / RAM / disk / net / temperature / uptime
  ProcessManager          - start/stop/restart/status of epc & enb services
  UsrpProvider            - USRP B210 presence via UHD
  S1Provider              - eNB <-> EPC S1 link state
  SrsranMetricsProvider   - srsENB metrics (UE list, DL/UL bitrates)
  CoreTrafficProvider     - core network traffic (SGi / GTP interfaces)

Implementations:
  app.mock.*    - Windows / development simulation (MOCK_MODE)
  app.providers.linux_* - production implementation on Ubuntu (ARM64)
"""
from app.providers.base import (
    CoreTrafficProvider,
    ProcessManager,
    S1Provider,
    SrsranMetricsProvider,
    SystemMetricsProvider,
    UsrpProvider,
)
from app.providers.factory import Providers, build_providers

__all__ = [
    "CoreTrafficProvider",
    "ProcessManager",
    "S1Provider",
    "SrsranMetricsProvider",
    "SystemMetricsProvider",
    "UsrpProvider",
    "Providers",
    "build_providers",
]
