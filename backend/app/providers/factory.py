"""Composition root: builds the provider set for the current mode.

This is the ONLY module allowed to know about 'mock vs linux'.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from app.config import AppConfig
from app.providers.base import (
    CoreTrafficProvider,
    ProcessManager,
    S1Provider,
    SrsranMetricsProvider,
    SystemMetricsProvider,
    UsrpProvider,
)


@dataclass
class Providers:
    system: SystemMetricsProvider
    process: ProcessManager
    usrp: UsrpProvider
    s1: S1Provider
    srsran: SrsranMetricsProvider
    core_traffic: CoreTrafficProvider
    # Present only in mock mode; None in production (Linux) mode.
    mock_world: Optional[object] = None


def build_providers(config: AppConfig) -> Providers:
    mode = config.resolved_mode
    if mode == "mock":
        from app.mock.world import MockWorld
        from app.mock.process import MockProcessManager
        from app.mock.srsran import MockCoreTrafficProvider, MockS1Provider, MockSrsranMetricsProvider
        from app.mock.system import MockSystemMetricsProvider
        from app.mock.usrp import MockUsrpProvider

        world = MockWorld(config)
        return Providers(
            system=MockSystemMetricsProvider(world),
            process=MockProcessManager(world),
            usrp=MockUsrpProvider(world),
            s1=MockS1Provider(world),
            srsran=MockSrsranMetricsProvider(world),
            core_traffic=MockCoreTrafficProvider(world),
            mock_world=world,
        )

    from app.providers.linux_network import LinuxCoreTrafficProvider, LinuxS1Provider
    from app.providers.linux_process import LinuxSystemdProcessManager
    from app.providers.linux_srsran import LinuxSrsranMetricsProvider
    from app.providers.linux_system import LinuxSystemMetricsProvider
    from app.providers.linux_usrp import LinuxUhdUsrpProvider

    return Providers(
        system=LinuxSystemMetricsProvider(),
        process=LinuxSystemdProcessManager(config),
        usrp=LinuxUhdUsrpProvider(config),
        s1=LinuxS1Provider(config),
        srsran=LinuxSrsranMetricsProvider(config),
        core_traffic=LinuxCoreTrafficProvider(config),
        mock_world=None,
    )
