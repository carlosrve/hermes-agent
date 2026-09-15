"""Native outbound gates: local fixtures only, never a real peer."""
import json
from types import SimpleNamespace

from plugins.platforms.a2a import tools
from tools.registry import ToolRegistry


def registered(config=None):
    registry = ToolRegistry()
    ctx = SimpleNamespace(
        get_config=lambda key, default=None: config if key == 'outbound' else default,
        register_tool=lambda **kw: registry.register(**kw),
    )
    tools.register_tools(ctx)
    return registry


def test_native_registration_is_independent_and_direct_dispatch_denied(tmp_path, monkeypatch):
    monkeypatch.setenv('HERMES_HOME', str(tmp_path))
    monkeypatch.setenv('A2A_PORT', '9900')
    before = set(tmp_path.rglob('*'))
    registry = registered()
    entry = registry.get_entry('a2a_outbound')
    assert entry is not None
    assert entry.toolset == 'a2a_outbound'
    assert entry.check_fn() is False
    result = json.loads(registry.dispatch('a2a_outbound', {'action': 'prepare', 'message': 'hello'}))
    assert result['status'] == 'blocked'
    assert set(tmp_path.rglob('*')) == before


def test_prepare_uses_runtime_scope_and_immutable_store(tmp_path, monkeypatch):
    import model_tools
    from plugins.platforms.a2a.outbound import Client

    monkeypatch.setenv('HERMES_HOME', str(tmp_path))
    monkeypatch.setenv('NATIVE_TEST_BEARER', 'fixture-native-credential')
    config = dict(enabled=True, peer='zuri', runtime='codex', host='zurqui',
                  url='https://zurqui.tuna-gray.ts.net/rpc', token_env='NATIVE_TEST_BEARER')
    registry = registered(config)
    monkeypatch.setattr(model_tools, 'registry', registry)
    import tools.registry as registry_module
    monkeypatch.setattr(registry_module, 'registry', registry)
    monkeypatch.setattr(Client, '_open', lambda *a: (_ for _ in ()).throw(AssertionError('network forbidden')))
    entry = registry.get_entry('a2a_outbound')
    assert entry.check_fn() is True
    kwargs = dict(session_id='owner-session', enabled_tools=['a2a_outbound'],
                  enabled_toolsets=['a2a_outbound'], disabled_toolsets=[],
                  skip_pre_tool_call_hook=True, skip_tool_request_middleware=True,
                  skip_tool_execution_middleware=True)
    result = json.loads(model_tools.handle_function_call('a2a_outbound',
                        {'action': 'prepare', 'message': 'immutable hello'}, **kwargs))
    assert result['status'] == 'ok'
    assert result['local_state'] == 'prepared'
    assert result['authorization'] == 'blocked_bridge_missing'
    local_id = result['local_id']
    shown = json.loads(model_tools.handle_function_call('a2a_outbound',
                       {'action': 'show', 'local_id': local_id}, **kwargs))
    assert shown == result
    foreign = json.loads(model_tools.handle_function_call('a2a_outbound',
                         {'action': 'show', 'local_id': local_id}, **{**kwargs, 'session_id': 'child-session'}))
    assert foreign['status'] == 'blocked'


def test_unavailable_posix_client_does_not_break_legacy_registration(monkeypatch):
    import sys
    config = dict(enabled=True, peer='zuri', runtime='codex', host='zurqui',
                  url='https://zurqui.tuna-gray.ts.net/rpc', token_env='NATIVE_TEST_BEARER')
    monkeypatch.setitem(sys.modules, 'plugins.platforms.a2a.outbound', None)
    registry = registered(config)
    assert not registry.get_entry('a2a_outbound').check_fn()
    assert registry.get_entry('a2a_call') is not None
