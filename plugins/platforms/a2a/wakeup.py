"""Local wakeup extension for A2A clients.

This module is deliberately not part of the A2A wire protocol.  A2A push
notifications arrive as authenticated protocol payloads; this store converts
one terminal payload into one durable wakeup for the local Codex turn.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Callable, Optional


class WakeupProtocolError(ValueError):
    """Malformed or unauthenticated local wakeup payload."""


_TERMINAL = {"TASK_STATE_COMPLETED", "TASK_STATE_FAILED", "TASK_STATE_CANCELED", "TASK_STATE_REJECTED"}


def _canonical(payload: dict) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def sign(payload: dict, secret: str) -> str:
    """Return the HMAC used by an A2A push sender (local extension helper)."""
    return hmac.new(secret.encode(), _canonical(payload), hashlib.sha256).hexdigest()


class WakeupReceiver:
    """Durable, at-most-once wakeup receiver for a Codex turn.

    ``deliver`` is idempotent by ``event_id`` and task identity.  The callback
    is invoked only after the SQLite commit; after a process cut, ``recover``
    invokes it for committed but undelivered rows.  Callback failures leave the
    row pending and are therefore recoverable.  The callback is the explicit
    local handoff seam; it is never an A2A method and never calls native send.
    """

    def __init__(self, path: str | Path, *, secret: str, callback: Optional[Callable[[dict], None]] = None):
        if not isinstance(secret, str) or not secret:
            raise ValueError("wakeup secret required")
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._secret = secret
        self._callback = callback
        self._condition = threading.Condition()
        self._db = sqlite3.connect(str(self.path), isolation_level=None, check_same_thread=False)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA synchronous=FULL")
        self._db.execute("""CREATE TABLE IF NOT EXISTS wakeups (
            event_id TEXT PRIMARY KEY, task_id TEXT NOT NULL, context_id TEXT NOT NULL,
            payload TEXT NOT NULL, delivered INTEGER NOT NULL DEFAULT 0,
            created_at REAL NOT NULL, delivered_at REAL
        )""")

    def close(self) -> None:
        with self._condition:
            self._db.close()
            self._condition.notify_all()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()

    @staticmethod
    def _validate(payload: dict) -> dict:
        if not isinstance(payload, dict):
            raise WakeupProtocolError("payload must be an object")
        event_id = payload.get("eventId") or payload.get("event_id")
        task_id = payload.get("taskId") or payload.get("task_id")
        context_id = payload.get("contextId") or payload.get("context_id")
        state = payload.get("state")
        if not all(isinstance(v, str) and v for v in (event_id, task_id, context_id, state)):
            raise WakeupProtocolError("eventId, taskId, contextId and state are required")
        if state not in _TERMINAL:
            raise WakeupProtocolError("only terminal task wakeups are accepted")
        result = dict(payload)
        result.update(eventId=event_id, taskId=task_id, contextId=context_id, state=state)
        return result

    def receive(self, payload: dict, *, signature: str) -> bool:
        """Persist one authenticated push and dispatch it once.

        Returns True only for a newly committed event.  Duplicate delivery,
        including a duplicate after restart, returns False and never calls the
        callback again.
        """
        payload = self._validate(payload)
        if not isinstance(signature, str) or not hmac.compare_digest(signature, sign(payload, self._secret)):
            raise WakeupProtocolError("invalid wakeup signature")
        body = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
        with self._condition:
            try:
                self._db.execute(
                    "INSERT INTO wakeups(event_id,task_id,context_id,payload,created_at) VALUES (?,?,?,?,?)",
                    (payload["eventId"], payload["taskId"], payload["contextId"], body, time.time()),
                )
            except sqlite3.IntegrityError:
                return False
            self._condition.notify_all()
        self._dispatch(payload["eventId"])
        return True

    def _dispatch(self, event_id: str) -> bool:
        with self._condition:
            row = self._db.execute("SELECT payload, delivered FROM wakeups WHERE event_id=?", (event_id,)).fetchone()
            if not row or row[1]:
                return False
            payload = json.loads(row[0])
        if self._callback is None:
            return False
        self._callback(payload)
        with self._condition:
            self._db.execute("UPDATE wakeups SET delivered=1, delivered_at=? WHERE event_id=? AND delivered=0", (time.time(), event_id))
        return True

    def recover(self) -> int:
        """Replay committed pending events after a cut; each is marked once."""
        with self._condition:
            ids = [r[0] for r in self._db.execute("SELECT event_id FROM wakeups WHERE delivered=0 ORDER BY created_at, event_id")]
        return sum(self._dispatch(event_id) for event_id in ids)

    def wait(self, timeout: Optional[float] = None) -> Optional[dict]:
        """Block until a pending wakeup exists, returning its local payload."""
        deadline = None if timeout is None else time.monotonic() + timeout
        with self._condition:
            while True:
                row = self._db.execute("SELECT payload FROM wakeups WHERE delivered=0 ORDER BY created_at, event_id LIMIT 1").fetchone()
                if row:
                    return json.loads(row[0])
                remaining = None if deadline is None else deadline - time.monotonic()
                if remaining is not None and remaining <= 0:
                    return None
                self._condition.wait(remaining)

    def pending(self) -> list[dict]:
        with self._condition:
            return [json.loads(r[0]) for r in self._db.execute("SELECT payload FROM wakeups WHERE delivered=0 ORDER BY created_at, event_id")]
