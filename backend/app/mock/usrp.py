"""Mock USRP B210 provider (Windows dev mode)."""
from __future__ import annotations

import time

from app.mock.world import MockWorld
from app.models import UsrpStatus


class MockUsrpProvider:
    def __init__(self, world: MockWorld) -> None:
        self.world = world

    def get_status(self) -> UsrpStatus:
        w = self.world
        if w.usrp_fault:
            return UsrpStatus(
                ts=time.time(),
                connected=False,
                device="B210",
                serial="F5A6B7C8",
                detail="Device disconnected (USB) — uhd_find_devices returns no device",
            )
        return UsrpStatus(
            ts=time.time(),
            connected=True,
            device="B210",
            serial="F5A6B7C8",
            detail="UHD Device 0 | Product: B210 | Type: b200 | Master clock 30.72 MHz",
        )
