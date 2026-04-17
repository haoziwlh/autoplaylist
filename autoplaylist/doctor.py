from __future__ import annotations

import getpass
import os
import pathlib
import shutil
import subprocess

from rich.console import Console

from autoplaylist.player import _find_ytdlp, _get_browser
from autoplaylist.setup import (
    _detect_js_runtime,
    _detect_ytdlp_install_kind,
    _has_ytdlp_ejs,
)

_IPC_SOCK = f"/tmp/myplaylist-{getpass.getuser()}-mpv.sock"


def _find_orphan_mpv() -> list[int]:
    """Return PIDs of mpv processes using our IPC socket with no live daemon."""
    try:
        out = subprocess.check_output(
            ["pgrep", "-f", f"mpv.*{_IPC_SOCK}"],
            text=True, stderr=subprocess.DEVNULL,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return []
    pids = [int(p) for p in out.strip().splitlines() if p.strip()]
    if not pids:
        return []
    # If a daemon is alive and owns them, they're not orphans
    from autoplaylist.daemon import is_daemon_alive
    if is_daemon_alive():
        return []
    return pids


def run() -> None:
    c = Console()
    c.print("\n[bold]myplaylist doctor[/bold]")

    ytdlp_path = _find_ytdlp()
    ytdlp_ok = pathlib.Path(ytdlp_path).exists()
    kind = _detect_ytdlp_install_kind(ytdlp_path) if ytdlp_ok else "missing"
    ytdlp_mark = "[green]✓[/green]" if ytdlp_ok else "[red]missing[/red]"
    c.print(f"  yt-dlp:       {ytdlp_path}  ({kind})  {ytdlp_mark}")

    mpv_path = shutil.which("mpv")
    if mpv_path:
        c.print(f"  mpv:          {mpv_path}  [green]✓[/green]")
    else:
        c.print(f"  mpv:          [red]missing[/red] — run `myplaylist setup`")

    browser = _get_browser()
    if browser:
        c.print(f"  browser:      {browser}  [green]✓[/green]")
    else:
        c.print(f"  browser:      [yellow]none detected[/yellow] — YouTube bot-check may trigger")

    runtime = _detect_js_runtime()
    if runtime:
        name, path = runtime
        c.print(f"  js-runtime:   {name} ({path})  [green]✓[/green]")
    else:
        c.print(f"  js-runtime:   [yellow]missing[/yellow] — install deno: `brew install deno`")

    if ytdlp_ok and _has_ytdlp_ejs(ytdlp_path):
        c.print(f"  yt-dlp-ejs:   [green]installed[/green]  ✓")
    else:
        c.print(f"  yt-dlp-ejs:   [yellow]missing (remote fallback via --remote-components ejs:github)[/yellow]")

    # Orphan process detection
    from autoplaylist.daemon import read_pid
    stale_pid = read_pid()
    if stale_pid is not None:
        try:
            os.kill(stale_pid, 0)
        except ProcessLookupError:
            c.print(f"  daemon:       [yellow]stale PID file ({stale_pid} not running)[/yellow]"
                     " — run `myplaylist ctl quit` or delete ~/.myplaylist/daemon.pid")
            stale_pid = None

    orphans = _find_orphan_mpv()
    if orphans:
        pids_str = ", ".join(str(p) for p in orphans)
        c.print(f"  orphan mpv:   [red]{len(orphans)} orphan(s) (PID {pids_str})[/red]"
                 f" — kill with: kill {pids_str}")
    else:
        c.print(f"  orphan mpv:   [green]none[/green]  ✓")

    c.print()
