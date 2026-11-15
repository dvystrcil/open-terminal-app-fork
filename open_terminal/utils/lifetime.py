"""Server-side ceiling on how long a background /execute process may run.

``wait`` on /execute only bounds how long the *HTTP call* blocks; the
process itself keeps running after the call returns. Without a ceiling a
caller (or a model) can start ``sleep 999999`` and it stays tracked and
alive forever, with nothing on the server side to reclaim it.
"""

import asyncio
import logging

log = logging.getLogger(__name__)


async def enforce_max_lifetime(background_process, lifetime: float, grace: float) -> None:
    """Kill *background_process* if it is still running after *lifetime* seconds.

    Sends SIGTERM to the process group first; if the process has not exited
    *grace* seconds later, sends SIGKILL. ``kill_reason`` is set before the
    first signal so ``log_process`` records the process as ``killed`` (not
    ``done``) and writes the reason into its output, where the caller sees it.

    Returns once the process has exited, or after the SIGKILL grace period
    if it still has not.
    """
    log_task = background_process.log_task
    try:
        await asyncio.wait_for(asyncio.shield(log_task), timeout=lifetime)
        return  # finished on its own
    except asyncio.TimeoutError:
        pass

    # Killed by DELETE /execute/{id} (or exited) while we were waking up.
    if log_task.done() or background_process.status != "running":
        return

    background_process.kill_reason = (
        f"exceeded the server's max lifetime of {lifetime:g}s "
        "(OPEN_TERMINAL_PROCESS_MAX_LIFETIME) and was killed"
    )
    for force in (False, True):
        try:
            background_process.runner.kill(force=force)
        except OSError as exc:  # e.g. PermissionError on a foreign-uid group
            log.warning(
                "max-lifetime kill (force=%s) of %r failed: %s",
                force,
                background_process.command,
                exc,
            )
        try:
            await asyncio.wait_for(asyncio.shield(log_task), timeout=grace)
            return
        except asyncio.TimeoutError:
            continue

    log.warning(
        "process %r still running %gs after SIGKILL",
        background_process.command,
        grace,
    )
