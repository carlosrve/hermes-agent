"""Opt-in outbound A2A 1.0 recovery. No inbound server or automatic resend."""
from __future__ import annotations

from contextlib import closing, contextmanager
import base64
import binascii
import copy
from datetime import datetime
import fcntl
import hashlib
import re
import socket
import threading
import json
import math
import os
from pathlib import Path
import sqlite3
import uuid
import http.client
import time
from urllib.parse import urlsplit


# The private canary endpoint is certificate-bound. Keep this exact allowlist;
# do not replace it with suffix/wildcard matching or a caller-supplied host.
REMOTE_ENDPOINT_HOST = 'zurqui.tuna-gray.ts.net'


class ProtocolError(ValueError):
    """Untrusted, malformed or excessive peer response."""


# A2A v1.0.0 normative specification/a2a.proto, tag commit 173695755607e884aa9acf8ce4feed90e32727a1.
# Task.contextId is OPTIONAL, unlike update.contextId. Message.parts has no
# minItems requirement; Artifact.parts does. Part.data is any JSON value.
_STATES = tuple(f'TASK_STATE_{s}' for s in (
    'UNSPECIFIED', 'SUBMITTED', 'WORKING', 'COMPLETED', 'FAILED', 'CANCELED',
    'INPUT_REQUIRED', 'REJECTED', 'AUTH_REQUIRED'))
_ROLES = ('ROLE_UNSPECIFIED', 'ROLE_USER', 'ROLE_AGENT')
_SCHEMAS = {
    'task': ({'id': 'identity', 'status': 'status'},
             {'contextId': 'optional_identity', 'artifacts': 'list:artifact', 'history': 'list:message'}),
    'message': ({'messageId': 'identity', 'role': 'role', 'parts': 'list:part'},
                {'contextId': 'optional_identity', 'taskId': 'optional_identity',
                 'extensions': 'list:string', 'referenceTaskIds': 'list:string'}),
    'status': ({'state': 'state'}, {'message': 'message', 'timestamp': 'timestamp'}),
    'artifact': ({'artifactId': 'identity', 'parts': 'list:part'},
                 {'name': 'string', 'description': 'string', 'extensions': 'list:string'}),
    'statusUpdate': ({'taskId': 'identity', 'contextId': 'identity', 'status': 'status'}, {}),
    'artifactUpdate': ({'taskId': 'identity', 'contextId': 'identity', 'artifact': 'artifact'},
                       {'append': 'boolean', 'lastChunk': 'boolean'}),
    'part': ({}, {'filename': 'string', 'mediaType': 'string'}),
}


def _field_names(value, fields):
    """Read ProtoJSON's two legal spellings, rejecting ambiguous aliases."""
    result = dict(value)
    for field in fields:
        alias = re.sub(r'[A-Z]', lambda m: '_' + m[0].lower(), field)
        if alias != field and alias in value:
            if field in value:
                raise ProtocolError('Duplicate protocol field alias')
            result[field] = result.pop(alias)
    return result


def _validate(kind, value):
    """Validate the full known object before changing any correlation or state.

    Optional nulls are unset (ProtoJSON); extension fields are retained as data.
    Required fields may not be absent/null. Return a validated read view, never
    rewrite the original event. Integer enum representations follow ProtoJSON;
    unknown enum values fail closed rather than certifying a terminal result.
    """
    if kind.startswith('list:'):
        if not isinstance(value, list):
            raise ProtocolError('Invalid protocol array')
        return [_validate(kind[5:], item) for item in value]
    if kind in {'state', 'role'}:
        names = _STATES if kind == 'state' else _ROLES
        if type(value) is int and 0 <= value < len(names):
            return names[value]
        if not isinstance(value, str) or value not in names:
            raise ProtocolError('Invalid protocol enum')
        return value
    if kind in {'string', 'identity', 'optional_identity', 'state', 'role', 'raw', 'timestamp'}:
        if not isinstance(value, str):
            raise ProtocolError('Invalid protocol string')
        if kind == 'identity' and not value:
            raise ProtocolError('Missing remote identity')
        if kind in {'identity', 'optional_identity'} and len(value) > 1024:
            raise ProtocolError('Remote identity limit')

        if kind == 'raw':
            try:
                base64.b64decode(value + '=' * (-len(value) % 4), altchars=b'-_', validate=True)
            except (ValueError, binascii.Error):
                raise ProtocolError('Invalid base64 part') from None
        if kind == 'timestamp':
            if not re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,9})?(?:Z|[+-]\d\d:\d\d)', value):
                raise ProtocolError('Invalid status timestamp')
            try:
                datetime.fromisoformat(value)
            except ValueError:
                raise ProtocolError('Invalid status timestamp') from None
        return value
    if kind == 'boolean':
        if type(value) is not bool:
            raise ProtocolError('Invalid protocol boolean')
        return value
    if not isinstance(value, dict):
        raise ProtocolError('Invalid protocol object')
    required, optional = _SCHEMAS[kind]
    value = _field_names(value, {*required, *optional})
    for field, field_kind in required.items():
        value[field] = _validate(field_kind, value.get(field))
    for field, field_kind in optional.items():
        if value.get(field) is not None:
            value[field] = _validate(field_kind, value[field])
    if value.get('metadata') is not None and not isinstance(value['metadata'], dict):
        raise ProtocolError('Invalid protocol metadata')
    if kind == 'message' and value['role'] == 'ROLE_AGENT':
        # Normative Message prose requires context for server-originated messages.
        _validate('identity', value.get('contextId'))
    if kind == 'artifact' and not value['parts']:
        raise ProtocolError('Artifact requires at least one part')
    if kind == 'part':
        content = [k for k in ('text', 'raw', 'url', 'data') if k in value and (value[k] is not None or k == 'data')]
        if len(content) != 1:
            raise ProtocolError('Invalid Part content oneof')
        field = content[0]
        if field != 'data':
            _validate('raw' if field == 'raw' else 'string', value[field])
    return value


def _finite_json(value, depth=0):
    """Validate JSON-native data without interpreting arbitrary string contents.

    ProtoJSON special float strings remain strings: Value/Struct do not turn
    them into numbers. No typed float fields are consumed by this client.
    Check native envelopes too, not only text decoded by the transport.
    """
    if depth > 64:
        raise ProtocolError('JSON nesting limit')
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ProtocolError('Nonfinite JSON number')
    elif isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ProtocolError('Invalid JSON object key')
            _finite_json(item, depth + 1)
    elif isinstance(value, list):
        for item in value:
            _finite_json(item, depth + 1)
    elif value is not None and not isinstance(value, (str, int, bool)):
        raise ProtocolError('Invalid JSON value')
    return value


def _wire_json(raw):
    """Reject ambiguous keys, non-JSON constants and deeply nested peer data."""
    text = raw if isinstance(raw, str) else raw.decode('utf-8', errors='strict')
    depth = 0
    quoted = escaped = False
    for char in text:
        if quoted:
            if escaped:
                escaped = False
            elif char == '\\':
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char in '[{':
            depth += 1
            if depth > 64:
                raise ProtocolError('JSON nesting limit')
        elif char in ']}':
            depth -= 1

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ProtocolError('Duplicate JSON key')
            result[key] = value
        return result

    def constant(value):
        raise ProtocolError('Invalid JSON constant')

    return _finite_json(json.loads(text, object_pairs_hook=pairs, parse_constant=constant))


def sse_events(read):
    """Bound memory and wire volume; tolerate CR/LF/CRLF and SSE comments.

    EOF is not an event delimiter. No reconnect, retry field or Last-Event-ID.
    """
    line = bytearray()
    data = []
    size = total = count = 0
    after_cr = False
    first = True
    while chunk := read(4096):
        total += len(chunk)
        if total > 8 * 1024 * 1024:
            raise ProtocolError('Stream byte limit')
        for byte in chunk:
            if after_cr and byte == 10:
                after_cr = False
                continue
            after_cr = byte == 13
            if byte not in (10, 13):
                line.append(byte)
                if len(line) > 65536:
                    raise ProtocolError('SSE line limit')
                continue
            text = line.decode('utf-8', errors='strict')
            line.clear()
            if first:
                text = text.removeprefix('\ufeff')
                first = False
            if not text:
                if data:
                    count += 1
                    if count > 4096:
                        raise ProtocolError('SSE event count limit')
                    yield _wire_json('\n'.join(data))
                data, size = [], 0
            elif text.startswith('data:') or text == 'data':
                value = text.partition(':')[2].removeprefix(' ')
                size += len(value.encode()) + 1
                if size > 1024 * 1024:
                    raise ProtocolError('SSE event limit')
                data.append(value)
    if line or data:
        raise ProtocolError('Truncated SSE event')


class Client:
    """One configured logical peer, direct pinned RPC URL; no AgentCard fetching."""
    def __init__(self, config, store):
        allowed = {'enabled', 'peer', 'runtime', 'host', 'url', 'token_env', 'timeout', 'allow_loopback_http'}
        if not isinstance(config, dict) or set(config) - allowed:
            raise ValueError('Unknown outbound configuration fields')
        if config.get('enabled') is not True or any(config.get(k) != v for k, v in
                {'peer': 'zuri', 'runtime': 'codex', 'host': 'zurqui'}.items()):
            raise ValueError('Only explicitly enabled zuri / codex / zurqui is supported')
        url = urlsplit(config.get('url', ''))
        loopback = config.get('allow_loopback_http') is True and url.hostname in {'127.0.0.1', '::1'}
        if (url.scheme != 'https' and not (loopback and url.scheme == 'http')) or not url.hostname:
            raise ValueError('HTTPS required (HTTP loopback fixture must be explicit)')
        if url.hostname != REMOTE_ENDPOINT_HOST and not loopback:
            raise ValueError('Endpoint hostname must be the configured certificate FQDN')
        if url.username or url.password or url.query or url.fragment or any(c.isspace() for c in config['url']):
            raise ValueError('Endpoint must not contain credentials, query, fragment or whitespace')
        if not isinstance(config.get('token_env'), str) or not config['token_env'].isidentifier():
            raise ValueError('A bearer environment variable name is required')
        timeout = config.get('timeout', 30)
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 0 < timeout <= 300:
            raise ValueError('Timeout must be between zero and 300 seconds')
        self.config = dict(config)
        self.store = store
        self.binding = {k: config[k] for k in ('peer', 'runtime', 'host', 'url')}

    def prepare(self, text):
        token = self._token()
        if not isinstance(text, str) or not text.strip() or len(text.encode()) > 65536:
            raise ValueError('Message must be nonempty and at most 64 KiB')
        if token in text:
            raise ValueError('Bearer credential in message rejected')
        return self.store.prepare(self.binding, text)

    def _token(self):
        token = os.environ.get(self.config['token_env'])
        if not token:
            raise ValueError('Configured bearer environment variable is unset or empty')
        return token

    @contextmanager
    def _open(self, body, stream):
        token = self._token()  # Resolve before connecting; never send unauthenticated.
        url = urlsplit(self.binding['url'])
        cls = http.client.HTTPSConnection if url.scheme == 'https' else http.client.HTTPConnection
        timeout = self.config.get('timeout', 30)
        connection = cls(url.hostname, url.port, timeout=timeout)
        deadline = time.monotonic() + timeout
        response = timer = None
        expired = threading.Event()
        try:
            connection.connect()
            sock = connection.sock

            def expire():
                expired.set()
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    # Socket may already be closed; this is cleanup, never persistence.
                    return

            timer = threading.Timer(max(.001, deadline - time.monotonic()), expire)
            timer.daemon = True
            timer.start()
            connection.request('POST', url.path or '/', body=json.dumps(body, allow_nan=False).encode(), headers={
                'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json',
                'A2A-Version': '1.0', 'Accept': 'text/event-stream' if stream else 'application/json'})
            response = connection.getresponse()
            if response.status != 200:
                raise ProtocolError('Peer HTTP status ' + str(response.status))
            expected = 'text/event-stream' if stream else 'application/json'
            if response.getheader('Content-Type', '').split(';')[0].strip().lower() != expected:
                raise ProtocolError('Unexpected Content-Type')

            def read(size):
                if expired.is_set() or time.monotonic() >= deadline:
                    raise TimeoutError('A2A response deadline exceeded')
                if response.isclosed():
                    return b''
                data = response.read1(size)
                if expired.is_set():
                    raise TimeoutError('A2A response deadline exceeded')
                return data

            yield read
        except (http.client.HTTPException, OSError, ProtocolError) as exc:
            # Do NOT convert disk errors raised inside the consumer to timeouts.
            if expired.is_set() and isinstance(exc, (http.client.HTTPException, ProtocolError)):
                raise TimeoutError('A2A response deadline exceeded') from None
            raise
        finally:
            if timer is not None:
                timer.cancel()
                timer.join()
            if response is not None:
                response.close()
            connection.close()

    def _event(self, record, envelope, request_id):
        _finite_json(envelope)
        if self._token() in json.dumps(envelope, ensure_ascii=False, allow_nan=False):
            raise ProtocolError('Credential echoed by peer; response rejected')
        if not isinstance(envelope, dict) or envelope.get('jsonrpc') != '2.0' or envelope.get('id') != request_id:
            raise ProtocolError('Invalid JSON-RPC correlation')
        if 'error' in envelope:
            raise ProtocolError('Peer JSON-RPC error')
        result = envelope.get('result')
        if not isinstance(result, dict):
            raise ProtocolError('Invalid StreamResponse')
        view = _field_names(result, ('task', 'statusUpdate', 'artifactUpdate', 'message'))
        kinds = [k for k in ('task', 'statusUpdate', 'artifactUpdate', 'message') if view.get(k) is not None]
        if len(kinds) != 1 or not isinstance(view[kinds[0]], dict):
            raise ProtocolError('Invalid StreamResponse oneof')
        kind = kinds[0]
        value = _validate(kind, view[kind])
        # StreamResponse.message is explicitly FROM the agent (proto:775-781).
        # Task.history and TaskStatus.message describe associated messages, not
        # a standalone server reply; do not impose this positional rule there.
        if kind == 'message' and value['role'] != 'ROLE_AGENT':
            raise ProtocolError('StreamResponse message must be from agent')
        candidate = copy.deepcopy(record)
        task_id = value.get('id') if kind == 'task' else value.get('taskId')
        context_id = value.get('contextId')
        for field, new in (('task_id', task_id), ('context_id', context_id)):
            if new:
                if not isinstance(new, str) or len(new) > 1024:
                    raise ProtocolError('Invalid remote identity')
                if candidate[field] and candidate[field] != new:
                    raise ProtocolError('Remote identity changed')
                candidate[field] = new
        if kind in {'task', 'statusUpdate'}:
            candidate['remote_state'] = value['status']['state']
        candidate['events'].append(copy.deepcopy(result))
        state = candidate['remote_state']
        waiting = {'TASK_STATE_INPUT_REQUIRED', 'TASK_STATE_AUTH_REQUIRED'}
        terminal = {'TASK_STATE_COMPLETED', 'TASK_STATE_FAILED', 'TASK_STATE_CANCELED', 'TASK_STATE_REJECTED'}
        candidate['local_state'] = ('intervention_required' if state in waiting else
                                 'observed' if state in terminal or kind == 'message' else 'uncertain')
        self.store.save(candidate)
        record.clear()
        record.update(candidate)

    def send(self, local_id):
        with self.store.writer(local_id) as acquired:
            if not acquired:
                raise ValueError('Request has an active writer; use resume to observe')
            return self._send(local_id)

    def _send(self, local_id):
        self._token()
        record = self.store.claim_send(local_id, self.binding)
        with self._open(record['request'], True) as read:
            for event in sse_events(read):
                self._event(record, event, record['request']['id'])
                if record['local_state'] in {'observed', 'intervention_required'}:
                    break
        return record

    def resume(self, local_id):
        """GetTask only when idle; observe an active writer without invalidating it."""
        with self.store.writer(local_id) as acquired:
            record = self.store.load(local_id)
            if record['binding'] != self.binding:
                raise ValueError('Peer binding changed; refusing recovery')
            if not acquired or not record['task_id']:
                return record
            return self._resume(record)

    def _resume(self, record):
        body = {'jsonrpc': '2.0', 'id': uuid.uuid4().hex, 'method': 'GetTask',
                'params': {'id': record['task_id']}}
        with self._open(body, False) as read:
            raw = bytearray()
            while chunk := read(4096):
                raw.extend(chunk)
                if len(raw) > 1024 * 1024:
                    raise ProtocolError('GetTask response limit')
            envelope = _wire_json(raw)
            if not isinstance(envelope, dict) or envelope.get('id') != body['id'] or envelope.get('jsonrpc') != '2.0':
                raise ProtocolError('Invalid GetTask correlation')
            if 'error' in envelope:
                if not isinstance(envelope['error'], dict) or 'result' in envelope:
                    raise ProtocolError('Malformed GetTask error')
                error = envelope['error']
                if type(error.get('code')) is not int or not isinstance(error.get('message'), str):
                    raise ProtocolError('Malformed GetTask error fields')
                if 'data' in error:
                    details = error['data']
                    if not isinstance(details, list) or any(
                        not isinstance(d, dict) or not isinstance(d.get('@type'), str) for d in details
                    ):
                        raise ProtocolError('Malformed GetTask error details')
                if envelope['error'].get('code') == -32001:
                    record['local_state'] = 'remote_missing'
                    self.store.save(record)
                    return record
                raise ProtocolError('GetTask JSON-RPC error')
            envelope['result'] = {'task': envelope.get('result')}
            self._event(record, envelope, body['id'])
        return record


def _sync_dir(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


class Store:
    """Private local filesystem only. SQLite FULL commits, then directory fsync.

    Persistence exceptions deliberately propagate. Never use a network filesystem.
    """
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(mode=0o700, parents=False, exist_ok=True)
        if self.directory.is_symlink() or self.directory.stat().st_mode & 0o077:
            raise ValueError('State directory must be private (0700), not a symlink')
        _sync_dir(self.directory.parent)
        self.path = self.directory / 'outbound.sqlite3'
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        os.close(fd)
        with closing(self._connect()) as db, db:
            db.execute('CREATE TABLE IF NOT EXISTS requests (id TEXT PRIMARY KEY, body TEXT NOT NULL)')
        _sync_dir(self.directory)

    def _connect(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.execute('PRAGMA journal_mode=DELETE')
        db.execute('PRAGMA synchronous=FULL')
        return db

    @contextmanager
    def writer(self, local_id):
        """One network writer per request, across threads/processes, until close.

        Kernel releases flock on process death. Never unlink lock files: replacing
        the inode would allow two owners. No SQLite transaction spans the network;
        readers can see each FULL commit immediately. CAS remains a second guard.
        """
        name = hashlib.sha256(local_id.encode()).hexdigest() + '.lock'
        fd = os.open(self.directory / name, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                yield False
            else:
                try:
                    yield True
                finally:
                    fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)

    def prepare(self, binding, text):
        local_id = uuid.uuid4().hex
        request = {'jsonrpc': '2.0', 'id': local_id, 'method': 'SendStreamingMessage',
                   'params': {'message': {'role': 'ROLE_USER', 'messageId': uuid.uuid4().hex,
                                          'parts': [{'text': text}]}}}
        record = {'revision': 0, 'local_id': local_id, 'binding': binding, 'request': request,
                  'local_state': 'prepared', 'remote_state': None, 'task_id': None,
                  'context_id': None, 'events': []}
        with closing(self._connect()) as db, db:
            db.execute('INSERT INTO requests VALUES (?, ?)', (local_id, json.dumps(record, allow_nan=False)))
        _sync_dir(self.directory)
        return local_id

    def load(self, local_id):
        with closing(self._connect()) as db:
            row = db.execute('SELECT body FROM requests WHERE id=?', (local_id,)).fetchone()
        if row is None:
            raise ValueError('Unknown local request ID')
        return json.loads(row[0])

    def claim_send(self, local_id, binding):
        """Atomic one-shot claim, committed BEFORE any network bytes are sent."""
        with closing(self._connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT body FROM requests WHERE id=?', (local_id,)).fetchone()
            if row is None:
                raise ValueError('Unknown local request ID')
            record = json.loads(row[0])
            if record['binding'] != binding or record['local_state'] != 'prepared':
                raise ValueError('Binding mismatch or already attempted; use resume only')
            record['local_state'] = 'uncertain'
            record['revision'] += 1
            db.execute('UPDATE requests SET body=? WHERE id=?', (json.dumps(record, allow_nan=False), local_id))
        _sync_dir(self.directory)
        return record

    def save(self, record):
        next_revision = record['revision'] + 1
        body = json.dumps({**record, 'revision': next_revision}, allow_nan=False)
        if len(body.encode()) > 8 * 1024 * 1024:
            raise ValueError('Durable record size limit exceeded')
        with closing(self._connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT body FROM requests WHERE id=?', (record['local_id'],)).fetchone()
            if row is None:
                raise ValueError('Unknown local request ID')
            if json.loads(row[0])['revision'] != record['revision']:
                raise ValueError('Concurrent update; reload before explicit recovery')
            db.execute('UPDATE requests SET body=? WHERE id=?', (body, record['local_id']))
        _sync_dir(self.directory)
        record['revision'] = next_revision


def main(argv=None):
    """Separate opt-in operator CLI, not a native Hermes config option."""
    import argparse
    import sys
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True, help='Explicit outbound peer JSON file')
    parser.add_argument('--store', required=True, help='Private state directory; parent must exist')
    parser.add_argument('action', choices=['prepare', 'send', 'resume', 'show'])
    parser.add_argument('value', help='Message for prepare, local ID for other actions')
    args = parser.parse_args(argv)
    try:
        cfg = json.loads(Path(args.config).read_text(encoding="utf-8"))
        store = Store(args.store)
        client = Client(cfg, store)
        if args.action == 'prepare':
            result = store.load(client.prepare(args.value))
        elif args.action == 'show':
            result = store.load(args.value)
        else:
            result = getattr(client, args.action)(args.value)
        print(json.dumps(result, allow_nan=False))
        return 0
    except (OSError, sqlite3.Error, ValueError, http.client.HTTPException) as exc:
        # Never echo peer response, URL, message or credentials through exceptions.
        print(json.dumps({'error': type(exc).__name__, 'action': args.action,
                          'guidance': 'No automatic resend. Inspect local record; resume only.'}), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
