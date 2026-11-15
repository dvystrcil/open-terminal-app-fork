"""End-to-end: a real open-terminal server enforces OPEN_TERMINAL_PROCESS_MAX_LIFETIME
on processes started through POST /execute (open-terminal#9)."""

import os
import socket
import subprocess
import sys
import time

import httpx
import pytest

API_KEY = "test-key"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _server(tmp_path, **env):
    port = _free_port()
    proc = subprocess.Popen(
        [sys.executable, "-m", "open_terminal", "run", "--host", "127.0.0.1", "--port", str(port)],
        env={
            **os.environ,
            "OPEN_TERMINAL_API_KEY": API_KEY,
            "OPEN_TERMINAL_LOG_DIR": str(tmp_path / "logs"),
            "HOME": str(tmp_path),
            **env,
        },
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    client = httpx.Client(
        base_url=f"http://127.0.0.1:{port}",
        headers={"Authorization": f"Bearer {API_KEY}"},
        timeout=10,
    )
    deadline = time.time() + 20
    while time.time() < deadline:
        try:
            if client.get("/health").status_code == 200:
                return proc, client
        except httpx.TransportError:
            pass
        time.sleep(0.2)
    proc.kill()
    pytest.fail("server did not start")


@pytest.fixture
def capped_server(tmp_path):
    proc, client = _server(
        tmp_path,
        OPEN_TERMINAL_PROCESS_MAX_LIFETIME="1",
        OPEN_TERMINAL_PROCESS_KILL_GRACE="1",
    )
    yield client
    proc.terminate()
    proc.wait(timeout=10)


@pytest.fixture
def uncapped_server(tmp_path):
    proc, client = _server(tmp_path)
    yield client
    proc.terminate()
    proc.wait(timeout=10)


def test_execute_process_past_max_lifetime_is_killed(capped_server):
    started = capped_server.post("/execute", json={"command": "sleep 60"}).json()
    assert started["status"] == "running"

    status = capped_server.get(
        f"/execute/{started['id']}/status", params={"wait": 10}
    ).json()

    assert status["status"] == "killed"
    text = "".join(e["data"] for e in status["output"])
    assert "max lifetime" in text


def test_short_command_unaffected_by_cap(capped_server):
    result = capped_server.post(
        "/execute", params={"wait": 5}, json={"command": "echo hello"}
    ).json()
    assert result["status"] == "done"
    assert result["exit_code"] == 0


def test_no_cap_by_default(uncapped_server):
    started = uncapped_server.post("/execute", json={"command": "sleep 3"}).json()
    status = uncapped_server.get(
        f"/execute/{started['id']}/status", params={"wait": 10}
    ).json()
    assert status["status"] == "done"
    assert status["exit_code"] == 0
