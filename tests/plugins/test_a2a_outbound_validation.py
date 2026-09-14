"""A2A 1.0 contract regressions, based on the pinned normative proto.

No live peers. Payloads are explicit local protocol fixtures, not codex-a2a.
"""
import copy
import importlib
import io
import json
from contextlib import contextmanager

import pytest


MESSAGE = {'messageId': 'm1', 'contextId': 'c', 'role': 'ROLE_AGENT', 'parts': [{'text': 'answer'}]}
ARTIFACT = {'artifactId': 'a1', 'parts': [{'text': 'answer'}]}
TASK = {'id': 't', 'contextId': 'c', 'status': {'state': 'TASK_STATE_WORKING'}}
STATUS = {'taskId': 't', 'contextId': 'c', 'status': {'state': 'TASK_STATE_WORKING'}}
UPDATE = {'taskId': 't', 'contextId': 'c', 'artifact': ARTIFACT}
VARIANTS = {'message': MESSAGE, 'task': TASK, 'statusUpdate': STATUS, 'artifactUpdate': UPDATE}


def setup_client(tmp_path, monkeypatch):
    m = importlib.import_module('plugins.platforms.a2a.outbound')
    monkeypatch.setenv('A2A_VALIDATION_TOKEN', 'fixture-credential')
    cfg = {'enabled': True, 'peer': 'zuri', 'runtime': 'codex', 'host': 'zurqui',
           'url': 'https://zurqui/rpc', 'token_env': 'A2A_VALIDATION_TOKEN'}
    client = m.Client(cfg, m.Store(tmp_path / 'state'))
    record = client.store.claim_send(client.prepare('hello'), client.binding)
    return m, client, record


def envelope(record, result):
    return {'jsonrpc': '2.0', 'id': record['request']['id'], 'result': result}


@pytest.mark.parametrize('role', ['ROLE_USER', 'ROLE_UNSPECIFIED', 0, 1])
@pytest.mark.parametrize('context', [None, 'c'])
@pytest.mark.parametrize('ack', [False, True])
def test_server_message_role_rejected_without_mutation(tmp_path, monkeypatch, role, context, ack):
    m, client, record = setup_client(tmp_path, monkeypatch)
    if ack:
        client._event(record, envelope(record, {'task': TASK}), record['request']['id'])
    before = copy.deepcopy(record)
    message = {**MESSAGE, 'role': role, 'contextId': context}
    with pytest.raises(m.ProtocolError):
        client._event(record, envelope(record, {'message': message}), record['request']['id'])
    assert record == before
    assert client.store.load(record['local_id']) == before


@pytest.mark.parametrize('role', ['ROLE_USER', 'ROLE_UNSPECIFIED', 0, 1])
def test_user_message_followed_by_task_is_not_certified(tmp_path, monkeypatch, role):
    m, client, _ = setup_client(tmp_path, monkeypatch)
    local_id = client.prepare('stream')
    calls = []

    @contextmanager
    def response(body, stream):
        calls.append(body['method'])
        results = [{'message': {'messageId': 'm', 'role': role, 'parts': []}}, {'task': TASK}]
        wire = ''.join('data: ' + json.dumps({'jsonrpc': '2.0', 'id': body['id'], 'result': r})
                       + '\n\n' for r in results)
        yield io.BytesIO(wire.encode()).read

    monkeypatch.setattr(client, '_open', response)
    with pytest.raises(m.ProtocolError):
        client.send(local_id)
    result = client.resume(local_id)
    assert result['local_state'] == 'uncertain'
    assert result['events'] == []
    assert result['task_id'] is None
    with pytest.raises(ValueError, match='already attempted'):
        client.send(local_id)
    assert calls == ['SendStreamingMessage']


@pytest.mark.parametrize('number', ['1e999', '-1e999', 'NaN', 'Infinity', '-Infinity'])
@pytest.mark.parametrize('path', ['data', 'metadata', 'artifact', 'history', 'error', 'extension'])
@pytest.mark.parametrize('transport', ['sse', 'gettask'])
def test_nonfinite_wire_preserves_last_ack(tmp_path, monkeypatch, number, path, transport):
    m, client, record = setup_client(tmp_path, monkeypatch)
    client._event(record, envelope(record, {'task': TASK}), record['request']['id'])
    before = copy.deepcopy(record)
    task = copy.deepcopy(TASK)
    nested = {'nested': [0, {'value': 'NUMBER_MARKER'}]}
    if path == 'data':
        task['status']['message'] = {**MESSAGE, 'parts': [{'data': nested}]}
    elif path == 'artifact':
        task['artifacts'] = [{**ARTIFACT, 'metadata': nested, 'parts': [{'data': nested}]}]
    elif path == 'history':
        task['history'] = [{**MESSAGE, 'role': 'ROLE_USER', 'parts': [{'data': nested}]}]
    else:
        task[path] = nested

    @contextmanager
    def response(body, stream):
        result = {'task': task} if stream else task
        payload = {'jsonrpc': '2.0', 'id': body['id'], 'result': result}
        if path == 'error':
            payload.pop('result')
            payload['error'] = {'code': -32001, 'message': 'missing',
                                'data': [{'@type': 'example.invalid/detail', **nested}]}
        raw = json.dumps(payload).replace('"NUMBER_MARKER"', number)
        yield io.BytesIO((('data: ' + raw + '\n\n') if stream else raw).encode()).read

    monkeypatch.setattr(client, '_open', response)
    with pytest.raises(m.ProtocolError):
        if transport == 'gettask':
            client.resume(record['local_id'])
        else:
            with client._open(record['request'], True) as read:
                for event in m.sse_events(read):
                    client._event(record, event, record['request']['id'])
    assert record == before
    assert client.store.load(record['local_id']) == before


@pytest.mark.parametrize('number', [float('nan'), float('inf'), float('-inf')])
@pytest.mark.parametrize('kind', VARIANTS)
def test_native_nonfinite_rejected_before_mutation(tmp_path, monkeypatch, number, kind):
    m, client, record = setup_client(tmp_path, monkeypatch)
    before = copy.deepcopy(record)
    result = {kind: {**VARIANTS[kind], 'metadata': {'nested': [number]}}}
    with pytest.raises(m.ProtocolError):
        client._event(record, envelope(record, result), record['request']['id'])
    assert record == before
    assert client.store.load(record['local_id']) == before


def test_store_nonfinite_serialization_is_defensive(tmp_path, monkeypatch):
    _, client, record = setup_client(tmp_path, monkeypatch)
    before = copy.deepcopy(record)
    record['events'].append({'nested': [float('nan')]})
    with pytest.raises(ValueError):
        client.store.save(record)
    assert record['revision'] == before['revision']
    assert client.store.load(record['local_id']) == before


@pytest.mark.parametrize('role', ['ROLE_USER', 1, 'ROLE_AGENT', 2])
@pytest.mark.parametrize('position', ['history', 'status'])
def test_associated_messages_and_finite_json_remain_valid(tmp_path, monkeypatch, role, position):
    _, client, record = setup_client(tmp_path, monkeypatch)
    data = [1.79e308, -1.79e308, 0.0, 'NaN', 'Infinity', '-Infinity', '1e999', None, True]
    message = {**MESSAGE, 'role': role, 'parts': [{'data': {'nested': data}}]}
    if role in ('ROLE_USER', 1):
        message.pop('contextId')
    task = copy.deepcopy(TASK)
    if position == 'history':
        task['history'] = [message]
    else:
        task['status']['message'] = message
    client._event(record, envelope(record, {'task': task}), record['request']['id'])
    assert client.store.load(record['local_id']) == record
    assert record['events'] == [{'task': task}]


MISSING = object()


def changed(kind, path, value=MISSING):
    result = copy.deepcopy(VARIANTS[kind])
    target = result
    for key in path[:-1]:
        target = target[key]
    if value is MISSING:
        target.pop(path[-1])
    else:
        target[path[-1]] = value
    return {kind: result}


INVALID = [
    pytest.param({'message': {}}, id='empty-message'),
    pytest.param({'task': {'id': 't', 'contextId': 'c'}}, id='task-no-status'),
]
for kind, paths in {
    'message': [('messageId',), ('role',), ('parts',), ('contextId',)],
    'task': [('id',), ('status',), ('status', 'state')],
    'statusUpdate': [('taskId',), ('contextId',), ('status',), ('status', 'state')],
    'artifactUpdate': [('taskId',), ('contextId',), ('artifact',), ('artifact', 'artifactId'), ('artifact', 'parts')],
}.items():
    for path in paths:
        INVALID.append(pytest.param(changed(kind, path), id=kind + '-missing-' + '.'.join(path)))
for kind, path, values in [
    ('message', ('messageId',), ['', 0, False, [], {}]),
    ('message', ('role',), ['agent', 'BAD_ROLE', False, {}, None]),
    ('message', ('parts',), [None, {}, ['text'], [{}], [{'text': 1}], [{'text': 'x', 'data': {}}],
                            [{'raw': '%%%'}], [{'url': 5}], [{'metadata': {}}]]),
    ('message', ('contextId',), [0, False, [], {}]),
    ('message', ('taskId',), [0, False, [], {}]),
    ('message', ('metadata',), [[], 'x']),
    ('message', ('extensions',), ['uri', [3]]),
    ('message', ('referenceTaskIds',), ['t', [False]]),
    ('task', ('id',), ['', 0, False, [], {}]),
    ('task', ('contextId',), [0, False, [], {}]),
    ('task', ('status',), [None, [], 'completed']),
    ('task', ('status', 'state'), [None, {}, False, 'completed', 'TASK_STATE_BOGUS']),
    ('task', ('status', 'message'), [{}]),
    ('task', ('status', 'timestamp'), [5, 'not-a-date', '2026-02-30T01:02:03Z']),
    ('task', ('history',), [{}, [{}]]),
    ('task', ('artifacts',), [{}, [{}], [{'artifactId': 'a', 'parts': []}]]),
    ('statusUpdate', ('contextId',), ['', 0]),
    ('statusUpdate', ('status',), [{}]),
    ('artifactUpdate', ('artifact',), [None, [], {}]),
    ('artifactUpdate', ('artifact', 'artifactId'), ['', False]),
    ('artifactUpdate', ('artifact', 'parts'), [None, [], [{}]]),
    ('artifactUpdate', ('append',), [1, 'true']),
    ('artifactUpdate', ('lastChunk',), [0, 'false']),
    ('artifactUpdate', ('metadata',), [[], 1]),
]:
    for index, value in enumerate(values):
        INVALID.append(pytest.param(changed(kind, path, value), id=f'{kind}-bad-{".".join(path)}-{index}'))


@pytest.mark.parametrize('result', INVALID)
def test_malformed_variant_preserves_memory_and_durable_state(tmp_path, monkeypatch, result):
    m, client, record = setup_client(tmp_path, monkeypatch)
    client._event(record, envelope(record, {'task': TASK}), record['request']['id'])
    before = copy.deepcopy(record)
    with pytest.raises(m.ProtocolError):
        client._event(record, envelope(record, result), record['request']['id'])
    assert record == before
    assert client.store.load(record['local_id']) == before


@pytest.mark.parametrize('kind', VARIANTS)
def test_legitimate_variants_are_persisted(tmp_path, monkeypatch, kind):
    _, client, record = setup_client(tmp_path, monkeypatch)
    result = {kind: copy.deepcopy(VARIANTS[kind])}
    client._event(record, envelope(record, result), record['request']['id'])
    assert client.store.load(record['local_id']) == record
    assert record['events'] == [result]


@pytest.mark.parametrize('result', [
    {'task': {'id': 't', 'status': {'state': 'TASK_STATE_UNSPECIFIED'}}},
    {'message': {**MESSAGE, 'parts': []}},
    {'message': {**MESSAGE, 'parts': [{'text': ''}, {'raw': '-_8', 'mediaType': 'application/octet-stream'},
                                   {'url': 'urn:example:file'}, {'data': None}, {'data': [False, 1, 's']}]}},
    {'task': {**TASK, 'history': [{'messageId': 'user-1', 'role': 'ROLE_USER', 'parts': [{'data': True}]}]}},
    {'statusUpdate': {**STATUS, 'status': {'state': 'TASK_STATE_WORKING', 'timestamp': '2026-09-13T01:02:03.123456789Z',
                                        'message': MESSAGE}}},
    {'artifactUpdate': {**UPDATE, 'append': False, 'lastChunk': True, 'metadata': {'extension': {'x': [None]}}}},
    {'task': {**TASK, 'metadata': None, 'history': [], 'artifacts': []}},
])
def test_protocol_optional_and_non_text_content_not_overrestricted(tmp_path, monkeypatch, result):
    _, client, record = setup_client(tmp_path, monkeypatch)
    client._event(record, envelope(record, result), record['request']['id'])
    assert record['events'] == [result]
    assert client.store.load(record['local_id']) == record


@pytest.mark.parametrize('result, expected', [
    ({'task': {**TASK, 'status': {'state': 3}}}, 'TASK_STATE_COMPLETED'),
    ({'task': {**TASK, 'status': {'state': 6}}}, 'TASK_STATE_INPUT_REQUIRED'),
    ({'message': {**MESSAGE, 'role': 2}}, None),
    ({'task': TASK, 'message': None}, 'TASK_STATE_WORKING'),
    ({'status_update': {'task_id': 't', 'context_id': 'c', 'status': {'state': 2}}}, 'TASK_STATE_WORKING'),
    ({'message': {'message_id': 'm', 'context_id': 'c', 'role': 'ROLE_AGENT',
                  'parts': [{'raw': 'YQ==', 'media_type': 'text/plain'}]}}, None),
])
def test_protojson_read_forms_preserve_original_events(tmp_path, monkeypatch, result, expected):
    _, client, record = setup_client(tmp_path, monkeypatch)
    client._event(record, envelope(record, result), record['request']['id'])
    assert record['remote_state'] == expected
    assert record['events'] == [result]
    assert client.store.load(record['local_id']) == record


@pytest.mark.parametrize('error', [
    {'code': -32001}, {'code': -32001, 'message': []},
    {'code': -32001, 'message': 'missing', 'data': 'bad'},
])
def test_gettask_error_validated_before_remote_missing(tmp_path, monkeypatch, error):
    m, client, record = setup_client(tmp_path, monkeypatch)
    client._event(record, envelope(record, {'task': TASK}), record['request']['id'])
    before = copy.deepcopy(record)

    @contextmanager
    def response(body, stream):
        yield io.BytesIO(json.dumps({'jsonrpc': '2.0', 'id': body['id'], 'error': error}).encode()).read

    monkeypatch.setattr(client, '_open', response)
    with pytest.raises(m.ProtocolError):
        client.resume(record['local_id'])
    assert client.store.load(record['local_id']) == before


def test_rejected_identity_does_not_partially_mutate_record(tmp_path, monkeypatch):
    m, client, record = setup_client(tmp_path, monkeypatch)
    record['context_id'] = 'existing'
    client.store.save(record)
    before = copy.deepcopy(record)
    with pytest.raises(m.ProtocolError, match='identity changed'):
        client._event(record, envelope(record, {'task': TASK}), record['request']['id'])
    assert record == before
    assert client.store.load(record['local_id']) == before


@pytest.mark.parametrize('result', [{}, {'id': 't', 'contextId': 'c'}, {**TASK, 'status': {}}])
def test_malformed_gettask_result_preserves_last_ack(tmp_path, monkeypatch, result):
    m, client, record = setup_client(tmp_path, monkeypatch)
    client._event(record, envelope(record, {'task': TASK}), record['request']['id'])
    before = copy.deepcopy(record)

    @contextmanager
    def response(body, stream):
        assert body['method'] == 'GetTask'
        assert not stream
        yield io.BytesIO(json.dumps({'jsonrpc': '2.0', 'id': body['id'], 'result': result}).encode()).read

    monkeypatch.setattr(client, '_open', response)
    with pytest.raises(m.ProtocolError):
        client.resume(record['local_id'])
    assert client.store.load(record['local_id']) == before
    with pytest.raises(ValueError, match='already attempted'):
        client.send(record['local_id'])
