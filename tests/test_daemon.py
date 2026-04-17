"""Tests for daemon PID helpers and subscribe protocol."""
from __future__ import annotations

import json
import socket
import threading
import time
import uuid

import pytest

from autoplaylist import player as _player
from autoplaylist.discovery import Track
from autoplaylist.player import PlayerCore, CtlServer


@pytest.fixture(autouse=True)
def _stub_mpv_ipc(monkeypatch):
    monkeypatch.setattr(_player, "_mpv_pause", lambda *a, **k: None)
    monkeypatch.setattr(_player, "_mpv_quit", lambda *a, **k: None)
    monkeypatch.setattr(_player, "_mpv_seek", lambda *a, **k: None)
    monkeypatch.setattr(_player, "_mpv_seek_absolute", lambda *a, **k: None)
    monkeypatch.setattr(_player, "_get_mpv_pos", lambda *a, **k: None)


def _mk_track(title: str, artist: str = "tester", duration: int = 180) -> Track:
    return Track(
        title=title, artist=artist,
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


# ---------------------------------------------------------------------------
# 7.1  PID file helpers
# ---------------------------------------------------------------------------

class TestPidHelpers:
    def test_write_read_remove(self, tmp_path, monkeypatch):
        pid_file = tmp_path / "daemon.pid"
        from autoplaylist import daemon
        monkeypatch.setattr(daemon, "_PID_FILE", pid_file)

        daemon.write_pid()
        import os
        assert daemon.read_pid() == os.getpid()

        daemon.remove_pid()
        assert daemon.read_pid() is None

    def test_is_daemon_alive_current_process(self, tmp_path, monkeypatch):
        pid_file = tmp_path / "daemon.pid"
        ctl_sock = f"/tmp/test-ctl-{uuid.uuid4().hex[:8]}.sock"
        from autoplaylist import daemon
        monkeypatch.setattr(daemon, "_PID_FILE", pid_file)
        monkeypatch.setattr(daemon, "_CTL_SOCK", ctl_sock)

        # Start a listener so the socket check succeeds
        import socket as _socket
        srv = _socket.socket(_socket.AF_UNIX, _socket.SOCK_STREAM)
        srv.bind(ctl_sock)
        srv.listen(1)

        try:
            daemon.write_pid()
            import os
            assert daemon.is_daemon_alive() == os.getpid()
            daemon.remove_pid()
        finally:
            srv.close()
            try:
                os.unlink(ctl_sock)
            except FileNotFoundError:
                pass

    def test_is_daemon_alive_stale(self, tmp_path, monkeypatch):
        pid_file = tmp_path / "daemon.pid"
        from autoplaylist import daemon
        monkeypatch.setattr(daemon, "_PID_FILE", pid_file)
        monkeypatch.setattr(daemon, "_CTL_SOCK", str(tmp_path / "ctl.sock"))

        # Write a PID that doesn't exist
        pid_file.write_text("99999999")
        assert daemon.is_daemon_alive() is None
        assert not pid_file.exists()  # cleaned up

    def test_read_pid_missing_file(self, tmp_path, monkeypatch):
        pid_file = tmp_path / "nonexistent.pid"
        from autoplaylist import daemon
        monkeypatch.setattr(daemon, "_PID_FILE", pid_file)
        assert daemon.read_pid() is None


# ---------------------------------------------------------------------------
# 7.2  Subscribe protocol
# ---------------------------------------------------------------------------

def _connect_subscribe(sock_path: str) -> socket.socket:
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(3.0)
    s.connect(sock_path)
    s.sendall(json.dumps({"cmd": "subscribe"}).encode() + b"\n")
    return s


def _recv_event(s: socket.socket) -> dict:
    buf = b""
    while b"\n" not in buf:
        chunk = s.recv(4096)
        if not chunk:
            raise ConnectionError("closed")
        buf += chunk
    line, _ = buf.split(b"\n", 1)
    return json.loads(line)


class TestSubscribe:
    @pytest.fixture(autouse=True)
    def _setup(self):
        self.core = _mk_core(3)
        self.sock_path = f"/tmp/test-ctl-{uuid.uuid4().hex[:8]}.sock"
        self.server = CtlServer(self.core, sock_path=self.sock_path)
        self.server.start()
        time.sleep(0.1)
        yield
        self.server.stop()

    def test_subscribe_gets_snapshot(self):
        s = _connect_subscribe(self.sock_path)
        ev = _recv_event(s)
        assert ev["event"] == "snapshot"
        assert ev["data"]["playlist_name"] == "demo"
        assert len(ev["data"]["tracks"]) == 3
        assert ev["data"]["paused"] is False
        s.close()

    def test_broadcast_reaches_subscriber(self):
        s = _connect_subscribe(self.sock_path)
        _recv_event(s)  # snapshot
        s.settimeout(2.0)

        # Broadcast an event
        self.server.broadcast({"event": "paused", "data": {"paused": True}})
        ev = _recv_event(s)
        assert ev["event"] == "paused"
        assert ev["data"]["paused"] is True
        s.close()


# ---------------------------------------------------------------------------
# 7.3  Event broadcast with multiple subscribers
# ---------------------------------------------------------------------------

class TestBroadcastMultiple:
    @pytest.fixture(autouse=True)
    def _setup(self):
        self.core = _mk_core(3)
        self.sock_path = f"/tmp/test-ctl-{uuid.uuid4().hex[:8]}.sock"
        self.server = CtlServer(self.core, sock_path=self.sock_path)
        self.server.start()
        time.sleep(0.1)
        yield
        self.server.stop()

    def test_two_subscribers(self):
        s1 = _connect_subscribe(self.sock_path)
        s2 = _connect_subscribe(self.sock_path)
        _recv_event(s1)  # snapshot
        _recv_event(s2)  # snapshot
        s1.settimeout(2.0)
        s2.settimeout(2.0)

        self.server.broadcast({"event": "mode_changed", "data": {"mode": "shuffle"}})
        ev1 = _recv_event(s1)
        ev2 = _recv_event(s2)
        assert ev1["event"] == "mode_changed"
        assert ev2["event"] == "mode_changed"
        s1.close()
        s2.close()

    def test_dead_subscriber_removed(self):
        s1 = _connect_subscribe(self.sock_path)
        s2 = _connect_subscribe(self.sock_path)
        _recv_event(s1)
        _recv_event(s2)
        time.sleep(0.1)

        # Close s1 to simulate dead subscriber
        s1.close()
        time.sleep(0.1)

        # Broadcast should not crash and should clean up s1
        self.server.broadcast({"event": "paused", "data": {"paused": True}})
        s2.settimeout(2.0)
        ev = _recv_event(s2)
        assert ev["event"] == "paused"

        # Verify s1 was removed
        with self.server._sub_lock:
            assert len(self.server._subscribers) <= 1
        s2.close()


# ---------------------------------------------------------------------------
# 7.4  Integration: CtlServer commands + subscribe
# ---------------------------------------------------------------------------

class TestCtlIntegrationWithSubscribe:
    def test_command_and_subscribe_roundtrip(self):
        core = _mk_core(5)
        sock_path = f"/tmp/test-ctl-{uuid.uuid4().hex[:8]}.sock"
        server = CtlServer(core, sock_path=sock_path)
        server.start()
        time.sleep(0.1)

        try:
            # Subscribe
            sub = _connect_subscribe(sock_path)
            snap = _recv_event(sub)
            assert snap["event"] == "snapshot"
            assert len(snap["data"]["tracks"]) == 5
            sub.settimeout(2.0)

            # Send a pause command via one-shot connection
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.settimeout(2.0)
            s.connect(sock_path)
            s.sendall(json.dumps({"cmd": "pause"}).encode() + b"\n")
            resp = b""
            while b"\n" not in resp:
                resp += s.recv(1024)
            s.close()
            r = json.loads(resp.strip())
            assert r["ok"] is True
            assert r["paused"] is True

            sub.close()
        finally:
            server.stop()
