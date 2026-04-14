"""Unit tests for JS runtime + yt-dlp install-kind detection in setup.py."""
from __future__ import annotations

import pathlib

from autoplaylist import setup


def test_detect_js_runtime_found(tmp_path, monkeypatch):
    fake = tmp_path / "deno"
    fake.write_text("#!/bin/sh\n")
    fake.chmod(0o755)

    def fake_which(name: str):
        return str(fake) if name == "deno" else None

    monkeypatch.setattr(setup.shutil, "which", fake_which)
    monkeypatch.setattr(setup, "_EXTRA_PATHS", ())

    result = setup._detect_js_runtime()
    assert result == ("deno", str(fake))


def test_detect_js_runtime_missing(monkeypatch):
    monkeypatch.setattr(setup.shutil, "which", lambda _n: None)
    monkeypatch.setattr(setup, "_EXTRA_PATHS", ())
    assert setup._detect_js_runtime() is None


def test_detect_js_runtime_via_extra_paths(tmp_path, monkeypatch):
    extra = tmp_path / "opt" / "bin"
    extra.mkdir(parents=True)
    (extra / "node").write_text("")
    monkeypatch.setattr(setup.shutil, "which", lambda _n: None)
    monkeypatch.setattr(setup, "_EXTRA_PATHS", (str(extra),))
    result = setup._detect_js_runtime()
    assert result is not None and result[0] == "node"


def test_install_kind_pipx():
    home = str(pathlib.Path.home())
    p = f"{home}/.local/pipx/venvs/myplaylist/bin/yt-dlp"
    assert setup._detect_ytdlp_install_kind(p) == "pipx"


def test_install_kind_homebrew():
    assert setup._detect_ytdlp_install_kind("/opt/homebrew/bin/yt-dlp") == "homebrew"


def test_install_kind_user_pip():
    home = str(pathlib.Path.home())
    assert setup._detect_ytdlp_install_kind(f"{home}/.local/bin/yt-dlp") == "user-pip"
    assert setup._detect_ytdlp_install_kind(f"{home}/Library/Python/3.12/bin/yt-dlp") == "user-pip"


def test_install_kind_other():
    assert setup._detect_ytdlp_install_kind("/tmp/weird/yt-dlp") == "other"
