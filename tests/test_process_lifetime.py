"""Tests for the background-process max-lifetime reaper (open-terminal#9).

These run real subprocesses under the real PtyRunner and the real
log_process(), so they exercise the same kill path production uses.
"""

import asyncio
import json
import os
import time
from dataclasses import dataclass, field
from typing import Optional

from open_terminal.utils.lifetime import enforce_max_lifetime
from open_terminal.utils.log import log_process, read_log
from open_terminal.utils.runner import create_runner


@dataclass
class _Proc:
    """Minimal stand-in with the fields log_process/enforce_max_lifetime use."""

    command: str
    runner: object
    log_path: Optional[str]
    status: str = "running"
    exit_code: Optional[int] = None
    log_task: Optional[asyncio.Task] = field(default=None, repr=False)
    finished_at: Optional[float] = None
    kill_reason: Optional[str] = None


async def _start(command: str, tmp_path) -> _Proc:
    runner = await create_runner(command, str(tmp_path), None)
    proc = _Proc(command=command, runner=runner, log_path=str(tmp_path / "p.jsonl"))
    proc.log_task = asyncio.create_task(log_process(proc))
    return proc


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    # A zombie still answers kill(0); treat it as dead.
    try:
        with open(f"/proc/{pid}/stat") as f:
            return f.read().split(") ", 1)[1][0] != "Z"
    except FileNotFoundError:
        return False


def test_process_past_lifetime_is_killed_and_marked(tmp_path):
    async def scenario():
        proc = await _start("sleep 30", tmp_path)
        started = time.monotonic()
        await enforce_max_lifetime(proc, lifetime=0.5, grace=2)
        return proc, time.monotonic() - started

    proc, elapsed = asyncio.run(scenario())
    assert elapsed < 5, "reaper should not wait for the command to finish"
    assert proc.status == "killed"
    assert proc.kill_reason and "max lifetime" in proc.kill_reason
    assert not _alive(proc.runner.pid)


def test_kill_reason_is_visible_in_output(tmp_path):
    async def scenario():
        proc = await _start("sleep 30", tmp_path)
        await enforce_max_lifetime(proc, lifetime=0.5, grace=2)
        output, _, _ = await read_log(proc.log_path)
        return output

    output = asyncio.run(scenario())
    text = "".join(e["data"] for e in output)
    assert "max lifetime" in text


def test_end_record_carries_kill_reason(tmp_path):
    async def scenario():
        proc = await _start("sleep 30", tmp_path)
        await enforce_max_lifetime(proc, lifetime=0.5, grace=2)
        return proc

    proc = asyncio.run(scenario())
    with open(proc.log_path) as f:
        records = [json.loads(line) for line in f if line.strip()]
    end = [r for r in records if r["type"] == "end"]
    assert end and "max lifetime" in end[0]["kill_reason"]


def test_sigterm_ignoring_process_is_sigkilled_after_grace(tmp_path):
    async def scenario():
        proc = await _start("trap '' TERM; sleep 30", tmp_path)
        await asyncio.sleep(0.3)  # let the trap install
        started = time.monotonic()
        await enforce_max_lifetime(proc, lifetime=0.2, grace=0.5)
        elapsed = time.monotonic() - started
        # Checked here, while the loop is live: after asyncio.run() returns,
        # teardown has already waited out the (TERM-immune) sleep.
        return proc, elapsed, proc.log_task.done(), _alive(proc.runner.pid)

    proc, elapsed, log_task_done, alive = asyncio.run(scenario())
    assert elapsed < 5
    assert log_task_done and not alive, "SIGTERM-immune process survived the grace period"
    assert proc.status == "killed"


def test_children_of_the_command_are_killed_too(tmp_path):
    pidfile = tmp_path / "child.pid"

    async def scenario():
        proc = await _start(f"sleep 30 & echo $! > {pidfile}; wait", tmp_path)
        await asyncio.sleep(0.3)
        await enforce_max_lifetime(proc, lifetime=0.2, grace=1)
        return proc

    asyncio.run(scenario())
    child = int(pidfile.read_text())
    time.sleep(0.2)
    assert not _alive(child)


def test_process_that_finishes_in_time_is_left_alone(tmp_path):
    async def scenario():
        proc = await _start("echo hi", tmp_path)
        await enforce_max_lifetime(proc, lifetime=5, grace=1)
        return proc

    proc = asyncio.run(scenario())
    assert proc.status == "done"
    assert proc.exit_code == 0
    assert proc.kill_reason is None


def test_process_killed_elsewhere_first_is_not_relabelled(tmp_path):
    """DELETE /execute/{id} racing the reaper must not be reported as a timeout."""

    async def scenario():
        proc = await _start("sleep 30", tmp_path)
        reaper = asyncio.create_task(enforce_max_lifetime(proc, lifetime=5, grace=1))
        await asyncio.sleep(0.2)
        proc.runner.kill()
        await proc.log_task
        await reaper
        return proc

    proc = asyncio.run(scenario())
    assert proc.kill_reason is None
