"""Status endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import get_runtime
from app.runtime import Runtime

router = APIRouter(tags=["status"])


@router.get("/api/status")
def get_status(runtime: Runtime = Depends(get_runtime)) -> dict:
    """Full live snapshot (same payload as the WebSocket push)."""
    return runtime.snapshot().model_dump(mode="json")
