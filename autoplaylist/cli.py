from __future__ import annotations

import warnings
warnings.filterwarnings("ignore")

import typer
from typing import Optional

_EPILOG = (
    "Run [bold]myplaylist COMMAND --help[/bold] to see all options for a command.\n\n"
    "[dim]Examples:[/dim]\n"
    "  myplaylist new \"rainy lo-fi jazz\"\n"
    "  myplaylist new --seed \"王菲 - 红豆\" --count 20\n"
    "  myplaylist new --seed \"https://youtube.com/watch?v=...\" --name my-mix\n"
    "  myplaylist play <name>\n"
    "  myplaylist export <name> --format m3u"
)

app = typer.Typer(
    name="myplaylist",
    help="Generate and play music playlists from prompts or seed songs.",
    rich_markup_mode="rich",
    epilog=_EPILOG,
)


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is None:
        from autoplaylist import _commands
        _commands.cmd_play(None)


@app.command()
def new(
    prompt: Optional[str] = typer.Argument(None, help="Natural language description, e.g. 'rainy lo-fi jazz'"),
    seed: Optional[str] = typer.Option(None, "--seed", "-s", help="Seed as 'Artist - Title' or YouTube URL"),
    count: int = typer.Option(20, "--count", "-n", min=1, max=50, help="Number of tracks  [default: 20, max: 50]"),
    name: Optional[str] = typer.Option(None, "--name", help="Playlist name (auto-generated if omitted)"),
) -> None:
    """Generate a new playlist from a prompt or seed song.

    \b
    Examples:
      myplaylist new "rainy lo-fi jazz"
      myplaylist new --seed "孙燕姿 - 遇见" --count 15
      myplaylist new --seed "https://youtube.com/..." --name weekend-mix
    """
    from autoplaylist.setup import ensure_setup
    from autoplaylist import _commands
    ensure_setup()
    _commands.cmd_new(prompt=prompt, seed=seed, count=count, name=name)


@app.command("list")
def list_playlists() -> None:
    """List all saved playlists."""
    from autoplaylist import _commands
    _commands.cmd_list()


@app.command()
def show(name: str = typer.Argument(..., help="Playlist name")) -> None:
    """Show the track listing of a saved playlist."""
    from autoplaylist import _commands
    _commands.cmd_show(name)


@app.command()
def play(
    name: Optional[str] = typer.Argument(None, help="Playlist name (default: most recent)"),
    debug: bool = typer.Option(False, "--debug", help="Log yt-dlp/mpv output to ~/.myplaylist/player.log"),
) -> None:
    """Play a saved playlist in the terminal.

    \b
    Controls during playback:
      p        pause / resume
      n        skip to next track
      ↑ ↓      move cursor
      ← →      previous / next page
      0-9      jump to track number + Enter
      Enter    play selected track
      [ ]      previous / next playlist
      q        quit
    """
    from autoplaylist import _commands
    _commands.cmd_play(name, debug=debug)


@app.command()
def export(
    name: str = typer.Argument(..., help="Playlist name"),
    format: str = typer.Option("m3u", "--format", "-f", help="Export format: m3u, csv, json  [default: m3u]"),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="Output file path (default: <name>.<format>)"),
) -> None:
    """Export a playlist to m3u, csv, or json."""
    from autoplaylist import _commands
    _commands.cmd_export(name, format=format, output=output)


@app.command()
def delete(name: str = typer.Argument(..., help="Playlist name")) -> None:
    """Delete a saved playlist."""
    from autoplaylist import _commands
    _commands.cmd_delete(name)


@app.command()
def config(
    lastfm_key: Optional[str] = typer.Option(None, "--lastfm-key", help="Set Last.fm API key"),
    lastfm_secret: Optional[str] = typer.Option(None, "--lastfm-secret", help="Set Last.fm API secret"),
    cookie_file: Optional[str] = typer.Option(None, "--cookie-file", help="Path to cookies.txt for yt-dlp (fixes YouTube bot check)"),
    cache_max_mb: Optional[int] = typer.Option(None, "--cache-max-mb", help="Max audio cache size in MB (default 500, 0 = disable)"),
    show: bool = typer.Option(False, "--show", help="Show current config"),
) -> None:
    """View or update configuration (Last.fm API key etc.)."""
    from autoplaylist import config as cfg
    from rich.console import Console
    c = Console()
    if lastfm_key:
        cfg.set_value("lastfm_key", lastfm_key)
        c.print(f"[green]✓ Last.fm API key saved[/green]")
    if lastfm_secret:
        cfg.set_value("lastfm_secret", lastfm_secret)
        c.print(f"[green]✓ Last.fm API secret saved[/green]")
    if cookie_file is not None:
        cfg.set_value("cookie_file", cookie_file or None)
        if cookie_file:
            c.print(f"[green]✓ Cookie file saved: {cookie_file}[/green]")
        else:
            c.print(f"[green]✓ Cookie file cleared[/green]")
    if cache_max_mb is not None:
        cfg.set_value("cache_max_mb", cache_max_mb)
        if cache_max_mb == 0:
            c.print("[green]✓ Audio cache disabled[/green]")
        else:
            c.print(f"[green]✓ Audio cache limit set to {cache_max_mb} MB[/green]")
    if show or not any([lastfm_key, lastfm_secret, cookie_file is not None, cache_max_mb is not None]):
        current = cfg.load()
        key = current.get("lastfm_key") or "(not set)"
        secret = current.get("lastfm_secret") or "(not set)"
        cookies = current.get("cookie_file") or "(not set)"
        c.print(f"lastfm_key:    {key}")
        c.print(f"lastfm_secret: {secret}")
        c.print(f"cookie_file:   {cookies}")
        c.print(f"cache_max_mb:  {current.get('cache_max_mb', 500)} MB")
        c.print(f"setup_complete: {current.get('setup_complete')}")


@app.command()
def cache(
    clear: bool = typer.Option(False, "--clear", help="Delete all cached audio and lyrics"),
    clear_audio: bool = typer.Option(False, "--clear-audio", help="Delete cached audio only"),
    clear_lyrics: bool = typer.Option(False, "--clear-lyrics", help="Delete cached lyrics only"),
) -> None:
    """Show or clear the local audio/lyrics cache (~/.myplaylist/cache/)."""
    from autoplaylist import cache as _cache
    from rich.console import Console
    c = Console()

    if clear or clear_audio:
        n = _cache.clear_audio()
        c.print(f"[green]✓ Deleted {n} cached audio file(s)[/green]")
    if clear or clear_lyrics:
        n = _cache.clear_lyrics()
        c.print(f"[green]✓ Deleted {n} cached lyrics file(s)[/green]")
    if not (clear or clear_audio or clear_lyrics):
        st = _cache.stats()
        mb = st["audio_bytes"] / (1024 * 1024)
        c.print(f"Audio:  {st['audio_files']} files  ({mb:.1f} MB)")
        c.print(f"Lyrics: {st['lyrics_files']} files")
        c.print(f"Path:   {_cache._CACHE_DIR}")


@app.command()
def setup() -> None:
    """Run (or re-run) first-time setup: choose LLM backend, configure Last.fm, install mpv."""
    from autoplaylist.setup import ensure_setup
    ensure_setup(force=True)


@app.command()
def uninstall(
    keep_data: bool = typer.Option(False, "--keep-data", help="Keep playlists and config"),
) -> None:
    """Uninstall myplaylist and remove all data."""
    from autoplaylist import _commands
    _commands.cmd_uninstall(keep_data=keep_data)


if __name__ == "__main__":
    app()
