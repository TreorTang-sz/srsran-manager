"""srsENB endpoints: status + control."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import get_runtime, require_token
from app.models import ServiceName
from app.runtime import Runtime

router = APIRouter(tags=["enb"])


@router.get("/api/enb")
def get_enb(runtime: Runtime = Depends(get_runtime)) -> dict:
    snap = runtime.snapshot()
    return {
        "service": snap.services.get("enb").model_dump(mode="json") if snap.services.get("enb") else None,
        "metrics": snap.enb_metrics.model_dump(mode="json"),
    }


@router.post("/api/enb/start", dependencies=[Depends(require_token)])
def start_enb(runtime: Runtime = Depends(get_runtime)) -> dict:
    return runtime.control.start_service(ServiceName.ENB)


@router.post("/api/enb/stop", dependencies=[Depends(require_token)])
def stop_enb(runtime: Runtime = Depends(get_runtime)) -> dict:
    return runtime.control.stop_service(ServiceName.ENB)


@router.post("/api/enb/restart", dependencies=[Depends(require_token)])
def restart_enb(runtime: Runtime = Depends(get_runtime)) -> dict:
    return runtime.control.restart_service(ServiceName.ENB)
