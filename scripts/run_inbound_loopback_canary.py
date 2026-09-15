#!/usr/bin/env python3
"""Run a bounded, authenticated inbound A2A canary for offline tests.

The listener is deliberately a foreground child-process harness.  It uses the
production A2AAdapter/RequestHandler and only replaces the gateway's model
completion with an explicitly labelled callback fixture.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys

from gateway.config import PlatformConfig
from plugins.platforms.a2a import protocol
from plugins.platforms.a2a.adapter import A2AAdapter


async def main() -> None:
    port = int(os.environ["A2A_CANARY_PORT"])
    adapter = A2AAdapter(PlatformConfig(enabled=True, extra={"port": port}))

    async def callback_fixture(event):
        # This is not a model invocation. Keep the distinction visible in the
        # result consumed by the parent test and in the evidence.
        await adapter.send(
            event.source.chat_id,
            "CALLBACK_FIXTURE_REPLY: " + event.text,
            metadata={"notify": True},
        )

    adapter.handle_message = callback_fixture  # type: ignore[assignment]
    adapter._message_handler = object()  # enable the real dispatch path
    if not await adapter.connect():
        raise RuntimeError("adapter failed to bind loopback canary")
    print(json.dumps({"ready": True, "port": port, "listener": "loopback-only", "simulation": True}), flush=True)
    try:
        # Keep the listener in this foreground process group. STOP is sent by
        # the parent after HTTP assertions; no daemon survives the test.
        await asyncio.to_thread(sys.stdin.readline)
    finally:
        await adapter.disconnect()
        print(json.dumps({"stopped": True, "cleanup": True}), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
