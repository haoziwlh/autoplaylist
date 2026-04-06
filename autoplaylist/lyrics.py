from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from typing import Optional

_TIMEOUT = 6

# ---------------------------------------------------------------------------
# LRC parser (shared)
# ---------------------------------------------------------------------------

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


def _fingerprint(lrc: list[tuple[float, str]]) -> str:
    """Simple dedup key: first 3 lyric lines joined."""
    return " | ".join(t for _, t in lrc[:3])


# ---------------------------------------------------------------------------
# Source: lrclib.net
# ---------------------------------------------------------------------------

def _fetch_lrclib_candidates(artist: str, title: str) -> list[list[tuple[float, str]]]:
    """Return up to 3 synced-lyric candidates from lrclib.net."""
    results: list[list[tuple[float, str]]] = []

    # 1. Exact match (artist + title)
    if artist and title:
        try:
            params = urllib.parse.urlencode({"artist_name": artist, "track_name": title})
            req = urllib.request.Request(
                f"https://lrclib.net/api/get?{params}",
                headers={"User-Agent": "myplaylist/1.0"},
            )
            with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
                data = json.loads(resp.read().decode())
            synced = data.get("syncedLyrics") or ""
            if synced:
                parsed = _parse_lrc(synced)
                if parsed:
                    results.append(parsed)
        except Exception:
            pass

    # 2. Search API (returns multiple candidates)
    try:
        q = f"{artist} {title}".strip() if artist else title
        params = urllib.parse.urlencode({"q": q})
        req = urllib.request.Request(
            f"https://lrclib.net/api/search?{params}",
            headers={"User-Agent": "myplaylist/1.0"},
        )
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            items = json.loads(resp.read().decode())
        seen = {_fingerprint(r) for r in results}
        for item in items:
            if len(results) >= 3:
                break
            synced = item.get("syncedLyrics") or ""
            if not synced:
                continue
            parsed = _parse_lrc(synced)
            if not parsed:
                continue
            fp = _fingerprint(parsed)
            if fp not in seen:
                seen.add(fp)
                results.append(parsed)
    except Exception:
        pass

    return results


# ---------------------------------------------------------------------------
# Source: Netease Cloud Music
# ---------------------------------------------------------------------------

def fetch_netease(artist: str, title: str) -> list[tuple[float, str]]:
    """Fetch time-synced lyrics from Netease Cloud Music (no API key required)."""
    _HEADERS = {
        "Referer": "https://music.163.com",
        "User-Agent": "Mozilla/5.0",
    }
    try:
        # Search for song
        q = f"{artist} {title}".strip() if artist else title
        data = urllib.parse.urlencode({"s": q, "type": "1", "limit": "3"}).encode()
        req = urllib.request.Request(
            "https://music.163.com/api/search/get",
            data=data,
            headers=_HEADERS,
        )
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            result = json.loads(resp.read().decode())
        songs = result.get("result", {}).get("songs", [])
        if not songs:
            return []
        song_id = songs[0]["id"]

        # Fetch lyrics
        req2 = urllib.request.Request(
            f"https://music.163.com/api/song/lyric?id={song_id}&lv=1",
            headers=_HEADERS,
        )
        with urllib.request.urlopen(req2, timeout=_TIMEOUT) as resp2:
            ldata = json.loads(resp2.read().decode())
        lrc_str = ldata.get("lrc", {}).get("lyric", "")
        if not lrc_str:
            return []
        return _parse_lrc(lrc_str)
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def fetch_candidates(artist: str, title: str) -> list[list[tuple[float, str]]]:
    """
    Fetch all available lyric candidates for a track.

    Returns a list of candidates, each being a list of (seconds, text) tuples.
    lrclib results come first; Netease appended if not duplicate.
    Returns [] if no candidates found from any source.
    """
    candidates = _fetch_lrclib_candidates(artist, title)

    # Append Netease if it adds a unique result
    netease = fetch_netease(artist, title)
    if netease:
        seen = {_fingerprint(c) for c in candidates}
        if _fingerprint(netease) not in seen:
            candidates.append(netease)

    return candidates


def fetch_lrc(artist: str, title: str) -> list[tuple[float, str]]:
    """
    Fetch time-synced lyrics. Returns the best single candidate or [].
    Backwards-compatible wrapper around fetch_candidates().
    """
    candidates = fetch_candidates(artist, title)
    return candidates[0] if candidates else []


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
