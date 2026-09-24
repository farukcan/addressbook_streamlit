import asyncio
import json
import socket
import time
from pathlib import Path
from typing import Any

import httpx2
import pytest
from mcp import ClientSession
from mcp.client.sse import sse_client
from mcp.server.transport_security import TransportSecuritySettings

from db import ContactNotFoundError
from mcp_server import (
    SHUTDOWN_TIMEOUT_SECONDS,
    ContactDict,
    client_cli_command,
    client_config_json,
    RunningServer,
    ServerConfig,
    create_contact,
    edit_contact,
    get_contact,
    list_contacts,
    load_state,
    remove_contact,
    save_state,
    server_url,
    start_server,
    stop_server,
    transport_security,
)

HOST: str = "127.0.0.1"


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((HOST, 0))
        port: int = sock.getsockname()[1]
        return port


def raw_request(config: ServerConfig, authorization: bytes) -> bytes:
    """Send a GET to the SSE endpoint with a raw Authorization header and return the response start."""
    with socket.create_connection((config.host, config.port), timeout=5.0) as sock:
        sock.sendall(
            b"GET /sse HTTP/1.1\r\nHost: "
            + f"{config.host}:{config.port}".encode()
            + b"\r\nAuthorization: "
            + authorization
            + b"\r\nConnection: close\r\n\r\n"
        )
        return sock.recv(256)


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "contacts.db"


def test_create_and_list(db_path: Path) -> None:
    created: ContactDict = create_contact(db_path, "Alice", "555 111", "alice@example.com", "London")
    assert created["name"] == "Alice"
    assert list_contacts(db_path, "london") == [created]
    assert list_contacts(db_path, "nobody") == []


def test_create_validates(db_path: Path) -> None:
    with pytest.raises(ValueError, match="Name is required"):
        create_contact(db_path, "  ", "", "", "")
    with pytest.raises(ValueError, match="Invalid email"):
        create_contact(db_path, "Alice", "", "bad", "")


def test_edit_and_remove(db_path: Path) -> None:
    created: ContactDict = create_contact(db_path, "Alice", "", "", "")
    contact_id: int = int(created["id"])
    updated: ContactDict = edit_contact(db_path, contact_id, "Bob", "555 222", "bob@example.com", "Paris")
    assert get_contact(db_path, contact_id) == updated
    assert remove_contact(db_path, contact_id) == updated
    assert list_contacts(db_path, "") == []


def test_missing_id_raises(db_path: Path) -> None:
    with pytest.raises(ContactNotFoundError):
        get_contact(db_path, 999)
    with pytest.raises(ContactNotFoundError):
        remove_contact(db_path, 999)


async def call_over_sse(url: str, headers: dict[str, str] | None) -> tuple[list[str], list[str]]:
    """Connect as an MCP client, then return the tool names and the names in the contact list."""
    async with sse_client(url, headers=headers) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            tools: list[str] = [tool.name for tool in (await session.list_tools()).tools]
            await session.call_tool(
                "create_contact",
                {"name": "Alice", "phone": "", "email": "", "address": "London"},
            )
            result: Any = await session.call_tool("list_contacts", {"query": ""})
            names: list[str] = [contact["name"] for contact in result.structured_content["result"]]
            return tools, names


def test_sse_client_can_manage_contacts(db_path: Path) -> None:
    config: ServerConfig = ServerConfig(host=HOST, port=free_port(), token=None)
    running: RunningServer = start_server(db_path, config)
    try:
        tools, names = asyncio.run(call_over_sse(server_url(config), None))
    finally:
        stop_server(running)
    assert "create_contact" in tools
    assert names == ["Alice"]
    assert [contact["name"] for contact in list_contacts(db_path, "")] == ["Alice"]


def test_token_is_required_when_configured(db_path: Path) -> None:
    config: ServerConfig = ServerConfig(host=HOST, port=free_port(), token="s3cret")
    running: RunningServer = start_server(db_path, config)
    try:
        response: httpx2.Response = httpx2.get(server_url(config), timeout=5.0)
        assert response.status_code == 401
        wrong: httpx2.Response = httpx2.get(
            server_url(config), headers={"Authorization": "Bearer wrong"}, timeout=5.0
        )
        assert wrong.status_code == 401
        # httpx refuses non-ASCII headers, so this one goes out as raw bytes.
        assert b" 401 " in raw_request(config, "Bearer t\xc3\xb6k\xc3\xa9n".encode("latin-1"))
        _, names = asyncio.run(call_over_sse(server_url(config), {"Authorization": "Bearer s3cret"}))
    finally:
        stop_server(running)
    assert names == ["Alice"]


def test_client_config_without_token() -> None:
    config: ServerConfig = ServerConfig(host=HOST, port=8765, token=None)
    assert json.loads(client_config_json(config)) == {
        "mcpServers": {"address-book": {"url": "http://127.0.0.1:8765/sse"}}
    }
    assert client_cli_command(config) == (
        "claude mcp add --transport sse address-book http://127.0.0.1:8765/sse"
    )


def test_client_config_with_token() -> None:
    config: ServerConfig = ServerConfig(host="0.0.0.0", port=9000, token="s3cret")
    entry: dict[str, Any] = json.loads(client_config_json(config))["mcpServers"]["address-book"]
    assert entry["headers"] == {"Authorization": "Bearer s3cret"}
    assert '--header "Authorization: Bearer s3cret"' in client_cli_command(config)


@pytest.mark.parametrize(
    ("host", "port", "token"),
    [("", 8765, None), ("   ", 8765, None), ("127.0.0.1", 0, None), ("127.0.0.1", 8765, "  ")],
)
def test_invalid_config_raises(host: str, port: int, token: str | None) -> None:
    with pytest.raises(ValueError):
        ServerConfig(host=host, port=port, token=token)


def test_transport_security_allows_the_bound_address() -> None:
    lan: TransportSecuritySettings = transport_security("192.168.1.5")
    assert lan.enable_dns_rebinding_protection is True
    assert "192.168.1.5:*" in lan.allowed_hosts
    assert "[::1]:*" in transport_security("::1").allowed_hosts
    # A wildcard bind serves every interface, so no Host value can be allow-listed up front.
    assert transport_security("0.0.0.0").enable_dns_rebinding_protection is False


async def stop_while_connected(config: ServerConfig, running: RunningServer) -> float:
    """Keep an SSE session open, stop the server and return how long the stop took."""
    async with sse_client(server_url(config)) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            started: float = time.monotonic()
            await asyncio.to_thread(stop_server, running)
            return time.monotonic() - started


def test_stop_server_with_a_connected_client(db_path: Path) -> None:
    config: ServerConfig = ServerConfig(host=HOST, port=free_port(), token=None)
    running: RunningServer = start_server(db_path, config)
    elapsed: float = asyncio.run(stop_while_connected(config, running))
    assert elapsed < SHUTDOWN_TIMEOUT_SECONDS
    assert not running.thread.is_alive()


def test_wildcard_bind_is_shown_as_loopback() -> None:
    assert server_url(ServerConfig(host="0.0.0.0", port=8765, token=None)) == "http://127.0.0.1:8765/sse"


def test_state_round_trip(tmp_path: Path) -> None:
    state_path: Path = tmp_path / "mcp_state.json"
    assert load_state(state_path) is None

    with_token: ServerConfig = ServerConfig(host="0.0.0.0", port=9000, token="s3cret")
    save_state(state_path, with_token)
    assert load_state(state_path) == with_token
    # The file holds the token, so only its owner may read it.
    assert state_path.stat().st_mode & 0o077 == 0

    without_token: ServerConfig = ServerConfig(host=HOST, port=8765, token=None)
    save_state(state_path, without_token)
    assert load_state(state_path) == without_token


def test_stopped_server_is_not_remembered(tmp_path: Path) -> None:
    state_path: Path = tmp_path / "mcp_state.json"
    save_state(state_path, ServerConfig(host=HOST, port=8765, token=None))
    save_state(state_path, None)
    assert not state_path.exists()
    assert load_state(state_path) is None


def test_malformed_state_raises(tmp_path: Path) -> None:
    state_path: Path = tmp_path / "mcp_state.json"
    state_path.write_text('{"host": "127.0.0.1", "port": "8765", "token": null}', encoding="utf-8")
    with pytest.raises(ValueError, match="Malformed MCP server state"):
        load_state(state_path)
