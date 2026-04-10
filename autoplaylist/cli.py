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
    detach: bool = typer.Option(False, "--detach", "-d", help="Start playback as a background daemon"),
) -> None:
    """Play a saved playlist in the terminal.

    \b
    Controls during playback:
      p        pause / resume
      n        skip to next track
      b        detach to background daemon
      ↑ ↓      move cursor
      ← →      previous / next page
      0-9      jump to track number + Enter
      Enter    play selected track
      [ ]      previous / next playlist
      q        quit
    """
    if detach:
        from autoplaylist import _commands
        _commands.cmd_play_detach(name, debug=debug)
    else:
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
    llm_backend: Optional[str] = typer.Option(None, "--llm-backend", help="LLM backend: claude|gemini|groq|qwen|deepseek|kimi|ollama|openai-compat"),
    llm_api_key: Optional[str] = typer.Option(None, "--llm-api-key", help="API key for groq/qwen/deepseek/kimi/openai-compat backends"),
    llm_model: Optional[str] = typer.Option(None, "--llm-model", help="Override default model for the selected backend"),
    ollama_model: Optional[str] = typer.Option(None, "--ollama-model", help="Ollama model name (default: qwen2.5:7b)"),
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
    if llm_backend is not None:
        cfg.set_value("llm_backend", llm_backend)
        c.print(f"[green]✓ LLM backend set to: {llm_backend}[/green]")
    if llm_api_key is not None:
        cfg.set_value("llm_api_key", llm_api_key)
        c.print("[green]✓ LLM API key saved[/green]")
    if llm_model is not None:
        cfg.set_value("llm_model", llm_model)
        c.print(f"[green]✓ LLM model override: {llm_model}[/green]")
    if ollama_model is not None:
        cfg.set_value("ollama_model", ollama_model)
        c.print(f"[green]✓ Ollama model set to: {ollama_model}[/green]")
    changed = any([lastfm_key, lastfm_secret, cookie_file is not None, cache_max_mb is not None,
                   llm_backend, llm_api_key, llm_model, ollama_model])
    if show or not changed:
        current = cfg.load()
        key = current.get("lastfm_key") or "(not set)"
        secret = current.get("lastfm_secret") or "(not set)"
        cookies = current.get("cookie_file") or "(not set)"
        backend = current.get("llm_backend", "claude")
        api_k = current.get("llm_api_key") or "(not set)"
        model_ov = current.get("llm_model") or "(default)"
        c.print(f"llm_backend:   {backend}")
        c.print(f"llm_api_key:   {api_k}")
        c.print(f"llm_model:     {model_ov}")
        if backend == "ollama":
            c.print(f"ollama_model:  {current.get('ollama_model', 'qwen2.5:7b')}")
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


@app.command()
def hotkeys(
    show: bool = typer.Option(False, "--show", help="Show current key bindings and skhd status"),
    remove: bool = typer.Option(False, "--remove", help="Remove hotkey config and stop skhd"),
) -> None:
    """Set up global keyboard shortcuts via skhd (macOS only).

    \b
    Default bindings:
      Ctrl+Alt+P   pause / resume
      Ctrl+Alt+N   next track
      Ctrl+Alt+Q   quit daemon
      Ctrl+Alt+R   cycle play mode
      Ctrl+Alt+A   open attach TUI
    """
    from autoplaylist import hotkeys as hk
    from rich.console import Console
    c = Console()

    if show:
        bindings = hk.get_bindings()
        running = hk.is_service_running()
        c.print(f"\n[bold]skhd service:[/bold] {'[green]running[/green]' if running else '[red]not running[/red]'}")
        c.print(f"[bold]Config:[/bold] {hk._SKHD_CONFIG}\n")
        for action, hotkey in bindings.items():
            label = hk._ACTION_COMMANDS.get(action, action)
            c.print(f"  [cyan]{hotkey:20s}[/cyan]  →  {label}")
        c.print()
        return

    if remove:
        has_others = hk.remove_bindings()
        if has_others:
            hk.restart_service()
            c.print("[green]✓ myplaylist hotkeys removed (skhd kept for other bindings)[/green]")
        else:
            hk.stop_service()
            c.print("[green]✓ myplaylist hotkeys removed, skhd service stopped[/green]")
        from autoplaylist import config as cfg
        cfg.set_value("hotkeys", None)
        return

    # Default action: install + configure + start
    hk.ensure_skhd()
    bindings = hk.get_bindings()
    hk.write_bindings(bindings)

    # Start or restart the service
    if hk.is_service_running():
        hk.restart_service()
    else:
        hk.start_service()

    c.print("[green]✓ Global hotkeys configured[/green]\n")
    for action, hotkey in bindings.items():
        label = hk._ACTION_COMMANDS.get(action, action)
        c.print(f"  [cyan]{hotkey:20s}[/cyan]  →  {label}")

    c.print(
        "\n[bold yellow]⚠  Accessibility permission required[/bold yellow]\n"
        "  skhd needs Accessibility access to capture global hotkeys.\n"
        "  Open: [bold]System Settings → Privacy & Security → Accessibility[/bold]\n"
        "  Add and enable [bold]skhd[/bold] in the list.\n"
    )
    # Offer to open System Settings directly
    try:
        import subprocess as _sp
        _sp.run(
            ["open", "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"],
            check=False, stdout=_sp.DEVNULL, stderr=_sp.DEVNULL,
        )
        c.print("  [dim](System Settings opened)[/dim]\n")
    except Exception:
        pass


@app.command()
def attach() -> None:
    """Attach a TUI to a running background player daemon.

    \b
    Keyboard controls work the same as normal play mode.
    Press q or b to detach (daemon keeps playing).
    """
    from autoplaylist.daemon import is_daemon_alive
    pid = is_daemon_alive()
    if pid is None:
        from rich.console import Console
        Console().print("[red]No player daemon is running[/red]")
        raise typer.Exit(code=1)
    from autoplaylist.player import attach_tui
    attach_tui()


# ---------------------------------------------------------------------------
# ctl — remote player control
# ---------------------------------------------------------------------------

ctl_app = typer.Typer(
    name="ctl",
    help="Send commands to a running player (next, pause, status, etc.).",
)
app.add_typer(ctl_app, name="ctl")


def _ctl_send(cmd: str, arg: str | None = None) -> dict:
    """Connect to the control socket, send a JSON-line command, return response."""
    import json
    import socket
    import getpass

    sock_path = f"/tmp/myplaylist-{getpass.getuser()}-ctl.sock"
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(3.0)
        s.connect(sock_path)
    except (FileNotFoundError, ConnectionRefusedError, OSError):
        from rich.console import Console
        Console().print("[red]No player is running[/red]")
        raise typer.Exit(code=1)
    req: dict = {"cmd": cmd}
    if arg is not None:
        req["arg"] = arg
    s.sendall(json.dumps(req).encode() + b"\n")
    data = b""
    while b"\n" not in data and len(data) < 4096:
        chunk = s.recv(1024)
        if not chunk:
            break
        data += chunk
    s.close()
    try:
        return json.loads(data.strip())
    except (json.JSONDecodeError, ValueError):
        return {"ok": False, "error": "bad response"}


@ctl_app.command("status")
def ctl_status() -> None:
    """Show current playback status."""
    resp = _ctl_send("status")
    if not resp.get("ok"):
        print(resp.get("error", "unknown error"))
        raise typer.Exit(code=1)
    st = resp["status"]
    state = "Paused" if st["paused"] else "Playing"
    label = f"{st['artist']} - {st['track']}" if st.get("artist") else st.get("track", "?")
    print(f"{state} [{st['idx'] + 1}/{st['total']}] {label} ({st['mode']})")


@ctl_app.command("next")
def ctl_next() -> None:
    """Skip to the next track."""
    resp = _ctl_send("next")
    if resp.get("ok"):
        print("Skipped to next track")
    else:
        print(resp.get("error", "failed"))


@ctl_app.command("pause")
def ctl_pause() -> None:
    """Toggle pause / resume."""
    resp = _ctl_send("pause")
    if resp.get("ok"):
        print("Paused" if resp.get("paused") else "Resumed")
    else:
        print(resp.get("error", "failed"))


@ctl_app.command("mode")
def ctl_mode(
    value: Optional[str] = typer.Argument(None, help="Set mode: seq, repeat, shuffle (omit to cycle)"),
) -> None:
    """Cycle or set play mode."""
    resp = _ctl_send("mode", value)
    if resp.get("ok"):
        print(f"Mode: {resp.get('mode')}")
    else:
        print(resp.get("error", "failed"))


@ctl_app.command("quit")
def ctl_quit() -> None:
    """Stop the player."""
    resp = _ctl_send("quit")
    if resp.get("ok"):
        print("Player stopped")
    else:
        print(resp.get("error", "failed"))


if __name__ == "__main__":
    app()
