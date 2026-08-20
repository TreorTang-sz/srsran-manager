"""UE, USRP, S1 and throughput endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.api.deps import get_runtime
from app.runtime import Runtime

router = APIRouter(tags=["radio"])


@router.get("/api/ue")
def get_ues(runtime: Runtime = Depends(get_runtime)) -> dict:
    metrics = runtime.snapshot().enb_metrics
    return {
        "count": metrics.ue_count,
        "ues": [u.model_dump(mode="json") for u in metrics.ues],
    }


@router.get("/api/usrp")
def get_usrp(runtime: Runtime = Depends(get_runtime)) -> dict:
    return runtime.snapshot().usrp.model_dump(mode="json")


@router.get("/api/s1")
def get_s1(runtime: Runtime = Depends(get_runtime)) -> dict:
    return runtime.snapshot().s1.model_dump(mode="json")


@router.get("/api/throughput")
def get_throughput(
    runtime: Runtime = Depends(get_runtime),
    window: int = Query(default=60, ge=10, le=3600, description="seconds"),
) -> dict:
    points = runtime.history.window(window)
    return {
        "window": window,
        "count": len(points),
        "points": [p.model_dump(mode="json") for p in points],
    }
