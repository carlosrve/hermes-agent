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

    def test_restart_prunes_old_terminal_rows_from_persistent_store(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "tasks.db"
            with protocol.TaskStore(path) as store:
                for index in range(store._MAX_TERMINAL + 5):
                    task_id = f"task-{index}"
                    store.create(task_id, "ctx-1", "peer")
                    store.complete(task_id, protocol.STATE_COMPLETED, f"reply-{index}")
                self.assertIsNone(store.get("task-0"))
                self.assertIsNotNone(store.get("task-504"))

            with protocol.TaskStore(path) as reopened:
                records = []
                offset = 0
                while True:
                    page, offset = reopened.list(page_size=100, offset=offset)
                    records.extend(page)
                    if not offset:
                        break
                self.assertEqual(store._MAX_TERMINAL, len(records))
                self.assertIsNone(reopened.get("task-0"))
                self.assertIsNotNone(reopened.get("task-504"))

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
