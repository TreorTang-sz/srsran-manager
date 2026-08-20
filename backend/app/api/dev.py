"""Development fault-injection API.

Only mounted in mock mode (or when security.dev_fault_api is explicitly
enabled in the config — never by default in production).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import get_runtime, require_token
from app.mock.faults import FAULT_NAMES, FaultController
from app.runtime import Runtime

router = APIRouter(tags=["dev"])


def _faults(runtime: Runtime) -> FaultController:
    if runtime.faults is None:
        raise HTTPException(status_code=404, detail="fault injection not available (not mock mode)")
    return runtime.faults


@router.get("/api/dev/faults")
def list_faults(runtime: Runtime = Depends(get_runtime)) -> dict:
    if runtime.faults is None:
        return {"available": False, "faults": FAULT_NAMES}
    return {"available": True, "faults": FAULT_NAMES, "active": runtime.faults.active_faults()}


# NOTE: /clear must be registered BEFORE /{name}, otherwise the path
# parameter route swallows it.
@router.post("/api/dev/fault/clear", dependencies=[Depends(require_token)])
def clear_faults(runtime: Runtime = Depends(get_runtime)) -> dict:
    controller = _faults(runtime)
    return controller.clear()


@router.post("/api/dev/fault/{name}", dependencies=[Depends(require_token)])
def inject_fault(
    name: str,
    runtime: Runtime = Depends(get_runtime),
    times: int = Query(default=1, ge=1, le=10),
) -> dict:
    controller = _faults(runtime)
    if name not in FAULT_NAMES:
        raise HTTPException(status_code=404, detail=f"unknown fault '{name}', options: {FAULT_NAMES}")
    return controller.inject(name, times)
