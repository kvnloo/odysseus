"""An OAuth callback must consume signed state before a second token exchange.

This checks the HTTP callback, not just the state-consumption helper: a replay
must never reach Google's token endpoint, even if the same code is offered again.
"""

from types import SimpleNamespace
from unittest import mock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


@pytest.mark.asyncio
async def test_google_callback_replay_never_reexchanges_token(monkeypatch):
    from core.database import Base, EmailAccount
    from routes.email_helpers import make_oauth_state
    from routes.email_routes import setup_email_routes

    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "test-client-secret")
    monkeypatch.delenv("GOOGLE_OAUTH_REDIRECT_URI", raising=False)

    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    try:
        Base.metadata.create_all(engine)
        session_factory = sessionmaker(bind=engine)
        with session_factory() as session:
            session.add(
                EmailAccount(
                    id="oauth-replay-account",
                    owner="alice",
                    name="Alice",
                    imap_user="alice@example.edu",
                    smtp_user="alice@example.edu",
                )
            )
            session.commit()

        router = setup_email_routes()
        callback = next(
            route.endpoint
            for route in router.routes
            if route.path == "/api/email/oauth/google/callback"
            and "GET" in getattr(route, "methods", set())
        )
        request = SimpleNamespace(
            headers={"host": "localhost:7000"},
            url=SimpleNamespace(scheme="http"),
        )
        state = make_oauth_state("oauth-replay-account", "alice")

        token_response = mock.MagicMock()
        token_response.json.return_value = {
            "access_token": "ya29.test-access-token",
            "refresh_token": "1//test-refresh-token",
            "expires_in": 3600,
        }
        userinfo_response = mock.MagicMock()
        userinfo_response.is_success = True
        userinfo_response.json.return_value = {
            "email": "alice@example.edu",
            "name": "Alice",
        }

        with (
            mock.patch("core.database.SessionLocal", session_factory),
            mock.patch("httpx.post", return_value=token_response) as exchange,
            mock.patch("httpx.get", return_value=userinfo_response) as userinfo,
        ):
            first = await callback(
                code="4/first-code", state=state, error=None, request=request
            )
            replay = await callback(
                code="4/replayed-code", state=state, error=None, request=request
            )

        first_redirect = first.headers["location"]
        replay_redirect = replay.headers["location"]
        assert "email_oauth_error=" not in first_redirect, first_redirect
        assert "email_oauth_error=invalid_state" in replay_redirect
        assert "4/replayed-code" not in replay_redirect
        exchange.assert_called_once()
        userinfo.assert_called_once()
    finally:
        engine.dispose()
