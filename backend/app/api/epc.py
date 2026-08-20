"""srsEPC endpoints: status + control."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import get_runtime, require_token
from app.models import ServiceName
from app.runtime import Runtime

router = APIRouter(tags=["epc"])


@router.get("/api/epc")
def get_epc(runtime: Runtime = Depends(get_runtime)) -> dict:
    snap = runtime.snapshot()
    service = snap.services.get("epc")
    return {
        "service": service.model_dump(mode="json") if service else None,
    }


@router.post("/api/epc/start", dependencies=[Depends(require_token)])
def start_epc(runtime: Runtime = Depends(get_runtime)) -> dict:
    return runtime.control.start_service(ServiceName.EPC)


@router.post("/api/epc/stop", dependencies=[Depends(require_token)])
def stop_epc(runtime: Runtime = Depends(get_runtime)) -> dict:
    return runtime.control.stop_service(ServiceName.EPC)


@router.post("/api/epc/restart", dependencies=[Depends(require_token)])
def restart_epc(runtime: Runtime = Depends(get_runtime)) -> dict:
    return runtime.control.restart_service(ServiceName.EPC)
