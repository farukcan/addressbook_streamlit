import json
import shutil
import socket
from pathlib import Path

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

APP_FILES: tuple[str, ...] = ("app.py", "db.py", "mcp_server.py", "live_update.py")
APP_TIMEOUT_SECONDS: int = 60


@pytest.fixture
def app(tmp_path: Path) -> AppTest:
    """Run the app from a copy, so its contacts.db lands in the temporary directory.

    The MCP server handle is an `st.cache_resource`, which lives in the process rather than in one
    app run, so it is dropped here to keep the tests independent.
    """
    st.cache_resource.clear()
    for name in APP_FILES:
        shutil.copy(Path(__file__).parent / name, tmp_path / name)
    return AppTest.from_file(str(tmp_path / "app.py"), default_timeout=APP_TIMEOUT_SECONDS)


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        port: int = sock.getsockname()[1]
        return port


def button_labels(at: AppTest) -> list[str]:
    return [button.label for button in at.button]


def test_contacts_tab_add_and_edit(app: AppTest) -> None:
    at: AppTest = app.run()
    at.text_input(key="add_name").input("Alice")
    [b for b in at.button if b.label == "Add"][0].click().run()
    assert [toast.value for toast in at.toast] == ["Added 'Alice'."]
    contact_id: int = int(at.dataframe[0].value["id"][0])
    at.session_state["editing_id"] = contact_id
    at.run()
    assert at.text_input(key=f"edit_{contact_id}_name").value == "Alice"


def test_blank_token_blocks_start(app: AppTest) -> None:
    at: AppTest = app.run()
    at.checkbox(key="mcp_require_token").set_value(True).run()
    at.text_input(key="mcp_token").set_value("   ").run()
    assert [error.value for error in at.error] == [
        "The token must not be empty while a token is required."
    ]
    assert "Start server" not in button_labels(at)


def test_blank_host_blocks_start(app: AppTest) -> None:
    at: AppTest = app.run()
    at.text_input(key="mcp_host").set_value("  ").run()
    assert [error.value for error in at.error] == ["Host must not be empty."]
    assert "Start server" not in button_labels(at)


def test_non_local_host_without_token_warns(app: AppTest) -> None:
    at: AppTest = app.run()
    at.text_input(key="mcp_host").set_value("0.0.0.0").run()
    assert at.warning[0].value.startswith("Without a token")
    assert "Start server" in button_labels(at)


def test_start_failure_is_shown(app: AppTest) -> None:
    at: AppTest = app.run()
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as taken:
        taken.bind(("127.0.0.1", 0))
        taken.listen()
        at.number_input(key="mcp_port").set_value(taken.getsockname()[1]).run()
        [b for b in at.button if b.label == "Start server"][0].click().run()
    assert not at.exception
    assert "the port may already be in use" in at.error[0].value
    assert "Start server" in button_labels(at)


def test_settings_survive_start_and_stop(app: AppTest) -> None:
    at: AppTest = app.run()
    port: int = free_port()
    at.checkbox(key="mcp_require_token").set_value(True).run()
    token: str = at.text_input(key="mcp_token").value
    at.number_input(key="mcp_port").set_value(port).run()
    [b for b in at.button if b.label == "Start server"][0].click().run()
    assert not at.exception
    assert at.success[0].value == f"Running · http://127.0.0.1:{port}/sse"
    assert token in at.code[0].value

    [b for b in at.button if b.label == "Stop server"][0].click().run()
    assert not at.exception
    assert at.number_input(key="mcp_port").value == port
    assert at.checkbox(key="mcp_require_token").value is True
    assert at.text_input(key="mcp_token").value == token


def write_state(tmp_path: Path, port: int, token: str | None) -> None:
    (tmp_path / "mcp_state.json").write_text(
        json.dumps({"host": "127.0.0.1", "port": port, "token": token}), encoding="utf-8"
    )


def test_server_left_running_starts_again(app: AppTest, tmp_path: Path) -> None:
    port: int = free_port()
    write_state(tmp_path, port, None)
    at: AppTest = app.run()
    assert not at.exception
    assert at.success[0].value == f"Running · http://127.0.0.1:{port}/sse"

    [b for b in at.button if b.label == "Stop server"][0].click().run()
    assert not (tmp_path / "mcp_state.json").exists()
    assert "Start server" in button_labels(at)


def test_start_is_remembered_and_stop_forgets_it(app: AppTest, tmp_path: Path) -> None:
    at: AppTest = app.run()
    port: int = free_port()
    at.number_input(key="mcp_port").set_value(port).run()
    [b for b in at.button if b.label == "Start server"][0].click().run()
    assert not at.exception
    state: dict[str, object] = json.loads((tmp_path / "mcp_state.json").read_text(encoding="utf-8"))
    assert state == {"host": "127.0.0.1", "port": port, "token": None}

    [b for b in at.button if b.label == "Stop server"][0].click().run()
    assert not (tmp_path / "mcp_state.json").exists()


def test_failed_restart_is_reported(app: AppTest, tmp_path: Path) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as taken:
        taken.bind(("127.0.0.1", 0))
        taken.listen()
        write_state(tmp_path, taken.getsockname()[1], None)
        at: AppTest = app.run()
    assert not at.exception
    assert at.error[0].value.startswith("Could not restart the MCP server")
    # The app stays usable: the settings and the Start button are there.
    assert "Start server" in button_labels(at)
