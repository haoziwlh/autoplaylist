from __future__ import annotations

import pathlib
import shutil

from rich.console import Console

from autoplaylist.player import _find_ytdlp, _get_browser
from autoplaylist.setup import (
    _detect_js_runtime,
    _detect_ytdlp_install_kind,
    _has_ytdlp_ejs,
)


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

    c.print()
