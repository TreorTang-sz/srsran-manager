"""Whole-network control endpoints (dangerous — token required)."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import get_runtime, require_token
from app.runtime import Runtime

router = APIRouter(tags=["network"])


@router.post("/api/network/start", dependencies=[Depends(require_token)])
def start_network(runtime: Runtime = Depends(get_runtime)) -> dict:
    return runtime.control.start_network()


@router.post("/api/network/stop", dependencies=[Depends(require_token)])
def stop_network(runtime: Runtime = Depends(get_runtime)) -> dict:
    return runtime.control.stop_network()


@router.post("/api/network/restart", dependencies=[Depends(require_token)])
def restart_network(runtime: Runtime = Depends(get_runtime)) -> dict:
    return runtime.control.restart_network()
