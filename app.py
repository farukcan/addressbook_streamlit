"""Streamlit UI for the contact book. Run with: uv run streamlit run app.py

Layout: search + contact table on the left, a form panel on the right.
Each table row has Edit and Delete buttons. Edit loads the contact into the panel by id;
Delete asks for confirmation in a dialog. When nothing is being edited the panel shows the new-contact form.
"""

import secrets
import sqlite3
from contextlib import closing
from dataclasses import asdict
from pathlib import Path

import streamlit as st
from streamlit.typing import ButtonColumnClickState
from typing import TypedDict

import mcp_server
from db import (
    Contact,
    ContactData,
    add_contact,
    connect,
    delete_contact,
    get_contact,
    normalize_contact,
    search_contacts,
    update_contact,
    validate_contact,
)
from mcp_server import RunningServer, ServerConfig

DB_PATH: Path = Path(__file__).parent / "contacts.db"
MCP_STATE_PATH: Path = Path(__file__).parent / "mcp_state.json"
LOGO_PATH: Path = Path(__file__).parent / "assets" / "logo-128.png"
FLASH_KEY: str = "flash"
EDITING_ID_KEY: str = "editing_id"
PENDING_DELETE_KEY: str = "pending_delete_id"
EDIT_CLICK_KEY: str = "edit_click"
DELETE_CLICK_KEY: str = "delete_click"
ADD_PREFIX: str = "add"
MCP_DEFAULT_HOST: str = "127.0.0.1"
MCP_DEFAULT_PORT: int = 8765
MCP_TOKEN_KEY: str = "mcp_token"
MCP_SETTINGS_KEY: str = "mcp_settings"
LOCAL_HOSTS: frozenset[str] = frozenset({"127.0.0.1", "localhost", "::1"})
EDIT_ICON: str = ":material/edit:"
DELETE_ICON: str = ":material/delete:"


class McpSettings(TypedDict):
    """MCP tab inputs, kept outside the widget keys so they survive while the server runs."""

    host: str
    port: int
    require_token: bool
    token: str


class McpHandle(TypedDict):
    """The MCP server of this process, plus why an automatic start failed."""

    running: RunningServer | None
    start_error: str | None


@st.cache_resource
def mcp_handle() -> McpHandle:
    """App-wide handle for the MCP server, built once per process and shared by every session.

    A server the previous run left running is started again here, so closing the app without
    stopping it resumes it on the next launch.
    """
    config: ServerConfig | None = mcp_server.load_state(MCP_STATE_PATH)
    if config is None:
        return McpHandle(running=None, start_error=None)
    try:
        return McpHandle(running=mcp_server.start_server(DB_PATH, config), start_error=None)
    # Reported in the MCP tab: raising here would leave the whole app unusable.
    except (OSError, RuntimeError, TimeoutError) as error:
        return McpHandle(running=None, start_error=f"Could not restart the MCP server: {error}")


def finish_change(message: str) -> None:
    """Queue a toast and rerun so every view shows fresh data."""
    st.session_state[FLASH_KEY] = message
    st.rerun()


def remember_clicked_id(click_key: str, target_key: str, row_ids: list[int]) -> None:
    """Table button callback: store the id of the clicked row under `target_key`.

    `row_ids` is bound when the table renders, so the clicked row index maps to the list the user saw.
    """
    click: ButtonColumnClickState = st.session_state[click_key]
    st.session_state[target_key] = row_ids[click.row]


def cancel_edit() -> None:
    """Close the edit panel; the panel then shows the new-contact form."""
    st.session_state[EDITING_ID_KEY] = None


def contact_fields(key_prefix: str, initial: ContactData) -> ContactData:
    """Render the contact input widgets inside the current form and return their values."""
    name: str = st.text_input("Name *", value=initial.name, key=f"{key_prefix}_name")
    phone_col, email_col = st.columns(2)
    phone: str = phone_col.text_input("Phone", value=initial.phone, key=f"{key_prefix}_phone")
    email: str = email_col.text_input("Email", value=initial.email, key=f"{key_prefix}_email")
    address: str = st.text_area("Address", value=initial.address, key=f"{key_prefix}_address")
    return ContactData(name=name, phone=phone, email=email, address=address)


def show_errors(errors: list[str]) -> None:
    for error in errors:
        st.error(error)


def render_contact_list(conn: sqlite3.Connection) -> None:
    """Render search + table with per-row Edit and Delete buttons."""
    query: str = st.text_input(
        "Search",
        placeholder="🔍  Search name, phone, email or address",
        label_visibility="collapsed",
    )
    contacts: list[Contact] = search_contacts(conn, query)
    row_ids: list[int] = [c.id for c in contacts]
    rows: list[dict[str, str | int]] = [
        {**asdict(c), "edit": EDIT_ICON, "delete": DELETE_ICON} for c in contacts
    ]
    st.dataframe(
        rows,
        hide_index=True,
        width="stretch",
        # Fits the rows instead of padding the table with empty ones; scrolls past ten.
        height="auto",
        column_config={
            "id": None,
            "name": "Name",
            "phone": "Phone",
            "email": "Email",
            "address": "Address",
            "edit": st.column_config.ButtonColumn(
                "",
                width="small",
                help="Edit",
                type="tertiary",
                on_click=remember_clicked_id,
                args=(EDIT_CLICK_KEY, EDITING_ID_KEY, row_ids),
                key=EDIT_CLICK_KEY,
            ),
            "delete": st.column_config.ButtonColumn(
                "",
                width="small",
                help="Delete",
                type="tertiary",
                on_click=remember_clicked_id,
                args=(DELETE_CLICK_KEY, PENDING_DELETE_KEY, row_ids),
                key=DELETE_CLICK_KEY,
            ),
        },
    )
    st.caption(f"{len(contacts)} contacts")


def render_add(conn: sqlite3.Connection) -> None:
    st.subheader("New contact")
    empty: ContactData = ContactData(name="", phone="", email="", address="")
    with st.form("add_form", border=False):
        data: ContactData = normalize_contact(contact_fields(ADD_PREFIX, empty))
        submitted: bool = st.form_submit_button("Add", type="primary", width="stretch")
    if not submitted:
        return
    errors: list[str] = validate_contact(data)
    if errors:
        show_errors(errors)
        return
    add_contact(conn, data)
    # Clear the form only on success so invalid input stays editable.
    for key in [k for k in st.session_state if str(k).startswith(f"{ADD_PREFIX}_")]:
        del st.session_state[key]
    finish_change(f"Added '{data.name}'.")


def render_edit(conn: sqlite3.Connection, contact: Contact) -> None:
    st.subheader("Edit contact")
    initial: ContactData = ContactData(
        name=contact.name, phone=contact.phone, email=contact.email, address=contact.address
    )
    # Widget keys include the id so switching contacts reloads the form values.
    with st.form(f"edit_form_{contact.id}", border=False):
        data: ContactData = normalize_contact(contact_fields(f"edit_{contact.id}", initial))
        save_col, cancel_col = st.columns(2)
        saved: bool = save_col.form_submit_button("Save", type="primary", width="stretch")
        cancel_col.form_submit_button("Cancel", on_click=cancel_edit, width="stretch")
    if not saved:
        return
    errors: list[str] = validate_contact(data)
    if errors:
        show_errors(errors)
        return
    update_contact(conn, contact.id, data)
    st.session_state[EDITING_ID_KEY] = None
    finish_change(f"Updated '{data.name}'.")


@st.dialog("Delete contact")
def confirm_delete(contact: Contact) -> None:
    """Confirmation dialog. It reruns as a fragment with the same args, so it opens its own connection."""
    st.write(f"Delete '{contact.name}'? This cannot be undone.")
    delete_col, cancel_col = st.columns(2)
    if delete_col.button("Delete", type="primary", width="stretch"):
        with closing(connect(DB_PATH)) as conn:
            delete_contact(conn, contact.id)
        # Keep an unrelated edit panel (and its unsaved input) open.
        if st.session_state[EDITING_ID_KEY] == contact.id:
            st.session_state[EDITING_ID_KEY] = None
        finish_change(f"Deleted '{contact.name}'.")
    if cancel_col.button("Cancel", width="stretch"):
        st.rerun()


def render_mcp_settings(handle: McpHandle) -> ServerConfig | None:
    """Render the inputs and the Start button shown while the server is stopped.

    Returns the configured settings, or None when the token field is on but empty.
    """
    settings: McpSettings = st.session_state[MCP_SETTINGS_KEY]
    host: str = st.text_input(
        "Host",
        value=settings["host"],
        key="mcp_host",
        help="127.0.0.1 keeps the server on this machine. Use your LAN IP or 0.0.0.0 to accept "
        "connections from your network.",
    ).strip()
    port: int = int(
        st.number_input(
            "Port", min_value=1, max_value=65535, value=settings["port"], step=1, key="mcp_port"
        )
    )
    require_token: bool = st.checkbox(
        "Require a bearer token", value=settings["require_token"], key="mcp_require_token"
    )
    token: str | None = None
    if require_token:
        token = st.text_input("Token", value=settings["token"], key=MCP_TOKEN_KEY).strip() or None
    st.session_state[MCP_SETTINGS_KEY] = McpSettings(
        host=host,
        port=port,
        require_token=require_token,
        token=token if token is not None else settings["token"],
    )
    if not host:
        st.error("Host must not be empty.")
    if require_token and token is None:
        st.error("The token must not be empty while a token is required.")
    complete: bool = bool(host) and not (require_token and token is None)
    if complete and host not in LOCAL_HOSTS and token is None:
        st.warning(
            "Without a token, anyone who can reach this address can read and change your contacts."
        )
    if not complete:
        return None
    config: ServerConfig = ServerConfig(host=host, port=port, token=token)
    if st.button("Start server", type="primary"):
        try:
            handle["running"] = mcp_server.start_server(DB_PATH, config)
        # Shown in the UI, which is configured to hide tracebacks.
        except (OSError, RuntimeError, TimeoutError) as error:
            st.error(str(error))
            return config
        # Remembered so the next launch brings the server back up.
        mcp_server.save_state(MCP_STATE_PATH, config)
        finish_change("MCP server started.")
    return config


def render_mcp_status(handle: McpHandle, running: RunningServer) -> None:
    """Render the state of the running server and the Stop button."""
    st.success(f"Running · {mcp_server.server_url(running.config)}")
    if running.config.host not in LOCAL_HOSTS and running.config.token is None:
        st.warning(
            "Without a token, anyone who can reach this address can read and change your contacts."
        )
    if st.button("Stop server"):
        try:
            mcp_server.stop_server(running)
        except TimeoutError as error:
            st.error(str(error))
        finally:
            # Drop the handle even on a failed shutdown; keeping it would make Stop unusable.
            handle["running"] = None
            mcp_server.save_state(MCP_STATE_PATH, None)
        finish_change("MCP server stopped.")


def render_mcp_help(config: ServerConfig) -> None:
    """Explain how to connect an AI agent to the server."""
    st.subheader("Connect an agent")
    setups: dict[str, mcp_server.ClientSetup] = mcp_server.client_setups(config)
    # No widget key: an auto-keyed radio re-keys when the client list changes, instead of
    # returning a name that is no longer offered.
    client: str | None = st.radio("Client", list(setups), horizontal=True, label_visibility="collapsed")
    if client is None:
        raise RuntimeError("Client radio returned no selection although clients are listed.")
    setup: mcp_server.ClientSetup = setups[client]
    st.caption(setup.hint)
    st.code(setup.snippet, language=setup.language)
    st.caption(
        "Tools: list_contacts, get_contact, create_contact, update_contact, delete_contact. "
        "The server runs inside this app; it stops when the app exits and starts again with the "
        "app unless you stop it here."
    )
    if config.host in mcp_server.WILDCARD_HOSTS:
        st.caption("Bound to every interface: agents on other machines use this machine's address.")


def initial_mcp_settings() -> McpSettings:
    """Seed the MCP inputs from the remembered server, falling back to the defaults.

    They are kept outside the widget keys so they survive while the server hides the inputs. The
    token is generated once per session, so the field is never empty when it is switched on.
    """
    remembered: ServerConfig | None = mcp_server.load_state(MCP_STATE_PATH)
    if remembered is None:
        return McpSettings(
            host=MCP_DEFAULT_HOST,
            port=MCP_DEFAULT_PORT,
            require_token=False,
            token=secrets.token_urlsafe(24),
        )
    return McpSettings(
        host=remembered.host,
        port=remembered.port,
        require_token=remembered.token is not None,
        token=remembered.token if remembered.token is not None else secrets.token_urlsafe(24),
    )


def render_mcp_tab() -> None:
    st.subheader("MCP server")
    st.caption("Serve this address book over SSE so AI agents can read and manage it.")
    handle: McpHandle = mcp_handle()
    if handle["start_error"] is not None:
        st.error(handle["start_error"])
    running: RunningServer | None = handle["running"]
    if running is not None:
        render_mcp_status(handle, running)
        render_mcp_help(running.config)
        return
    config: ServerConfig | None = render_mcp_settings(handle)
    if config is not None:
        render_mcp_help(config)


def main() -> None:
    st.set_page_config(page_title="Address Book", page_icon=str(LOGO_PATH), layout="wide")
    st.logo(str(LOGO_PATH), size="large")
    st.title("Address Book")
    st.session_state.setdefault(EDITING_ID_KEY, None)
    st.session_state.setdefault(MCP_SETTINGS_KEY, initial_mcp_settings())
    if FLASH_KEY in st.session_state:
        st.toast(st.session_state.pop(FLASH_KEY), icon="✅")
    # Pop before opening so dismissing the dialog (X / Esc) does not reopen it on the next run.
    pending_delete_id: int | None = st.session_state.pop(PENDING_DELETE_KEY, None)

    conn: sqlite3.Connection = connect(DB_PATH)
    try:
        if pending_delete_id is not None:
            confirm_delete(get_contact(conn, pending_delete_id))
        contacts_tab, mcp_tab = st.tabs(["Contacts", "MCP"])
        with contacts_tab:
            list_col, form_col = st.columns([3, 2], gap="large")
            with list_col:
                render_contact_list(conn)
            with form_col, st.container(border=True):
                editing_id: int | None = st.session_state[EDITING_ID_KEY]
                if editing_id is None:
                    render_add(conn)
                else:
                    render_edit(conn, get_contact(conn, editing_id))
        with mcp_tab:
            render_mcp_tab()
    finally:
        conn.close()


main()
