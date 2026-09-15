from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from plugins.platforms.a2a import protocol


class TaskStorePersistenceTests(unittest.TestCase):
    def test_restart_preserves_task_state_reply_and_push_config(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "tasks.db"
            with protocol.TaskStore(path) as store:
                created = store.create("task-1", "ctx-1", "peer")
                self.assertEqual(created["state"], protocol.STATE_SUBMITTED)
                store.set_state("task-1", protocol.STATE_WORKING)
                config = store.set_push_config("task-1", "http://127.0.0.1:9/callback")
                self.assertIsNotNone(config)
                assert config is not None
                self.assertTrue(config["configId"])
                store.complete("task-1", protocol.STATE_COMPLETED, "real bounded result")

            with protocol.TaskStore(path) as reopened:
                task = reopened.get("task-1")
                self.assertIsNotNone(task)
                assert task is not None
                self.assertEqual(task["state"], protocol.STATE_COMPLETED)
                self.assertEqual(task["reply"], "real bounded result")
                config = reopened.get_push_config("task-1")
                self.assertIsNotNone(config)
                assert config is not None
                self.assertEqual(config["pushNotificationConfig"]["url"],
                                 "http://127.0.0.1:9/callback")

    def test_uncertain_submitted_task_remains_queryable_without_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "tasks.db"
            with protocol.TaskStore(path) as store:
                store.create("task-uncertain", "ctx-1", "peer")
            with protocol.TaskStore(path) as reopened:
                task = reopened.get("task-uncertain")
                self.assertIsNotNone(task)
                assert task is not None
                self.assertEqual(task["state"], protocol.STATE_SUBMITTED)
                self.assertEqual(task["reply"], "")


if __name__ == "__main__":
    unittest.main()
