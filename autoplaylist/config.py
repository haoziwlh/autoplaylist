from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

_BASE_DIR = Path.home() / ".myplaylist"
_CONFIG_FILE = _BASE_DIR / "config.json"
_PLAYLISTS_DIR = _BASE_DIR / "playlists"
_OLD_BASE_DIR = Path.home() / ".autoplaylist"


def _migrate_if_needed() -> None:
    """Move ~/.autoplaylist → ~/.myplaylist on first run after rename."""
    if _OLD_BASE_DIR.exists() and not _BASE_DIR.exists():
        import shutil
        shutil.move(str(_OLD_BASE_DIR), str(_BASE_DIR))

_DEFAULTS: dict[str, Any] = {
    "llm_backend": "claude",
    "gemini_api_key": None,
    "lastfm_key": None,
    "lastfm_secret": None,
    "setup_complete": False,
}


def base_dir() -> Path:
    return _BASE_DIR


def playlists_dir() -> Path:
    return _PLAYLISTS_DIR


def _ensure_dirs() -> None:
    _migrate_if_needed()
    _BASE_DIR.mkdir(parents=True, exist_ok=True)
    _PLAYLISTS_DIR.mkdir(parents=True, exist_ok=True)


def load() -> dict[str, Any]:
    _ensure_dirs()
    if not _CONFIG_FILE.exists():
        return dict(_DEFAULTS)
    with open(_CONFIG_FILE) as f:
        data = json.load(f)
    return {**_DEFAULTS, **data}


def save(config: dict[str, Any]) -> None:
    _ensure_dirs()
    with open(_CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)


def get(key: str, default: Any = None) -> Any:
    return load().get(key, default)


def set_value(key: str, value: Any) -> None:
    config = load()
    config[key] = value
    save(config)


def is_setup_complete() -> bool:
    return bool(get("setup_complete", False))


def get_lastfm_key() -> str | None:
    return get("lastfm_key")


def get_lastfm_secret() -> str | None:
    return get("lastfm_secret")
