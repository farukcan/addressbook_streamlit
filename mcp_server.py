"""SSE MCP server that exposes the address book to AI agents.

The server runs in a background thread of the Streamlit process and is started and stopped
from the MCP tab. Every tool call opens its own SQLite connection, because the calls run in
that thread rather than in the Streamlit script run.
"""

import contextlib
import json
import secrets
import threading
import time
from contextlib import closing
from dataclasses import asdict, dataclass
from pathlib import Path

import uvicorn
from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

import db
from live_update import request_rerun_of_open_sessions

SSE_PATH: str = "/sse"
SERVER_NAME: str = "address-book"
STARTUP_TIMEOUT_SECONDS: float = 10.0
SHUTDOWN_TIMEOUT_SECONDS: float = 10.0
GRACEFUL_SHUTDOWN_SECONDS: int = 3
# Binding to one of these means "every interface", so the Host header of a request is unknown.
WILDCARD_HOSTS: frozenset[str] = frozenset({"0.0.0.0", "::"})

ContactDict = dict[str, str | int]


@dataclass(frozen=True)
class ServerConfig:
    """Where the MCP server listens and whether it requires a bearer token."""

    host: str
    port: int
    token: str | None

    def __post_init__(self) -> None:
        if not self.host.strip():
            raise ValueError("MCP server host must not be empty.")
        if not 1 <= self.port <= 65535:
            raise ValueError(f"MCP server port out of range: {self.port}")
        if self.token is not None and not self.token.strip():
            raise ValueError("MCP server token must not be empty; use None for no authentication.")


@dataclass(frozen=True)
class RunningServer:
    """Handle for a server running in a background thread."""

    config: ServerConfig
    server: uvicorn.Server
    thread: threading.Thread


class BearerTokenMiddleware:
    """ASGI middleware that rejects requests without the configured bearer token."""

    def __init__(self, app: ASGIApp, token: str) -> None:
        self.app = app
        self.token = token

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers: dict[bytes, bytes] = dict(scope["headers"])
        # Compared as bytes: a non-ASCII header would make compare_digest raise on str.
        authorization: bytes = headers.get(b"authorization", b"")
        if not secrets.compare_digest(authorization, b"Bearer " + self.token.encode("utf-8")):
            response: JSONResponse = JSONResponse({"error": "unauthorized"}, status_code=401)
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)


def list_contacts(db_path: Path, query: str) -> list[ContactDict]:
    """Return contacts matching `query`; an empty query returns all of them."""
    with closing(db.connect(db_path)) as conn:
        return [asdict(contact) for contact in db.search_contacts(conn, query)]


def get_contact(db_path: Path, contact_id: int) -> ContactDict:
    """Return one contact by id."""
    with closing(db.connect(db_path)) as conn:
        return asdict(db.get_contact(conn, contact_id))


def create_contact(db_path: Path, name: str, phone: str, email: str, address: str) -> ContactDict:
    """Create a contact and return it."""
    data: db.ContactData = db.normalize_contact(
        db.ContactData(name=name, phone=phone, email=email, address=address)
    )
    errors: list[str] = db.validate_contact(data)
    if errors:
        raise ValueError(f"Invalid contact: {' '.join(errors)}")
    with closing(db.connect(db_path)) as conn:
        contact_id: int = db.add_contact(conn, data)
        created: ContactDict = asdict(db.get_contact(conn, contact_id))
    request_rerun_of_open_sessions()
    return created


def edit_contact(
    db_path: Path, contact_id: int, name: str, phone: str, email: str, address: str
) -> ContactDict:
    """Overwrite all fields of an existing contact and return it."""
    data: db.ContactData = db.normalize_contact(
        db.ContactData(name=name, phone=phone, email=email, address=address)
    )
    errors: list[str] = db.validate_contact(data)
    if errors:
        raise ValueError(f"Invalid contact: {' '.join(errors)}")
    with closing(db.connect(db_path)) as conn:
        db.update_contact(conn, contact_id, data)
        updated: ContactDict = asdict(db.get_contact(conn, contact_id))
    request_rerun_of_open_sessions()
    return updated


def remove_contact(db_path: Path, contact_id: int) -> ContactDict:
    """Delete a contact and return the deleted record."""
    with closing(db.connect(db_path)) as conn:
        contact: db.Contact = db.get_contact(conn, contact_id)
        db.delete_contact(conn, contact_id)
    request_rerun_of_open_sessions()
    return asdict(contact)


def build_mcp_server(db_path: Path) -> MCPServer:
    """Register the address book tools on a new MCP server."""
    server: MCPServer = MCPServer(
        name=SERVER_NAME,
        instructions="Read and manage the contacts of a local address book.",
    )

    @server.tool(name="list_contacts", description="List contacts. Pass an empty query to get all of them.")
    def list_contacts_tool(query: str) -> list[ContactDict]:
        return list_contacts(db_path, query)

    @server.tool(name="get_contact", description="Get one contact by id.")
    def get_contact_tool(contact_id: int) -> ContactDict:
        return get_contact(db_path, contact_id)

    @server.tool(name="create_contact", description="Create a contact. Name is required; the other fields may be empty.")
    def create_contact_tool(name: str, phone: str, email: str, address: str) -> ContactDict:
        return create_contact(db_path, name, phone, email, address)

    @server.tool(name="update_contact", description="Overwrite all fields of an existing contact.")
    def update_contact_tool(
        contact_id: int, name: str, phone: str, email: str, address: str
    ) -> ContactDict:
        return edit_contact(db_path, contact_id, name, phone, email, address)

    @server.tool(name="delete_contact", description="Delete a contact by id and return the deleted record.")
    def delete_contact_tool(contact_id: int) -> ContactDict:
        return remove_contact(db_path, contact_id)

    return server


def bracket_ipv6(host: str) -> str:
    """Wrap an IPv6 literal in brackets so it can be used in a URL or a Host header."""
    return f"[{host}]" if ":" in host else host


def transport_security(host: str) -> TransportSecuritySettings:
    """Allow the addresses clients can reach this server on.

    A wildcard bind serves every interface, so the Host header cannot be known in advance and
    rebinding protection has to be off; any other bind only accepts its own address and localhost.
    """
    if host in WILDCARD_HOSTS:
        return TransportSecuritySettings(enable_dns_rebinding_protection=False)
    bound: str = bracket_ipv6(host)
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=[f"{bound}:*", "127.0.0.1:*", "localhost:*", "[::1]:*"],
        allowed_origins=[
            f"http://{bound}:*",
            "http://127.0.0.1:*",
            "http://localhost:*",
            "http://[::1]:*",
        ],
    )


def build_app(db_path: Path, config: ServerConfig) -> Starlette:
    """Build the SSE app for `config`, requiring a bearer token when one is set."""
    app: Starlette = build_mcp_server(db_path).sse_app(
        sse_path=SSE_PATH, transport_security=transport_security(config.host)
    )
    if config.token is not None:
        app.add_middleware(BearerTokenMiddleware, token=config.token)
    return app


def run_until_exit(server: uvicorn.Server) -> None:
    """Thread target. uvicorn exits the process on a bind error; `start_server` reports that instead."""
    with contextlib.suppress(SystemExit):
        server.run()


def start_server(db_path: Path, config: ServerConfig) -> RunningServer:
    """Start the SSE server in a background thread and wait until it accepts connections."""
    uvicorn_config: uvicorn.Config = uvicorn.Config(
        build_app(db_path, config),
        host=config.host,
        port=config.port,
        log_level="warning",
        # Open SSE streams never finish on their own, so cap the graceful wait.
        timeout_graceful_shutdown=GRACEFUL_SHUTDOWN_SECONDS,
    )
    server: uvicorn.Server = uvicorn.Server(uvicorn_config)
    thread: threading.Thread = threading.Thread(
        target=run_until_exit, args=(server,), name="mcp-sse-server", daemon=True
    )
    thread.start()
    deadline: float = time.monotonic() + STARTUP_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if server.started:
            return RunningServer(config=config, server=server, thread=thread)
        if not thread.is_alive():
            raise RuntimeError(
                f"MCP server thread stopped during startup: host={config.host} port={config.port} "
                "(the port may already be in use)"
            )
        time.sleep(0.05)
    server.should_exit = True
    thread.join(timeout=SHUTDOWN_TIMEOUT_SECONDS)
    raise TimeoutError(
        f"MCP server did not start within {STARTUP_TIMEOUT_SECONDS}s: host={config.host} port={config.port}"
    )


def stop_server(running: RunningServer) -> None:
    """Ask the server to exit, then force it if connected clients keep it alive."""
    running.server.should_exit = True
    running.thread.join(timeout=SHUTDOWN_TIMEOUT_SECONDS)
    if running.thread.is_alive():
        running.server.force_exit = True
        running.thread.join(timeout=SHUTDOWN_TIMEOUT_SECONDS)
    if running.thread.is_alive():
        raise TimeoutError(
            f"MCP server did not stop within {SHUTDOWN_TIMEOUT_SECONDS}s: "
            f"host={running.config.host} port={running.config.port}"
        )


def save_state(state_path: Path, config: ServerConfig | None) -> None:
    """Record the running server, or clear the record when it is stopped.

    The file holds the token, so it is written readable by its owner only.
    """
    if config is None:
        state_path.unlink(missing_ok=True)
        return
    state_path.write_text(
        json.dumps({"host": config.host, "port": config.port, "token": config.token}),
        encoding="utf-8",
    )
    state_path.chmod(0o600)


def load_state(state_path: Path) -> ServerConfig | None:
    """Return the server a previous run left running, or None when it was stopped."""
    if not state_path.exists():
        return None
    state: dict[str, str | int | None] = json.loads(state_path.read_text(encoding="utf-8"))
    host: str | int | None = state["host"]
    port: str | int | None = state["port"]
    token: str | int | None = state["token"]
    if not isinstance(host, str) or not isinstance(port, int) or not isinstance(token, str | None):
        raise ValueError(f"Malformed MCP server state: path={state_path} state={state}")
    return ServerConfig(host=host, port=port, token=token)


def server_url(config: ServerConfig) -> str:
    """Return the SSE endpoint URL clients connect to.

    A wildcard bind has no address of its own, so it is shown as loopback; clients on another
    machine use this machine's address on the network instead.
    """
    host: str = "127.0.0.1" if config.host in WILDCARD_HOSTS else config.host
    return f"http://{bracket_ipv6(host)}:{config.port}{SSE_PATH}"


def client_config_json(config: ServerConfig) -> str:
    """Return the JSON snippet an MCP client needs to connect to this server."""
    entry: dict[str, object] = {"url": server_url(config)}
    if config.token is not None:
        entry["headers"] = {"Authorization": f"Bearer {config.token}"}
    return json.dumps({"mcpServers": {SERVER_NAME: entry}}, indent=2)


def client_cli_command(config: ServerConfig) -> str:
    """Return a Claude Code CLI command that registers this server."""
    header: str = "" if config.token is None else f' --header "Authorization: Bearer {config.token}"'
    return f"claude mcp add --transport sse {SERVER_NAME} {server_url(config)}{header}"
