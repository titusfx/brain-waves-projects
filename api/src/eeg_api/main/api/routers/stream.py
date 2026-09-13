"""The real-time channel: one WebSocket carrying the stream and the session events.

A WebSocket rather than Server-Sent Events or polling, for one reason: the browser
must both receive the sample stream and be told about a state change *immediately*,
and the flow runner has to keep running whether or not anyone is watching. A socket
makes "the tab was closed" a non-event.

Message types sent to the client:

``hello``    once, on connect: sample rate, channels, device, catalog pointer
``history``  once, on connect: the last few seconds, so the chart is not blank
``tick``     ~10/s: new samples, per-channel metrics, alpha, session state
``session``  immediately, on every state change of a running flow
``source``   immediately, when the stream is switched
``recording``immediately, when a dataset starts or finishes
``ping``     every 10 s of silence, so a dropped connection is noticed
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from eeg_api.services.hub import AcquisitionHub


router = APIRouter(tags=["stream"])

#: Send a ping after this long without a message, which also detects a dead socket.
IDLE_PING_SECONDS = 10.0

#: Seconds of history to replay on connect.
HISTORY_SECONDS = 8.0


@router.websocket("/ws/stream")
async def stream(websocket: WebSocket) -> None:
    hub: AcquisitionHub = websocket.app.state.hub
    await websocket.accept()
    subscriber = hub.subscribe()
    try:
        await websocket.send_json(hub.hello())
        await websocket.send_json({"type": "history", **hub.snapshot(HISTORY_SECONDS, 1200)})
        while True:
            try:
                message: dict[str, Any] = await asyncio.wait_for(
                    subscriber.get(), timeout=IDLE_PING_SECONDS
                )
            except TimeoutError:
                await websocket.send_json({"type": "ping", "t": round(time.monotonic(), 3)})
                continue
            await websocket.send_json(message)
    except WebSocketDisconnect:
        pass
    except RuntimeError:
        # Raised when the socket is closed between the ping and the send; the client
        # is gone either way, and a traceback here would be noise, not a fault.
        pass
    finally:
        hub.unsubscribe(subscriber)
