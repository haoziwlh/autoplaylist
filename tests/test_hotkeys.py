"""Tests for global hotkey management (autoplaylist.hotkeys)."""
from __future__ import annotations

import pathlib
import sys

import pytest

from autoplaylist import hotkeys as hk


# ---------------------------------------------------------------------------
# 3.1  write_bindings
# ---------------------------------------------------------------------------

class TestWriteBindings:
    def test_new_file(self, tmp_path, monkeypatch):
        skhdrc = tmp_path / "skhdrc"
        monkeypatch.setattr(hk, "_SKHD_CONFIG", skhdrc)

        hk.write_bindings(hk._DEFAULT_BINDINGS)

        content = skhdrc.read_text()
        assert hk._MARKER_BEGIN in content
        assert hk._MARKER_END in content
        assert "ctl pause" in content
        assert "ctl next" in content

    def test_existing_file_with_other_content(self, tmp_path, monkeypatch):
        skhdrc = tmp_path / "skhdrc"
        skhdrc.write_text("# yabai bindings\nalt - h : yabai -m window --focus west\n")
        monkeypatch.setattr(hk, "_SKHD_CONFIG", skhdrc)

        hk.write_bindings(hk._DEFAULT_BINDINGS)

        content = skhdrc.read_text()
        assert "yabai" in content
        assert hk._MARKER_BEGIN in content
        assert hk._MARKER_END in content

    def test_rerun_replaces_block(self, tmp_path, monkeypatch):
        skhdrc = tmp_path / "skhdrc"
        monkeypatch.setattr(hk, "_SKHD_CONFIG", skhdrc)

        hk.write_bindings(hk._DEFAULT_BINDINGS)
        hk.write_bindings({"pause": "ctrl + shift - p", "next": "ctrl + shift - n"})

        content = skhdrc.read_text()
        # Only one marker block
        assert content.count(hk._MARKER_BEGIN) == 1
        assert "ctrl + shift - p" in content
        # Old binding gone
        assert "ctrl + alt - p" not in content


# ---------------------------------------------------------------------------
# 3.2  remove_bindings
# ---------------------------------------------------------------------------

class TestRemoveBindings:
    def test_remove_with_other_bindings(self, tmp_path, monkeypatch):
        skhdrc = tmp_path / "skhdrc"
        skhdrc.write_text(
            "# yabai\nalt - h : yabai focus\n"
            f"\n{hk._MARKER_BEGIN}\nctrl + alt - p : myplaylist ctl pause\n{hk._MARKER_END}\n"
        )
        monkeypatch.setattr(hk, "_SKHD_CONFIG", skhdrc)

        has_others = hk.remove_bindings()

        assert has_others is True
        content = skhdrc.read_text()
        assert "yabai" in content
        assert hk._MARKER_BEGIN not in content

    def test_remove_only_myplaylist(self, tmp_path, monkeypatch):
        skhdrc = tmp_path / "skhdrc"
        skhdrc.write_text(
            f"{hk._MARKER_BEGIN}\nctrl + alt - p : myplaylist ctl pause\n{hk._MARKER_END}\n"
        )
        monkeypatch.setattr(hk, "_SKHD_CONFIG", skhdrc)

        has_others = hk.remove_bindings()

        assert has_others is False
        assert not skhdrc.exists()

    def test_remove_no_block(self, tmp_path, monkeypatch):
        skhdrc = tmp_path / "skhdrc"
        skhdrc.write_text("# empty\n")
        monkeypatch.setattr(hk, "_SKHD_CONFIG", skhdrc)

        has_others = hk.remove_bindings()
        assert has_others is False


# ---------------------------------------------------------------------------
# 3.3  get_bindings
# ---------------------------------------------------------------------------

class TestGetBindings:
    def test_defaults(self, monkeypatch):
        monkeypatch.setattr(hk.cfg, "get", lambda key, default=None: None)
        bindings = hk.get_bindings()
        assert bindings == hk._DEFAULT_BINDINGS

    def test_custom_from_config(self, monkeypatch):
        custom = {"pause": "ctrl + shift - x", "next": "ctrl + shift - y"}
        monkeypatch.setattr(hk.cfg, "get", lambda key, default=None: custom if key == "hotkeys" else None)
        bindings = hk.get_bindings()
        assert bindings["pause"] == "ctrl + shift - x"
        assert bindings["next"] == "ctrl + shift - y"
        # Defaults for actions not in custom
        assert bindings["quit"] == hk._DEFAULT_BINDINGS["quit"]


# ---------------------------------------------------------------------------
# 3.4  _myplaylist_bin
# ---------------------------------------------------------------------------

class TestMyplaylistBin:
    def test_resolves_sibling(self, tmp_path, monkeypatch):
        fake_bin = tmp_path / "myplaylist"
        fake_bin.write_text("#!/bin/sh\n")
        fake_bin.chmod(0o755)
        fake_python = tmp_path / "python"
        monkeypatch.setattr(sys, "executable", str(fake_python))
        assert hk._myplaylist_bin() == str(fake_bin)

    def test_falls_back_to_which(self, tmp_path, monkeypatch):
        # Point executable to a dir with no myplaylist sibling
        monkeypatch.setattr(sys, "executable", str(tmp_path / "python"))
        monkeypatch.setattr(hk.shutil, "which", lambda n: "/usr/local/bin/myplaylist" if n == "myplaylist" else None)
        assert hk._myplaylist_bin() == "/usr/local/bin/myplaylist"

    def test_falls_back_to_bare(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sys, "executable", str(tmp_path / "python"))
        monkeypatch.setattr(hk.shutil, "which", lambda n: None)
        assert hk._myplaylist_bin() == "myplaylist"
