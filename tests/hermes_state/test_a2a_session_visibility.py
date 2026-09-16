import pytest

from gateway.config import GatewayConfig, Platform
from gateway.session import SessionSource, SessionStore
from hermes_state import SessionDB


@pytest.fixture
def db(tmp_path):
    database = SessionDB(tmp_path / "state.db")
    try:
        yield database
    finally:
        database.close()


def _record(db, session_id, context_id, *, source="a2a"):
    db.record_gateway_session_peer(
        session_id,
        source=source,
        user_id="zuri",
        session_key=f"agent:main:{source}:dm:{context_id}",
        chat_id=context_id,
        chat_type="dm",
    )


def _a2a_source(context_id):
    return SessionSource(
        platform=Platform("a2a"),
        chat_id=context_id,
        chat_type="dm",
        user_id="zuri",
    )


def _store(tmp_path, monkeypatch):
    import hermes_state

    monkeypatch.setattr(hermes_state, "DEFAULT_DB_PATH", tmp_path / "state.db")
    return SessionStore(sessions_dir=tmp_path / "sessions", config=GatewayConfig())


def test_a2a_gateway_session_is_hidden_by_default(db):
    db.create_session("a2a-session", source="a2a")
    _record(db, "a2a-session", "ctx-one")
    assert db.get_session("a2a-session")["hidden"] == 1


def test_human_gateway_session_remains_visible(db):
    db.create_session("human-session", source="telegram")
    _record(db, "human-session", "chat-one", source="telegram")
    assert db.get_session("human-session")["hidden"] == 0


def test_same_a2a_context_reuses_session_store_entry(tmp_path, monkeypatch):
    store = _store(tmp_path, monkeypatch)
    try:
        first = store.get_or_create_session(_a2a_source("ctx-one"))
        second = store.get_or_create_session(_a2a_source("ctx-one"))
        assert second.session_id == first.session_id
    finally:
        store._db.close()


def test_different_a2a_context_creates_different_session(tmp_path, monkeypatch):
    store = _store(tmp_path, monkeypatch)
    try:
        first = store.get_or_create_session(_a2a_source("ctx-one"))
        second = store.get_or_create_session(_a2a_source("ctx-two"))
        assert second.session_id != first.session_id
    finally:
        store._db.close()


def test_explicit_unhide_survives_peer_refresh(db):
    db.create_session("a2a-session", source="a2a")
    _record(db, "a2a-session", "ctx-one")
    assert db.set_session_hidden("a2a-session", False)
    _record(db, "a2a-session", "ctx-one")
    assert db.get_session("a2a-session")["hidden"] == 0
