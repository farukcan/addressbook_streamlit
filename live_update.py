"""Make open browser sessions rerun after a write that did not come from a script run.

Streamlit has no public way to trigger a rerun from another thread, so this reaches into the
runtime's session manager. `test_live_update.py` pins that private API: it fails if a Streamlit
upgrade renames it, instead of the app silently going stale.
"""

from streamlit.runtime import Runtime, get_instance
from streamlit.runtime.session_manager import ActiveSessionInfo


def request_rerun_of_open_sessions() -> int:
    """Ask every open browser session to rerun and return how many were asked.

    Returns 0 when there is no Streamlit runtime, which is what running outside the app looks like.
    """
    if not Runtime.exists():
        return 0
    sessions: list[ActiveSessionInfo] = get_instance()._session_mgr.list_active_sessions()
    for session_info in sessions:
        session_info.session.request_rerun(None)
    return len(sessions)
