"""Integration test for yt-dlp discovery. Requires network. Skipped by default.

Run with: pytest -m slow
"""
import pytest


@pytest.mark.slow
def test_ytdlp_search_returns_tracks():
    from autoplaylist.discovery import search_ytdlp
    tracks = search_ytdlp("Norah Jones Come Away With Me", count=3)
    assert len(tracks) > 0
    assert all(t.youtube_url.startswith("https://") for t in tracks)


@pytest.mark.slow
def test_discover_from_prompt():
    from autoplaylist.discovery import discover_from_prompt
    tracks = discover_from_prompt("relaxing jazz piano", count=5)
    assert 1 <= len(tracks) <= 5
    assert all(t.youtube_url for t in tracks)
