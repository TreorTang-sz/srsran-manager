"""Event and log query endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.api.deps import get_runtime
from app.runtime import Runtime

router = APIRouter(tags=["history"])


@router.get("/api/events")
def get_events(
    runtime: Runtime = Depends(get_runtime),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    type: str | None = Query(default=None),
    severity: str | None = Query(default=None),
    source: str | None = Query(default=None),
) -> dict:
    records = runtime.event_store.query_events(
        limit=limit, offset=offset, type=type, severity=severity, source=source)
    return {
        "count": len(records),
        "total": runtime.event_store.event_count(type=type),
        "events": [r.model_dump(mode="json") for r in records],
    }


@router.get("/api/logs")
def get_logs(
    runtime: Runtime = Depends(get_runtime),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    level: str | None = Query(default=None),
    module: str | None = Query(default=None),
) -> dict:
    records = runtime.log_store.query_logs(
        limit=limit, offset=offset, level=level, module=module)
    return {"count": len(records), "logs": [r.model_dump(mode="json") for r in records]}
