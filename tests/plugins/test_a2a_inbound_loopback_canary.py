from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import uuid
import unittest

from plugins.platforms.a2a import protocol


ROOT = pathlib.Path(__file__).resolve().parents[2]
PYTHON = ROOT / ".venv" / "bin" / "python"
SCRIPT = ROOT / "scripts" / "run_inbound_loopback_canary.py"


def post(url: str, payload: dict, token: str) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as response:
        return json.loads(response.read().decode())


def post_stream(url: str, payload: dict, token: str) -> list[dict]:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as response:
        events = []
        for line in response.read().decode().splitlines():
            if line.startswith("data:") and line[5:].strip():
                events.append(json.loads(line[5:].strip()))
        return events


class TestInboundLoopbackCanary(unittest.TestCase):
    def test_send_gettask_and_cleanup_use_real_adapter_http(self):
        port = 39000 + (os.getpid() % 2000)
        token = "canary-test-" + uuid.uuid4().hex
        with tempfile.TemporaryDirectory(prefix="a2a-inbound-canary-") as home, tempfile.TemporaryDirectory(
            prefix="a2a-inbound-secret-"
        ) as secret_dir:
            token_file = pathlib.Path(secret_dir) / "bearer"
            token_file.write_text(token, encoding="utf-8")
            token_file.chmod(0o600)
            env = os.environ.copy()
            env.update(
                {
                    "PYTHONPATH": str(ROOT),
                    "HOME": home,
                    "A2A_BEARER_TOKEN": token_file.read_text(encoding="utf-8"),
                    "A2A_CANARY_PORT": str(port),
                    "A2A_HOST": "127.0.0.1",
                    "A2A_REPLY_TIMEOUT": "10",
                    "A2A_TASK_STORE_PATH": str(pathlib.Path(home) / "a2a-tasks.db"),
                }
            )
            base = f"http://127.0.0.1:{port}/"
            proc = subprocess.Popen(
                [str(PYTHON), str(SCRIPT)],
                cwd=ROOT,
                env=env,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            try:
                task_id = ""
                ready = json.loads(proc.stdout.readline())
                self.assertEqual({"ready": True, "listener": "loopback-only", "simulation": True},
                                 {k: ready[k] for k in ("ready", "listener", "simulation")})
                body = {
                    "jsonrpc": "2.0",
                    "id": "send-1",
                    "method": "SendStreamingMessage",
                    "params": {
                        "message": protocol_message("inbound canary"),
                    },
                }
                events = post_stream(base, body, token)
                self.assertGreaterEqual(len(events), 3)
                sent = next(e for e in events if "task" in e.get("result", {}))
                task = sent["result"]["task"]
                task_id = task["id"]
                self.assertEqual("send-1", sent["id"])
                artifact = next(e["result"]["artifactUpdate"]["artifact"] for e in events if "artifactUpdate" in e.get("result", {}))
                self.assertIn("CALLBACK_FIXTURE_REPLY", artifact["parts"][0]["text"])

                fetched = post(
                    base,
                    {"jsonrpc": "2.0", "id": "get-1", "method": "GetTask", "params": {"id": task["id"]}},
                    token,
                )
                self.assertEqual(task["id"], fetched["result"]["id"])
                self.assertEqual("TASK_STATE_COMPLETED", fetched["result"]["status"]["state"])
                self.assertIn("CALLBACK_FIXTURE_REPLY", fetched["result"]["artifacts"][0]["parts"][0]["text"])
            finally:
                if proc.stdin:
                    proc.stdin.write("STOP\n")
                    proc.stdin.flush()
                stdout, stderr = proc.communicate(timeout=10)
                self.assertEqual(0, proc.returncode, stderr)
                stopped = [json.loads(line) for line in stdout.splitlines() if line.strip()]
                self.assertTrue(any(item.get("stopped") and item.get("cleanup") for item in stopped))
                self.assertFalse(token_file.stat().st_mode & 0o077)
                with protocol.TaskStore(pathlib.Path(home) / "a2a-tasks.db") as reopened:
                    persisted = reopened.get(task_id)
                    self.assertIsNotNone(persisted)
                    assert persisted is not None
                    self.assertEqual(persisted["state"], protocol.STATE_COMPLETED)
                    self.assertIn("CALLBACK_FIXTURE_REPLY", persisted["reply"])
                with self.assertRaises(urllib.error.URLError):
                    urllib.request.urlopen(base, timeout=1)


def protocol_message(text: str) -> dict:
    return {
        "role": "ROLE_USER",
        "messageId": "canary-message",
        "contextId": "canary-context",
        "parts": [{"text": text}],
    }


if __name__ == "__main__":
    unittest.main()
