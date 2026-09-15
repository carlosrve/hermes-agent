"""Control fixtures are not human authority. No socket, model, send or queue resolver."""
from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from plugins.platforms.a2a import protocol

BINDING = dict(task_id="task", context_id="ctx", peer="peer", agent_slug="zuri", tenant="t1",
               origin_route_id="origin", objective_id="objective", delegation_id="delegation",
               session_key="session", profile_home="fixture-profile")


class ControlFixture:
    """Durable authenticated-route fixture; no grant/decision API or send method."""
    def __init__(self, path):
        self.db = sqlite3.connect(path)
        self.db.execute("CREATE TABLE IF NOT EXISTS outbox (id TEXT PRIMARY KEY, body TEXT)")
        self.active = True

    def put(self, ident="approval-1", **changes):
        value = dict(BINDING, approval_id=ident, payload_digest="a" * 64, **changes)
        self.db.execute("INSERT OR REPLACE INTO outbox VALUES (?, ?)", (ident, json.dumps(value)))
        self.db.commit()
        return value

    def observations(self, binding):
        assert binding == BINDING
        return [json.loads(row[0]) for row in self.db.execute("SELECT body FROM outbox ORDER BY rowid")]

    def validate(self, binding, observation):
        if not self.active:
            raise ValueError("inactive binding")
        row = self.db.execute("SELECT body FROM outbox WHERE id=?", (observation["approval_id"],)).fetchone()
        if row is None or json.loads(row[0]) != observation:
            raise ValueError("unverified observation")
        if any(observation.get(k) != v for k, v in binding.items()):
            raise ValueError("binding mismatch")
        return True

    def close(self):
        self.db.close()


class ApprovalObservationTaskStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)
        self.control = ControlFixture(self.path / "control.db")
        self.addCleanup(self.control.close)

    def store(self):
        store = protocol.TaskStore(self.path / "tasks.db", approval_control=self.control)
        self.addCleanup(store.close)
        if store.get("task") is None:
            store.create("task", "ctx", "peer", "zuri", "t1")
            store.set_state("task", protocol.STATE_WORKING)
            store.bind_approval_context("task", BINDING)
        return store

    def test_recovery_crashes_between_stores_revalidates_without_resend(self):
        # Before control commit: no row. After commit/before projection: recover.
        store = self.store()
        self.assertEqual(store.recover_approval_observations("task"), [])
        original = self.control.put()
        store.close()
        store = self.store()
        self.assertFalse(store.recover_approval_observations("task")[0]["duplicate"])
        # After task commit/before caller ack: reopen both stores and replay.
        store.close()
        self.control.close()
        self.control = ControlFixture(self.path / "control.db")
        self.addCleanup(self.control.close)
        store = self.store()
        self.assertTrue(store.recover_approval_observations("task")[0]["duplicate"])
        self.assertEqual(len(store.list_approval_observations("task")), 1)
        self.assertEqual(store.get("task")["reply"], "")
        self.assertEqual(store.get("task")["state"], protocol.STATE_WORKING)
        self.control.active = False
        with self.assertRaisesRegex(ValueError, "inactive"):
            store.recover_approval_observations("task")
        self.assertEqual(self.control.observations(BINDING), [original])

    def test_pending_approval_survives_age_until_expired(self):
        self._lifecycle_case("expired")

    def test_pending_approval_survives_age_until_revoked(self):
        self._lifecycle_case("revoked")

    def _lifecycle_case(self, lifecycle):
        store = self.store()
        self.control.put()
        store.recover_approval_observations("task")
        with patch.object(protocol.time, "time", return_value=10**12):
            self.assertEqual(store.fail_orphans(1), [])
        self.assertEqual(store.get("task")["state"], protocol.STATE_WORKING)
        self.control.lifecycle = lambda binding: {"state": lifecycle, "evidence_id": "control-evidence"}
        store.refresh_approval_lifecycle("task")
        self.assertEqual(store.get("task")["approval_lifecycle"], lifecycle)
        store.close()
        store = self.store()
        self.assertEqual(store.fail_orphans(10**15), ["task"])
        rec = store.get("task")
        self.assertEqual(rec["state"], protocol.STATE_FAILED)
        self.assertEqual(rec["approval_lifecycle_evidence"], "control-evidence")
        with self.assertRaises(ValueError):
            store.record_approval_observation("task", self.control.put("new"))

    def test_dedup_conflict_scope_latest_and_reopen(self):
        store = self.store()
        first = self.control.put("z-first", reason="PRIVATE_ACTION")
        self.assertFalse(store.record_approval_observation("task", first)["duplicate"])
        self.assertTrue(store.record_approval_observation("task", first)["duplicate"])
        second = self.control.put("a-latest", reason="SECOND_PRIVATE_ACTION")
        store.record_approval_observation("task", second)
        changed = self.control.put("z-first", reason="conflicting")
        with self.assertRaisesRegex(ValueError, "conflicting"):
            store.record_approval_observation("task", changed)
        store.close()
        store = self.store()
        rows = store.list_approval_observations("task", "zuri", "t1")
        self.assertEqual([r["approval_id"] for r in rows], ["z-first", "a-latest"])
        self.assertEqual(store.list_approval_observations("task", "other", "t1"), [])
        self.assertIsNone(store.get_approval_observation("task", "z-first", "zuri", "other"))
        task = store.to_task(store.get("task"), approval_observations=rows)
        self.assertEqual(protocol.extract_text(task["status"]["message"]), "approval-observation/v1 a-latest")
        self.assertEqual(task["status"]["message"]["role"], protocol.ROLE_AGENT)
        self.assertEqual(task["status"]["state"], protocol.STATE_WORKING)
        self.assertNotIn("PRIVATE_ACTION", json.dumps(task))
        self.assertNotIn("PRIVATE_ACTION", (self.path / "tasks.db").read_bytes().decode("utf8", errors="ignore"))
        self.assertEqual(store.get("task")["reply"], "")

    def test_scope_binding_is_not_mutable_through_get_or_list(self):
        store = self.store()
        store.get("task")["approval_binding"]["tenant"] = "other"
        records, _ = store.list()
        records[0]["approval_binding"]["origin_route_id"] = "foreign"
        self.assertEqual(store.get("task")["approval_binding"], BINDING)

    def test_admission_and_observation_identity_boundaries(self):
        store = self.store()
        for field in BINDING:
            with self.subTest(field=field):
                with self.assertRaises(ValueError):
                    store.bind_approval_context("task", dict(BINDING, **{field: "foreign"}))
                observation = self.control.put()
                observation[field] = "foreign"
                with self.assertRaises(ValueError):
                    store.record_approval_observation("task", observation)
        for ident in ("with space", "line\nbreak", "a,b", "x" * 129):
            with self.assertRaises(ValueError):
                store.record_approval_observation("task", self.control.put(ident))
        self.assertEqual(store.list_approval_observations("task"), [])

    def test_failed_task_commit_leaves_no_cache_row_then_recovers(self):
        store = self.store()
        self.control.put()
        store._db.execute("CREATE TRIGGER fail_insert BEFORE INSERT ON approval_observations BEGIN SELECT RAISE(ABORT, 'fixture cut'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            store.recover_approval_observations("task")
        self.assertEqual(store.list_approval_observations("task"), [])
        store._db.execute("DROP TRIGGER fail_insert")
        store.close()
        store = self.store()
        self.assertFalse(store.recover_approval_observations("task")[0]["duplicate"])

    def test_real_gettask_handler_scopes_and_projects_after_reopen(self):
        from gateway.config import PlatformConfig
        from plugins.platforms.a2a.adapter import A2AAdapter
        store = self.store()
        self.control.put()
        store.recover_approval_observations("task")
        store.close()
        adapter = A2AAdapter(PlatformConfig(enabled=True, extra={"token": "fixture-only"}))
        adapter.tasks = self.store()
        result = adapter._rpc_tasks_get("rpc-id", {"taskId": "task"}, {"slug": "zuri", "tenant": "t1"})
        self.assertEqual(result["id"], "rpc-id")
        self.assertEqual(result["result"]["status"]["state"], protocol.STATE_WORKING)
        self.assertEqual(protocol.extract_text(result["result"]["status"]["message"]), "approval-observation/v1 approval-1")
        foreign = adapter._rpc_tasks_get("rpc-id", {"taskId": "task"}, {"slug": "zuri", "tenant": "foreign"})
        self.assertEqual(foreign["error"]["code"], protocol.ERR_TASK_NOT_FOUND)

    def test_terminal_pruning_removes_observations_together(self):
        store = self.store()
        self.control.put()
        store.recover_approval_observations("task")
        store._MAX_TERMINAL = 0
        store.complete("task", protocol.STATE_CANCELED)
        self.assertIsNone(store.get_approval_observation("task", "approval-1"))
        self.assertEqual(store._db.execute("SELECT COUNT(*) FROM approval_observations").fetchone()[0], 0)

    def test_unverified_control_and_mismatched_admission_fail_closed(self):
        store = self.store()
        obs = self.control.put()
        with self.assertRaises(ValueError):
            store.record_approval_observation("task", dict(obs, tenant="other"))
        self.assertEqual(store.list_approval_observations("task"), [])
        store.close()
        with protocol.TaskStore(self.path / "tasks.db") as reopened:
            with self.assertRaises(ValueError):
                reopened.record_approval_observation("task", obs)


if __name__ == "__main__":
    unittest.main()
