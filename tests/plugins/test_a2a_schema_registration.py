"""Regression tests for A2A client-tool schema registration."""

from __future__ import annotations

import json

from plugins.platforms.a2a import tools as a2a_tools
from tools import tool_search
from tools.registry import ToolRegistry


def test_a2a_call_schema_round_trips_through_tool_describe(monkeypatch):
    registry = ToolRegistry()

    # The client tools are config-gated now (test_a2a_tools_gate.py):
    # open the gate the way a real install would — configure a peer.
    monkeypatch.setattr(
        a2a_tools,
        "_load_config",
        lambda: {"a2a_agents": {"peer": {"url": "http://localhost:9999"}}},
    )

    class _Context:
        def register_tool(self, name, toolset, schema, handler, **kwargs):
            registry.register(
                name=name,
                toolset=toolset,
                schema=schema,
                handler=handler,
                **kwargs,
            )

    a2a_tools.register_tools(_Context())
    definitions = registry.get_definitions({"a2a_call"})
    monkeypatch.setattr(
        tool_search,
        "is_deferrable_tool_name",
        # #97979 added the defer_tools positional (curated-set override).
        lambda name, defer_tools=None: name == "a2a_call",
    )

    described = json.loads(
        tool_search.dispatch_tool_describe(
            {"names": ["a2a_call"]},
            current_tool_defs=definitions,
        )
    )["tools"]["a2a_call"]

    assert described["description"]
    assert described["parameters"]["required"] == ["agent", "message"]
    assert set(described["parameters"]["properties"]) == {
        "agent",
        "message",
        "context_id",
    }


def test_native_discovery_opt_in_schema_without_legacy_or_inbound(tmp_path, monkeypatch):
    import yaml
    from hermes_cli.plugins import discover_plugins, get_plugin_manager
    from tools.registry import registry
    import model_tools

    monkeypatch.setenv('HERMES_HOME', str(tmp_path))
    monkeypatch.delenv('A2A_PORT', raising=False)
    discover_plugins(force=True)
    manager = get_plugin_manager()
    loaded = next(p for p in manager._plugins.values() if p.manifest.name == 'a2a-platform')
    assert 'a2a_outbound' in loaded.manifest.provides_tools
    assert loaded.deferred is True
    entry = registry.get_entry('a2a_outbound')
    assert entry is not None and entry.check_fn() is False
    assert not registry.get_definitions({'a2a_outbound'})
    config = {'plugins': {'entries': {loaded.manifest.key: {'settings': {'outbound': {
        'enabled': True, 'peer': 'zuri', 'runtime': 'codex', 'host': 'zurqui',
        'url': 'https://zurqui/rpc', 'token_env': 'NATIVE_TEST_BEARER'
    }}}}}}
    (tmp_path / 'config.yaml').write_text(yaml.safe_dump(config))
    discover_plugins(force=True)
    assert registry.get_entry('a2a_outbound').check_fn() is True
    definitions = registry.get_definitions({'a2a_outbound'})
    assert len(definitions) == 1
    params = definitions[0]['function']['parameters']
    assert set(params['properties']) == {'action', 'message', 'local_id'}
    assert params['additionalProperties'] is False
    assert not registry.get_entry('a2a_call').check_fn()
    assert 'a2a_outbound' not in model_tools._select_tool_names(['hermes-cli'], [], quiet_mode=True)
    assert 'a2a_outbound' in model_tools._select_tool_names(['a2a_outbound'], [], quiet_mode=True)
    monkeypatch.setenv('NATIVE_TEST_BEARER', 'fixture-native-credential')
    described = json.loads(model_tools.handle_function_call('tool_describe', {'names': ['a2a_outbound']},
                           enabled_toolsets=['a2a_outbound'], disabled_toolsets=[]))
    assert 'a2a_outbound' in described['tools']
    bridge_args = {'calls': [{'name': 'a2a_outbound', 'arguments': {'action': 'prepare', 'message': 'hello'}}]}
    kwargs = dict(session_id='owner', enabled_toolsets=['a2a_outbound'], disabled_toolsets=[])
    denied = json.loads(model_tools.handle_function_call('tool_call', bridge_args, **kwargs))
    assert denied['status'] == 'blocked'
    accepted = json.loads(model_tools.handle_function_call('tool_call', bridge_args,
                           enabled_tools=['a2a_outbound'], **kwargs))
    assert accepted['local_state'] == 'prepared'
    denied = json.loads(model_tools.handle_function_call('tool_call', bridge_args,
                        session_id='owner', enabled_tools=['a2a_outbound'],
                        enabled_toolsets=['a2a_outbound'], disabled_toolsets=['a2a_outbound']))
    assert denied.get('error') or denied.get('status') == 'blocked'
