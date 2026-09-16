from __future__ import annotations

import json
from pathlib import Path

import pytest

from plugins.platforms.a2a.wakeup import WakeupProtocolError, WakeupReceiver, sign


def payload(event_id="evt-1"):
    return {"eventId": event_id, "taskId": "task-1", "contextId": "ctx-1", "state": "TASK_STATE_COMPLETED", "text": "answer"}


def test_direct_receive_commits_before_explicit_codex_callback(tmp_path: Path):
    seen = []
    receiver = WakeupReceiver(tmp_path / "wakeup.sqlite3", secret="shared", callback=seen.append)
    event = payload()
    assert receiver.receive(event, signature=sign(event, "shared")) is True
    assert seen == [event]
    assert receiver.pending() == []
    receiver.close()


def test_cut_recovery_replays_committed_event_once(tmp_path: Path):
    event = payload()
    first = WakeupReceiver(tmp_path / "wakeup.sqlite3", secret="shared")
    assert first.receive(event, signature=sign(event, "shared")) is True
    assert first.pending() == [event]
    first.close()

    seen = []
    reopened = WakeupReceiver(tmp_path / "wakeup.sqlite3", secret="shared", callback=seen.append)
    assert reopened.recover() == 1
    assert seen == [event]
    assert reopened.recover() == 0
    assert reopened.pending() == []
    reopened.close()


def test_duplicate_final_send_never_wakes_twice_even_after_restart(tmp_path: Path):
    event = payload("same-final")
    seen = []
    receiver = WakeupReceiver(tmp_path / "wakeup.sqlite3", secret="shared", callback=seen.append)
    signature = sign(event, "shared")
    assert receiver.receive(event, signature=signature) is True
    assert receiver.receive(event, signature=signature) is False
    receiver.close()

    reopened = WakeupReceiver(tmp_path / "wakeup.sqlite3", secret="shared", callback=seen.append)
    assert reopened.receive(event, signature=signature) is False
    assert reopened.recover() == 0
    assert len(seen) == 1
    reopened.close()


@pytest.mark.parametrize("bad", [
    {"eventId": "e", "taskId": "t", "contextId": "c", "state": "TASK_STATE_WORKING"},
    {"eventId": "e", "taskId": "t", "state": "TASK_STATE_COMPLETED"},
])
def test_receiver_rejects_non_terminal_or_incomplete_payload(tmp_path: Path, bad):
    receiver = WakeupReceiver(tmp_path / "wakeup.sqlite3", secret="shared")
    with pytest.raises(WakeupProtocolError):
        receiver.receive(bad, signature=sign(bad, "shared"))
    receiver.close()


def test_invalid_signature_does_not_persist(tmp_path: Path):
    receiver = WakeupReceiver(tmp_path / "wakeup.sqlite3", secret="shared")
    with pytest.raises(WakeupProtocolError):
        receiver.receive(payload(), signature="wrong")
    assert receiver.pending() == []
    receiver.close()
