#!/usr/bin/env python3
"""Supported operator entry point for the pinned Hermes outbound client.

This is deliberately separate from the model-facing native tool. It accepts a
protected bearer file and performs one explicit send or GetTask-only resume.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import stat
import sys

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from plugins.platforms.a2a.outbound import Client, Store

TOKEN_ENV = "A2A_OPERATOR_BEARER"
REMOTE_ENDPOINT_HOST = "zurqui.tuna-gray.ts.net"
_MAX_RESPONSE_TEXT = 8192


def _read_token(path: Path) -> str:
    if path.is_symlink():
        raise ValueError("token file must not be a symlink")
    resolved = path.resolve(strict=True)
    if not resolved.is_file():
        raise ValueError("token file must be a regular file")
    if stat.S_IMODE(resolved.stat().st_mode) != 0o600:
        raise ValueError("token file must have mode 0600")
    token = resolved.read_text(encoding="utf-8").strip()
    if len(token) != 64 or any(c not in "0123456789abcdef" for c in token.lower()):
        raise ValueError("invalid bearer file")
    return token


def _validate_state_dir(path: Path) -> Path:
    if path.exists():
        if path.is_symlink() or not path.is_dir():
            raise ValueError("state path must be a directory")
        if stat.S_IMODE(path.stat().st_mode) != 0o700:
            raise ValueError("state directory must have mode 0700")
    else:
        path.mkdir(mode=0o700, parents=False)
    return path.resolve()


def _response_text(record: dict) -> str:
    remaining = _MAX_RESPONSE_TEXT
    collected = []
    for event in reversed(record.get("events", [])):
        task = event.get("task") if isinstance(event, dict) else None
        if task is None and isinstance(event, dict):
            update = event.get("artifactUpdate")
            if isinstance(update, dict):
                task = update.get("artifact")
        if not isinstance(task, dict):
            continue
        artifacts = task.get("artifacts", [])
        if isinstance(task.get("parts"), list):
            artifacts = [task]
        for artifact in artifacts:
            if not isinstance(artifact, dict):
                continue
            for part in artifact.get("parts", []):
                if isinstance(part, dict) and isinstance(part.get("text"), str):
                    if remaining:
                        text = part["text"]
                        chunk = text[:remaining]
                        collected.append(chunk)
                        remaining -= len(chunk)
                    if not remaining:
                        return "".join(collected)
        if collected:
            return "".join(collected)
    return ""


def _output(record: dict, *, action: str, before_events: int) -> dict:
    events = record.get("events", [])
    return {
        "status": "ok",
        "action": action,
        "local_id": record["local_id"],
        "local_state": record.get("local_state"),
        "remote_state": record.get("remote_state"),
        "event_count": len(events),
        "new_event_count": max(0, len(events) - before_events),
        "response_text": _response_text(record),
        "simulation": False,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--prompt", help="new prompt to send")
    group.add_argument("--local-id", help="existing local request ID to resume")
    parser.add_argument("--token-file", required=True, type=Path)
    parser.add_argument("--state-dir", required=True, type=Path)
    parser.add_argument("--url", default=f"https://{REMOTE_ENDPOINT_HOST}")
    parser.add_argument("--timeout", type=float, default=30)
    return parser


def main(argv=None) -> int:
    args = _parser().parse_args(argv)
    local_id = None
    action = "resume" if args.local_id is not None else "send"
    try:
        token = _read_token(args.token_file)
        state_dir = _validate_state_dir(args.state_dir)
        if args.timeout <= 0 or args.timeout > 300:
            raise ValueError("timeout must be between zero and 300 seconds")
        if not isinstance(args.url, str) or any(c.isspace() for c in args.url):
            raise ValueError("invalid endpoint")
        config = {
            "enabled": True,
            "peer": "zuri",
            "runtime": "codex",
            "host": "zurqui",
            "url": args.url,
            "token_env": TOKEN_ENV,
            "timeout": args.timeout,
        }
        os.environ[TOKEN_ENV] = token
        store = Store(state_dir)
        client = Client(config, store)
        if args.prompt is not None:
            local_id = client.prepare(args.prompt)
            before = 0
            record = client.send(local_id)
        else:
            local_id = args.local_id
            record = store.load(local_id)
            before = len(record.get("events", []))
            record = client.resume(local_id)

        print(json.dumps(_output(record, action=action, before_events=before), ensure_ascii=False, allow_nan=False))
        return 0
    except Exception:
        print(json.dumps({"status": "error", "reason": "operator_request_failed",
                          "action": action, "local_id": local_id},
                         ensure_ascii=False, allow_nan=False), file=sys.stderr)
        return 2
    finally:
        os.environ.pop(TOKEN_ENV, None)


if __name__ == "__main__":
    raise SystemExit(main())
