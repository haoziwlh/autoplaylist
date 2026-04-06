"""Smoke tests for export module — no network calls."""
import csv
import json
from pathlib import Path

import pytest


def _sample_playlist():
    return {
        "name": "test-export",
        "created_at": "2025-01-01T00:00:00+00:00",
        "prompt": "lo-fi jazz",
        "tracks": [
            {
                "title": "Come Away With Me",
                "artist": "Norah Jones",
                "youtube_url": "https://www.youtube.com/watch?v=abc123",
                "duration_seconds": 211,
                "source": "lastfm",
            },
            {
                "title": "Don't Know Why",
                "artist": "Norah Jones",
                "youtube_url": "https://www.youtube.com/watch?v=def456",
                "duration_seconds": 189,
                "source": "ytdlp",
            },
        ],
    }


def test_export_m3u(tmp_path):
    from autoplaylist.export import export_m3u
    out = tmp_path / "test.m3u"
    export_m3u(_sample_playlist(), out)
    content = out.read_text()
    assert content.startswith("#EXTM3U")
    assert "#EXTINF:211,Norah Jones - Come Away With Me" in content
    assert "https://www.youtube.com/watch?v=abc123" in content


def test_export_csv(tmp_path):
    from autoplaylist.export import export_csv
    out = tmp_path / "test.csv"
    export_csv(_sample_playlist(), out)
    with open(out, newline="") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 2
    assert rows[0]["title"] == "Come Away With Me"
    assert rows[0]["artist"] == "Norah Jones"
    assert rows[1]["youtube_url"] == "https://www.youtube.com/watch?v=def456"


def test_export_json(tmp_path):
    from autoplaylist.export import export_json
    out = tmp_path / "test.json"
    export_json(_sample_playlist(), out)
    data = json.loads(out.read_text())
    assert data["name"] == "test-export"
    assert len(data["tracks"]) == 2
    assert data["tracks"][0]["title"] == "Come Away With Me"
