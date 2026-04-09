"""Unit tests for PlayerCore — pure state machine, no TTY, no mpv.

Tests monkeypatch the mpv IPC helpers so command methods that issue IPC
calls (toggle_pause, seek_relative, stop_current) become no-ops. This
lets us exercise the state transitions without launching any process.
"""
from __future__ import annotations

import pytest

from autoplaylist import player as _player
from autoplaylist.discovery import Track
from autoplaylist.player import PlayerCore, PlayerSnapshot


@pytest.fixture(autouse=True)
def _stub_mpv_ipc(monkeypatch):
    """Silence all mpv IPC calls so PlayerCore can be driven in isolation."""
    monkeypatch.setattr(_player, "_mpv_pause", lambda *a, **k: None)
    monkeypatch.setattr(_player, "_mpv_quit", lambda *a, **k: None)
    monkeypatch.setattr(_player, "_mpv_seek", lambda *a, **k: None)
    monkeypatch.setattr(_player, "_mpv_seek_absolute", lambda *a, **k: None)
    monkeypatch.setattr(_player, "_get_mpv_pos", lambda *a, **k: None)


def _mk_track(title: str, duration: int = 180) -> Track:
    return Track(
        title=title,
        artist="tester",
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


# ── pick_next_idx ───────────────────────────────────────────────────────────

def test_pick_next_idx_seq_within_range():
    core = _mk_core(5)
    core.current_idx = 2
    core.play_mode = "seq"
    assert core.pick_next_idx() == 3


def test_pick_next_idx_seq_off_end_returns_none():
    core = _mk_core(5)
    core.current_idx = 4  # last
    core.play_mode = "seq"
    assert core.pick_next_idx() is None


def test_pick_next_idx_repeat_returns_current():
    core = _mk_core(5)
    core.current_idx = 2
    core.play_mode = "repeat"
    assert core.pick_next_idx() == 2


def test_pick_next_idx_shuffle_excludes_current():
    core = _mk_core(5)
    core.current_idx = 2
    core.play_mode = "shuffle"
    # Run many times; must never return the current index
    seen = {core.pick_next_idx() for _ in range(200)}
    assert 2 not in seen
    assert seen.issubset({0, 1, 3, 4})


def test_pick_next_idx_shuffle_single_track():
    core = _mk_core(1)
    core.current_idx = 0
    core.play_mode = "shuffle"
    # With only one track, falls through to seq path → off-end → None
    assert core.pick_next_idx() is None


def test_pick_next_idx_empty_tracks():
    core = _mk_core(0)
    assert core.pick_next_idx() is None


# ── seek_relative clamping ──────────────────────────────────────────────────

def test_seek_relative_clamps_below_zero(monkeypatch):
    core = _mk_core(5)
    core.current_idx = 0
    core.lyric["pos"] = 2.0  # 2s in
    calls = []
    monkeypatch.setattr(_player, "_mpv_seek_absolute", lambda p: calls.append(p))
    core.seek_relative(-30.0)
    assert calls and calls[-1] == 0.0


def test_seek_relative_clamps_below_duration(monkeypatch):
    core = _mk_core(5)
    core.current_idx = 0  # duration=180
    core.lyric["pos"] = 170.0
    calls = []
    monkeypatch.setattr(_player, "_mpv_seek_absolute", lambda p: calls.append(p))
    core.seek_relative(+60.0)
    # Clamp to duration - 1 = 179.0 (not 180.0), preventing auto-advance
    assert calls and calls[-1] == 179.0


# ── toggle_pause ────────────────────────────────────────────────────────────

def test_toggle_pause_flips_state():
    core = _mk_core(3)
    assert core.paused is False
    assert core.toggle_pause() is True
    assert core.paused is True
    assert core.toggle_pause() is False
    assert core.paused is False


def test_toggle_pause_resume_resets_lyric_sync():
    core = _mk_core(3)
    core.paused = True
    core.last_pos_ts = 12345.0
    core.lyric["off"] = 42
    core.prev_lrc_line = "stale"
    core.toggle_pause()  # resume
    assert core.last_pos_ts == 0.0
    assert core.lyric["off"] == 0
    assert core.prev_lrc_line is None


# ── cycle_mode / set_mode ───────────────────────────────────────────────────

def test_cycle_mode_rotation():
    core = _mk_core(3)
    assert core.play_mode == "seq"
    assert core.cycle_mode() == "repeat"
    assert core.cycle_mode() == "shuffle"
    assert core.cycle_mode() == "seq"


def test_set_mode_ignores_invalid():
    core = _mk_core(3)
    core.set_mode("bogus")
    assert core.play_mode == "seq"
    core.set_mode("shuffle")
    assert core.play_mode == "shuffle"


# ── select (cursor clamp) ───────────────────────────────────────────────────

def test_select_clamps_low():
    core = _mk_core(5)
    core.cursor_idx = 2
    old = core.select(-10)
    assert old == 2
    assert core.cursor_idx == 0


def test_select_clamps_high():
    core = _mk_core(5)
    core.cursor_idx = 0
    core.select(99)
    assert core.cursor_idx == 4  # len-1


# ── jump_to ─────────────────────────────────────────────────────────────────

def test_jump_to_resets_lyric_and_pause():
    core = _mk_core(5)
    core.current_idx = 0
    core.paused = True
    core.lyric["line"] = "stale line"
    core.lyric["idx"] = 3
    old = core.jump_to(2)
    assert old == 0
    assert core.current_idx == 2
    assert core.cursor_idx == 2
    assert core.paused is False
    assert core.lyric["line"] is None
    assert core.lyric["idx"] is None


# ── next_track ──────────────────────────────────────────────────────────────

def test_next_track_advances():
    core = _mk_core(5)
    core.current_idx = 1
    old = core.next_track()
    assert old == 1
    assert core.current_idx == 2
    assert core.cursor_idx == 2


def test_next_track_at_end_returns_none():
    core = _mk_core(3)
    core.current_idx = 2  # last
    old = core.next_track()
    assert old is None
    # current_idx was incremented but caller sees None and should not repaint


# ── delete_cursor ───────────────────────────────────────────────────────────

def test_delete_cursor_non_playing():
    core = _mk_core(5)
    core.current_idx = 0
    core.cursor_idx = 3
    del_idx, was_playing, empty = core.delete_cursor()
    assert del_idx == 3
    assert was_playing is False
    assert empty is False
    assert len(core.tracks) == 4
    assert core.current_idx == 0  # unchanged (cursor was above)


def test_delete_cursor_above_current_shifts_current():
    core = _mk_core(5)
    core.current_idx = 3
    core.cursor_idx = 1  # delete track 1, current should shift to 2
    _, was_playing, _ = core.delete_cursor()
    assert was_playing is False
    assert core.current_idx == 2


def test_delete_cursor_playing_marks_was_playing():
    core = _mk_core(5)
    core.current_idx = 2
    core.cursor_idx = 2
    _, was_playing, empty = core.delete_cursor()
    assert was_playing is True
    assert empty is False


def test_delete_cursor_empty_last_track():
    core = _mk_core(1)
    core.current_idx = 0
    core.cursor_idx = 0
    _, _, empty = core.delete_cursor()
    assert empty is True


# ── snapshot ────────────────────────────────────────────────────────────────

def test_snapshot_is_immutable_copy():
    core = _mk_core(5)
    core.current_idx = 3
    core.paused = True
    core.play_mode = "shuffle"
    snap = core.snapshot()
    assert isinstance(snap, PlayerSnapshot)
    assert snap.current_idx == 3
    assert snap.paused is True
    assert snap.play_mode == "shuffle"
    assert snap.tracks_count == 5
    # Mutating core after snapshot does not affect the snapshot
    core.current_idx = 0
    assert snap.current_idx == 3
    # Snapshot is frozen
    with pytest.raises(Exception):
        snap.current_idx = 99  # type: ignore[misc]


# ── subscribe / _emit ───────────────────────────────────────────────────────

def test_subscribe_receives_events():
    core = _mk_core(5)
    events = []
    core.subscribe(lambda ev: events.append(ev))
    core.toggle_pause()
    core.cycle_mode()
    core.select(2)
    assert ("Paused",) in events
    assert ("ModeChanged", "repeat") in events
    assert any(ev[0] == "CursorMoved" for ev in events)


def test_subscribe_swallows_callback_exceptions():
    core = _mk_core(5)
    ok = []
    core.subscribe(lambda ev: (_ for _ in ()).throw(RuntimeError("boom")))
    core.subscribe(lambda ev: ok.append(ev))
    core.toggle_pause()  # must not raise
    assert ok  # the good subscriber still ran


# ── tab switch: verifies the UI-side reset is self-consistent ──────────────
# (Tab switch side-effects happen in play_playlist's main loop, not in
# PlayerCore directly. Here we only cover request_switch_tab marking the
# switch_tab field.)

def test_request_switch_tab_sets_direction():
    core = _mk_core(5)
    core.request_switch_tab(-1)
    assert core.switch_tab == -1
    core.request_switch_tab(+1)
    assert core.switch_tab == 1
