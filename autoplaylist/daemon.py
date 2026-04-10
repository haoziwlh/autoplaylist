"""Daemon lifecycle management for headless playback.

Provides double-fork daemonization, PID file helpers, and the headless
playback entry point.
"""
from __future__ import annotations

import os
import pathlib
import signal
import sys

_PID_FILE = pathlib.Path.home() / ".myplaylist" / "daemon.pid"
_LOG_FILE = pathlib.Path.home() / ".myplaylist" / "daemon.log"


# ---------------------------------------------------------------------------
# PID file helpers
# ---------------------------------------------------------------------------

def write_pid() -> None:
    _PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    _PID_FILE.write_text(str(os.getpid()))


def read_pid() -> int | None:
    try:
        return int(_PID_FILE.read_text().strip())
    except (FileNotFoundError, ValueError):
        return None


def remove_pid() -> None:
    try:
        _PID_FILE.unlink()
    except FileNotFoundError:
        pass


def is_daemon_alive() -> int | None:
    """Return PID if daemon is alive, else None. Cleans up stale PID file."""
    pid = read_pid()
    if pid is None:
        return None
    try:
        os.kill(pid, 0)  # signal 0 = check existence
        return pid
    except (ProcessLookupError, PermissionError):
        # Process dead — clean up stale PID file
        remove_pid()
        return None


# ---------------------------------------------------------------------------
# Double-fork daemonize
# ---------------------------------------------------------------------------

def daemonize(fn, *args, **kwargs) -> int:
    """Double-fork to fully detach from terminal. Calls fn(*args, **kwargs)
    in the grandchild. Returns the grandchild PID to the caller.

    The caller (original process) returns normally after the fork.
    """
    # First fork
    pid = os.fork()
    if pid > 0:
        # Parent: wait for child to exit, then return grandchild PID
        _, status = os.waitpid(pid, 0)
        # Child writes grandchild PID to PID file before _exit
        # Read it back
        return read_pid() or 0

    # Child: new session
    os.setsid()

    # Second fork — prevent re-acquiring a controlling terminal
    pid2 = os.fork()
    if pid2 > 0:
        # First child: write grandchild PID so parent can read it, then exit
        _PID_FILE.parent.mkdir(parents=True, exist_ok=True)
        _PID_FILE.write_text(str(pid2))
        os._exit(0)

    # Grandchild: the actual daemon
    # Redirect stdio
    _LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    sys.stdin.close()
    log_fd = open(_LOG_FILE, "a")
    os.dup2(log_fd.fileno(), 1)  # stdout
    os.dup2(log_fd.fileno(), 2)  # stderr

    # Install signal handlers for clean shutdown
    def _shutdown(signum, frame):
        remove_pid()
        sys.exit(0)

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGHUP, signal.SIG_IGN)

    try:
        fn(*args, **kwargs)
    finally:
        remove_pid()
        log_fd.close()

    os._exit(0)
