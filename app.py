"""Streamlit UI for the contact book. Run with: uv run streamlit run app.py

Layout: search + contact table on the left, a form panel on the right.
Each table row has Edit and Delete buttons. Edit loads the contact into the panel by id;
Delete asks for confirmation in a dialog. When nothing is being edited the panel shows the new-contact form.
"""

import sqlite3
from contextlib import closing
from dataclasses import asdict
from pathlib import Path

import streamlit as st
from streamlit.typing import ButtonColumnClickState

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

DB_PATH: Path = Path(__file__).parent / "contacts.db"
FLASH_KEY: str = "flash"
EDITING_ID_KEY: str = "editing_id"
PENDING_DELETE_KEY: str = "pending_delete_id"
EDIT_CLICK_KEY: str = "edit_click"
DELETE_CLICK_KEY: str = "delete_click"
ADD_PREFIX: str = "add"
TABLE_HEIGHT_PX: int = 480
EDIT_ICON: str = ":material/edit:"
DELETE_ICON: str = ":material/delete:"


def finish_change(message: str) -> None:
    """After a DB write: queue a toast and rerun so every view shows fresh data."""
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
        height=TABLE_HEIGHT_PX,
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


def main() -> None:
    st.set_page_config(page_title="Address Book", page_icon="📇", layout="wide")
    st.title("📇 Address Book")
    st.session_state.setdefault(EDITING_ID_KEY, None)
    if FLASH_KEY in st.session_state:
        st.toast(st.session_state.pop(FLASH_KEY), icon="✅")
    # Pop before opening so dismissing the dialog (X / Esc) does not reopen it on the next run.
    pending_delete_id: int | None = st.session_state.pop(PENDING_DELETE_KEY, None)

    conn: sqlite3.Connection = connect(DB_PATH)
    try:
        if pending_delete_id is not None:
            confirm_delete(get_contact(conn, pending_delete_id))
        list_col, form_col = st.columns([3, 2], gap="large")
        with list_col:
            render_contact_list(conn)
        with form_col, st.container(border=True):
            editing_id: int | None = st.session_state[EDITING_ID_KEY]
            if editing_id is None:
                render_add(conn)
            else:
                render_edit(conn, get_contact(conn, editing_id))
    finally:
        conn.close()


main()
