"""Tests for CtlServer command dispatch and _ctl_send client helper."""
from __future__ import annotations

import json
import socket
import threading
import time

import pytest

from autoplaylist import player as _player
from autoplaylist.discovery import Track
from autoplaylist.player import PlayerCore, CtlServer


@pytest.fixture(autouse=True)
def _stub_mpv_ipc(monkeypatch):
    """Silence all mpv IPC calls so PlayerCore can be driven in isolation."""
    monkeypatch.setattr(_player, "_mpv_pause", lambda *a, **k: None)
    monkeypatch.setattr(_player, "_mpv_quit", lambda *a, **k: None)
    monkeypatch.setattr(_player, "_mpv_seek", lambda *a, **k: None)
    monkeypatch.setattr(_player, "_mpv_seek_absolute", lambda *a, **k: None)
    monkeypatch.setattr(_player, "_get_mpv_pos", lambda *a, **k: None)


def _mk_track(title: str, artist: str = "tester", duration: int = 180) -> Track:
    return Track(
        title=title,
        artist=artist,
        youtube_url=f"https://example.invalid/{title}",
        duration_seconds=duration,
    )


def _mk_core(n_tracks: int = 5) -> PlayerCore:
    tracks = [_mk_track(f"t{i}") for i in range(n_tracks)]
    playlists = [{"name": "demo", "tracks": tracks, "prompt": ""}]
    core = PlayerCore(playlists=playlists, active_idx=0, debug=False)
    core.playlist_name = "demo"
    core.tracks = list(tracks)
    core.n = len(tracks)
    core.vh = min(10, core.n)
    return core


def _send_cmd(sock_path: str, cmd: str, arg: str | None = None) -> dict:
    """Helper: connect, send JSON-line, read response."""
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(3.0)
    s.connect(sock_path)
    req: dict = {"cmd": cmd}
    if arg is not None:
        req["arg"] = arg
    s.sendall(json.dumps(req).encode() + b"\n")
    data = b""
    while b"\n" not in data and len(data) < 4096:
        chunk = s.recv(1024)
        if not chunk:
            break
        data += chunk
    s.close()
    return json.loads(data.strip())


# ---------------------------------------------------------------------------
# 4.1  Unit test CtlServer command dispatch
# ---------------------------------------------------------------------------

class TestCtlServerDispatch:
    @pytest.fixture(autouse=True)
    def _setup(self, monkeypatch):
        import uuid
        self.core = _mk_core(5)
        self.sock_path = f"/tmp/test-ctl-{uuid.uuid4().hex[:8]}.sock"
        self.server = CtlServer(self.core, sock_path=self.sock_path)
        self.server.start()
        time.sleep(0.1)  # let accept loop start
        yield
        self.server.stop()

    def test_status_returns_track_info(self):
        resp = _send_cmd(self.sock_path, "status")
        assert resp["ok"] is True
        st = resp["status"]
        assert st["idx"] == 0
        assert st["total"] == 5
        assert st["paused"] is False
        assert st["mode"] == "seq"
        assert st["artist"] == "tester"
        assert st["track"] == "t0"

    def test_pause_toggles(self):
        resp = _send_cmd(self.sock_path, "pause")
        assert resp["ok"] is True
        assert resp["paused"] is True
        resp2 = _send_cmd(self.sock_path, "pause")
        assert resp2["paused"] is False

    def test_mode_cycle(self):
        resp = _send_cmd(self.sock_path, "mode")
        assert resp["ok"] is True
        assert resp["mode"] == "repeat"
        resp2 = _send_cmd(self.sock_path, "mode")
        assert resp2["mode"] == "shuffle"
        resp3 = _send_cmd(self.sock_path, "mode")
        assert resp3["mode"] == "seq"

    def test_mode_set_explicit(self):
        resp = _send_cmd(self.sock_path, "mode", "shuffle")
        assert resp["ok"] is True
        assert resp["mode"] == "shuffle"

    def test_next_advances(self):
        resp = _send_cmd(self.sock_path, "next")
        assert resp["ok"] is True
        # core.current_idx should have advanced
        assert self.core.current_idx == 1

    def test_quit_posts_event(self):
        resp = _send_cmd(self.sock_path, "quit")
        assert resp["ok"] is True
        ev = self.core._ui_q.get(timeout=1.0)
        assert ev == ("ctl_quit",)

    def test_unknown_command(self):
        resp = _send_cmd(self.sock_path, "foobar")
        assert resp["ok"] is False
        assert "unknown command" in resp["error"]

    def test_malformed_json(self):
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(3.0)
        s.connect(self.sock_path)
        s.sendall(b"not json\n")
        data = b""
        while b"\n" not in data and len(data) < 4096:
            chunk = s.recv(1024)
            if not chunk:
                break
            data += chunk
        s.close()
        resp = json.loads(data.strip())
        assert resp["ok"] is False
        assert "invalid request" in resp["error"]


# ---------------------------------------------------------------------------
# 4.2  Unit test _ctl_send helper
# ---------------------------------------------------------------------------

class TestCtlSend:
    def test_ctl_send_no_player(self, tmp_path, monkeypatch):
        """_ctl_send should print error and raise SystemExit when no socket."""
        monkeypatch.setattr("getpass.getuser", lambda: "testuser")
        from autoplaylist import cli as _cli
        from click.exceptions import Exit
        with pytest.raises(Exit):
            _cli._ctl_send("status")


# ---------------------------------------------------------------------------
# 4.3  Integration test: CtlServer with real PlayerCore
# ---------------------------------------------------------------------------

class TestCtlIntegration:
    def test_status_mode_roundtrip(self, monkeypatch):
        """Start CtlServer with a real PlayerCore, send commands, verify."""
        import uuid
        core = _mk_core(3)
        sock_path = f"/tmp/test-ctl-{uuid.uuid4().hex[:8]}.sock"
        server = CtlServer(core, sock_path=sock_path)
        server.start()
        time.sleep(0.1)
        try:
            # status
            r = _send_cmd(sock_path, "status")
            assert r["ok"] and r["status"]["total"] == 3

            # mode → repeat
            r = _send_cmd(sock_path, "mode", "repeat")
            assert r["mode"] == "repeat"

            # status reflects new mode
            r = _send_cmd(sock_path, "status")
            assert r["status"]["mode"] == "repeat"

            # pause
            r = _send_cmd(sock_path, "pause")
            assert r["paused"] is True
            r = _send_cmd(sock_path, "status")
            assert r["status"]["paused"] is True
        finally:
            server.stop()
