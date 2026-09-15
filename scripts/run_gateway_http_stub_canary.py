"""Foreground loopback HTTP canary for real GatewayRunner/A2A wiring.

The model boundary is explicitly simulated. Admission and authorization remain
those installed by GatewayRunner._wire_adapter_handlers.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import tempfile
import urllib.request
from pathlib import Path
from types import MethodType

from gateway.config import GatewayConfig, PlatformConfig
from gateway.run import GatewayRunner
from plugins.platforms.a2a.adapter import A2AAdapter

_TOKEN = "turn53-test-bearer"
_REPLY = "TURN53_SIMULATED_MODEL_REPLY"


def _task_from(payload: dict) -> dict:
    result = payload.get("result") or {}
    task = result.get("task") if isinstance(result, dict) else None
    return task if isinstance(task, dict) else result


def _sse_task(raw: bytes) -> dict:
    tasks = []
    for line in raw.decode("utf-8").splitlines():
        if not line.startswith("data:"):
            continue
        result = (json.loads(line[5:].strip()).get("result") or {})
        if "task" in result:
            task = result["task"]
            task_id = task.get("id")
        elif "statusUpdate" in result:
            update = result["statusUpdate"]
            task_id = update.get("taskId")
            task = {"id": task_id, "contextId": update.get("contextId"), "status": update.get("status", {})}
        elif "artifactUpdate" in result:
            update = result["artifactUpdate"]
            task_id = update.get("taskId")
            artifact = update.get("artifact", {})
            text = "".join(p.get("text", "") for p in artifact.get("parts", []) if isinstance(p, dict))
            task = {"id": task_id, "contextId": update.get("contextId"),
                    "status": {"state": "TASK_STATE_COMPLETED"}, "_reply": text}
        else:
            continue
        if task_id:
            tasks.append(task)
    if not tasks:
        raise AssertionError("stream contained no task envelope")
    final = tasks[-1]
    final.setdefault("_reply", "")
    for item in tasks:
        if item.get("_reply"):
            final["_reply"] = item["_reply"]
    return final


def _post(port: int, payload: dict) -> bytes:
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/", data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {_TOKEN}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as response:
        return response.read()


async def _run() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="a2a-gateway-stub-") as d:
        home = Path(d)
        old = {k: os.environ.get(k) for k in ("HERMES_HOME", "A2A_HOST", "A2A_BEARER_TOKEN")}
        os.environ.update({"HERMES_HOME": str(home), "A2A_HOST": "127.0.0.1", "A2A_BEARER_TOKEN": _TOKEN})
        config = GatewayConfig(platforms={}, sessions_dir=home / "sessions", loop_watchdog=False)
        runner = GatewayRunner(config=config)
        task_db = home / "tasks.db"
        adapter = None
        model_calls = 0

        async def simulated_model(self, event, source, _quick_key, run_generation):
            nonlocal model_calls
            del self, event, run_generation
            model_calls += 1
            await active_adapter.send(source.chat_id, _REPLY, metadata={"notify": True})
            return _REPLY

        runner._handle_message_with_agent = MethodType(simulated_model, runner)
        try:
            active_adapter = A2AAdapter(PlatformConfig(enabled=True, extra={
                "port": 0, "task_store_path": str(task_db), "advertised_toolsets": []}))
            adapter = active_adapter
            runner.adapters[adapter.platform] = adapter
            runner._wire_adapter_handlers(adapter)
            if not await adapter.connect():
                raise RuntimeError("adapter did not connect")
            port = adapter._httpd.server_address[1]
            send = await asyncio.to_thread(_post, port, {
                "jsonrpc": "2.0", "id": "send-53", "method": "SendStreamingMessage",
                "params": {"message": {"role": "user", "parts": [{"kind": "text", "text": "turn53"}]}}})
            task = _sse_task(send)
            if task["status"]["state"] != "TASK_STATE_COMPLETED":
                raise AssertionError(task)
            await adapter.disconnect()
            adapter.tasks.close()
            adapter = A2AAdapter(PlatformConfig(enabled=True, extra={
                "port": 0, "task_store_path": str(task_db), "advertised_toolsets": []}))
            active_adapter = adapter
            runner.adapters[adapter.platform] = adapter
            runner._wire_adapter_handlers(adapter)
            if not await adapter.connect():
                raise RuntimeError("adapter did not reconnect")
            get = await asyncio.to_thread(_post, adapter._httpd.server_address[1], {
                "jsonrpc": "2.0", "id": "get-53", "method": "GetTask",
                "params": {"id": task["id"]}})
            got = _task_from(json.loads(get))
            restored_reply = "".join(
                part.get("text", "")
                for artifact in got.get("artifacts", [])
                for part in artifact.get("parts", [])
                if isinstance(part, dict)
            )
            result = {
                "task_id": task["id"],
                "send_state": task["status"]["state"],
                "reply": task.get("_reply", ""),
                "get_state": got["status"]["state"],
                "get_reply": restored_reply,
                "model_calls": model_calls,
                "simulated": True,
            }
            if (result["get_state"] != "TASK_STATE_COMPLETED"
                    or result["reply"] != _REPLY
                    or result["get_reply"] != _REPLY
                    or model_calls != 1):
                raise AssertionError(result)
            Path(args.output).write_text(json.dumps(result, sort_keys=True) + "\n")
        finally:
            if adapter is not None:
                await adapter.disconnect()
                adapter.tasks.close()
            for key, value in old.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value


if __name__ == "__main__":
    asyncio.run(_run())
