"""WebSocket endpoint — pushes the full snapshot once per second.

Read-only data (no token needed). The browser never polls; all live
values (system metrics, services, S1, USRP, UEs, throughput, watchdog
state, recent events) arrive through this socket.
"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.runtime import Runtime

router = APIRouter(tags=["ws"])


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    await websocket.accept()
    runtime: Runtime = websocket.app.state.runtime
    try:
        while True:
            snapshot = runtime.snapshot()
            payload = snapshot.model_dump(mode="json")
            payload["type"] = "snapshot"
            await websocket.send_json(payload)
            await asyncio.sleep(1.0)
    except WebSocketDisconnect:
        return
    except Exception:  # noqa: BLE001
        return
