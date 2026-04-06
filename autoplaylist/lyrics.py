from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from typing import Optional

_TIMEOUT = 6


def fetch_lrc(artist: str, title: str) -> list[tuple[float, str]]:
    """
    Fetch time-synced lyrics from lrclib.net.
    artist/title should already be clean (LLM-recommended names).
    Falls back to title-only if artist+title returns nothing.
    Returns [(seconds, text), ...] or [].
    """
    attempts = []
    if artist and title:
        attempts.append((artist, title))
    if title:
        attempts.append(("", title))   # title-only fallback

    for a, t in attempts:
        try:
            params = urllib.parse.urlencode({"artist_name": a, "track_name": t})
            url = f"https://lrclib.net/api/get?{params}"
            req = urllib.request.Request(url, headers={"User-Agent": "myplaylist/1.0"})
            with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
                data = json.loads(resp.read().decode())
            synced = data.get("syncedLyrics") or ""
            if synced:
                return _parse_lrc(synced)
        except Exception:
            pass

    # Fallback: search API with title only (avoids artist charset mismatch)
    if title:
        try:
            params = urllib.parse.urlencode({"q": title})
            url = f"https://lrclib.net/api/search?{params}"
            req = urllib.request.Request(url, headers={"User-Agent": "myplaylist/1.0"})
            with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
                results = json.loads(resp.read().decode())
            for item in results:
                synced = item.get("syncedLyrics") or ""
                if synced:
                    return _parse_lrc(synced)
        except Exception:
            pass

    return []


def _parse_lrc(lrc: str) -> list[tuple[float, str]]:
    result: list[tuple[float, str]] = []
    pattern = re.compile(r"\[(\d+):(\d+(?:\.\d+)?)\](.*)")
    for line in lrc.splitlines():
        m = pattern.match(line.strip())
        if m:
            mins, secs, text = m.groups()
            t = int(mins) * 60 + float(secs)
            txt = text.strip()
            if txt:
                result.append((t, txt))
    return sorted(result, key=lambda x: x[0])


def current_line(lrc: list[tuple[float, str]], pos: float) -> Optional[str]:
    """Return the lyric line active at playback position `pos` seconds."""
    if not lrc:
        return None
    result: Optional[str] = None
    for t, line in lrc:
        if pos >= t:
            result = line
        else:
            break
    return result
