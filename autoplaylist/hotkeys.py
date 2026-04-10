"""Global hotkey management via skhd (macOS only).

Installs skhd, generates config with default/custom key bindings,
manages the skhd service lifecycle.
"""
from __future__ import annotations

import os
import pathlib
import platform
import shutil
import subprocess
import sys

from autoplaylist import config as cfg

_SKHD_CONFIG = pathlib.Path.home() / ".config" / "skhd" / "skhdrc"
_MARKER_BEGIN = "# --- BEGIN myplaylist ---"
_MARKER_END = "# --- END myplaylist ---"

_DEFAULT_BINDINGS: dict[str, str] = {
    "pause": "ctrl + alt - p",
    "next": "ctrl + alt - n",
    "quit": "ctrl + alt - q",
    "mode": "ctrl + alt - r",
    "attach": "ctrl + alt - a",
}

# Maps action names to the shell command skhd should execute.
_ACTION_COMMANDS: dict[str, str] = {
    "pause": "myplaylist ctl pause",
    "next": "myplaylist ctl next",
    "quit": "myplaylist ctl quit",
    "mode": "myplaylist ctl mode",
    "attach": 'osascript -e \'tell app "Terminal" to do script "myplaylist attach"\'',
}


def ensure_skhd() -> None:
    """Install skhd via Homebrew if not already present.

    Raises SystemExit on non-macOS or if Homebrew is unavailable.
    """
    if platform.system() != "Darwin":
        print("Global hotkeys are currently macOS-only.")
        raise SystemExit(1)

    if shutil.which("skhd"):
        return

    if not shutil.which("brew"):
        print("Homebrew not found. Install it from https://brew.sh/ then retry.")
        raise SystemExit(1)

    print("Installing skhd...")
    env = {**os.environ, "HOMEBREW_NO_AUTO_UPDATE": "1", "HOMEBREW_NO_ENV_HINTS": "1"}
    subprocess.check_call(
        ["brew", "install", "koekeishiya/formulae/skhd"],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    print("✓ skhd installed")


def _myplaylist_bin() -> str:
    """Resolve the absolute path to the myplaylist executable.

    Prefers the binary next to the current Python interpreter (pipx/venv),
    falls back to shutil.which, then bare 'myplaylist'.
    """
    # Check sibling of current python (e.g. ~/.local/pipx/venvs/myplaylist/bin/)
    bin_dir = pathlib.Path(sys.executable).parent
    candidate = bin_dir / "myplaylist"
    if candidate.is_file():
        return str(candidate)
    # Fall back to PATH lookup
    found = shutil.which("myplaylist")
    if found:
        return found
    return "myplaylist"


# ---------------------------------------------------------------------------
# skhdrc read / write
# ---------------------------------------------------------------------------

def _read_skhdrc() -> str:
    """Read the skhd config file. Returns empty string if missing."""
    try:
        return _SKHD_CONFIG.read_text()
    except FileNotFoundError:
        return ""


def _write_skhdrc(content: str) -> None:
    """Write the skhd config file, creating parent dirs as needed."""
    _SKHD_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    _SKHD_CONFIG.write_text(content)


# ---------------------------------------------------------------------------
# Binding block management
# ---------------------------------------------------------------------------

def _build_block(bindings: dict[str, str]) -> str:
    """Generate the marker-delimited skhd config block from bindings."""
    mp = _myplaylist_bin()
    lines = [_MARKER_BEGIN]
    for action, hotkey in bindings.items():
        if action not in _ACTION_COMMANDS:
            continue
        cmd = _ACTION_COMMANDS[action].replace("myplaylist", mp)
        lines.append(f"{hotkey} : {cmd}")
    lines.append(_MARKER_END)
    return "\n".join(lines)


def write_bindings(bindings: dict[str, str]) -> None:
    """Write the myplaylist binding block to skhdrc.

    Replaces an existing marker block if present, otherwise appends.
    """
    content = _read_skhdrc()
    block = _build_block(bindings)

    if _MARKER_BEGIN in content:
        # Replace existing block
        before = content[:content.index(_MARKER_BEGIN)]
        after_marker = content[content.index(_MARKER_END) + len(_MARKER_END):]
        new_content = before.rstrip("\n") + "\n" + block + after_marker
    else:
        # Append
        if content and not content.endswith("\n"):
            content += "\n"
        new_content = content + "\n" + block + "\n" if content else block + "\n"

    _write_skhdrc(new_content)


def remove_bindings() -> bool:
    """Remove the myplaylist marker block from skhdrc.

    Returns True if other (non-myplaylist) bindings remain in the file.
    """
    content = _read_skhdrc()
    if _MARKER_BEGIN not in content:
        return False

    before = content[:content.index(_MARKER_BEGIN)]
    after = content[content.index(_MARKER_END) + len(_MARKER_END):]
    remaining = (before + after).strip()

    if remaining:
        _write_skhdrc(remaining + "\n")
        return True
    else:
        try:
            _SKHD_CONFIG.unlink()
        except FileNotFoundError:
            pass
        return False


# ---------------------------------------------------------------------------
# skhd service lifecycle
# ---------------------------------------------------------------------------

def start_service() -> None:
    subprocess.run(["skhd", "--start-service"], check=False,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def restart_service() -> None:
    subprocess.run(["skhd", "--restart-service"], check=False,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def stop_service() -> None:
    subprocess.run(["skhd", "--stop-service"], check=False,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def is_service_running() -> bool:
    """Check if skhd service is loaded in launchd."""
    r = subprocess.run(
        ["launchctl", "list"],
        capture_output=True, text=True,
    )
    return "skhd" in r.stdout


# ---------------------------------------------------------------------------
# Config persistence (custom bindings in ~/.myplaylist/config.json)
# ---------------------------------------------------------------------------

def get_bindings() -> dict[str, str]:
    """Return current bindings: custom from config.json, falling back to defaults."""
    custom = cfg.get("hotkeys")
    if isinstance(custom, dict) and custom:
        merged = dict(_DEFAULT_BINDINGS)
        merged.update(custom)
        return merged
    return dict(_DEFAULT_BINDINGS)


def save_bindings(bindings: dict[str, str]) -> None:
    """Persist custom bindings to ~/.myplaylist/config.json."""
    cfg.set_value("hotkeys", bindings)
