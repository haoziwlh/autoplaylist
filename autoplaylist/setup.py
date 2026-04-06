from __future__ import annotations

import importlib
import os
import platform
import shutil
import subprocess
import sys

from rich.console import Console
from rich.prompt import Prompt

from autoplaylist import config as cfg

console = Console()

_PYTHON_PACKAGES = ["yt_dlp", "pylast", "rich", "typer"]
_PACKAGE_INSTALL_NAMES = {
    "yt_dlp": "yt-dlp",
    "pylast": "pylast",
    "rich": "rich",
    "typer": "typer",
}


# ---------------------------------------------------------------------------
# 2.2  Python package installation
# ---------------------------------------------------------------------------

def _ensure_python_packages() -> None:
    for module in _PYTHON_PACKAGES:
        try:
            importlib.import_module(module)
        except ImportError:
            install_name = _PACKAGE_INSTALL_NAMES[module]
            console.print(f"[yellow]Installing {install_name}...[/yellow]")
            subprocess.check_call(
                [sys.executable, "-m", "pip", "install", "--quiet", install_name]
            )
            console.print(f"[green]✓ {install_name} installed[/green]")


# ---------------------------------------------------------------------------
# 2.3  mpv installation
# ---------------------------------------------------------------------------

def _ensure_mpv() -> None:
    if shutil.which("mpv"):
        return

    system = platform.system()
    console.print("[yellow]mpv not found — installing...[/yellow]")

    if system == "Darwin":
        if not shutil.which("brew"):
            console.print(
                "[red]Homebrew not found. Please install mpv manually: https://mpv.io/installation/[/red]"
            )
            raise SystemExit(1)
        env = {**os.environ, "HOMEBREW_NO_AUTO_UPDATE": "1", "HOMEBREW_NO_ENV_HINTS": "1"}
        subprocess.check_call(
            ["brew", "install", "mpv"],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    elif system == "Linux":
        try:
            subprocess.check_call(["sudo", "apt-get", "install", "-y", "mpv"])
        except FileNotFoundError:
            console.print(
                "[red]apt-get not found. Please install mpv manually: https://mpv.io/installation/[/red]"
            )
            raise SystemExit(1)
    else:
        console.print(
            f"[red]Unsupported platform '{system}'. Please install mpv manually: https://mpv.io/installation/[/red]"
        )
        raise SystemExit(1)

    console.print("[green]✓ mpv installed[/green]")


# ---------------------------------------------------------------------------
# 2.3b  LLM backend wizard
# ---------------------------------------------------------------------------



def _setup_llm() -> None:
    console.print("\n[bold cyan]LLM Backend Setup[/bold cyan]")
    console.print(
        "myplaylist uses an LLM to generate song recommendations.\n"
        "Choose a backend:\n"
        "  [bold][1][/bold] Claude CLI  — uses your Claude Code subscription\n"
        "  [bold][2][/bold] Gemini API  — Google Gemini API key (free tier available)\n"
    )

    choice = Prompt.ask("Choice", default="1").strip()

    if choice == "2":
        # Step 1: collect key
        api_key = Prompt.ask("Gemini API key").strip()
        if not api_key:
            console.print("[yellow]No key entered. Falling back to Claude CLI.[/yellow]")
            cfg.set_value("llm_backend", "claude")
            return

        # Step 2: install SDK if needed
        try:
            import google.generativeai  # type: ignore  # noqa: F401
        except ImportError:
            console.print("[yellow]Installing google-generativeai...[/yellow]")
            try:
                subprocess.check_call(
                    [sys.executable, "-m", "pip", "install", "--quiet", "google-generativeai"]
                )
                console.print("[green]✓ google-generativeai installed[/green]")
            except subprocess.CalledProcessError:
                console.print(
                    "[red]Failed to install google-generativeai. "
                    "Check your network, or run: pip install google-generativeai[/red]"
                )
                console.print("[yellow]Falling back to Claude CLI.[/yellow]")
                cfg.set_value("llm_backend", "claude")
                return

        # Step 3: save key directly (validated on first actual use)
        cfg.set_value("llm_backend", "gemini")
        cfg.set_value("gemini_api_key", api_key)
        console.print("[green]✓ Gemini API key saved. Using gemini-2.5-flash.[/green]")
    else:
        cfg.set_value("llm_backend", "claude")
        console.print("[green]✓ Using Claude CLI.[/green]")


# ---------------------------------------------------------------------------
# 2.4  Last.fm API key wizard
# ---------------------------------------------------------------------------

def _setup_lastfm() -> None:
    console.print("\n[bold cyan]Last.fm API Setup[/bold cyan]")
    console.print(
        "myplaylist uses Last.fm to find similar songs.\n"
        "Get a free API key at: [link]https://www.last.fm/api/account/create[/link]\n"
        "(Press Enter to skip and use yt-dlp-only mode)\n"
    )

    key = Prompt.ask("Last.fm API key", default="").strip()
    if not key:
        cfg.set_value("lastfm_key", None)
        cfg.set_value("lastfm_secret", None)
        console.print(
            "[yellow]Skipped. Running in yt-dlp-only mode "
            "(similar-song quality will be lower).[/yellow]"
        )
        return

    secret = Prompt.ask("Last.fm API secret (optional, press Enter to skip)", default="").strip()

    cfg.set_value("lastfm_key", key)
    cfg.set_value("lastfm_secret", secret or None)
    console.print("[green]✓ Last.fm API key saved[/green]")


# ---------------------------------------------------------------------------
# 2.5  Entry point: ensure_setup
# ---------------------------------------------------------------------------

def ensure_setup(force: bool = False) -> None:
    """Run first-time setup if not already done. Safe to call on every invocation.

    Pass force=True to re-run even if setup was previously completed (e.g. from
    the explicit `myplaylist setup` command).
    """
    if cfg.is_setup_complete() and not force:
        return

    console.print("\n[bold]myplaylist — first-run setup[/bold]\n")

    _setup_llm()
    _ensure_python_packages()
    _ensure_mpv()
    _setup_lastfm()

    cfg.set_value("setup_complete", True)
    console.print("\n[bold green]Setup complete! You're ready to use myplaylist.[/bold green]\n")
