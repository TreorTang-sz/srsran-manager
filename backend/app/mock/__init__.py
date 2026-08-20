"""Windows / development Mock Mode.

All mock providers serve data through the SAME interfaces as the Linux
providers (see app/providers/base.py). Business logic (watchdog, API,
frontend) cannot tell the difference.
"""
from app.mock.world import MockWorld

__all__ = ["MockWorld"]
