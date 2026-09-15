from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from plugins.platforms.a2a import protocol


class ApprovalObservationTaskStoreTests(unittest.TestCase):
    def test_duplicate_conflict_scope_and_reopen(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "tasks.db"
            observation = {"task_id": "task-1", "operation": "write", "target": "fixture"}
            with protocol.TaskStore(path) as store:
                store.create("task-1", "ctx", "peer", agent_slug="zuri", tenant="t1")
                created = store.record_approval_observation("task-1", "approval-1", observation, "zuri", "t1")
                self.assertIsNotNone(created)
                assert created is not None
                self.assertFalse(created["duplicate"])
                duplicate = store.record_approval_observation("task-1", "approval-1", observation, "zuri", "t1")
                self.assertIsNotNone(duplicate)
                assert duplicate is not None
                self.assertTrue(duplicate["duplicate"])
                self.assertEqual(len(store.list_approval_observations("task-1", "zuri", "t1")), 1)
                self.assertEqual(store.list_approval_observations("task-1", "other", "t1"), [])
                with self.assertRaisesRegex(ValueError, "conflicting"):
                    store.record_approval_observation("task-1", "approval-1", {"different": True}, "zuri", "t1")

            with protocol.TaskStore(path) as reopened:
                rows = reopened.list_approval_observations("task-1", "zuri", "t1")
                self.assertEqual(rows[0]["observation"], observation)
                self.assertEqual(reopened.get_approval_observation("task-1", "approval-1", "other", "t1"), None)

    def test_missing_or_wrong_scope_never_creates_observation(self):
        store = protocol.TaskStore()
        store.create("task-1", "ctx", "peer", agent_slug="zuri", tenant="t1")
        self.assertIsNone(store.record_approval_observation("task-1", "a", {}, "rafa", "t1"))
        self.assertIsNone(store.record_approval_observation("ghost", "a", {}, "zuri", "t1"))
        with self.assertRaises(ValueError):
            store.record_approval_observation("task-1", "a", {"bad": float("nan")}, "zuri", "t1")

    def test_get_task_exposes_only_opaque_working_hint(self):
        store = protocol.TaskStore()
        store.create("task-1", "ctx", "peer")
        store.set_state("task-1", protocol.STATE_WORKING)
        store.record_approval_observation("task-1", "approval-1", {"reason": "private"})
        rec = store.get("task-1")
        assert rec is not None
        task = protocol.TaskStore.to_task(rec, approval_observations=store.list_approval_observations("task-1"))
        message = task["status"]["message"]
        self.assertEqual(protocol.extract_text(message), "approval-observation/v1 approval-1")
        self.assertNotIn("private", str(task))
        self.assertNotIn("approval_id", str(task))
        self.assertEqual(task["status"]["state"], protocol.STATE_WORKING)


if __name__ == "__main__":
    unittest.main()
