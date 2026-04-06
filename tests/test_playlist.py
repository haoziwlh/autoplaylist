"""Smoke tests for playlist module — no network calls."""
import pytest
from autoplaylist.discovery import Track


def _make_tracks(n=3):
    return [
        Track(title=f"Song {i}", artist=f"Artist {i}", youtube_url=f"https://youtube.com/watch?v={i}", duration_seconds=180)
        for i in range(n)
    ]


def test_save_and_load(tmp_path, monkeypatch):
    monkeypatch.setattr("autoplaylist.config._BASE_DIR", tmp_path / ".autoplaylist")
    monkeypatch.setattr("autoplaylist.config._CONFIG_FILE", tmp_path / ".autoplaylist" / "config.json")
    monkeypatch.setattr("autoplaylist.config._PLAYLISTS_DIR", tmp_path / ".autoplaylist" / "playlists")

    from autoplaylist import playlist as pl
    tracks = _make_tracks()
    pl.save("test-pl", tracks, "test prompt")
    data = pl.load("test-pl")
    assert data["name"] == "test-pl"
    assert len(data["tracks"]) == 3
    assert data["tracks"][0]["title"] == "Song 0"


def test_list_all(tmp_path, monkeypatch):
    monkeypatch.setattr("autoplaylist.config._BASE_DIR", tmp_path / ".autoplaylist")
    monkeypatch.setattr("autoplaylist.config._CONFIG_FILE", tmp_path / ".autoplaylist" / "config.json")
    monkeypatch.setattr("autoplaylist.config._PLAYLISTS_DIR", tmp_path / ".autoplaylist" / "playlists")

    from autoplaylist import playlist as pl
    assert pl.list_all() == []
    pl.save("a", _make_tracks(2), "prompt a")
    pl.save("b", _make_tracks(5), "prompt b")
    all_pl = pl.list_all()
    assert len(all_pl) == 2
    names = {p["name"] for p in all_pl}
    assert names == {"a", "b"}


def test_delete(tmp_path, monkeypatch):
    monkeypatch.setattr("autoplaylist.config._BASE_DIR", tmp_path / ".autoplaylist")
    monkeypatch.setattr("autoplaylist.config._CONFIG_FILE", tmp_path / ".autoplaylist" / "config.json")
    monkeypatch.setattr("autoplaylist.config._PLAYLISTS_DIR", tmp_path / ".autoplaylist" / "playlists")

    from autoplaylist import playlist as pl
    pl.save("del-me", _make_tracks(), "x")
    assert pl.exists("del-me")
    pl.delete("del-me")
    assert not pl.exists("del-me")


def test_load_not_found(tmp_path, monkeypatch):
    monkeypatch.setattr("autoplaylist.config._BASE_DIR", tmp_path / ".autoplaylist")
    monkeypatch.setattr("autoplaylist.config._CONFIG_FILE", tmp_path / ".autoplaylist" / "config.json")
    monkeypatch.setattr("autoplaylist.config._PLAYLISTS_DIR", tmp_path / ".autoplaylist" / "playlists")

    from autoplaylist import playlist as pl
    with pytest.raises(FileNotFoundError):
        pl.load("nonexistent")


def test_slugify():
    from autoplaylist.playlist import slugify
    assert slugify("下雨天的 lo-fi jazz") != ""
    assert "-" in slugify("hello world")
    assert len(slugify("a" * 100)) <= 32


def test_deduplicate():
    from autoplaylist.discovery import deduplicate, Track
    tracks = [
        Track("Come Away With Me", "Norah Jones", "https://yt.com/1"),
        Track("come away with me", "norah jones", "https://yt.com/2"),
        Track("Don't Know Why", "Norah Jones", "https://yt.com/3"),
    ]
    result = deduplicate(tracks)
    assert len(result) == 2
