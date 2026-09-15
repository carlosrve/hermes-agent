"""Isolated queue characterization, not human approval or an A2A grant."""

import threading
from types import SimpleNamespace

import pytest

from tools import approval
from tools.approval_gateway_wait import _ApprovalEntry
from tui_gateway import methods_prompt
from tui_gateway.transport import FanoutTransport, bind_transport, reset_transport


class Peer:
    def __init__(self, profile="owner"):
        self.auth_identity = {"user_id": "fixture-user", "provider": "fixture", "profile": profile}
        self.closed = False

    def write(self, obj: dict) -> bool:
        return True

    def close(self):
        self.closed = True


@pytest.fixture
def queue(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    # The real in-memory queue and entries, isolated from any live process/state.
    entries = [_ApprovalEntry({"request_id": name}) for name in ("one", "two")]
    foreign = _ApprovalEntry({"request_id": "foreign"})
    queues = {"owner": entries.copy(), "foreign-session": [foreign]}
    monkeypatch.setattr(approval, "_gateway_queues", queues)
    yield queues, entries, foreign


def event(session, **params):
    return methods_prompt.build_a2a_approval_event(
        session, {"a2a_event": True, "request_id": "one", **params})


def test_context_fanout_exact_reconnect_and_real_queue_unchanged(queue):
    queues, entries, foreign_entry = queue
    owner, attached_other_profile, foreign = Peer(), Peer("other"), Peer()
    fanout = FanoutTransport(owner, attached_other_profile)
    session = {"session_key": "owner", "transport": fanout,
               "auth_identity": dict(owner.auth_identity)}
    before = {key: approval.list_gateway_approvals(key) for key in queues}
    assert event(session) is None  # no bound caller
    for peer, allowed in ((owner, True), (attached_other_profile, False), (foreign, False)):
        token = bind_transport(peer)
        try:
            assert (event(session) is not None) is allowed
            assert event(session, request_id="foreign") is None
            assert event({**session, "session_key": "stale"}) is None
            assert event(session, all=True) is None
        finally:
            reset_transport(token)
    token = bind_transport(owner)
    try:
        seen = []
        built = methods_prompt.build_a2a_approval_event(
            session, {"a2a_event": True, "request_id": "one"}, callback=seen.append)
        assert built is not None
        assert seen == [built]
        assert built["session_id"] == "owner"
        assert methods_prompt.build_a2a_approval_event(
            session, {"a2a_event": True, "request_id": "one"}, transport=fanout) is None
        fanout.detach(owner)
        assert event(session) is None
        fanout.attach(owner)
        assert event(session)["request_id"] == "one"
        owner.closed = True
        assert event(session) is None
    finally:
        reset_transport(token)
    assert {key: approval.list_gateway_approvals(key) for key in queues} == before
    for entry in entries + [foreign_entry]:
        assert entry.result is None
        assert not entry.event.is_set()
        assert not entry.acknowledged


@pytest.mark.parametrize("injection", [
    {"choice": "once"}, {"decision": "approve"}, {"approval_id": "invented"},
    {"auth_identity": {"user_id": "invented", "provider": "fixture"}},
    {"objective_id": "invented"}, {"coordinator": "invented"}, {"all": None},
])
def test_worker_fields_cannot_select_identity_decision_or_objective(queue, injection):
    peer = Peer()
    session = {"session_key": "owner", "transport": peer}
    token = bind_transport(peer)
    try:
        assert event(session, **injection) is None
    finally:
        reset_transport(token)
    assert len(approval.list_gateway_approvals("owner")) == 2
    assert all(entry.result is None and not entry.event.is_set() for entry in queue[1])


def test_attached_peer_cannot_cross_explicit_session_profile(queue, tmp_path):
    from hermes_constants import set_hermes_home_override, reset_hermes_home_override

    peer = Peer()
    fanout = FanoutTransport(peer)
    session = {"session_key": "owner", "transport": fanout,
               "profile_home": tmp_path / "owner-profile"}
    transport_token = bind_transport(peer)
    try:
        for home, allowed in ((tmp_path / "owner-profile", True),
                              (tmp_path / "other-profile", False)):
            profile_token = set_hermes_home_override(home)
            try:
                assert fanout.contains(peer)
                assert (event(session) is not None) is allowed
            finally:
                reset_hermes_home_override(profile_token)
    finally:
        reset_transport(transport_token)
    assert all(entry.result is None and not entry.event.is_set() for entry in queue[1])


def legacy_fixture_server(sessions):
    # Bind the actual registered handler to only fixture session lookup/globals.
    server = SimpleNamespace(
        _sessions=sessions, _sessions_lock=threading.Lock(), _methods={},
        _profile_scoped=lambda fn: fn,
        _ok=lambda rid, result: {"id": rid, "result": result},
        _err=lambda rid, code, message: {"id": rid, "error": {"code": code}},
        _find_live_session_by_key=lambda key: next(
            ((sid, session) for sid, session in sessions.items()
             if session["session_key"] == key), None),
    )
    server._sess = lambda params, rid: (
        (sessions[params["session_id"]], None) if params["session_id"] in sessions
        else (None, server._err(rid, 4001, "missing")))
    methods_prompt.register(server)
    return server


def test_legacy_stale_request_fallback_and_all_are_fixture_only(queue):
    queues, entries, foreign = queue
    server = legacy_fixture_server({"live-owner": {"session_key": "owner"},
                                    "live-foreign": {"session_key": "foreign-session"}})
    handler = server._methods["approval.respond"]
    # Observed unrelated request selects another live session on stale sid.
    # "deny" only on synthetic entries; this is NOT an approval authorization test.
    result = handler(1, {"session_id": "stale", "request_id": "foreign", "choice": "deny", "all": True})
    assert result["result"]["resolved"] == 1
    assert foreign.result == "deny" and foreign.event.is_set()
    assert approval.list_gateway_approvals("owner") == [entry.data for entry in entries]
    # Stored-id reconnect plus all selects both entries when no request is supplied.
    result = handler(2, {"session_id": "owner", "choice": "deny", "all": True})
    assert result["result"]["resolved"] == 2
    assert all(entry.result == "deny" and entry.event.is_set() for entry in entries)
    assert queues == {}


def test_gateway_does_not_promote_uncorrelated_callback_to_approval_needed(queue, monkeypatch):
    from tui_gateway import server

    peer = Peer()
    seen, legacy = [], []
    session = {"session_key": "owner", "transport": peer,
               "a2a_approval_callback": seen.append}
    monkeypatch.setattr(server, "_sessions", {"live-owner": session})
    monkeypatch.setattr(server, "_emit", lambda *args: legacy.append(args))
    server._emit_approval_request("live-owner", {"request_id": "one"})
    assert len(legacy) == 1
    assert legacy[0][0] == "approval.request"
    # A callable plus a session ID does not establish an ObjectiveGrant or its
    # coordinator/return route. Fail closed instead of inventing that authority.
    assert seen == []
    assert len(approval.list_gateway_approvals("owner")) == 2
