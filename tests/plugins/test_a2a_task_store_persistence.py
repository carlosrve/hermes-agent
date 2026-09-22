from __future__ import annotations

import tempfile
import unittest
import os
import stat
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from plugins.platforms.a2a import protocol


class TaskStorePersistenceTests(unittest.TestCase):
    @pytest.mark.skipif(sys.platform.startswith("win"), reason="POSIX mode bits not enforced on Windows")
    def test_new_store_is_private_under_umask_022(self):
        with tempfile.TemporaryDirectory() as directory:
            private_dir = Path(directory) / "a2a-state"
            path = private_dir / "tasks.db"
            previous = os.umask(0o022)
            try:
                with protocol.TaskStore(path):
                    pass
            finally:
                os.umask(previous)

            self.assertEqual(stat.S_IMODE(private_dir.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    @pytest.mark.skipif(sys.platform == "win32", reason="Symlinks require elevated privileges on Windows")
    def test_store_rejects_symlink_database(self):
        with tempfile.TemporaryDirectory() as directory:
            private_dir = Path(directory) / "a2a-state"
            private_dir.mkdir(mode=0o700)
            target = Path(directory) / "target.db"
            target.write_bytes(b"do-not-touch")
            path = private_dir / "tasks.db"
            path.symlink_to(target)

            with self.assertRaises((OSError, ValueError)):
                protocol.TaskStore(path)
            self.assertEqual(target.read_bytes(), b"do-not-touch")

    @pytest.mark.skipif(sys.platform.startswith("win"), reason="POSIX mode bits not enforced on Windows")
    def test_store_rejects_non_regular_and_insecure_existing_database(self):
        with tempfile.TemporaryDirectory() as directory:
            private_dir = Path(directory) / "a2a-state"
            private_dir.mkdir(mode=0o700)
            non_regular = private_dir / "directory.db"
            non_regular.mkdir(mode=0o700)
            with self.assertRaises(ValueError):
                protocol.TaskStore(non_regular)

            insecure = private_dir / "insecure.db"
            insecure.write_bytes(b"do-not-open")
            insecure.chmod(0o644)
            with self.assertRaises(PermissionError):
                protocol.TaskStore(insecure)
            self.assertEqual(insecure.read_bytes(), b"do-not-open")

    def test_memory_only_store_does_not_open_a_database(self):
        with protocol.TaskStore() as store:
            self.assertIsNone(store._db)

    @pytest.mark.skipif(sys.platform.startswith("win"), reason="POSIX ownership is not available on Windows")
    def test_store_rejects_directory_not_owned_by_effective_user(self):
        with tempfile.TemporaryDirectory() as directory:
            private_dir = Path(directory) / "a2a-state"
            private_dir.mkdir(mode=0o700)
            with patch.object(os, "geteuid", return_value=os.geteuid() + 1):
                with self.assertRaises(PermissionError):
                    protocol.TaskStore(private_dir / "tasks.db")

    @pytest.mark.skipif(sys.platform.startswith("win"), reason="POSIX inode replacement regression")
    def test_store_detects_database_replacement_during_sqlite_open(self):
        with tempfile.TemporaryDirectory() as directory:
            private_dir = Path(directory) / "a2a-state"
            private_dir.mkdir(mode=0o700)
            path = private_dir / "tasks.db"
            replacement = private_dir / "replacement.db"
            replacement.write_bytes(b"")
            replacement.chmod(0o600)
            real_connect = protocol.sqlite3.connect

            def replace_after_connect(*args, **kwargs):
                connection = real_connect(*args, **kwargs)
                os.replace(replacement, path)
                return connection

            with patch.object(protocol.sqlite3, "connect", side_effect=replace_after_connect):
                with self.assertRaises(RuntimeError):
                    protocol.TaskStore(path)

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
