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
def play(name: Optional[str] = typer.Argument(None, help="Playlist name (default: most recent)")) -> None:
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
    _commands.cmd_play(name)


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
    if show or (not lastfm_key and not lastfm_secret):
        current = cfg.load()
        key = current.get("lastfm_key") or "(not set)"
        secret = current.get("lastfm_secret") or "(not set)"
        c.print(f"lastfm_key:    {key}")
        c.print(f"lastfm_secret: {secret}")
        c.print(f"setup_complete: {current.get('setup_complete')}")


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
