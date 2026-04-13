from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncGenerator

from fastapi import APIRouter, Depends, Request
from sse_starlette.sse import EventSourceResponse

from monitor.config import Settings, get_settings
from monitor.deps import get_dispatcher, get_snapshot
from monitor.services.alert_dispatcher import AlertDispatcher
from monitor.services.snapshot import SnapshotBuilder

log = logging.getLogger(__name__)

router = APIRouter(prefix="/sse", tags=["sse"])


@router.get("")
async def stream(
    request: Request,
    snap: SnapshotBuilder = Depends(get_snapshot),
    dispatcher: AlertDispatcher = Depends(get_dispatcher),
    settings: Settings = Depends(get_settings),
) -> EventSourceResponse:
    """Unified SSE stream: snapshot tick + alert push.

    Two event types:
      - `snapshot` — the full dashboard view, emitted every `sse_tick_seconds`
      - `alert`    — emitted immediately when the dispatcher receives one
    """
    alert_queue = dispatcher.subscribe_local()

    async def gen() -> AsyncGenerator[dict, None]:
        try:
            while not await request.is_disconnected():
                try:
                    alert = await asyncio.wait_for(
                        alert_queue.get(), timeout=settings.sse_tick_seconds
                    )
                    yield {
                        "event": "alert",
                        "data": alert.model_dump_json(),
                    }
                    continue
                except asyncio.TimeoutError:
                    pass

                try:
                    snapshot = await snap.build()
                    yield {
                        "event": "snapshot",
                        "data": snapshot.model_dump_json(),
                    }
                except Exception as exc:
                    log.exception("snapshot build failed in SSE loop")
                    yield {
                        "event": "error",
                        "data": json.dumps({"error": str(exc)}),
                    }
        finally:
            dispatcher.unsubscribe_local(alert_queue)

    return EventSourceResponse(gen())
