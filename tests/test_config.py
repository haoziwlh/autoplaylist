"""Smoke tests for config module — no network calls."""
import json
import pytest
from pathlib import Path


def test_load_defaults(tmp_path, monkeypatch):
    monkeypatch.setattr("autoplaylist.config._BASE_DIR", tmp_path / ".autoplaylist")
    monkeypatch.setattr("autoplaylist.config._CONFIG_FILE", tmp_path / ".autoplaylist" / "config.json")
    monkeypatch.setattr("autoplaylist.config._PLAYLISTS_DIR", tmp_path / ".autoplaylist" / "playlists")

    from autoplaylist import config
    cfg = config.load()
    assert cfg["lastfm_key"] is None
    assert cfg["setup_complete"] is False


def test_save_and_load(tmp_path, monkeypatch):
    base = tmp_path / ".autoplaylist"
    monkeypatch.setattr("autoplaylist.config._BASE_DIR", base)
    monkeypatch.setattr("autoplaylist.config._CONFIG_FILE", base / "config.json")
    monkeypatch.setattr("autoplaylist.config._PLAYLISTS_DIR", base / "playlists")

    from autoplaylist import config
    config.set_value("lastfm_key", "test-key-123")
    assert config.get_lastfm_key() == "test-key-123"


def test_is_setup_complete_false(tmp_path, monkeypatch):
    base = tmp_path / ".autoplaylist"
    monkeypatch.setattr("autoplaylist.config._BASE_DIR", base)
    monkeypatch.setattr("autoplaylist.config._CONFIG_FILE", base / "config.json")
    monkeypatch.setattr("autoplaylist.config._PLAYLISTS_DIR", base / "playlists")

    from autoplaylist import config
    assert not config.is_setup_complete()


def test_is_setup_complete_true(tmp_path, monkeypatch):
    base = tmp_path / ".autoplaylist"
    monkeypatch.setattr("autoplaylist.config._BASE_DIR", base)
    monkeypatch.setattr("autoplaylist.config._CONFIG_FILE", base / "config.json")
    monkeypatch.setattr("autoplaylist.config._PLAYLISTS_DIR", base / "playlists")

    from autoplaylist import config
    config.set_value("setup_complete", True)
    assert config.is_setup_complete()
