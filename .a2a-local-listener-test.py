import asyncio
import json
import os
import sys
import urllib.error
import urllib.request

sys.path.insert(0, "/opt/hermes")
os.environ["A2A_BEARER_TOKEN"] = "local-test-token"
os.environ["A2A_HOST"] = "127.0.0.1"
os.environ["A2A_PORT"] = "19900"

from gateway.config import PlatformConfig
from plugins.platforms.a2a.adapter import A2AAdapter


async def main():
    adapter = A2AAdapter(PlatformConfig(enabled=True, extra={}))
    assert await adapter.connect()
    req = urllib.request.Request(
        "http://127.0.0.1:19900/.well-known/agent-card.json",
        headers={"Authorization": "Bearer local-test-token"},
    )
    with urllib.request.urlopen(req, timeout=5) as response:
        card = json.load(response)
    assert card["supportedInterfaces"][0]["protocolVersion"] == "1.0"
    bad = urllib.request.Request(
        "http://127.0.0.1:19900/",
        data=b'{"jsonrpc":"2.0","id":"probe","method":"GetTask","params":{"id":"missing"}}',
        headers={"Content-Type": "application/json", "A2A-Version": "1.0"},
        method="POST",
    )
    try:
        urllib.request.urlopen(bad, timeout=5)
    except urllib.error.HTTPError as error:
        assert error.code == 401
    else:
        raise AssertionError("unauthenticated request accepted")
    await adapter.disconnect()
    print(json.dumps({
        "listener": "started_and_stopped",
        "bind": "127.0.0.1:19900",
        "agent_card": "a2a_1.0",
        "unauthenticated": "401",
    }))


asyncio.run(main())
