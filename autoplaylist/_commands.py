from __future__ import annotations

import sys
import termios
from typing import Optional


def _cooked_input(prompt: str) -> str:
    """Reset terminal to sane state, then read a line."""
    try:
        import subprocess as _sp
        _sp.run(["stty", "sane"], check=False, stderr=_sp.DEVNULL)
    except Exception:
        pass
    return input(prompt)

from rich.console import Console
from rich.prompt import Confirm, Prompt
from rich.table import Table

from autoplaylist import playlist as pl
from autoplaylist import discovery

console = Console()


# ---------------------------------------------------------------------------
# 5.4  new
# ---------------------------------------------------------------------------

def cmd_new(
    prompt: Optional[str],
    seed: Optional[str],
    count: int,
    name: Optional[str],
) -> None:
    if not prompt and not seed:
        console.print("[red]Provide a prompt or --seed.[/red]")
        raise SystemExit(1)

    if count > 50:
        console.print("[yellow]Count capped at 50.[/yellow]")
        count = 50

    source = seed or prompt

    if seed:
        tracks = discovery.discover_from_seed(seed, count=count)
    else:
        tracks = discovery.discover_from_prompt(prompt, count=count)  # type: ignore[arg-type]

    # Determine playlist name
    if not name:
        name = pl.slugify(seed or prompt or "playlist")  # type: ignore[arg-type]
        console.print(f"[dim]Auto-generated name: {name}[/dim]")

    # 5.3 Collision handling
    if pl.exists(name):
        ans = _cooked_input(f"Playlist '{name}' already exists. Overwrite? [y/N] ").strip().lower()
        if ans != "y":
            new_name = _cooked_input("Enter a new name: ").strip()
            if not new_name:
                print("Aborted.")
                raise SystemExit(1)
            name = pl.slugify(new_name)

    path = pl.save(name, tracks, source or "")
    console.print(f"[green]✓ Saved playlist '[bold]{name}[/bold]' with {len(tracks)} tracks → {path}[/green]")


# ---------------------------------------------------------------------------
# 5.5  list
# ---------------------------------------------------------------------------

def _dw(s: str) -> int:
    """Display width: CJK/fullwidth chars count as 2 columns."""
    w = 0
    for c in s:
        cp = ord(c)
        if (0x1100 <= cp <= 0x115F or 0x2E80 <= cp <= 0x303E or
                0x3041 <= cp <= 0x33FF or 0x4E00 <= cp <= 0x9FFF or
                0xAC00 <= cp <= 0xD7A3 or 0xF900 <= cp <= 0xFAFF or
                0xFF01 <= cp <= 0xFF60):
            w += 2
        else:
            w += 1
    return w


def _pad(s: str, width: int) -> str:
    return s + " " * max(0, width - _dw(s))


def cmd_list() -> None:
    playlists = pl.list_all()
    if not playlists:
        sys.stdout.write("\r\nNo playlists yet. Run: autoplaylist new <prompt>\r\n\r\n")
        sys.stdout.flush()
        return

    sys.stdout.write("\r\n")
    sys.stdout.write(f"  {_pad('NAME', 22)}  {'TRACKS':>6}  {'CREATED':<12}  PROMPT / SEED\r\n")
    sys.stdout.write(f"  {'-'*22}  {'-'*6}  {'-'*12}  {'-'*30}\r\n")
    for p in playlists:
        created = p["created_at"][:10] if p["created_at"] else "-"
        prompt = p["prompt"] or "-"
        if _dw(prompt) > 40:
            while _dw(prompt) > 37:
                prompt = prompt[:-1]
            prompt += "..."
        name = _pad(p["name"], 22)
        sys.stdout.write(f"  {name}  {p['track_count']:>6}  {created:<12}  {prompt}\r\n")
    sys.stdout.write("\r\n")
    sys.stdout.flush()


# ---------------------------------------------------------------------------
# 5.6  show
# ---------------------------------------------------------------------------

def cmd_show(name: str) -> None:
    try:
        data = pl.load(name)
    except FileNotFoundError as e:
        print(f"Error: {e}")
        raise SystemExit(1)

    tracks = data.get("tracks", [])
    print(f"\n  {name}  ({len(tracks)} tracks)")
    print(f"  Prompt: {data.get('prompt', '—')}\n")

    for i, t in enumerate(tracks, 1):
        dur = _fmt_duration(t.get("duration_seconds", 0))
        artist = t.get("artist", "")
        title = t.get("title", "")
        label = f"{artist} — {title}"
        if len(label) > 55:
            label = label[:52] + "..."
        print(f"  {i:>3}.  {label:<55}  {dur}")
    print()


# ---------------------------------------------------------------------------
# 5.7  delete
# ---------------------------------------------------------------------------

def cmd_delete(name: str) -> None:
    if not pl.exists(name):
        print(f"Playlist '{name}' not found.")
        raise SystemExit(1)
    ans = _cooked_input(f"Delete playlist '{name}'? [y/N] ").strip().lower()
    if ans == "y":
        pl.delete(name)
        print(f"Deleted '{name}'.")
    else:
        print("Aborted.")


# ---------------------------------------------------------------------------
# play / export — delegate to player/export modules
# ---------------------------------------------------------------------------

def cmd_play(name: str) -> None:
    try:
        data = pl.load(name)
    except FileNotFoundError as e:
        console.print(f"[red]{e}[/red]")
        raise SystemExit(1)
    tracks = pl.tracks_from_data(data)
    from autoplaylist.player import play_playlist
    play_playlist(name, tracks, data.get("prompt", ""))


def cmd_export(name: str, format: str, output: Optional[str]) -> None:
    try:
        data = pl.load(name)
    except FileNotFoundError as e:
        console.print(f"[red]{e}[/red]")
        raise SystemExit(1)

    from autoplaylist import export as exp
    import pathlib

    fmt = format.lower()
    default_name = f"{name}.{fmt}"
    out_path = pathlib.Path(output) if output else pathlib.Path(default_name)

    if not out_path.parent.exists():
        console.print(f"[red]Directory does not exist: {out_path.parent}[/red]")
        raise SystemExit(1)

    if fmt == "m3u":
        exp.export_m3u(data, out_path)
    elif fmt == "csv":
        exp.export_csv(data, out_path)
    elif fmt == "json":
        exp.export_json(data, out_path)
    else:
        console.print(f"[red]Unknown format '{fmt}'. Use: m3u, csv, json[/red]")
        raise SystemExit(1)

    console.print(f"[green]✓ Exported to {out_path}[/green]")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def cmd_uninstall(keep_data: bool = False) -> None:
    import shutil
    import subprocess
    import sys

    console.print("\n[bold red]Uninstall autoplaylist[/bold red]\n")

    from autoplaylist import config as cfg
    data_dir = cfg.base_dir()

    if not keep_data and data_dir.exists():
        count = len(list((data_dir / "playlists").glob("*.json"))) if (data_dir / "playlists").exists() else 0
        if count:
            print(f"This will delete {count} saved playlist(s) in {data_dir}")
        ans = _cooked_input("Remove all data? [y/N] ").strip().lower()
        if ans != "y":
            keep_data = True

    if not keep_data and data_dir.exists():
        shutil.rmtree(data_dir)
        console.print(f"[green]✓ Removed {data_dir}[/green]")
    else:
        console.print(f"[dim]Keeping data at {data_dir}[/dim]")

    console.print("[dim]Uninstalling Python package...[/dim]")
    subprocess.call([sys.executable, "-m", "pip", "uninstall", "autoplaylist", "-y", "-q"])
    console.print("[green]✓ autoplaylist uninstalled[/green]")
    console.print("\n[dim]Note: mpv was not removed (it may be used by other apps).[/dim]")
    console.print("[dim]To remove mpv: brew uninstall mpv[/dim]\n")


def _fmt_duration(seconds: int) -> str:
    if not seconds:
        return "—"
    m, s = divmod(seconds, 60)
    return f"{m}:{s:02d}"
