"""Streamlit UI for the contact book. Run with: uv run streamlit run app.py"""

import sqlite3
from dataclasses import asdict
from pathlib import Path

import streamlit as st

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
ADD_PREFIX: str = "add"


def rerun_with_message(message: str) -> None:
    """Store a success message for the next run and rerun so every view shows fresh data."""
    st.session_state[FLASH_KEY] = message
    st.rerun()


def contact_fields(key_prefix: str, initial: ContactData) -> ContactData:
    """Render the contact input widgets inside the current form and return their values."""
    return ContactData(
        name=st.text_input("İsim *", value=initial.name, key=f"{key_prefix}_name"),
        phone=st.text_input("Telefon", value=initial.phone, key=f"{key_prefix}_phone"),
        email=st.text_input("E-posta", value=initial.email, key=f"{key_prefix}_email"),
        address=st.text_area("Adres", value=initial.address, key=f"{key_prefix}_address"),
    )


def show_errors(errors: list[str]) -> None:
    for error in errors:
        st.error(error)


def render_list(conn: sqlite3.Connection) -> None:
    query: str = st.text_input("Ara", placeholder="İsim, telefon, e-posta veya adres")
    contacts: list[Contact] = search_contacts(conn, query)
    st.caption(f"{len(contacts)} kişi")
    st.dataframe(
        [asdict(c) for c in contacts],
        hide_index=True,
        width="stretch",
        column_config={
            "id": None,
            "name": "İsim",
            "phone": "Telefon",
            "email": "E-posta",
            "address": "Adres",
        },
    )


def render_add(conn: sqlite3.Connection) -> None:
    empty: ContactData = ContactData(name="", phone="", email="", address="")
    with st.form("add_form"):
        data: ContactData = normalize_contact(contact_fields(ADD_PREFIX, empty))
        submitted: bool = st.form_submit_button("Ekle", type="primary")
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
    rerun_with_message(f"'{data.name}' eklendi.")


def render_edit(conn: sqlite3.Connection) -> None:
    contacts: list[Contact] = search_contacts(conn, "")
    if not contacts:
        st.info("Henüz kişi yok.")
        return
    by_id: dict[int, Contact] = {c.id: c for c in contacts}
    # Select by id with a stable key so the selection survives label changes after edits.
    selected_id: int | None = st.selectbox(
        "Kişi seç",
        list(by_id),
        format_func=lambda i: f"{by_id[i].name} ({by_id[i].phone})" if by_id[i].phone else by_id[i].name,
        key="edit_select",
    )
    if selected_id is None:
        raise RuntimeError("Selectbox returned no contact although contacts exist.")
    selected: Contact = by_id[selected_id]
    initial: ContactData = ContactData(
        name=selected.name, phone=selected.phone, email=selected.email, address=selected.address
    )
    # Widget keys include the id so switching contacts reloads the form values.
    with st.form(f"edit_form_{selected.id}"):
        data: ContactData = normalize_contact(contact_fields(f"edit_{selected.id}", initial))
        save_col, delete_col = st.columns(2)
        saved: bool = save_col.form_submit_button("Kaydet", type="primary", width="stretch")
        deleted: bool = delete_col.form_submit_button("Sil", width="stretch")
    if deleted:
        delete_contact(conn, selected.id)
        rerun_with_message(f"'{selected.name}' silindi.")
    if saved:
        errors: list[str] = validate_contact(data)
        if errors:
            show_errors(errors)
            return
        update_contact(conn, selected.id, data)
        rerun_with_message(f"'{data.name}' güncellendi.")


def main() -> None:
    st.set_page_config(page_title="Adres Defteri", page_icon="📇")
    st.title("📇 Adres Defteri")
    if FLASH_KEY in st.session_state:
        st.success(st.session_state.pop(FLASH_KEY))

    conn: sqlite3.Connection = connect(DB_PATH)
    try:
        list_tab, add_tab, edit_tab = st.tabs(["Liste", "Ekle", "Düzenle / Sil"])
        with list_tab:
            render_list(conn)
        with add_tab:
            render_add(conn)
        with edit_tab:
            render_edit(conn)
    finally:
        conn.close()


main()
