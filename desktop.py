"""Desktop launcher: runs the Streamlit app on localhost and shows it in a native window.

Run with: uv run python desktop.py
Closing the window stops the Streamlit server.
"""

import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import webview

APP_PATH: Path = Path(__file__).parent / "app.py"
HOST: str = "127.0.0.1"
STARTUP_TIMEOUT_SECONDS: float = 30.0
WINDOW_TITLE: str = "Address Book"


def find_free_port(host: str) -> int:
    """Ask the OS for an unused TCP port on `host`."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        port: int = sock.getsockname()[1]
        return port


def start_server(app_path: Path, host: str, port: int) -> subprocess.Popen[bytes]:
    """Start Streamlit in a child process bound to localhost only."""
    return subprocess.Popen(
        [
            sys.executable, "-m", "streamlit", "run", str(app_path),
            "--server.headless", "true",
            "--server.address", host,
            "--server.port", str(port),
            "--browser.gatherUsageStats", "false",
        ],
        # Streamlit reads .streamlit/config.toml from the working directory.
        cwd=app_path.parent,
    )


def wait_until_healthy(server: subprocess.Popen[bytes], health_url: str, timeout_seconds: float) -> None:
    """Poll the Streamlit health endpoint until it answers, the server exits, or the timeout passes."""
    deadline: float = time.monotonic() + timeout_seconds
    last_error: OSError | None = None
    while time.monotonic() < deadline:
        exit_code: int | None = server.poll()
        if exit_code is not None:
            raise RuntimeError(f"Streamlit server exited during startup: exit_code={exit_code}")
        try:
            with urllib.request.urlopen(health_url, timeout=1) as response:
                if response.status == 200:
                    return
        # OSError covers URLError, refused connections and read timeouts while the server boots.
        except OSError as error:
            last_error = error
        time.sleep(0.2)
    raise TimeoutError(
        f"Streamlit server not healthy after {timeout_seconds}s: url={health_url} last_error={last_error!r}"
    )


def main() -> None:
    port: int = find_free_port(HOST)
    base_url: str = f"http://{HOST}:{port}"
    server: subprocess.Popen[bytes] = start_server(APP_PATH, HOST, port)
    try:
        wait_until_healthy(server, f"{base_url}/_stcore/health", STARTUP_TIMEOUT_SECONDS)
        webview.create_window(WINDOW_TITLE, base_url, width=1000, height=750)
        webview.start()  # Blocks until the window is closed.
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait()
            raise


if __name__ == "__main__":
    main()
