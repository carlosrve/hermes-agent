"""Opt-in native facade; no human dispatch bridge, therefore no send path.

Scope is trusted Python runtime metadata, NOT an OS security boundary. An agent
with same-user terminal access can edit files/import this code/read its env.
"""
from dataclasses import dataclass
import hashlib
import json
import re
from pathlib import Path

from hermes_constants import get_hermes_home


@dataclass(frozen=True)
class DispatchScope:
    """Dispatcher-only metadata, never accepted from model arguments."""
    home: Path
    session_id: str
    tools: frozenset[str]


def _client(ctx, store=None):
    from plugins.platforms.a2a.outbound import Client
    config = ctx.get_config('outbound', None)
    if not isinstance(config, dict) or config.get('allow_loopback_http') is True:
        raise ValueError('Invalid native configuration')
    return Client(config, store)


def _available(ctx):
    try:
        _client(ctx)
        return True
    except Exception:
        return False


def _store(scope):
    from plugins.platforms.a2a.outbound import Store
    # Atomic ownership by namespace: no separate, crash-prone owner sidecar.
    # Hashing avoids path traversal; it is NOT secrecy or proof of authority.
    digest = hashlib.sha256(scope.session_id.encode()).hexdigest()
    return Store(scope.home / ('a2a-native-' + digest))


def _snapshot(record):
    from plugins.platforms.a2a.outbound import _STATES
    if (record['local_state'] not in ('prepared', 'uncertain', 'observed',
                                     'intervention_required', 'remote_missing')
            or record['remote_state'] not in (None, *_STATES)
            or not isinstance(record['local_id'], str)
            or re.fullmatch(r'[0-9a-f]{32}', record['local_id']) is None):
        raise ValueError('Invalid snapshot')
    return {'status': 'ok', 'local_id': record['local_id'],
            'local_state': record['local_state'], 'remote_state': record['remote_state'],
            'authorization': 'blocked_bridge_missing'}


def _handle(ctx, args, scope):
    if not _available(ctx):
        return {'status': 'blocked', 'reason': 'outbound_unavailable'}
    if (not isinstance(scope, DispatchScope) or scope.home != get_hermes_home().resolve()
            or not isinstance(scope.session_id, str) or not scope.session_id.strip()
            or len(scope.session_id) > 1024 or 'a2a_outbound' not in scope.tools):
        return {'status': 'blocked', 'reason': 'trusted_scope_required'}
    if not isinstance(args, dict):
        return {'status': 'blocked', 'reason': 'invalid_arguments'}
    try:
        if isinstance(args.get('message'), str):
            args['message'].encode('utf-8')
    except UnicodeError:
        return {'status': 'blocked', 'reason': 'invalid_arguments'}
    action = args.get('action')
    expected = {'prepare': {'action', 'message'}, 'send': {'action', 'local_id'},
                'show': {'action', 'local_id'}, 'resume': {'action', 'local_id'}}
    if (not isinstance(action, str) or action not in expected or set(args) != expected[action]
            or (action == 'prepare' and (not isinstance(args['message'], str)
                or not args['message'].strip() or len(args['message'].encode()) > 65536))
            or (action != 'prepare' and (not isinstance(args['local_id'], str)
                or re.fullmatch(r'[0-9a-f]{32}', args['local_id']) is None))):
        return {'status': 'blocked', 'reason': 'invalid_arguments'}
    try:
        client = _client(ctx, _store(scope))
        if args['action'] == 'prepare':
            record = client.store.load(client.prepare(args['message']))
        else:
            record = client.store.load(args['local_id'])
            if record['binding'] != client.binding:
                raise ValueError('Binding changed')
        if action == 'resume':
            record = client.resume(args['local_id'])
        snapshot = _snapshot(record)
        if action == 'send':
            return {'status': 'blocked', 'reason': 'human_dispatch_bridge_missing',
                    'authorization': 'blocked_bridge_missing', 'notification_delivered': False,
                    'local_id': record['local_id'], 'local_state': record['local_state']}
        return snapshot
    except Exception:
        # Peer, environment and disk exception strings can contain sensitive data.
        return {'status': 'blocked', 'reason': 'request_unavailable'}


def register_tools(ctx):
    ctx.register_tool(
        name='a2a_outbound', toolset='a2a_outbound',
        schema={'name': 'a2a_outbound', 'description': 'Prepare and observe zuri jobs; send is blocked pending a human authorization bridge.',
                'parameters': {'type': 'object', 'additionalProperties': False,
                               'properties': {'action': {'type': 'string', 'enum': ['prepare', 'send', 'show', 'resume']},
                                              'message': {'type': 'string'}, 'local_id': {'type': 'string'}},
                               'required': ['action']}},
        handler=lambda args, **kw: json.dumps(_handle(ctx, args, kw.get('a2a_scope')), allow_nan=False),
        check_fn=lambda: _available(ctx),
    )
