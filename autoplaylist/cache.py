from __future__ import annotations

import hashlib
import json
import os
import threading
from pathlib import Path
from typing import Any

_CACHE_DIR  = Path.home() / ".myplaylist" / "cache"
_AUDIO_DIR  = _CACHE_DIR / "audio"
_LYRICS_DIR = _CACHE_DIR / "lyrics"

_MIN_AUDIO_BYTES = 10_000   # files smaller than 10 KB are considered incomplete
_EVICT_LOCK = threading.Lock()


def _ensure_dirs() -> None:
    _AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    _LYRICS_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Audio cache
# ---------------------------------------------------------------------------

def audio_path(video_id: str) -> Path:
    return _AUDIO_DIR / video_id


def tmp_audio_path(video_id: str) -> Path:
    return _AUDIO_DIR / f"{video_id}.tmp"


def get_cached_audio(video_id: str) -> Path | None:
    """Return path to valid cached audio, or None."""
    p = audio_path(video_id)
    try:
        if p.exists() and p.stat().st_size >= _MIN_AUDIO_BYTES:
            return p
    except OSError:
        pass
    return None


def touch_audio(video_id: str) -> None:
    """Update atime so LRU eviction knows this file was recently used."""
    p = audio_path(video_id)
    try:
        os.utime(p, None)
    except OSError:
        pass


def evict_audio_if_needed() -> None:
    """Delete least-recently-used audio files until total size < cache_max_mb."""
    from autoplaylist import config as cfg
    max_bytes = int(cfg.get("cache_max_mb", 500)) * 1024 * 1024

    with _EVICT_LOCK:
        try:
            files = [
                (f, f.stat())
                for f in _AUDIO_DIR.iterdir()
                if f.suffix != ".tmp" and f.is_file()
            ]
        except (FileNotFoundError, OSError):
            return

        total = sum(st.st_size for _, st in files)
        if total <= max_bytes:
            return

        # Oldest atime first
        files.sort(key=lambda x: x[1].st_atime)
        for f, st in files:
            if total <= max_bytes:
                break
            try:
                f.unlink()
                total -= st.st_size
            except OSError:
                pass


# ---------------------------------------------------------------------------
# Lyrics cache
# ---------------------------------------------------------------------------

def _lyrics_key(artist: str, title: str) -> str:
    raw = f"{artist.lower().strip()}|{title.lower().strip()}"
    return hashlib.sha256(raw.encode()).hexdigest()[:20]


def get_lyrics(artist: str, title: str) -> list | None:
    """Return cached lyric candidates [[( seconds, text ), ...], ...] or None."""
    p = _LYRICS_DIR / f"{_lyrics_key(artist, title)}.json"
    try:
        if not p.exists():
            return None
        data = json.loads(p.read_text(encoding="utf-8"))
        # Stored as list of lists of [seconds, text]; convert to tuples
        return [[(float(item[0]), item[1]) for item in cand] for cand in data]
    except Exception:
        return None


def save_lyrics(artist: str, title: str, candidates: list) -> None:
    """Persist lyric candidates to disk. Pass empty list to delete cached entry."""
    p = _LYRICS_DIR / f"{_lyrics_key(artist, title)}.json"
    if not candidates:
        p.unlink(missing_ok=True)
        return
    _ensure_dirs()
    try:
        p.write_text(json.dumps(candidates), encoding="utf-8")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Cache stats (for `myplaylist cache` command)
# ---------------------------------------------------------------------------

def stats() -> dict[str, Any]:
    result: dict[str, Any] = {"audio_files": 0, "audio_bytes": 0, "lyrics_files": 0}
    try:
        for f in _AUDIO_DIR.iterdir():
            if f.suffix != ".tmp" and f.is_file():
                result["audio_files"] += 1
                result["audio_bytes"] += f.stat().st_size
    except (FileNotFoundError, OSError):
        pass
    try:
        result["lyrics_files"] = sum(
            1 for f in _LYRICS_DIR.iterdir() if f.suffix == ".json"
        )
    except (FileNotFoundError, OSError):
        pass
    return result


def clear_audio() -> int:
    """Delete all cached audio files. Returns number deleted."""
    deleted = 0
    try:
        for f in _AUDIO_DIR.iterdir():
            if f.is_file():
                f.unlink()
                deleted += 1
    except (FileNotFoundError, OSError):
        pass
    return deleted


def clear_lyrics() -> int:
    """Delete all cached lyrics files. Returns number deleted."""
    deleted = 0
    try:
        for f in _LYRICS_DIR.iterdir():
            if f.suffix == ".json" and f.is_file():
                f.unlink()
                deleted += 1
    except (FileNotFoundError, OSError):
        pass
    return deleted
