"""SQLite data access layer for the contact book."""

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

EMAIL_PATTERN: re.Pattern[str] = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

SCHEMA: str = """
CREATE TABLE IF NOT EXISTS contacts (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    name    TEXT NOT NULL,
    phone   TEXT NOT NULL,
    email   TEXT NOT NULL,
    address TEXT NOT NULL
)
"""


class ContactNotFoundError(LookupError):
    """Raised when a contact id does not exist in the database."""


@dataclass(frozen=True)
class ContactData:
    """Editable fields of a contact (no id)."""

    name: str
    phone: str
    email: str
    address: str


@dataclass(frozen=True)
class Contact:
    """A stored contact row."""

    id: int
    name: str
    phone: str
    email: str
    address: str


def connect(db_path: Path) -> sqlite3.Connection:
    """Open the database and make sure the schema exists."""
    conn: sqlite3.Connection = sqlite3.connect(db_path)
    conn.execute(SCHEMA)
    conn.commit()
    return conn


def validate_contact(data: ContactData) -> list[str]:
    """Return human-readable validation errors; an empty list means valid."""
    errors: list[str] = []
    if not data.name.strip():
        errors.append("Name is required.")
    if data.email.strip() and not EMAIL_PATTERN.match(data.email.strip()):
        errors.append(f"Invalid email: {data.email}")
    return errors


def normalize_contact(data: ContactData) -> ContactData:
    """Return a copy with surrounding whitespace stripped from every field."""
    return ContactData(
        name=data.name.strip(),
        phone=data.phone.strip(),
        email=data.email.strip(),
        address=data.address.strip(),
    )


def add_contact(conn: sqlite3.Connection, data: ContactData) -> int:
    """Insert a contact and return its new id."""
    cursor: sqlite3.Cursor = conn.execute(
        "INSERT INTO contacts (name, phone, email, address) VALUES (?, ?, ?, ?)",
        (data.name, data.phone, data.email, data.address),
    )
    conn.commit()
    new_id: int | None = cursor.lastrowid
    if new_id is None:
        raise sqlite3.DatabaseError(f"Insert returned no row id for contact: {data}")
    return new_id


def search_contacts(conn: sqlite3.Connection, query: str) -> list[Contact]:
    """Return contacts whose name, phone, email or address contains `query`, sorted by name.

    An empty query matches every contact.
    """
    escaped: str = query.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    pattern: str = f"%{escaped}%"
    rows: list[tuple[int, str, str, str, str]] = conn.execute(
        """
        SELECT id, name, phone, email, address FROM contacts
        WHERE name LIKE ? ESCAPE '\\' OR phone LIKE ? ESCAPE '\\'
           OR email LIKE ? ESCAPE '\\' OR address LIKE ? ESCAPE '\\'
        ORDER BY name COLLATE NOCASE
        """,
        (pattern, pattern, pattern, pattern),
    ).fetchall()
    return [Contact(*row) for row in rows]


def update_contact(conn: sqlite3.Connection, contact_id: int, data: ContactData) -> None:
    """Overwrite all fields of an existing contact."""
    cursor: sqlite3.Cursor = conn.execute(
        "UPDATE contacts SET name = ?, phone = ?, email = ?, address = ? WHERE id = ?",
        (data.name, data.phone, data.email, data.address, contact_id),
    )
    conn.commit()
    if cursor.rowcount == 0:
        raise ContactNotFoundError(f"Contact not found for update: id={contact_id}")


def delete_contact(conn: sqlite3.Connection, contact_id: int) -> None:
    """Delete a contact by id."""
    cursor: sqlite3.Cursor = conn.execute("DELETE FROM contacts WHERE id = ?", (contact_id,))
    conn.commit()
    if cursor.rowcount == 0:
        raise ContactNotFoundError(f"Contact not found for delete: id={contact_id}")
