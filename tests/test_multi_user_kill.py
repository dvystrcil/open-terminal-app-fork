"""Killing a multi-user (`sudo -u <user>`) command must reach the user's processes.

Needs passwordless sudo and a second local account, so it only runs when
OPEN_TERMINAL_TEST_RUN_AS_USER names one (CI creates it; see test.yml).
"""

import asyncio
import os
import subprocess

import pytest

from open_terminal.utils.lifetime import enforce_max_lifetime
from open_terminal.utils.log import log_process
from open_terminal.utils.runner import create_runner

from .test_process_lifetime import _Proc

RUN_AS = os.environ.get("OPEN_TERMINAL_TEST_RUN_AS_USER")

pytestmark = pytest.mark.skipif(
    not RUN_AS
    or subprocess.run(["sudo", "-n", "true"], capture_output=True).returncode != 0,
    reason="set OPEN_TERMINAL_TEST_RUN_AS_USER and have passwordless sudo",
)


def _user_pids(pattern: str) -> list[int]:
    out = subprocess.run(
        ["pgrep", "-u", RUN_AS, "-f", pattern], capture_output=True, text=True
    ).stdout
    return [int(p) for p in out.split()]


@pytest.fixture
def marker():
    # A sleep length unique to this test run, so pgrep finds only ours.
    m = str(3000 + os.getpid() % 1000)
    yield m
    _reap_leftovers(m)


def _reap_leftovers(marker: str) -> None:
    subprocess.run(["sudo", "-n", "pkill", "-KILL", "-u", RUN_AS, "-f", f"sleep {marker}"])


async def _run(scenario, marker):
    """Run *scenario*, recording survivors, then clean up inside the loop.

    A surviving user process holds the PTY open, so log_process's executor
    read never returns and asyncio.run() teardown would hang on it instead
    of the test failing. Kill leftovers before leaving the loop.
    """
    try:
        result = await scenario()
        await asyncio.sleep(0.3)
        return result, _user_pids(f"sleep {marker}")
    finally:
        _reap_leftovers(marker)


async def _start(command: str, tmp_path) -> _Proc:
    runner = await create_runner(command, "/tmp", None, run_as_user=RUN_AS)
    proc = _Proc(command=command, runner=runner, log_path=str(tmp_path / "p.jsonl"))
    proc.log_task = asyncio.create_task(log_process(proc))
    await asyncio.sleep(1)  # let sudo spawn the user's processes
    return proc


@pytest.mark.parametrize(
    "command",
    [
        "sleep {m}; echo after",  # bash forks sleep (not exec): grandchild
        "sleep {m} & sleep {m}; wait",  # background job too
    ],
)
def test_kill_reaches_run_as_user_grandchildren(tmp_path, marker, command):
    async def scenario():
        proc = await _start(command.format(m=marker), tmp_path)
        assert _user_pids(f"sleep {marker}"), "precondition: user's sleep is running"
        proc.runner.kill()
        await asyncio.wait({proc.log_task}, timeout=5)

    _, survivors = asyncio.run(_run(scenario, marker))
    assert survivors == []


def test_max_lifetime_reaps_term_immune_run_as_user_process(tmp_path, marker):
    async def scenario():
        proc = await _start(f"trap '' TERM; sleep {marker}; echo after", tmp_path)
        await enforce_max_lifetime(proc, lifetime=0.2, grace=1)
        return proc, proc.log_task.done()

    (proc, done), survivors = asyncio.run(_run(scenario, marker))
    assert survivors == []
    assert done and proc.status == "killed"
