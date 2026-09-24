import inspect
from typing import Any

import pytest
from streamlit.runtime import Runtime
from streamlit.runtime.app_session import AppSession
from streamlit.runtime.session_manager import SessionManager

import live_update
from live_update import request_rerun_of_open_sessions


class FakeSession:
    """Records the rerun requests a session receives."""

    def __init__(self) -> None:
        self.rerun_requests: list[Any] = []

    def request_rerun(self, client_state: Any) -> None:
        self.rerun_requests.append(client_state)


class FakeSessionInfo:
    def __init__(self, session: FakeSession) -> None:
        self.session = session


class FakeSessionManager:
    def __init__(self, sessions: list[FakeSession]) -> None:
        self.sessions = sessions

    def list_active_sessions(self) -> list[FakeSessionInfo]:
        return [FakeSessionInfo(session) for session in self.sessions]


class FakeRuntime:
    def __init__(self, sessions: list[FakeSession]) -> None:
        self._session_mgr = FakeSessionManager(sessions)


def test_without_a_runtime_nothing_is_notified() -> None:
    assert Runtime.exists() is False
    assert request_rerun_of_open_sessions() == 0


def test_every_open_session_is_asked_to_rerun(monkeypatch: pytest.MonkeyPatch) -> None:
    sessions: list[FakeSession] = [FakeSession(), FakeSession()]
    monkeypatch.setattr(live_update.Runtime, "exists", staticmethod(lambda: True))
    monkeypatch.setattr(live_update, "get_instance", lambda: FakeRuntime(sessions))
    assert request_rerun_of_open_sessions() == 2
    assert [session.rerun_requests for session in sessions] == [[None], [None]]


def test_private_runtime_api_still_matches() -> None:
    """Fails when a Streamlit upgrade moves the private API this module depends on."""
    assert hasattr(Runtime, "exists")
    assert "_session_mgr" in inspect.getsource(Runtime.__init__)
    assert hasattr(SessionManager, "list_active_sessions")
    assert list(inspect.signature(AppSession.request_rerun).parameters) == ["self", "client_state"]
