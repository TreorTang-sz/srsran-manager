"""System metrics endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import get_runtime
from app.models import ServiceName
from app.runtime import Runtime

router = APIRouter(tags=["system"])


@router.get("/api/system")
def get_system(runtime: Runtime = Depends(get_runtime)) -> dict:
    return runtime.providers.system.get_metrics().model_dump(mode="json")


@router.get("/api/services")
def get_services(runtime: Runtime = Depends(get_runtime)) -> dict:
    return {
        "epc": runtime.providers.process.status(ServiceName.EPC).model_dump(mode="json"),
        "enb": runtime.providers.process.status(ServiceName.ENB).model_dump(mode="json"),
    }
