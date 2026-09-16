"""Foreground loopback HTTP canary through the real GatewayRunner turn path.

The model boundary is explicitly simulated by replacing only ``_run_agent``;
GatewayRunner._handle_message_with_agent and its admission/session/delivery
path remain real. The listener, HOME, database and credential are temporary.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import socket
import tempfile
import urllib.request
from pathlib import Path
from types import MethodType

from gateway.config import GatewayConfig, PlatformConfig
from gateway.run import GatewayRunner
from plugins.platforms.a2a.adapter import A2AAdapter

_TOKEN = "turn55-test-bearer"
_REPLY = "TURN55_SIMULATED_MODEL_REPLY"


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


def _assert_port_closed(port: int) -> None:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            raise AssertionError(f"canary listener still accepts connections on {port}")
    except OSError:
        return


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
        first_port = None
        second_port = None
        model_calls = 0

        async def simulated_run_agent(self, message, context_prompt, history, source, session_id, **turn_kwargs):
            nonlocal model_calls
            del self, message, context_prompt, history, source, session_id, turn_kwargs
            model_calls += 1
            return {
                "final_response": _REPLY,
                "messages": [{"role": "assistant", "content": _REPLY}],
                "api_calls": 1,
                "tools": [],
                "history_offset": 0,
                "session_id": "fixture-session",
            }

        # Keep _handle_message_with_agent, admission, session preparation,
        # persistence and adapter delivery real; simulate only the model seam.
        runner._run_agent = MethodType(simulated_run_agent, runner)
        try:
            active_adapter = A2AAdapter(PlatformConfig(enabled=True, extra={
                "port": 0, "task_store_path": str(task_db), "advertised_toolsets": []}))
            adapter = active_adapter
            runner.adapters[adapter.platform] = adapter
            runner._wire_adapter_handlers(adapter)
            if not await adapter.connect():
                raise RuntimeError("adapter did not connect")
            port = adapter._httpd.server_address[1]
            first_port = port
            send = await asyncio.to_thread(_post, port, {
                "jsonrpc": "2.0", "id": "send-55", "method": "SendStreamingMessage",
                "params": {"message": {"role": "user", "parts": [{"kind": "text", "text": "turn55"}]}}})
            task = _sse_task(send)
            if task["status"]["state"] != "TASK_STATE_COMPLETED":
                raise AssertionError(task)
            await adapter.disconnect()
            adapter.tasks.close()
            _assert_port_closed(first_port)
            adapter = A2AAdapter(PlatformConfig(enabled=True, extra={
                "port": 0, "task_store_path": str(task_db), "advertised_toolsets": []}))
            active_adapter = adapter
            runner.adapters[adapter.platform] = adapter
            runner._wire_adapter_handlers(adapter)
            if not await adapter.connect():
                raise RuntimeError("adapter did not reconnect")
            second_port = adapter._httpd.server_address[1]
            get = await asyncio.to_thread(_post, second_port, {
                "jsonrpc": "2.0", "id": "get-55", "method": "GetTask",
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
                "first_listener_closed": True,
                "second_listener_closed": True,
            }
            if (result["get_state"] != "TASK_STATE_COMPLETED"
                    or result["reply"] != _REPLY
                    or result["get_reply"] != _REPLY
                    or model_calls != 1):
                raise AssertionError(result)
            await adapter.disconnect()
            adapter.tasks.close()
            _assert_port_closed(second_port)
            adapter = None
            Path(args.output).write_text(
                json.dumps(result, sort_keys=True) + "\n", encoding="utf-8"
            )
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
