"""Exercise GatewayRunner A2A wiring with a real adapter and fake config.

This is an isolated gate/wiring check. It deliberately does not construct a
GatewayRunner session, invoke a model, enable native send, or touch production.
"""
from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from gateway.config import GatewayConfig, PlatformConfig
from gateway.run import GatewayRunner
from hermes_cli.config import get_hermes_home
from plugins.platforms.a2a.adapter import A2AAdapter


class GatewayA2AWiringTests(unittest.TestCase):
    def test_full_runner_constructs_and_wires_real_handler_in_isolated_home(self):
        # This constructs the actual runner/session store. It opens no adapter
        # listener and does not call a provider or model.
        with tempfile.TemporaryDirectory(prefix="a2a-full-runner-") as directory:
            home = Path(directory)
            with patch.dict(os.environ, {
                "HERMES_HOME": str(home),
                "A2A_HOST": "127.0.0.1",
                "A2A_BEARER_TOKEN": "fixture-runner-construction",
            }):
                config = GatewayConfig(platforms={}, sessions_dir=home / "sessions",
                                       loop_watchdog=False)
                runner = GatewayRunner(config=config)
                adapter = A2AAdapter(PlatformConfig(enabled=True, extra={
                    "port": 0,
                    "task_store_path": str(home / "a2a-tasks.db"),
                }))
                try:
                    runner._wire_adapter_handlers(adapter)
                    self.assertIs(getattr(adapter._message_handler, "__self__", None), runner)
                    self.assertEqual(get_hermes_home(), home)
                    self.assertEqual(runner.config.sessions_dir, home / "sessions")
                    self.assertTrue((home / "state.db").exists())
                finally:
                    adapter.tasks.close()

    def test_real_adapter_receives_runner_callbacks_and_auth_gate(self):
        old_host = os.environ.get("A2A_HOST")
        old_token = os.environ.get("A2A_BEARER_TOKEN")
        os.environ["A2A_HOST"] = "127.0.0.1"
        os.environ["A2A_BEARER_TOKEN"] = "fixture-token-not-production"
        try:
            config = SimpleNamespace(
                enabled=True,
                extra={"port": 0, "advertised_toolsets": []},
                multiplex_profiles=False,
            )
            adapter = A2AAdapter(config)
            runner = GatewayRunner.__new__(GatewayRunner)
            runner.config = config
            runner.session_store = Mock(name="session_store")
            runner._recover_telegram_topic_thread_id = Mock(name="topic_recovery")

            message = Mock(name="message_handler")
            fatal = Mock(name="fatal_error_handler")
            busy = Mock(name="busy_session_handler")
            auth = Mock(name="authorization_check", return_value=True)
            platform_event = Mock(name="platform_event_handler")

            GatewayRunner._wire_adapter_handlers(
                runner,
                adapter,
                message_handler=message,
                fatal_error_handler=fatal,
                busy_session_handler=busy,
                authorization_check=auth,
                platform_event_handler=platform_event,
                busy_text_mode="interrupt",
            )

            self.assertIs(adapter._message_handler, message)
            self.assertIs(adapter._fatal_error_handler, fatal)
            self.assertIs(adapter._busy_session_handler, busy)
            self.assertIs(adapter._authorization_check, auth)
            self.assertIs(adapter._platform_event_handler, platform_event)
            self.assertEqual(adapter._busy_text_mode, "interrupt")

            # The adapter's immutable security context authenticates the
            # configured fixture credential; no model/session callback is used.
            context = adapter._security_context
            self.assertEqual(
                context.authenticate("Bearer fixture-token-not-production", "127.0.0.1"),
                "ip:127.0.0.1",
            )
            self.assertIsNone(context.authenticate("Bearer wrong-token", "127.0.0.1"))
        finally:
            if old_host is None:
                os.environ.pop("A2A_HOST", None)
            else:
                os.environ["A2A_HOST"] = old_host
            if old_token is None:
                os.environ.pop("A2A_BEARER_TOKEN", None)
            else:
                os.environ["A2A_BEARER_TOKEN"] = old_token


if __name__ == "__main__":
    unittest.main()
