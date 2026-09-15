import contextlib
import io
import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import a2a_outbound_operator as operator


class FakeStore:
    def __init__(self, path):
        self.records = {}

    def load(self, local_id):
        return self.records[local_id].copy()


class FakeClient:
    def __init__(self, config, store):
        self.config = config
        self.store = store

    def prepare(self, prompt):
        self.store.records["a" * 32] = {
            "local_id": "a" * 32, "local_state": "prepared",
            "remote_state": None, "events": [],
        }
        return "a" * 32

    def send(self, local_id):
        record = self.store.records[local_id]
        record.update(local_state="observed", remote_state="TASK_STATE_COMPLETED",
                      events=[{"task": {"artifacts": [{"parts": [{"text": "done"}]}]}}])
        return record

    def resume(self, local_id):
        record = self.store.records[local_id]
        record.update(local_state="uncertain", remote_state="TASK_STATE_WORKING")
        return record


class FailingClient(FakeClient):
    def send(self, local_id):
        raise TimeoutError("simulated uncertain transport")


class OperatorTests(unittest.TestCase):
    def token_file(self, directory):
        path = Path(directory) / "bearer"
        path.write_text("c" * 64 + "\n", encoding="utf-8")
        path.chmod(0o600)
        return path

    def test_prompt_cli_outputs_bounded_sanitized_projection(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "state"
            state.mkdir(mode=0o700)
            with mock.patch.object(operator, "Store", FakeStore), mock.patch.object(operator, "Client", FakeClient):
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    self.assertEqual(operator.main([
                        "--prompt", "inspect", "--token-file", str(self.token_file(directory)),
                        "--state-dir", str(state), "--url", "https://zurqui.tuna-gray.ts.net",
                    ]), 0)
                result = json.loads(output.getvalue())
                self.assertEqual(result["action"], "send")
                self.assertEqual(result["local_id"], "a" * 32)
                self.assertEqual(result["response_text"], "done")
                self.assertNotIn("bearer", output.getvalue())
                self.assertNotIn("c" * 64, output.getvalue())

    def test_existing_id_is_resume_only(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "state"
            state.mkdir(mode=0o700)
            with mock.patch.object(operator, "Store", FakeStore), mock.patch.object(operator, "Client", FakeClient):
                fake_store = FakeStore(state)
                fake_store.records["b" * 32] = {
                    "local_id": "b" * 32, "local_state": "uncertain",
                    "remote_state": "TASK_STATE_WORKING", "events": [{"task": {}}],
                }
                with mock.patch.object(operator, "Store", return_value=fake_store):
                    output = io.StringIO()
                    with contextlib.redirect_stdout(output):
                        self.assertEqual(operator.main([
                            "--local-id", "b" * 32, "--token-file", str(self.token_file(directory)),
                            "--state-dir", str(state),
                        ]), 0)
                    result = json.loads(output.getvalue())
                    self.assertEqual(result["action"], "resume")
                    self.assertEqual(result["new_event_count"], 0)

    def test_token_and_state_permissions_are_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            token = self.token_file(directory)
            token.chmod(0o644)
            with self.assertRaises(ValueError): operator._read_token(token)
            token.chmod(0o600)
            link = Path(directory) / "token-link"
            link.symlink_to(token)
            with self.assertRaises(ValueError): operator._read_token(link)
            state = Path(directory) / "state"
            state.mkdir(mode=0o755)
            with self.assertRaises(ValueError): operator._validate_state_dir(state)

    def test_uncertain_send_error_exposes_prepared_local_id_only(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "state"
            state.mkdir(mode=0o700)
            stderr = io.StringIO()
            with mock.patch.object(operator, "Store", FakeStore), mock.patch.object(operator, "Client", FailingClient):
                with contextlib.redirect_stderr(stderr):
                    self.assertEqual(operator.main([
                        "--prompt", "inspect", "--token-file", str(self.token_file(directory)),
                        "--state-dir", str(state),
                    ]), 2)
            result = json.loads(stderr.getvalue())
            self.assertEqual(result["status"], "error")
            self.assertEqual(result["action"], "send")
            self.assertEqual(result["local_id"], "a" * 32)
            self.assertNotIn("simulated uncertain transport", stderr.getvalue())

    def test_response_text_is_bounded_while_accumulating_parts(self):
        text = operator._response_text({"events": [{"task": {"artifacts": [{
            "parts": [{"text": "a" * (operator._MAX_RESPONSE_TEXT + 100)}, {"text": "ignored"}]
        }]}}]})
        self.assertEqual(len(text), operator._MAX_RESPONSE_TEXT)
        self.assertEqual(text, "a" * operator._MAX_RESPONSE_TEXT)

    def test_response_text_reads_streamed_artifact_updates(self):
        text = operator._response_text({"events": [{"artifactUpdate": {
            "artifact": {"parts": [{"text": "streamed result"}]}
        }}]})
        self.assertEqual(text, "streamed result")


if __name__ == "__main__":
    unittest.main()
