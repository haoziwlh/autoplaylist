from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Any

from rich.console import Console

from autoplaylist import config as cfg
from autoplaylist import llm

console = Console()


# ---------------------------------------------------------------------------
# 5.1  Track dataclass (defined here, imported by playlist.py)
# ---------------------------------------------------------------------------

@dataclass
class Track:
    title: str
    artist: str
    youtube_url: str
    duration_seconds: int = 0
    source: str = "ytdlp"

    def norm_key(self) -> tuple[str, str]:
        """Normalised (artist, title) for deduplication."""
        def norm(s: str) -> str:
            s = s.lower()
            s = re.sub(r"[^\w\s]", "", s)
            return s.strip()
        return (norm(self.artist), norm(self.title))


# ---------------------------------------------------------------------------
# 4.1  yt-dlp search
# ---------------------------------------------------------------------------

def search_ytdlp(query: str, count: int = 10) -> list[Track]:
    """Search YouTube via yt-dlp ytsearch syntax."""
    try:
        import yt_dlp
    except ImportError:
        console.print("[red]yt-dlp not available[/red]")
        return []

    class _SilentLogger:
        def debug(self, msg: str) -> None: pass
        def info(self, msg: str) -> None: pass
        def warning(self, msg: str) -> None: pass
        def error(self, msg: str) -> None: pass

    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": True,
        "skip_download": True,
        "logger": _SilentLogger(),
    }

    search_url = f"ytsearch{count}:{query}"
    tracks: list[Track] = []

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(search_url, download=False)
            entries = info.get("entries", []) if info else []
            for entry in entries:
                if not entry:
                    continue
                video_id = entry.get("id", "")
                if not video_id:
                    continue
                title = entry.get("title", "Unknown")
                uploader = entry.get("uploader", "Unknown")
                artist, track_title = _split_title(title, uploader)
                duration = int(entry.get("duration") or 0)
                tracks.append(Track(
                    title=track_title,
                    artist=artist,
                    youtube_url=f"https://www.youtube.com/watch?v={video_id}",
                    duration_seconds=duration,
                    source="ytdlp",
                ))
    except Exception as e:
        console.print(f"[yellow]yt-dlp search error: {e}[/yellow]")

    return tracks


_YT_NOISE = re.compile(
    r'\s*[【\[（(『「【]\s*[^\]】）)』」【]*[】\]）)』」]\s*$'  # trailing 【...】 / [...]
    r'|\s*[|｜].*$'                                              # trailing | anything
    r'|\s*(official\s*(video|audio|mv|lyric|lyrics)?'
    r'|lyrics?\s*(video)?|動態歌詞|歌詞|MV|mv)\s*$',
    re.IGNORECASE,
)


def _clean_yt_title(s: str) -> str:
    """Strip common YouTube noise suffixes from a title/artist string."""
    prev = None
    while prev != s:
        prev = s
        s = _YT_NOISE.sub("", s).strip()
    return s


def _split_title(title: str, uploader: str) -> tuple[str, str]:
    """Try to split 'Artist - Title' from a YouTube video title."""
    if " - " in title:
        parts = title.split(" - ", 1)
        return _clean_yt_title(parts[0]), _clean_yt_title(parts[1])
    # CJK dash variants
    for sep in [" – ", " — "]:
        if sep in title:
            parts = title.split(sep, 1)
            return _clean_yt_title(parts[0]), _clean_yt_title(parts[1])
    # Fall back: uploader as artist, clean up the video title
    return uploader, _clean_yt_title(title)


def _is_garbage(t: Track) -> bool:
    """Return True if a track looks like a garbage/unusable search result."""
    title = t.title.strip()
    # Too short
    if len(title) < 2:
        return True
    # File extension only
    if re.match(r"^\.\w{1,5}$", title):
        return True
    # Only hashtags / spaces / punctuation
    if not re.search(r"[\w\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7a3]", title):
        return True
    # Spam hashtag titles like "# # # # # #"
    if re.match(r"^(#\s*){3,}$", title):
        return True
    return False


# ---------------------------------------------------------------------------
# 4.2  Last.fm: similar tracks
# ---------------------------------------------------------------------------

def search_lastfm_similar(artist: str, title: str, count: int = 10) -> list[Track]:
    key = cfg.get_lastfm_key()
    if not key:
        return []
    try:
        import pylast
        network = pylast.LastFMNetwork(api_key=key)
        track = network.get_track(artist, title)
        similar = track.get_similar(limit=count)
        tracks: list[Track] = []
        for item in similar:
            t = item.item
            tracks.append(Track(
                title=t.title,
                artist=t.artist.name,
                youtube_url="",
                duration_seconds=0,
                source="lastfm",
            ))
        return tracks
    except Exception as e:
        console.print(f"[yellow]Last.fm similar error: {e}[/yellow]")
        return []


# ---------------------------------------------------------------------------
# 4.3  Last.fm: keyword track search
# ---------------------------------------------------------------------------

def search_lastfm_tracks(keywords: str, count: int = 10) -> list[Track]:
    key = cfg.get_lastfm_key()
    if not key:
        return []
    try:
        import pylast
        network = pylast.LastFMNetwork(api_key=key)
        results = network.search_for_track("", keywords).get_next_page()
        tracks: list[Track] = []
        for t in results[:count]:
            tracks.append(Track(
                title=t.title,
                artist=t.artist.name,
                youtube_url="",
                duration_seconds=0,
                source="lastfm",
            ))
        return tracks
    except Exception as e:
        console.print(f"[yellow]Last.fm search error: {e}[/yellow]")
        return []


# ---------------------------------------------------------------------------
# 4.4  Deduplication
# ---------------------------------------------------------------------------

def deduplicate(tracks: list[Track]) -> list[Track]:
    seen: set[tuple[str, str]] = set()
    result: list[Track] = []
    for t in tracks:
        key = t.norm_key()
        if key not in seen:
            seen.add(key)
            result.append(t)
    return result


# ---------------------------------------------------------------------------
# 4.5  Resolve YouTube URL for a Last.fm track
# ---------------------------------------------------------------------------

def resolve_youtube_url(artist: str, title: str) -> str | None:
    query = f"{artist} {title} official audio"
    results = search_ytdlp(query, count=1)
    if results:
        return results[0].youtube_url
    return None


def _resolve_lastfm_tracks(tracks: list[Track], count: int) -> list[Track]:
    """Resolve YouTube URLs for Last.fm tracks, discarding failures."""
    resolved: list[Track] = []
    for t in tracks:
        if len(resolved) >= count:
            break
        if t.youtube_url:
            resolved.append(t)
            continue
        url = resolve_youtube_url(t.artist, t.title)
        if url:
            t.youtube_url = url
            resolved.append(t)
    return resolved


# ---------------------------------------------------------------------------
# 4.6  discover_from_prompt
# ---------------------------------------------------------------------------

def discover_from_prompt(prompt: str, count: int = 10) -> list[Track]:
    import sys as _sys

    _backend = cfg.get("llm_backend", "claude").capitalize()
    _sys.stdout.write(f"\r\nAsking {_backend} for recommendations...\r\n")
    _sys.stdout.flush()

    parsed = llm.parse_prompt(prompt)
    recommendations = llm.get_song_recommendations(parsed)

    if not recommendations:
        # LLM failed — fall back to raw YouTube search
        _sys.stdout.write("LLM unavailable, falling back to direct search...\r\n")
        _sys.stdout.flush()
        tracks = search_ytdlp(prompt, count=count + 5)
        clean = [t for t in tracks if not _is_garbage(t)]
        if not clean:
            print("No tracks found.")
            raise SystemExit(1)
        return clean[:count]

    _sys.stdout.write(f"Got {len(recommendations)} recommendations, searching YouTube...\r\n")
    _sys.stdout.flush()

    all_tracks: list[Track] = []
    for i, song_query in enumerate(recommendations):
        _sys.stdout.write(f"\r  [{i+1}/{len(recommendations)}] {song_query:<55}")
        _sys.stdout.flush()
        results = search_ytdlp(song_query, count=2)
        good = [t for t in results if not _is_garbage(t)]
        if good:
            t = good[0]
            # Override with clean LLM-recommended artist/title
            if " - " in song_query:
                parts = song_query.split(" - ", 1)
                t.artist = parts[0].strip()
                t.title = parts[1].strip()
            all_tracks.append(t)
        if len(all_tracks) >= count:
            break

    _sys.stdout.write("\r\n")
    _sys.stdout.flush()

    candidates = deduplicate(all_tracks)
    if not candidates:
        print("No tracks found. Try a different prompt.")
        raise SystemExit(1)
    return candidates[:count]


# ---------------------------------------------------------------------------
# 4.7  discover_from_seed
# ---------------------------------------------------------------------------

def _seed_words(seed_str: str, artist: str, title: str) -> set[str]:
    """Return lowercase words from the seed to use as a blacklist filter."""
    words: set[str] = set()
    for part in [seed_str, artist, title]:
        for w in part.lower().split():
            if len(w) >= 2:
                words.add(w)
    return words


def _not_seed(t: Track, blacklist: set[str]) -> bool:
    """Return True if the track does NOT look like a cover/version of the seed."""
    label = (t.title + " " + t.artist).lower()
    # If ALL seed words appear in the label, it's likely the same song
    if blacklist and all(w in label for w in blacklist):
        return False
    return True


def _fetch_seed_track(seed_str: str, artist: str, title: str, seed_url: str) -> "Track | None":
    """Search YouTube for the seed song itself to use as track #1."""
    query = seed_url if seed_url else (f"{artist} - {title}" if (artist and title) else seed_str)
    results = search_ytdlp(query, count=3)
    if not results:
        return None
    t = results[0]
    if title:
        t.title = title
    if artist:
        t.artist = artist
    return t


def discover_from_seed(seed_str: str, count: int = 10, allow_yt_fallback: bool = True,
                       quiet: bool = False) -> list[Track]:
    import sys as _sys

    def _print(msg: str) -> None:
        if not quiet:
            _sys.stdout.write(msg)
            _sys.stdout.flush()

    artist, title, seed_url = _parse_seed(seed_str)
    seed_blacklist = _seed_words(seed_str, artist, title)

    # Fetch seed track to prepend as track #1
    seed_track = _fetch_seed_track(seed_str, artist, title, seed_url)

    # Try Last.fm first
    lfm_similar: list[Track] = []
    if artist and title:
        _print("\r\nSearching Last.fm for similar tracks...\r\n")
        lfm_similar = search_lastfm_similar(artist, title, count=count)

    if lfm_similar:
        candidates = _resolve_lastfm_tracks(lfm_similar, count)
        candidates = [t for t in candidates if not _is_garbage(t) and _not_seed(t, seed_blacklist)]
        if candidates:
            result = candidates[:count - 1] if seed_track else candidates[:count]
            return ([seed_track] + result) if seed_track else result

    # Last.fm unavailable or empty — ask LLM for song recommendations
    seed_label = f"{artist} - {title}" if (artist and title) else seed_str
    _backend = cfg.get("llm_backend", "claude").capitalize()
    _print(f"\r\nAsking {_backend} for songs similar to '{seed_label}'...\r\n")

    parsed = llm.parse_prompt(seed_label)
    recommendations = llm.get_song_recommendations(parsed)

    if recommendations:
        _print(f"Got {len(recommendations)} recommendations, searching YouTube...\r\n")
        all_tracks: list[Track] = []
        want = (count - 1) if seed_track else count
        for i, song_query in enumerate(recommendations):
            _print(f"\r  [{i+1}/{len(recommendations)}] {song_query:<55}")
            results = search_ytdlp(song_query, count=2)
            good = [t for t in results if not _is_garbage(t) and _not_seed(t, seed_blacklist)]
            if good:
                t = good[0]
                if " - " in song_query:
                    parts = song_query.split(" - ", 1)
                    t.artist = parts[0].strip()
                    t.title = parts[1].strip()
                all_tracks.append(t)
            if len(all_tracks) >= want:
                break
        _print("\r\n")
        candidates = deduplicate(all_tracks)
        if candidates:
            result = candidates[:want]
            return ([seed_track] + result) if seed_track else result

    # Last resort: raw YouTube search excluding the seed title
    if not allow_yt_fallback:
        return []

    _sys.stdout.write("LLM unavailable, falling back to YouTube search...\r\n")
    _sys.stdout.flush()
    excl = f"-\"{title}\"" if title else ""
    fallback_query = f"{artist} {title} similar {excl}".strip() if (artist and title) else f"{seed_str} similar"
    candidates = search_ytdlp(fallback_query, count=count + 5)
    candidates = [t for t in candidates if not _is_garbage(t) and _not_seed(t, seed_blacklist)]
    if not candidates:
        print("No tracks found for this seed.")
        raise SystemExit(1)
    result = candidates[:count - 1] if seed_track else candidates[:count]
    return ([seed_track] + result) if seed_track else result


def _parse_seed(seed: str) -> tuple[str, str, str]:
    """Returns (artist, title, youtube_url). Any field may be empty string."""
    if seed.startswith("http://") or seed.startswith("https://"):
        meta = _extract_youtube_meta(seed)
        if not meta:
            console.print("[red]Could not extract metadata from YouTube URL.[/red]")
            raise SystemExit(1)
        artist, title = _split_title(meta.get("title", ""), meta.get("uploader", ""))
        return artist, title, seed

    if " - " in seed:
        parts = seed.split(" - ", 1)
        return parts[0].strip(), parts[1].strip(), ""

    return "", seed, ""


def _extract_youtube_meta(url: str) -> dict[str, Any] | None:
    try:
        import yt_dlp
        class _Q:
            def debug(self, m): pass
            def info(self, m): pass
            def warning(self, m): pass
            def error(self, m): pass
        ydl_opts = {"quiet": True, "no_warnings": True, "skip_download": True, "logger": _Q()}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            return info
    except Exception as e:
        console.print(f"[yellow]yt-dlp metadata error: {e}[/yellow]")
        return None
