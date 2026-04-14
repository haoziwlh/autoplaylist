from __future__ import annotations

import importlib
import os
import pathlib
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
# 2.3a  YouTube signature decryption prerequisites
# ---------------------------------------------------------------------------

_JS_RUNTIMES = ("deno", "node", "bun", "qjs")  # yt-dlp probes these by name
_EXTRA_PATHS = ("/opt/homebrew/bin", "/usr/local/bin", "/usr/bin")


def _detect_js_runtime() -> tuple[str, str] | None:
    """Return (runtime-name, path) for the first available JS runtime, else None."""
    for name in _JS_RUNTIMES:
        p = shutil.which(name)
        if p:
            return (name, p)
        for d in _EXTRA_PATHS:
            candidate = pathlib.Path(d) / name
            if candidate.exists():
                return (name, str(candidate))
    return None


def _detect_ytdlp_install_kind(ytdlp_path: str) -> str:
    """Classify yt-dlp install as 'pipx' | 'user-pip' | 'homebrew' | 'other'."""
    try:
        resolved = str(pathlib.Path(ytdlp_path).resolve())
    except Exception:
        resolved = ytdlp_path
    home = str(pathlib.Path.home())
    if "/pipx/venvs/" in resolved or resolved.startswith(f"{home}/.local/pipx/"):
        return "pipx"
    if "/Cellar/" in resolved or resolved.startswith("/opt/homebrew/") or \
            (resolved.startswith("/usr/local/") and "Cellar" in resolved):
        return "homebrew"
    if resolved.startswith(f"{home}/.local/bin/") or "/Library/Python/" in resolved:
        return "user-pip"
    return "other"


def _ytdlp_python(ytdlp_path: str) -> str | None:
    """Return the Python interpreter that runs this yt-dlp script (from shebang)."""
    try:
        with open(ytdlp_path, "r", encoding="utf-8", errors="ignore") as f:
            first = f.readline().strip()
    except Exception:
        return None
    if first.startswith("#!") and ("python" in first or "pypy" in first):
        return first[2:].strip()
    return None


def _has_ytdlp_ejs(ytdlp_path: str) -> bool:
    python = _ytdlp_python(ytdlp_path)
    if not python:
        return False
    try:
        r = subprocess.run(
            [python, "-c", "import yt_dlp_ejs"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=5,
        )
        return r.returncode == 0
    except Exception:
        return False


def _install_hint_missing_runtime() -> str:
    system = platform.system()
    if system == "Darwin":
        return "install one with: [cyan]brew install deno[/cyan]"
    if system == "Linux":
        return "install one with your package manager, e.g. [cyan]curl -fsSL https://deno.land/install.sh | sh[/cyan]"
    return "install deno from https://deno.land/"


def _ensure_ytdlp_ejs(ytdlp_path: str) -> str:
    """Try to install yt-dlp-ejs into the env that runs yt-dlp.

    Returns a short status string suitable for the summary line.
    """
    if _has_ytdlp_ejs(ytdlp_path):
        return "installed"

    kind = _detect_ytdlp_install_kind(ytdlp_path)

    if kind == "homebrew":
        return "managed by homebrew (remote fallback active)"

    if kind == "pipx":
        if not shutil.which("pipx"):
            return "inject skipped (pipx not on PATH; remote fallback active)"
        # Determine which pipx-managed package owns this yt-dlp.
        # If yt-dlp venv: `pipx inject yt-dlp yt-dlp-ejs`.
        # If myplaylist venv contains yt-dlp: inject into myplaylist.
        resolved = str(pathlib.Path(ytdlp_path).resolve())
        target = "yt-dlp"
        if "/venvs/myplaylist/" in resolved:
            target = "myplaylist"
        try:
            subprocess.check_call(
                ["pipx", "inject", target, "yt-dlp-ejs"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            return "installed"
        except Exception:
            return "inject failed (remote fallback active)"

    if kind == "user-pip":
        python = _ytdlp_python(ytdlp_path) or sys.executable
        try:
            subprocess.check_call(
                [python, "-m", "pip", "install", "--user", "--quiet", "yt-dlp-ejs"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            return "installed"
        except Exception:
            return "inject failed (remote fallback active)"

    # "other" — unknown install; don't risk polluting a system Python.
    return "install skipped (remote fallback active)"


def _setup_youtube_decrypt() -> None:
    """Detect JS runtime + try to install yt-dlp-ejs. Never raises."""
    from autoplaylist.player import _find_ytdlp

    console.print("\n[bold cyan]YouTube Signature Decryption[/bold cyan]")

    runtime = _detect_js_runtime()
    if runtime:
        name, path = runtime
        console.print(f"  js-runtime:   [green]{name}[/green] ({path}) ✓")
    else:
        console.print(
            f"  js-runtime:   [yellow]missing ⚠[/yellow] — {_install_hint_missing_runtime()}"
        )

    ytdlp_path = _find_ytdlp()
    status = _ensure_ytdlp_ejs(ytdlp_path)
    color = "green" if status == "installed" else "yellow"
    console.print(f"  yt-dlp-ejs:   [{color}]{status}[/{color}]")


# ---------------------------------------------------------------------------
# 2.3b  LLM backend wizard
# ---------------------------------------------------------------------------

def _detect_ollama() -> bool:
    """Return True if Ollama is reachable at localhost:11434."""
    import urllib.request
    try:
        urllib.request.urlopen("http://localhost:11434", timeout=1)
        return True
    except Exception:
        return False


def _prompt_api_key(backend_label: str, config_key: str = "llm_api_key") -> str | None:
    key = Prompt.ask(f"{backend_label} API key").strip()
    if not key:
        console.print("[yellow]No key entered. Falling back to Claude CLI.[/yellow]")
        return None
    cfg.set_value(config_key, key)
    return key


def _setup_llm() -> None:
    console.print("\n[bold cyan]LLM Backend Setup[/bold cyan]")
    console.print("myplaylist uses an LLM to generate song recommendations.")

    ollama_detected = _detect_ollama()
    ollama_tag = "[green](detected ✓)[/green]" if ollama_detected else "[dim](not running — install at ollama.com)[/dim]"

    console.print(
        "\nChoose a backend:\n"
        "  [bold][1][/bold] Claude       — uses your Claude Code subscription (recommended)\n"
        "  [bold][2][/bold] Gemini       — Google Gemini API key (free tier available)\n"
        "  [bold][3][/bold] Groq         — free tier, fast inference (llama3)\n"
        "  [bold][4][/bold] Qwen         — 通义千问, best for Chinese music (free credits)\n"
        "  [bold][5][/bold] DeepSeek     — free credits, strong reasoning\n"
        "  [bold][6][/bold] Kimi         — Moonshot AI, free credits\n"
        f"  [bold][7][/bold] Ollama       — local, no API key, offline {ollama_tag}\n"
        "  [bold][8][/bold] Custom       — any OpenAI-compatible endpoint\n"
    )

    choice = Prompt.ask("Choice", default="1").strip()

    if choice == "2":
        api_key = Prompt.ask("Gemini API key").strip()
        if not api_key:
            console.print("[yellow]No key entered. Falling back to Claude CLI.[/yellow]")
            cfg.set_value("llm_backend", "claude")
            return
        # keep gemini_api_key for backwards compat
        cfg.set_value("llm_backend", "gemini")
        cfg.set_value("gemini_api_key", api_key)
        console.print("[green]✓ Gemini configured (gemini-2.5-flash).[/green]")

    elif choice == "3":
        key = _prompt_api_key("Groq")
        if not key:
            cfg.set_value("llm_backend", "claude"); return
        cfg.set_value("llm_backend", "groq")
        console.print("[green]✓ Groq configured (llama-3.1-70b-versatile).[/green]")

    elif choice == "4":
        console.print("Get a free key at: https://dashscope.aliyun.com/")
        key = _prompt_api_key("Qwen / DashScope")
        if not key:
            cfg.set_value("llm_backend", "claude"); return
        cfg.set_value("llm_backend", "qwen")
        console.print("[green]✓ Qwen configured (qwen-turbo).[/green]")

    elif choice == "5":
        console.print("Get a free key at: https://platform.deepseek.com/")
        key = _prompt_api_key("DeepSeek")
        if not key:
            cfg.set_value("llm_backend", "claude"); return
        cfg.set_value("llm_backend", "deepseek")
        console.print("[green]✓ DeepSeek configured (deepseek-chat).[/green]")

    elif choice == "6":
        console.print("Get a free key at: https://platform.moonshot.cn/")
        key = _prompt_api_key("Kimi / Moonshot")
        if not key:
            cfg.set_value("llm_backend", "claude"); return
        cfg.set_value("llm_backend", "kimi")
        console.print("[green]✓ Kimi configured (moonshot-v1-8k).[/green]")

    elif choice == "7":
        if not ollama_detected:
            console.print(
                "[yellow]Ollama not detected. Install from https://ollama.com then run "
                "`ollama pull qwen2.5:7b` before using myplaylist.[/yellow]"
            )
        default_model = cfg.get("ollama_model", "qwen2.5:7b")
        model = Prompt.ask("Ollama model", default=default_model).strip() or default_model
        cfg.set_value("llm_backend", "ollama")
        cfg.set_value("ollama_model", model)
        console.print(f"[green]✓ Ollama configured (model: {model}).[/green]")

    elif choice == "8":
        endpoint = Prompt.ask("Endpoint URL (e.g. https://api.example.com/v1)").strip()
        model = Prompt.ask("Model name").strip()
        api_key = Prompt.ask("API key (press Enter if none)", default="").strip()
        if not endpoint or not model:
            console.print("[yellow]Endpoint or model missing. Falling back to Claude CLI.[/yellow]")
            cfg.set_value("llm_backend", "claude"); return
        cfg.set_value("llm_backend", "openai-compat")
        cfg.set_value("openai_compat_endpoint", endpoint)
        cfg.set_value("llm_model", model)
        if api_key:
            cfg.set_value("llm_api_key", api_key)
        console.print(f"[green]✓ Custom endpoint configured ({endpoint}).[/green]")

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

    existing_key = (cfg.get("lastfm_key") or "").strip()
    existing_secret = (cfg.get("lastfm_secret") or "").strip()

    def _mask(v: str) -> str:
        return f"(existing: {v[:4]}…{v[-2:]})" if len(v) >= 6 else "(existing set)"

    key_prompt = "Last.fm API key"
    if existing_key:
        key_prompt += f" {_mask(existing_key)}, press Enter to keep"
    key = Prompt.ask(key_prompt, default="").strip()

    if not key and not existing_key:
        cfg.set_value("lastfm_key", None)
        cfg.set_value("lastfm_secret", None)
        console.print(
            "[yellow]Skipped. Running in yt-dlp-only mode "
            "(similar-song quality will be lower).[/yellow]"
        )
        return

    secret_prompt = "Last.fm API secret (optional, press Enter to skip)"
    if existing_secret:
        secret_prompt = f"Last.fm API secret {_mask(existing_secret)}, press Enter to keep"
    secret = Prompt.ask(secret_prompt, default="").strip()

    if key:
        cfg.set_value("lastfm_key", key)
    if secret:
        cfg.set_value("lastfm_secret", secret)
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
    _setup_youtube_decrypt()
    _setup_lastfm()

    cfg.set_value("setup_complete", True)
    console.print("\n[bold green]Setup complete! You're ready to use myplaylist.[/bold green]\n")
