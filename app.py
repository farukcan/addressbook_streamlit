"""Streamlit UI for the contact book. Run with: uv run streamlit run app.py

Master-detail layout: search + contact table on the left, a form panel on the right.
Selecting a table row opens its edit form; with no selection the panel shows the new-contact form.
"""

import sqlite3
from dataclasses import asdict
from pathlib import Path

import streamlit as st
from streamlit.elements.arrow import DataframeState

from db import (
    Contact,
    ContactData,
    add_contact,
    connect,
    delete_contact,
    normalize_contact,
    search_contacts,
    update_contact,
    validate_contact,
)

DB_PATH: Path = Path(__file__).parent / "contacts.db"
FLASH_KEY: str = "flash"
TABLE_VERSION_KEY: str = "table_version"
ADD_PREFIX: str = "add"
TABLE_HEIGHT_PX: int = 480


def clear_selection() -> None:
    """Bump the table version; the table key changes, so its row selection starts empty."""
    st.session_state[TABLE_VERSION_KEY] += 1


def finish_change(message: str) -> None:
    """After a DB write: queue a toast, clear the selection and rerun so every view shows fresh data."""
    st.session_state[FLASH_KEY] = message
    clear_selection()
    st.rerun()


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


def render_contact_list(conn: sqlite3.Connection) -> Contact | None:
    """Render search + table and return the contact selected in the table, if any."""
    query: str = st.text_input(
        "Search",
        placeholder="🔍  Search name, phone, email or address",
        label_visibility="collapsed",
    )
    contacts: list[Contact] = search_contacts(conn, query)
    # Row indices are only valid for this exact list, so the key changes with the query and after writes.
    table_key: str = f"contacts_table_{st.session_state[TABLE_VERSION_KEY]}_{query}"
    event: DataframeState = st.dataframe(
        [asdict(c) for c in contacts],
        key=table_key,
        on_select="rerun",
        selection_mode="single-row",
        hide_index=True,
        width="stretch",
        height=TABLE_HEIGHT_PX,
        column_config={
            "id": None,
            "name": "Name",
            "phone": "Phone",
            "email": "Email",
            "address": "Address",
        },
    )
    st.caption(f"{len(contacts)} contacts · select a row to edit")
    rows: list[int] = event.selection.rows
    return contacts[rows[0]] if rows else None


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


def render_edit(conn: sqlite3.Connection, selected: Contact) -> None:
    title_col, new_col = st.columns([3, 2], vertical_alignment="center")
    title_col.subheader("Edit contact")
    new_col.button("＋ New contact", on_click=clear_selection, width="stretch")
    initial: ContactData = ContactData(
        name=selected.name, phone=selected.phone, email=selected.email, address=selected.address
    )
    # Widget keys include the id so switching contacts reloads the form values.
    with st.form(f"edit_form_{selected.id}", border=False):
        data: ContactData = normalize_contact(contact_fields(f"edit_{selected.id}", initial))
        save_col, delete_col = st.columns(2)
        saved: bool = save_col.form_submit_button("Save", type="primary", width="stretch")
        deleted: bool = delete_col.form_submit_button("Delete", width="stretch")
    if deleted:
        delete_contact(conn, selected.id)
        finish_change(f"Deleted '{selected.name}'.")
    if saved:
        errors: list[str] = validate_contact(data)
        if errors:
            show_errors(errors)
            return
        update_contact(conn, selected.id, data)
        finish_change(f"Updated '{data.name}'.")


def main() -> None:
    st.set_page_config(page_title="Address Book", page_icon="📇", layout="wide")
    st.title("📇 Address Book")
    st.session_state.setdefault(TABLE_VERSION_KEY, 0)
    if FLASH_KEY in st.session_state:
        st.toast(st.session_state.pop(FLASH_KEY), icon="✅")

    conn: sqlite3.Connection = connect(DB_PATH)
    try:
        list_col, form_col = st.columns([3, 2], gap="large")
        with list_col:
            selected: Contact | None = render_contact_list(conn)
        with form_col, st.container(border=True):
            if selected is None:
                render_add(conn)
            else:
                render_edit(conn, selected)
    finally:
        conn.close()


main()
