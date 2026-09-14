"""Outbound only; real loopback fixtures are NOT codex-a2a acceptance."""
import importlib
import io
import json
import os
import sqlite3
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest


@pytest.mark.parametrize('change', [
    {'enabled': False}, {'peer': 'other'}, {'runtime': 'hermes'}, {'host': 'other'},
    {'url': 'http://zurqui/rpc'}, {'url': 'https://user:secret@zurqui/rpc'},
    {'url': 'https://zurqui/rpc?token=secret'}, {'url': 'https://zurqui/rpc#fragment'},
    {'url': 'ftp://zurqui/rpc'}, {'url': 'https://public.example/rpc'},
    {'token': 'literal-secret'}, {'timeout': 0}, {'timeout': 301},
])
def test_config_rejects_unapproved_transport(tmp_path, change):
    cfg = {**config('https://zurqui/rpc'), **change}
    with pytest.raises(ValueError):
        module().Client(cfg, module().Store(tmp_path / 'requests'))


def test_credentials_fail_closed_without_durable_secret(tmp_path, monkeypatch):
    m = module()
    client = m.Client(config('https://zurqui/rpc'), m.Store(tmp_path / 'requests'))
    monkeypatch.delenv('A2A_TEST_TOKEN', raising=False)
    with pytest.raises(ValueError):
        client.prepare('hello')
    monkeypatch.setenv('A2A_TEST_TOKEN', 'fixture-secret')
    with pytest.raises(ValueError):
        client.prepare('do not persist fixture-secret')
    assert not b'fixture-secret' in client.store.path.read_bytes()


@pytest.mark.parametrize('state', ['TASK_STATE_WORKING', 'TASK_STATE_INPUT_REQUIRED', 'TASK_STATE_AUTH_REQUIRED'])
def test_remote_state_not_replaced_by_local_intervention(tmp_path, monkeypatch, state):
    m = module()
    store = m.Store(tmp_path / 'requests')
    monkeypatch.setenv('A2A_TEST_TOKEN', 'fixture-secret')
    events = [{'task': {'id': 'remote-1', 'contextId': 'ctx-1', 'status': {'state': state}}}]
    with peer_server(store, events) as (url, received):
        client = m.Client(config(url), store)
        result = client.send(client.prepare('hello'))
    assert result['remote_state'] == state
    assert result['local_state'] == ('uncertain' if state == 'TASK_STATE_WORKING' else 'intervention_required')
    assert len(received) == 1


def test_echoed_credential_is_not_persisted(tmp_path, monkeypatch):
    m = module()
    store = m.Store(tmp_path / 'requests')
    monkeypatch.setenv('A2A_TEST_TOKEN', 'fixture-secret')
    events = [{'task': {'id': 'remote-1', 'contextId': 'ctx-1', 'status': {'state': 'TASK_STATE_COMPLETED'},
                        'artifacts': [{'parts': [{'text': 'fixture-secret'}]}]}}]
    with peer_server(store, events) as (url, received):
        client = m.Client(config(url), store)
        with pytest.raises(ValueError):
            client.send(client.prepare('hello'))
    assert b'fixture-secret' not in store.path.read_bytes()



@contextmanager
def subprocess_peer(root, mode, port=0):
    fixture = Path(__file__).parent / 'fixtures' / 'a2a_outbound_peer.py'
    process = subprocess.Popen([sys.executable, str(fixture), str(root), str(port), mode],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        ready = process.stdout.readline().strip()
        assert ready, process.stderr.read()
        yield int(ready)
    finally:
        process.terminate()
        process.communicate(timeout=5)


def cli(tmp_path, cfg, action, value, check=True):
    config_path = tmp_path / 'peer.json'
    config_path.write_text(json.dumps(cfg))
    result = subprocess.run([sys.executable, '-m', 'plugins.platforms.a2a.outbound',
                             '--config', str(config_path), '--store', str(tmp_path / 'requests'),
                             action, value], capture_output=True, text=True, timeout=10,
                            env={**os.environ, 'A2A_TEST_TOKEN': 'fixture-secret'})
    if check:
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout)
    return result


@pytest.mark.parametrize('mode', ['durable', 'lost', 'before-ack'])
def test_separate_client_and_server_restart_never_resends(tmp_path, mode):
    with subprocess_peer(tmp_path, mode) as port:
        cfg = config(f'http://127.0.0.1:{port}/rpc')
        prepared = cli(tmp_path, cfg, 'prepare', 'hello')
        local_id = prepared['local_id']
        sent = cli(tmp_path, cfg, 'send', local_id, check=False)
        assert sent.returncode == (2 if mode == 'before-ack' else 0)
    # New server PROCESS, same bound endpoint. Each CLI invocation also a new process.
    with subprocess_peer(tmp_path, 'durable', port):
        resumed = cli(tmp_path, cfg, 'resume', local_id)
        duplicate = cli(tmp_path, cfg, 'send', local_id, check=False)
        assert duplicate.returncode == 2
    calls = [json.loads(line) for line in (tmp_path / 'calls.jsonl').read_text().splitlines()]
    if mode == 'before-ack':
        assert resumed['local_state'] == 'uncertain'
        assert resumed['task_id'] is None
        assert [c['method'] for c in calls] == ['SendStreamingMessage']
    else:
        assert [c['method'] for c in calls] == ['SendStreamingMessage', 'GetTask']
        assert resumed['task_id'] == 'remote-1'
        assert resumed['context_id'] == 'ctx-1'
        if mode == 'lost':
            assert resumed['remote_state'] == 'TASK_STATE_WORKING'
            assert resumed['local_state'] == 'remote_missing'
        else:
            assert resumed['remote_state'] == 'TASK_STATE_COMPLETED'
            assert resumed['events'][-1]['task']['artifacts'][0]['parts'][0]['text'] == 'durable fixture result'



@contextmanager
def peer_server(store, events):
    received = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            received.append(body)
            saved = store.load(body['id'])
            assert saved['local_state'] == 'uncertain'
            assert saved['request'] == body
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.end_headers()
            for event in events:
                envelope = {'jsonrpc': '2.0', 'id': body['id'], 'result': event}
                self.wfile.write(b': heartbeat\r\n\r\ndata: ' + json.dumps(envelope).encode() + b'\r\n\r\n')
                self.wfile.flush()

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}/rpc', received
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def config(url):
    return {'enabled': True, 'peer': 'zuri', 'runtime': 'codex', 'host': 'zurqui',
            'url': url, 'token_env': 'A2A_TEST_TOKEN', 'timeout': 2,
            'allow_loopback_http': True}


def test_stream_persists_identity_status_and_artifact(tmp_path, monkeypatch):
    m = module()
    store = m.Store(tmp_path / 'requests')
    monkeypatch.setenv('A2A_TEST_TOKEN', 'fixture-secret')
    events = [
        {'task': {'id': 'remote-1', 'contextId': 'ctx-1', 'status': {'state': 'TASK_STATE_WORKING'}}},
        {'artifactUpdate': {'taskId': 'remote-1', 'contextId': 'ctx-1',
                            'artifact': {'artifactId': 'a1', 'parts': [{'text': 'answer'}]}, 'lastChunk': True}},
        {'statusUpdate': {'taskId': 'remote-1', 'contextId': 'ctx-1', 'status': {'state': 'TASK_STATE_COMPLETED'}}},
    ]
    with peer_server(store, events) as (url, received):
        client = m.Client(config(url), store)
        local_id = client.prepare('hello')
        result = client.send(local_id)
    saved = m.Store(tmp_path / 'requests').load(local_id)
    assert saved == result
    assert saved['task_id'] == 'remote-1'
    assert saved['context_id'] == 'ctx-1'
    assert saved['remote_state'] == 'TASK_STATE_COMPLETED'
    assert saved['local_state'] == 'observed'
    assert saved['events'] == events
    assert len(received) == 1
    assert 'fixture-secret' not in json.dumps(saved)



def test_only_one_process_can_claim_a_prepared_send(tmp_path, monkeypatch):
    m = module()
    store = m.Store(tmp_path / 'requests')
    binding = {'peer': 'zuri', 'runtime': 'codex', 'host': 'zurqui', 'url': 'https://zurqui/rpc'}
    local_id = store.prepare(binding, 'hello')
    script = ('from plugins.platforms.a2a.outbound import Store; import sys; '
              'Store(sys.argv[1]).claim_send(sys.argv[2], ' + repr(binding) + ')')
    children = [subprocess.Popen([sys.executable, '-c', script, str(store.directory), local_id],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE) for _ in range(2)]
    for child in children:
        child.communicate(timeout=5)
    assert sorted(p.returncode for p in children) == [0, 1]
    assert store.load(local_id)['local_state'] == 'uncertain'


def test_fsync_failure_prevents_network(tmp_path, monkeypatch):
    m = module()
    monkeypatch.setenv('A2A_TEST_TOKEN', 'fixture-secret')
    store = m.Store(tmp_path / 'requests')
    with peer_server(store, []) as (url, calls):
        client = m.Client(config(url), store)
        local_id = client.prepare('hello')
        def broken(fd):
            raise OSError('injected fsync failure')
        monkeypatch.setattr(m.os, 'fsync', broken)
        with pytest.raises(OSError, match='fsync'):
            client.send(local_id)
        assert not calls


def test_persistence_failure_on_ack_is_not_swallowed(tmp_path, monkeypatch):
    m = module()
    monkeypatch.setenv('A2A_TEST_TOKEN', 'fixture-secret')
    store = m.Store(tmp_path / 'requests')
    events = [{'task': {'id': 'remote-1', 'contextId': 'ctx-1', 'status': {'state': 'TASK_STATE_WORKING'}}}]
    with peer_server(store, events) as (url, calls):
        client = m.Client(config(url), store)
        local_id = client.prepare('hello')
        real_save = store.save
        def broken(record):
            if record['task_id']:
                raise sqlite3.OperationalError('disk full')
            real_save(record)
        monkeypatch.setattr(store, 'save', broken)
        with pytest.raises(sqlite3.OperationalError, match='disk full'):
            client.send(local_id)
        assert len(calls) == 1
        assert store.load(local_id)['local_state'] == 'uncertain'


def test_client_killed_after_ack_recovers_from_durable_ids(tmp_path):
    with subprocess_peer(tmp_path, 'hold') as port:
        cfg = config(f'http://127.0.0.1:{port}/rpc')
        cfg['timeout'] = 20
        local_id = cli(tmp_path, cfg, 'prepare', 'hello')['local_id']
        command = [sys.executable, '-m', 'plugins.platforms.a2a.outbound', '--config', str(tmp_path / 'peer.json'),
                   '--store', str(tmp_path / 'requests'), 'send', local_id]
        child = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 env={**os.environ, 'A2A_TEST_TOKEN': 'fixture-secret'})
        try:
            deadline = time.monotonic() + 8
            store = module().Store(tmp_path / 'requests')
            while time.monotonic() < deadline:
                if store.load(local_id)['task_id']:
                    break
                time.sleep(.02)
            assert store.load(local_id)['task_id'] == 'remote-1'
            assert store.load(local_id)['context_id'] == 'ctx-1'
            assert child.poll() is None
        finally:
            child.kill()
            child.communicate(timeout=5)
    with subprocess_peer(tmp_path, 'durable', port):
        result = cli(tmp_path, cfg, 'resume', local_id)
    assert result['remote_state'] == 'TASK_STATE_COMPLETED'
    calls = [json.loads(x)['method'] for x in (tmp_path / 'calls.jsonl').read_text().splitlines()]
    assert calls == ['SendStreamingMessage', 'GetTask']


@pytest.mark.parametrize('wire', [b'data: {}', b'data: \xff\n\n', b'data: ' + b'x' * 65537 + b'\n\n',
                                  b'data: x\n' * 150000 + b'\n', b'data: {}\n\n' * 4097])
def test_sse_rejects_truncation_invalid_utf8_and_bounds(wire):
    with pytest.raises((ValueError, UnicodeError)):
        list(module().sse_events(io.BytesIO(wire).read))


@pytest.mark.parametrize('separator', [b'\n', b'\r', b'\r\n'])
def test_sse_multiline_comments_and_fragmented_unicode(separator):
    wire = separator.join([b'\xef\xbb\xbf: heartbeat', b'id: ignored', b'data: {"text":',
                           'data: "caf\u00e9"}'.encode(), b'', b''])
    stream = io.BytesIO(wire)
    assert list(module().sse_events(lambda n: stream.read(1))) == [{'text': 'caf\u00e9'}]


@pytest.mark.parametrize('mode', ['drip', 'headers'])
def test_stream_deadline_not_extended_by_heartbeats(tmp_path, monkeypatch, mode):
    monkeypatch.setenv('A2A_TEST_TOKEN', 'fixture-secret')
    with subprocess_peer(tmp_path, mode) as port:
        cfg = config(f'http://127.0.0.1:{port}/rpc')
        cfg['timeout'] = 1
        client = module().Client(cfg, module().Store(tmp_path / 'requests'))
        local_id = client.prepare('hello')
        start = time.monotonic()
        with pytest.raises(TimeoutError):
            client.send(local_id)
        assert time.monotonic() - start < 4
        assert client.store.load(local_id)['task_id'] == ('remote-1' if mode == 'drip' else None)


def test_stale_recovery_cannot_overwrite_newer_durable_event(tmp_path):
    store = module().Store(tmp_path / 'requests')
    local_id = store.prepare({'peer': 'zuri'}, 'hello')
    stale = store.load(local_id)
    latest = store.load(local_id)
    latest['local_state'] = 'uncertain'
    latest['task_id'] = 'acknowledged'
    store.save(latest)
    with pytest.raises(ValueError, match='Concurrent'):
        store.save(stale)
    assert store.load(local_id)['task_id'] == 'acknowledged'


def test_intervention_ends_stream_without_processing_followup(tmp_path, monkeypatch):
    monkeypatch.setenv('A2A_TEST_TOKEN', 'fixture-secret')
    store = module().Store(tmp_path / 'requests')
    events = [{'task': {'id': 'remote-1', 'contextId': 'ctx-1', 'status': {'state': 'TASK_STATE_INPUT_REQUIRED'}}},
              {'statusUpdate': {'taskId': 'remote-1', 'contextId': 'ctx-1', 'status': {'state': 'TASK_STATE_COMPLETED'}}}]
    with peer_server(store, events) as (url, calls):
        client = module().Client(config(url), store)
        result = client.send(client.prepare('hello'))
    assert result['local_state'] == 'intervention_required'
    assert result['events'] == events[:1]


def test_completed_message_remains_durable_on_resume_without_task(tmp_path, monkeypatch):
    monkeypatch.setenv('A2A_TEST_TOKEN', 'fixture-secret')
    store = module().Store(tmp_path / 'requests')
    events = [{'message': {'messageId': 'm1', 'contextId': 'ctx-1', 'role': 'ROLE_AGENT', 'parts': [{'text': 'answer'}]}}]
    with peer_server(store, events) as (url, calls):
        client = module().Client(config(url), store)
        local_id = client.prepare('hello')
        result = client.send(local_id)
        resumed = client.resume(local_id)
    assert result == resumed
    assert len(calls) == 1


@pytest.mark.parametrize('result', [
    {'task': {'id': 't', 'contextId': 'c', 'status': []}},
    {'task': {'id': 0, 'contextId': 'c', 'status': {'state': 'TASK_STATE_WORKING'}}},
    {'statusUpdate': {'taskId': 't', 'contextId': 'c', 'status': None}},
])
def test_malformed_peer_data_fails_as_protocol_error(tmp_path, monkeypatch, result):
    monkeypatch.setenv('A2A_TEST_TOKEN', 'fixture-secret')
    store = module().Store(tmp_path / 'requests')
    with peer_server(store, [result]) as (url, calls):
        client = module().Client(config(url), store)
        with pytest.raises(ValueError):
            client.send(client.prepare('hello'))


def test_redirect_is_not_followed_and_card_is_never_fetched(tmp_path, monkeypatch):
    monkeypatch.setenv('A2A_TEST_TOKEN', 'fixture-secret')
    with subprocess_peer(tmp_path, 'redirect') as port:
        client = module().Client(config(f'http://127.0.0.1:{port}/rpc'), module().Store(tmp_path / 'requests'))
        local_id = client.prepare('hello')
        with pytest.raises(module().ProtocolError, match='307'):
            client.send(local_id)
        calls = (tmp_path / 'calls.jsonl').read_text().splitlines()
        assert len(calls) == 1
        assert client.store.load(local_id)['local_state'] == 'uncertain'


def test_resume_rejects_changed_endpoint_before_network(tmp_path, monkeypatch):
    monkeypatch.setenv('A2A_TEST_TOKEN', 'fixture-secret')
    store = module().Store(tmp_path / 'requests')
    with subprocess_peer(tmp_path, 'durable') as port:
        cfg = config(f'http://127.0.0.1:{port}/rpc')
        client = module().Client(cfg, store)
        local_id = client.prepare('hello')
        client.send(local_id)
        changed = module().Client({**cfg, 'url': cfg['url'] + '/other'}, store)
        with pytest.raises(ValueError, match='binding'):
            changed.resume(local_id)
        assert len((tmp_path / 'calls.jsonl').read_text().splitlines()) == 1


def test_server_disconnect_during_execution_keeps_working(tmp_path):
    with subprocess_peer(tmp_path, 'hold') as port:
        cfg = config(f'http://127.0.0.1:{port}/rpc')
        cfg['timeout'] = 20
        local_id = cli(tmp_path, cfg, 'prepare', 'hello')['local_id']
        child = subprocess.Popen([sys.executable, '-m', 'plugins.platforms.a2a.outbound',
                                  '--config', str(tmp_path / 'peer.json'), '--store', str(tmp_path / 'requests'),
                                  'send', local_id], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                 env={**os.environ, 'A2A_TEST_TOKEN': 'fixture-secret'})
        store = module().Store(tmp_path / 'requests')
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline and not store.load(local_id)['task_id']:
            time.sleep(.02)
        assert store.load(local_id)['task_id'] == 'remote-1'
    # Server exited mid-stream; client stays alive until EOF (no client restart here).
    try:
        stdout, stderr = child.communicate(timeout=5)
        assert child.returncode == 0, stderr
        result = json.loads(stdout)
        assert result['remote_state'] == 'TASK_STATE_WORKING'
        assert result['local_state'] == 'uncertain'
    finally:
        if child.poll() is None:
            child.kill()
            child.communicate(timeout=5)
    with subprocess_peer(tmp_path, 'durable', port):
        assert cli(tmp_path, cfg, 'resume', local_id)['remote_state'] == 'TASK_STATE_COMPLETED'
    assert [json.loads(x)['method'] for x in (tmp_path / 'calls.jsonl').read_text().splitlines()] == ['SendStreamingMessage', 'GetTask']


@pytest.mark.parametrize('wire', [b'data: ' + b'[' * 1500 + b'0' + b']' * 1500 + b'\n\n',
                                 b'data: {"id":1,"id":2}\n\n', b'data: {"x":NaN}\n\n'])
def test_sse_rejects_noncanonical_or_too_deep_json(wire):
    with pytest.raises(ValueError):
        list(module().sse_events(io.BytesIO(wire).read))


def test_malformed_gettask_error_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setenv('A2A_TEST_TOKEN', 'fixture-secret')
    store = module().Store(tmp_path / 'requests')
    with subprocess_peer(tmp_path, 'bad-get') as port:
        client = module().Client(config(f'http://127.0.0.1:{port}/rpc'), store)
        local_id = client.prepare('hello')
        client.send(local_id)
        with pytest.raises(ValueError):
            client.resume(local_id)
        assert store.load(local_id)['remote_state'] == 'TASK_STATE_WORKING'


@pytest.mark.parametrize('result', [
    {'message': {}},
    {'task': {'id': 'remote-1', 'contextId': 'ctx-1'}},
    {'statusUpdate': {'taskId': 'remote-1', 'contextId': 'ctx-1'}},
    {'artifactUpdate': {'taskId': 'remote-1', 'contextId': 'ctx-1', 'artifact': {}}},
])
def test_malformed_first_loopback_event_never_certifies_or_resends(tmp_path, monkeypatch, result):
    monkeypatch.setenv('A2A_TEST_TOKEN', 'fixture-secret')
    m = module()
    store = m.Store(tmp_path / 'requests')
    followup = {'task': {'id': 'remote-1', 'contextId': 'ctx-1', 'status': {'state': 'TASK_STATE_COMPLETED'}}}
    with peer_server(store, [result, followup]) as (url, calls):
        client = m.Client(config(url), store)
        local_id = client.prepare('hello')
        with pytest.raises(m.ProtocolError):
            client.send(local_id)
        saved = store.load(local_id)
        assert saved['local_state'] == 'uncertain'
        assert saved['task_id'] is None
        assert saved['context_id'] is None
        assert saved['events'] == []
        assert client.resume(local_id) == saved
        with pytest.raises(ValueError, match='already attempted'):
            client.send(local_id)
        assert len(calls) == 1


@pytest.mark.parametrize('phase', ['before-ack', 'after-ack', 'during-get'])
def test_concurrent_resume_is_read_only_while_writer_active(tmp_path, monkeypatch, phase):
    """Cross-process observer, real loopback, deterministic network barriers."""
    from concurrent.futures import ThreadPoolExecutor

    monkeypatch.setenv('A2A_TEST_TOKEN', 'fixture-secret')
    m = module()
    store = m.Store(tmp_path / 'requests')
    entered, release = threading.Event(), threading.Event()
    calls = []
    task = {'id': 'remote-1', 'contextId': 'ctx-1', 'status': {'state': 'TASK_STATE_WORKING'}}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            calls.append(body['method'])
            streaming = body['method'] == 'SendStreamingMessage'
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream' if streaming else 'application/json')
            self.end_headers()
            if (streaming and phase == 'before-ack') or (not streaming and phase == 'during-get'):
                entered.set()
                assert release.wait(8)
            if streaming:
                payload = {'jsonrpc': '2.0', 'id': body['id'], 'result': {'task': task}}
                self.wfile.write(('data: ' + json.dumps(payload) + '\n\n').encode())
                self.wfile.flush()
                if phase == 'after-ack':
                    entered.set()
                    assert release.wait(8)
                    event = {'statusUpdate': {'taskId': 'remote-1', 'contextId': 'ctx-1',
                                             'status': {'state': 'TASK_STATE_INPUT_REQUIRED'}}}
                    payload['result'] = event
                    self.wfile.write(('data: ' + json.dumps(payload) + '\n\n').encode())
            else:
                completed = {**task, 'status': {'state': 'TASK_STATE_COMPLETED'}}
                self.wfile.write(json.dumps({'jsonrpc': '2.0', 'id': body['id'], 'result': completed}).encode())

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    cfg = {**config(f'http://127.0.0.1:{server.server_port}/rpc'), 'timeout': 10}
    client = m.Client(cfg, store)
    local_id = client.prepare('hello')
    try:
        if phase == 'during-get':
            client.send(local_id)
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(client.resume if phase == 'during-get' else client.send, local_id)
            try:
                assert entered.wait(5)
                if phase == 'after-ack':
                    deadline = time.monotonic() + 5
                    while not store.load(local_id)['task_id'] and time.monotonic() < deadline:
                        time.sleep(.01)
                    assert store.load(local_id)['task_id'] == 'remote-1'
                before = store.load(local_id)
                assert cli(tmp_path, cfg, 'resume', local_id) == before
                assert store.load(local_id) == before
            finally:
                release.set()
            result = pending.result(timeout=5)
        assert result['task_id'] == 'remote-1'
        assert result['context_id'] == 'ctx-1'
        if phase == 'after-ack':
            assert result['local_state'] == 'intervention_required'
        recovered = cli(tmp_path, cfg, 'resume', local_id)
        assert recovered['remote_state'] == 'TASK_STATE_COMPLETED'
        assert cli(tmp_path, cfg, 'send', local_id, check=False).returncode == 2
        assert calls == ['SendStreamingMessage'] + ['GetTask'] * (2 if phase == 'during-get' else 1)
    finally:
        release.set()
        server.shutdown()
        server.server_close()
        thread.join()


def test_resume_prepared_does_not_consume_send(tmp_path, monkeypatch):
    monkeypatch.setenv('A2A_TEST_TOKEN', 'fixture-secret')
    store = module().Store(tmp_path / 'requests')
    with peer_server(store, []) as (url, calls):
        client = module().Client(config(url), store)
        local_id = client.prepare('hello')
        before = store.load(local_id)
        assert client.resume(local_id) == before
        client.send(local_id)
        assert len(calls) == 1


def module():
    return importlib.import_module('plugins.platforms.a2a.outbound')


def test_prepare_is_durable_before_any_network(tmp_path):
    m = module()
    store = m.Store(tmp_path / 'requests')
    binding = {'peer': 'zuri', 'runtime': 'codex', 'host': 'zurqui', 'url': 'https://zurqui/rpc'}
    local_id = store.prepare(binding, 'hello')
    saved = m.Store(tmp_path / 'requests').load(local_id)
    assert saved['binding'] == binding
    assert saved['request']['method'] == 'SendStreamingMessage'
    assert saved['request']['params']['message']['parts'] == [{'text': 'hello'}]
    assert saved['local_state'] == 'prepared'
    assert saved['remote_state'] is None
    assert saved['task_id'] is None
    with sqlite3.connect(tmp_path / 'requests' / 'outbound.sqlite3') as db:
        assert db.execute('select count(*) from requests').fetchone()[0] == 1
    assert json.dumps(saved).find('Authorization') == -1
