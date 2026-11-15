import pytest

from sqlalchemy import create_engine
from sqlalchemy.orm import Session as SASession, sessionmaker
from sqlalchemy.pool import StaticPool

import core.session_manager as sm
from core.database import Base, Session as DbSession, ChatMessage as DbChatMessage
from core.models import Session, ChatMessage


def test_add_message_rolls_back_memory_when_database_commit_fails(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)

    NormalSessionLocal = sessionmaker(bind=engine)

    class FailingCommitSession(SASession):
        def commit(self):
            raise RuntimeError("simulated commit failure")

    FailingSessionLocal = sessionmaker(
        bind=engine,
        class_=FailingCommitSession,
    )

    session_id = "isolated-transaction-test"

    try:
        # Seed an existing session and one durable message.
        db = NormalSessionLocal()
        try:
            db.add(DbSession(
                id=session_id,
                name="Isolation test",
                endpoint_url="http://localhost",
                model="test-model",
                owner="alice",
                message_count=1,
            ))
            db.add(DbChatMessage(
                id="existing-message",
                session_id=session_id,
                role="user",
                content="Existing durable message",
            ))
            db.commit()
        finally:
            db.close()

        monkeypatch.setattr(sm, "SessionLocal", FailingSessionLocal)
        monkeypatch.setattr(
            sm,
            "reserve_message_upload_references",
            lambda *args, **kwargs: None,
        )

        manager = sm.SessionManager.__new__(sm.SessionManager)
        manager.sessions = {}
        manager.upload_handler = None

        cached_session = Session(
            id=session_id,
            name="Isolation test",
            endpoint_url="http://localhost",
            model="test-model",
            owner="alice",
            history=[
                ChatMessage("user", "Existing durable message")
            ],
        )
        cached_session.message_count = 1

        manager.sessions[session_id] = cached_session

        # Isolate this test from session hydration and unrelated DB reads.
        monkeypatch.setattr(
            manager,
            "get_session",
            lambda requested_id: cached_session,
        )

        new_message = ChatMessage("user", "Message that must not be lost")

        # A failed commit must be visible to the caller.
        with pytest.raises(RuntimeError, match="simulated commit failure"):
            manager.add_message(session_id, new_message)

        # The failed write must not remain in memory.
        assert len(cached_session.history) == 1
        assert cached_session.history[0].content == "Existing durable message"
        assert cached_session.message_count == 1

        # Verify the independent database still contains only the baseline.
        check = NormalSessionLocal()
        try:
            rows = (
                check.query(DbChatMessage)
                .filter(DbChatMessage.session_id == session_id)
                .all()
            )

            assert len(rows) == 1
            assert rows[0].id == "existing-message"
            assert rows[0].content == "Existing durable message"

            db_session = check.query(DbSession).filter(
                DbSession.id == session_id
            ).first()

            assert db_session.message_count == 1
        finally:
            check.close()

    finally:
        engine.dispose()


def test_add_message_rejects_missing_upload_without_phantom_history(monkeypatch):
    """An unavailable attachment must not leave a message in cached history."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    LocalSession = sessionmaker(bind=engine)
    session_id = "missing-attachment-transaction-test"

    try:
        db = LocalSession()
        try:
            db.add(DbSession(
                id=session_id,
                name="Attachment transaction test",
                endpoint_url="http://localhost",
                model="test-model",
                owner="alice",
                message_count=1,
            ))
            db.add(DbChatMessage(
                id="durable-before-failure",
                session_id=session_id,
                role="user",
                content="Previously saved",
            ))
            db.commit()
        finally:
            db.close()

        monkeypatch.setattr(sm, "SessionLocal", LocalSession)
        monkeypatch.setattr(
            sm,
            "reserve_message_upload_references",
            lambda *args, **kwargs: "expired-upload",
        )

        manager = sm.SessionManager.__new__(sm.SessionManager)
        manager.upload_handler = None
        cached_session = Session(
            id=session_id,
            name="Attachment transaction test",
            endpoint_url="http://localhost",
            model="test-model",
            owner="alice",
            history=[ChatMessage("user", "Previously saved")],
        )
        cached_session.message_count = 1
        manager.sessions = {session_id: cached_session}
        monkeypatch.setattr(
            manager, "get_session", lambda requested_id: cached_session
        )

        original_history = cached_session.history
        message = ChatMessage(
            "user",
            "Unpersistable attachment",
            metadata={"attachments": [{"id": "expired-upload"}]},
        )
        with pytest.raises(ValueError, match="no longer available"):
            manager.add_message(session_id, message)

        assert cached_session.history is original_history
        assert cached_session._history is original_history
        assert [m.content for m in cached_session.history] == ["Previously saved"]
        assert cached_session.message_count == 1

        check = LocalSession()
        try:
            rows = check.query(DbChatMessage).filter(
                DbChatMessage.session_id == session_id
            ).all()
            assert [row.content for row in rows] == ["Previously saved"]
            assert check.get(DbSession, session_id).message_count == 1
        finally:
            check.close()
    finally:
        engine.dispose()


def test_create_session_keeps_endpoint_options_when_fix_is_applied(monkeypatch):
    """A persistence fix must not remove existing create_session API options."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    LocalSession = sessionmaker(bind=engine)

    try:
        monkeypatch.setattr(sm, "SessionLocal", LocalSession)
        manager = sm.SessionManager.__new__(sm.SessionManager)
        manager.sessions = {}
        session = manager.create_session(
            "endpoint-options-regression",
            "Endpoint options",
            "http://localhost:8000/v1",
            "test-model",
            owner="alice",
            cwd="/project/worktree",
            headers={"X-Session-Test": "preserved"},
            endpoint_id="local-provider",
        )

        assert session.cwd == "/project/worktree"
        assert session.endpoint_id == "local-provider"
        assert session.headers == {"X-Session-Test": "preserved"}

        check = LocalSession()
        try:
            row = check.get(DbSession, "endpoint-options-regression")
            assert row is not None
            assert row.cwd == "/project/worktree"
            assert row.endpoint_id == "local-provider"
            assert row.headers == {"X-Session-Test": "preserved"}
        finally:
            check.close()
    finally:
        engine.dispose()
