import sqlite3
from collections.abc import Iterator
from contextlib import closing
from pathlib import Path

import pytest

from db import (
    ContactData,
    ContactNotFoundError,
    add_contact,
    connect,
    delete_contact,
    normalize_contact,
    search_contacts,
    update_contact,
    validate_contact,
)

ALICE: ContactData = ContactData(name="Alice", phone="555 111", email="alice@example.com", address="London")
BOB: ContactData = ContactData(name="bob", phone="555 222", email="bob@example.com", address="Paris")


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    with closing(connect(tmp_path / "test.db")) as connection:
        yield connection


def test_add_and_list_sorted_by_name(conn: sqlite3.Connection) -> None:
    add_contact(conn, BOB)
    add_contact(conn, ALICE)
    names: list[str] = [c.name for c in search_contacts(conn, "")]
    assert names == ["Alice", "bob"]


def test_search_matches_any_field(conn: sqlite3.Connection) -> None:
    add_contact(conn, ALICE)
    add_contact(conn, BOB)
    assert [c.name for c in search_contacts(conn, "paris")] == ["bob"]
    assert [c.name for c in search_contacts(conn, "111")] == ["Alice"]
    assert search_contacts(conn, "nobody") == []


def test_search_treats_wildcards_literally(conn: sqlite3.Connection) -> None:
    add_contact(conn, ALICE)
    add_contact(conn, ContactData(name="100% Real_Co", phone="", email="", address=""))
    assert [c.name for c in search_contacts(conn, "%")] == ["100% Real_Co"]
    assert [c.name for c in search_contacts(conn, "_")] == ["100% Real_Co"]


def test_update_contact(conn: sqlite3.Connection) -> None:
    contact_id: int = add_contact(conn, ALICE)
    update_contact(conn, contact_id, BOB)
    [stored] = search_contacts(conn, "")
    assert (stored.id, stored.name) == (contact_id, "bob")


def test_delete_contact(conn: sqlite3.Connection) -> None:
    contact_id: int = add_contact(conn, ALICE)
    delete_contact(conn, contact_id)
    assert search_contacts(conn, "") == []


def test_missing_id_raises(conn: sqlite3.Connection) -> None:
    with pytest.raises(ContactNotFoundError):
        update_contact(conn, 999, ALICE)
    with pytest.raises(ContactNotFoundError):
        delete_contact(conn, 999)


def test_data_persists_across_connections(tmp_path: Path) -> None:
    db_path: Path = tmp_path / "persist.db"
    with closing(connect(db_path)) as first:
        add_contact(first, ALICE)
    with closing(connect(db_path)) as second:
        assert [c.name for c in search_contacts(second, "")] == ["Alice"]


def test_validate_contact() -> None:
    assert validate_contact(ALICE) == []
    assert validate_contact(ContactData(name="Alice", phone="", email="", address="")) == []
    assert len(validate_contact(ContactData(name="  ", phone="", email="bad", address=""))) == 2


def test_normalize_contact_strips_whitespace() -> None:
    raw: ContactData = ContactData(name=" Alice ", phone=" 1 ", email=" a@b.co ", address=" x ")
    assert normalize_contact(raw) == ContactData(name="Alice", phone="1", email="a@b.co", address="x")
