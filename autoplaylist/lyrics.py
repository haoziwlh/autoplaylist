from __future__ import annotations

import base64
import json
import re
import threading
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
# Source: Kugou Music (酷狗)
# ---------------------------------------------------------------------------

def fetch_kugou(artist: str, title: str) -> list[tuple[float, str]]:
    """Fetch time-synced lyrics from Kugou Music (no API key required)."""
    _HEADERS = {"User-Agent": "Mozilla/5.0"}
    try:
        # 1. Search for song
        q = f"{artist} {title}".strip() if artist else title
        params = urllib.parse.urlencode(
            {"format": "json", "keyword": q, "page": "1", "pagesize": "5", "showtype": "1"}
        )
        req = urllib.request.Request(
            f"https://mobilecdn.kugou.com/api/v3/search/song?{params}",
            headers=_HEADERS,
        )
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            result = json.loads(resp.read().decode())
        songs = result.get("data", {}).get("info", [])
        if not songs:
            return []
        song = songs[0]
        hash_val = song.get("hash", "")
        album_audio_id = song.get("album_audio_id", 0)
        if not hash_val:
            return []

        # 2. Get lyrics candidates list
        params2 = urllib.parse.urlencode({
            "ver": "1", "man": "yes", "client": "mobi",
            "keyword": title, "duration": "", "hash": hash_val,
            "album_audio_id": album_audio_id,
        })
        req2 = urllib.request.Request(
            f"https://krcs.kugou.com/search?{params2}",
            headers=_HEADERS,
        )
        with urllib.request.urlopen(req2, timeout=_TIMEOUT) as resp2:
            ldata = json.loads(resp2.read().decode())
        candidates_list = ldata.get("candidates", [])
        if not candidates_list:
            return []
        cand = candidates_list[0]
        lrc_id = cand.get("id", "")
        access_key = cand.get("accesskey", "")
        if not lrc_id or not access_key:
            return []

        # 3. Download LRC (base64-encoded)
        params3 = urllib.parse.urlencode({
            "ver": "1", "client": "mobi",
            "id": lrc_id, "accesskey": access_key,
            "fmt": "lrc", "charset": "utf8",
        })
        req3 = urllib.request.Request(
            f"https://lyrics.kugou.com/download?{params3}",
            headers=_HEADERS,
        )
        with urllib.request.urlopen(req3, timeout=_TIMEOUT) as resp3:
            dl = json.loads(resp3.read().decode())
        encoded = dl.get("content", "")
        if not encoded:
            return []
        lrc_str = base64.b64decode(encoded).decode("utf-8", errors="ignore")
        return _parse_lrc(lrc_str)
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def fetch_candidates(artist: str, title: str) -> list[list[tuple[float, str]]]:
    """
    Fetch lyric candidates from all sources in parallel.

    Returns a list of unique candidates (lrclib, Netease, Kugou),
    deduplicated by fingerprint. Each candidate is [(seconds, text), ...].
    """
    results: dict[str, list[tuple[float, str]]] = {}
    lock = threading.Lock()

    def _fetch(key: str, fn, *args) -> None:
        try:
            val = fn(*args)
            if val:
                with lock:
                    results[key] = val
        except Exception:
            pass

    threads = [
        threading.Thread(target=_fetch, args=("lrclib", _fetch_lrclib_candidates, artist, title), daemon=True),
        threading.Thread(target=_fetch, args=("netease", fetch_netease, artist, title), daemon=True),
        threading.Thread(target=_fetch, args=("kugou",  fetch_kugou,   artist, title), daemon=True),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=_TIMEOUT + 1)

    # Merge: lrclib first (may return multiple), then netease, then kugou
    candidates: list[list[tuple[float, str]]] = []
    seen: set[str] = set()

    lrclib_result = results.get("lrclib")
    if isinstance(lrclib_result, list):
        if lrclib_result and isinstance(lrclib_result[0], list):
            for c in lrclib_result:
                fp = _fingerprint(c)
                if fp not in seen:
                    seen.add(fp)
                    candidates.append(c)
        elif lrclib_result:
            fp = _fingerprint(lrclib_result)
            if fp not in seen:
                seen.add(fp)
                candidates.append(lrclib_result)

    for key in ("netease", "kugou"):
        c = results.get(key)
        if c and isinstance(c, list) and c and isinstance(c[0], tuple):
            fp = _fingerprint(c)
            if fp not in seen:
                seen.add(fp)
                candidates.append(c)

    # Fallback: if few results and artist is set, retry lrclib with title only
    # (helps when artist name uses variant chars, e.g. 海來阿木 vs 海来阿木)
    if len(candidates) < 2 and artist and title:
        extra = _fetch_lrclib_candidates("", title)
        if isinstance(extra, list):
            for c in (extra if extra and isinstance(extra[0], list) else [extra] if extra else []):
                if c:
                    fp = _fingerprint(c)
                    if fp not in seen:
                        seen.add(fp)
                        candidates.append(c)

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
