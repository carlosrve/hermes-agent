from __future__ import annotations

import json
import sqlite3
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

    def test_reopening_legacy_oversized_database_applies_terminal_bound(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "tasks.db"
            with protocol.TaskStore(path) as store:
                for index in range(store._MAX_TERMINAL + 5):
                    store.create(f"task-{index}", "ctx-1", "peer")
            # Simulate rows left behind by the older implementation, which
            # did not prune terminal records from SQLite.
            with sqlite3.connect(path) as db:
                for task_id, payload in db.execute("SELECT task_id, payload FROM tasks").fetchall():
                    rec = json.loads(payload)
                    rec["state"] = protocol.STATE_COMPLETED
                    rec["reply"] = "legacy-result"
                    db.execute("UPDATE tasks SET payload = ? WHERE task_id = ?", (json.dumps(rec), task_id))

            with protocol.TaskStore(path) as reopened:
                self.assertIsNone(reopened.get("task-0"))
                self.assertIsNotNone(reopened.get("task-504"))
                records, _next, total = reopened.list(page_size=100, with_total=True)
                self.assertEqual(100, len(records))
                self.assertEqual(reopened._MAX_TERMINAL, total)
            with sqlite3.connect(path) as db:
                self.assertEqual(protocol.TaskStore._MAX_TERMINAL,
                                 db.execute("SELECT COUNT(*) FROM tasks").fetchone()[0])

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
