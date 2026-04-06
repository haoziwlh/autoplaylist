from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from autoplaylist import config as cfg
from autoplaylist.discovery import Track


def _playlist_path(name: str) -> Path:
    return cfg.playlists_dir() / f"{name}.json"


def _validate_name(name: str) -> str:
    """Validate and return a safe playlist name (kebab-case)."""
    if not re.match(r"^[a-z0-9][a-z0-9\-]{0,30}[a-z0-9]$", name) and not re.match(r"^[a-z0-9]$", name):
        raise ValueError(f"Invalid playlist name '{name}'. Use lowercase letters, numbers and hyphens.")
    return name


def slugify(text: str, max_len: int = 32) -> str:
    """Convert arbitrary text to a kebab-case slug."""
    text = text.lower()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    text = re.sub(r"-+", "-", text)
    text = text.strip("-")
    return text[:max_len].rstrip("-") or "playlist"


def save(name: str, tracks: list[Track], prompt_or_seed: str) -> Path:
    """Persist a playlist to disk. Returns the file path."""
    cfg.playlists_dir().mkdir(parents=True, exist_ok=True)
    path = _playlist_path(name)
    data = {
        "name": name,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "prompt": prompt_or_seed,
        "tracks": [
            {
                "title": t.title,
                "artist": t.artist,
                "youtube_url": t.youtube_url,
                "duration_seconds": t.duration_seconds,
                "source": t.source,
            }
            for t in tracks
        ],
    }
    with open(path, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    return path


def load(name: str) -> dict[str, Any]:
    """Load a playlist by name. Raises FileNotFoundError if not found."""
    path = _playlist_path(name)
    if not path.exists():
        available = [p.stem for p in cfg.playlists_dir().glob("*.json")]
        msg = f"Playlist '{name}' not found."
        if available:
            msg += f" Available: {', '.join(sorted(available))}"
        raise FileNotFoundError(msg)
    with open(path) as f:
        return json.load(f)


def list_all() -> list[dict[str, Any]]:
    """Return metadata for all saved playlists, sorted by creation date desc."""
    playlists = []
    for path in sorted(cfg.playlists_dir().glob("*.json")):
        try:
            with open(path) as f:
                data = json.load(f)
            playlists.append({
                "name": data.get("name", path.stem),
                "track_count": len(data.get("tracks", [])),
                "created_at": data.get("created_at", ""),
                "prompt": data.get("prompt", ""),
            })
        except Exception:
            continue
    return sorted(playlists, key=lambda x: x["created_at"], reverse=True)


def delete(name: str) -> None:
    """Delete a playlist file."""
    path = _playlist_path(name)
    if not path.exists():
        raise FileNotFoundError(f"Playlist '{name}' not found.")
    path.unlink()


def exists(name: str) -> bool:
    return _playlist_path(name).exists()


def tracks_from_data(data: dict[str, Any]) -> list[Track]:
    return [
        Track(
            title=t["title"],
            artist=t["artist"],
            youtube_url=t["youtube_url"],
            duration_seconds=t.get("duration_seconds", 0),
            source=t.get("source", "ytdlp"),
        )
        for t in data.get("tracks", [])
    ]
