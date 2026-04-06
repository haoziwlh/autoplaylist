from __future__ import annotations

import json
import os
import select
import signal
import socket
import subprocess
import sys
import termios
import threading
import time
import tty
from typing import Optional

from autoplaylist.discovery import Track

import getpass as _getpass
_IPC_SOCK = f"/tmp/myplaylist-{_getpass.getuser()}-mpv.sock"

# ---------------------------------------------------------------------------
# ANSI / box skin
# ---------------------------------------------------------------------------

_R  = "\033[0m"          # reset
_B  = "\033[1m"          # bold
_D  = "\033[2m"          # dim
_CY = "\033[36m"         # cyan
_YL = "\033[33m"         # yellow
_GR = "\033[32m"         # green
_RD = "\033[31m"         # red
_RV = "\033[7m"          # reverse video
_PL = "\033[1;38;5;45m"  # playing: bold sky-blue
_PP = "\033[2;38;5;39m"  # playing paused: dim blue
_CU = "\033[1;33m"       # cursor selected: bold amber

_IW = 80           # inner box width (panel closed)
_IW_NORMAL = 80
_TOP = "┌" + "─" * _IW + "┐"
_MID = "├" + "─" * _IW + "┤"
_BOT = "└" + "─" * _IW + "┘"
_NL  = "\r\n"


def _compute_panel_widths() -> Optional[tuple[int, int, int]]:
    """Return (total_iw, plw, lw) for lyrics panel, or None if terminal too narrow."""
    tw = shutil.get_terminal_size().columns
    iw = tw - 2  # subtract │ left and │ right border
    if iw < 82:
        return None
    plw = max(40, iw * 55 // 100)
    lw = iw - plw - 1  # 1 col for the divider │
    return iw, plw, lw


def _panel_top(plw: int, lw: int) -> str:
    return "┌" + "─" * plw + "┬" + "─" * lw + "┐"


def _panel_mid(plw: int, lw: int) -> str:
    return "├" + "─" * plw + "┤" + " " * lw + "│"


def _panel_bot(plw: int, lw: int) -> str:
    """Separator between track rows and controls: ├─plw─┴─lw─┤"""
    return "├" + "─" * plw + "┴" + "─" * lw + "┤"


# ---------------------------------------------------------------------------
# yt-dlp path
# ---------------------------------------------------------------------------

import pathlib
import re
import shutil

def _find_ytdlp() -> str:
    def _version(path: str) -> tuple:
        try:
            out = subprocess.check_output([path, "--version"], stderr=subprocess.DEVNULL, text=True).strip()
            return tuple(int(x) for x in re.findall(r"\d+", out))
        except Exception:
            return (0,)

    home = pathlib.Path.home()
    candidates = [
        "/opt/homebrew/bin/yt-dlp",   # macOS Homebrew (Apple Silicon + Intel)
        "/usr/local/bin/yt-dlp",      # macOS Homebrew (Intel), Linux manual
        "/usr/bin/yt-dlp",            # Linux system package
        str(home / ".local/bin/yt-dlp"),  # pip install --user / pipx
    ]
    # macOS pip install --user puts binaries under Library/Python/3.X/bin
    for minor in range(9, 16):
        candidates.append(str(home / f"Library/Python/3.{minor}/bin/yt-dlp"))
    # pipx venv (when myplaylist itself is installed via pipx)
    candidates.append(str(home / ".local/pipx/venvs/myplaylist/bin/yt-dlp"))

    w = shutil.which("yt-dlp")
    if w and w not in candidates:
        candidates.insert(0, w)
    existing = [p for p in candidates if pathlib.Path(p).exists()]
    return max(existing, key=_version) if existing else "yt-dlp"


# ---------------------------------------------------------------------------
# mpv launch via yt-dlp pipe
# ---------------------------------------------------------------------------

def _launch_mpv(youtube_url: str) -> tuple[subprocess.Popen, subprocess.Popen]:
    if os.path.exists(_IPC_SOCK):
        os.unlink(_IPC_SOCK)
    ytdlp_path = _find_ytdlp()
    ytdlp_proc = subprocess.Popen(
        [ytdlp_path, "-f", "bestaudio/best", "-o", "-", "--quiet", "--no-playlist", youtube_url],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    mpv_proc = subprocess.Popen(
        ["mpv", "--no-video", "--really-quiet", f"--input-ipc-server={_IPC_SOCK}", "-"],
        stdin=ytdlp_proc.stdout,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if ytdlp_proc.stdout:
        ytdlp_proc.stdout.close()
    return ytdlp_proc, mpv_proc


# ---------------------------------------------------------------------------
# mpv IPC
# ---------------------------------------------------------------------------

def _ipc_send(command: list) -> None:
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.connect(_IPC_SOCK)
        sock.sendall((json.dumps({"command": command}) + "\n").encode())
        sock.close()
    except Exception:
        pass


def _mpv_pause(paused: bool) -> None:
    _ipc_send(["set_property", "pause", paused])


def _mpv_quit() -> None:
    _ipc_send(["quit"])


def _get_mpv_pos() -> Optional[float]:
    """Query mpv IPC socket for current playback position in seconds."""
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(0.5)
        sock.connect(_IPC_SOCK)
        sock.sendall((json.dumps({"command": ["get_property", "time-pos"], "request_id": 1}) + "\n").encode())
        buf = b""
        try:
            while b"\n" not in buf:
                chunk = sock.recv(256)
                if not chunk:
                    break
                buf += chunk
        except OSError:
            pass
        sock.close()
        if not buf:
            return None
        data = json.loads(buf.split(b"\n")[0])
        val = data.get("data")
        return float(val) if val is not None else None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clean(text: str) -> str:
    """Strip emoji that confuse terminal width; keep CJK and other printable chars."""
    result = []
    for c in text:
        cp = ord(c)
        if cp > 0xFFFF:          # non-BMP: emoji, etc.
            continue
        if 0x2600 <= cp <= 0x27BF:  # misc symbols & dingbats (emoji-like)
            continue
        result.append(c)
    return "".join(result)


def _fmt_dur(seconds: int) -> str:
    if not seconds:
        return ""
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def _w(text: str, end: str = "") -> None:
    sys.stdout.write(text + end)
    sys.stdout.flush()


def _marquee(text: str, width: int, offset: int) -> str:
    """Return a window of `width` chars from scrolling `text`."""
    if not text:
        return " " * width
    if len(text) <= width:
        return f"{text:<{width}}"
    padded = text + "    "
    pos = offset % len(padded)
    doubled = padded + padded
    return doubled[pos: pos + width]


def _restore_terminal() -> None:
    """Fully reset terminal to sane state (undo tty.setraw)."""
    try:
        subprocess.run(["stty", "sane"], check=False, stderr=subprocess.DEVNULL)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Keyboard reader
# ---------------------------------------------------------------------------

class _KeyReader:
    def __init__(self) -> None:
        self._key: Optional[str] = None
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def consume(self) -> Optional[str]:
        key, self._key = self._key, None
        return key

    def _run(self) -> None:
        if not sys.stdin.isatty():
            return
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            while not self._stop.is_set():
                r, _, _ = select.select([fd], [], [], 0.1)
                if r:
                    ch = os.read(fd, 1)
                    if ch == b"\033":
                        r2, _, _ = select.select([fd], [], [], 0.15)
                        if r2:
                            ch2 = os.read(fd, 1)
                            if ch2 == b"[":
                                r3, _, _ = select.select([fd], [], [], 0.15)
                                if r3:
                                    ch3 = os.read(fd, 1)
                                    if ch3 == b"A":
                                        self._key = "UP"
                                    elif ch3 == b"B":
                                        self._key = "DOWN"
                                    elif ch3 == b"C":
                                        self._key = "RIGHT"
                                    elif ch3 == b"D":
                                        self._key = "LEFT"
                    else:
                        try:
                            self._key = ch.decode("utf-8", errors="replace")
                        except Exception:
                            pass
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)


# ---------------------------------------------------------------------------
# Box UI
# ---------------------------------------------------------------------------

def _cjk_width(s: str) -> int:
    """Display column width accounting for double-width CJK characters."""
    w = 0
    for c in s:
        cp = ord(c)
        if (0x1100 <= cp <= 0x115F or 0x2E80 <= cp <= 0x303E or
                0x3041 <= cp <= 0x33FF or 0x4E00 <= cp <= 0x9FFF or
                0xAC00 <= cp <= 0xD7A3 or 0xF900 <= cp <= 0xFAFF or
                0xFF01 <= cp <= 0xFF60):
            w += 2
        else:
            w += 1
    return w


def _truncate(s: str, max_cols: int) -> str:
    """Truncate string to max_cols display columns."""
    cols = 0
    for i, c in enumerate(s):
        cw = 2 if _cjk_width(c) == 2 else 1
        if cols + cw > max_cols - 3:
            return s[:i] + "..."
        cols += cw
    return s


def _make_label(t: Track, width: int = 44) -> str:
    import re as _re
    raw = _clean(t.title.strip())
    raw = _re.sub(r"\s+", " ", raw).strip()
    if not raw or len(raw) < 2:
        raw = _clean(t.artist.strip())
    return _truncate(raw, width) if _cjk_width(raw) > width else raw


_VIEW_H = 10   # max tracks shown at once in the box
_LABEL_W = 60  # label column display-width budget  (= _IW - 2-3-2-2-8-3 = 80-20)
_BAR_W = 16    # progress bar block width

# ---------------------------------------------------------------------------
# Adaptive control bar strings (visible text, no ANSI — used for width math)
# Tiers: full ≥ 113 cols  (symbol + word),  short fits in 80 (symbol only).
# L/l variant distinguishes panel open vs closed for the lyrics toggle.
# ---------------------------------------------------------------------------
# full bar: text labels only (no symbols), shown when terminal is wide enough (~92 cols)
_CTRL_VIS_FULL_OPEN  = ("  [p] pause [n] next [↑↓] sel [←→] pg"
                         " [↵] play [q] quit [L] lyrics [+] more [d] del [s] save  [[] prev []] next  [y] lyrics src")
_CTRL_VIS_FULL_CLOSE = ("  [p] pause [n] next [↑↓] sel [←→] pg"
                         " [↵] play [q] quit [l] lyrics [+] more [d] del [s] save  [[] prev []] next  [y] lyrics src")
# compact: symbols only, fits ≤ 80 (panel-closed box)
_CTRL_VIS_SHORT_OPEN  = "  [p]⏸  [n]⏭  [↑↓]  [←→]  [↵]▶  [q]✕  [L]♪  [+]  [d]✗  [s]↓  [[]←  []]→"
_CTRL_VIS_SHORT_CLOSE = "  [p]⏸  [n]⏭  [↑↓]  [←→]  [↵]▶  [q]✕  [l]♪  [+]  [d]✗  [s]↓  [[]←  []]→"


def _ctrl_bar(avail: int, panel_open: bool) -> tuple[str, str]:
    """Return (ctrl_vis, ctrl_disp) for the control bar, adapting to available width."""
    Ld = f"{_D}[L]{_R}" if panel_open else f"{_D}[l]{_R}"
    vis_full  = (_CTRL_VIS_FULL_OPEN  if panel_open else _CTRL_VIS_FULL_CLOSE)
    vis_short = (_CTRL_VIS_SHORT_OPEN if panel_open else _CTRL_VIS_SHORT_CLOSE)
    if avail >= _cjk_width(vis_full):
        vis = vis_full
        disp = (f"  {_D}[p]{_R} pause {_D}[n]{_R} next {_D}[↑↓]{_R} sel {_D}[←→]{_R} pg"
                f" {_D}[↵]{_R} play {_D}[q]{_R} quit {Ld} lyrics {_D}[+]{_R} more"
                f" {_D}[d]{_R} del {_D}[s]{_R} save"
                f"  {_D}[[]" f"{_R} prev {_D}[]]" f"{_R} next"
                f"  {_D}[y]{_R} lyrics src")
    else:
        vis = vis_short
        disp = (f"  {_D}[p]{_R}⏸  {_D}[n]{_R}⏭  {_D}[↑↓]{_R}  {_D}[←→]{_R}"
                f"  {_D}[↵]{_R}▶  {_D}[q]{_R}✕  {Ld}♪  {_D}[+]{_R}  {_D}[d]{_R}✗  {_D}[s]{_R}↓"
                f"  {_D}[[]" f"{_R}←  {_D}[]]" f"{_R}→")
    return vis, disp


def _fmt_progress(pos: float, duration: float, bar_w: int = _BAR_W) -> str:
    """Return compact progress string e.g. '████████░░░░░░░░  1:23/4:12'."""
    if duration <= 0:
        return ""
    frac = max(0.0, min(1.0, pos / duration))
    filled = round(frac * bar_w)
    bar = "█" * filled + "░" * (bar_w - filled)
    elapsed = _fmt_dur(int(pos))
    total   = _fmt_dur(int(duration))
    return f"{bar}  {elapsed}/{total}"


# ---------------------------------------------------------------------------
# Mood animation presets  (t=frame counter, w=column width, h=row count)
# Each returns a list of h strings, each exactly w display-cols wide.
# ---------------------------------------------------------------------------

import math as _math


def _anim_margin_str(mood: str, t: int, row: int, panel_h: int, w: int, side: int) -> str:
    """Return a string of `w` visible chars for the lyric margin animation.

    side: 0=left margin, 1=right margin.
    All presets are intentionally sparse (mostly spaces).
    """
    if w <= 0:
        return ""
    buf = [" "] * w
    h = max(1, panel_h)

    if mood == "calm":
        # One slowly-drifting dot per row
        col = int((_math.sin(t * 0.08 + row * 1.1 + side * 2.5) * 0.4 + 0.5) * (w - 1))
        col = max(0, min(w - 1, col))
        buf[col] = "∘" if (t // 6 + row + side) % 2 == 0 else "·"

    elif mood == "melancholic":
        # 2-3 drops per side: shape ╎(trail) │(body) ·(tip), splash ˜ on landing
        num_drops = max(2, w // 4)
        period = h + 3
        for i in range(num_drops):
            dc = (i * 3 + side * 5) % w
            phase = (t // 2 + (i * 5 + side * 11) % period) % period
            if phase < h:
                if row == phase:
                    buf[dc] = "·"           # tip (leading edge)
                elif row == phase - 1:
                    buf[dc] = "│"           # body
                elif row == phase - 2:
                    buf[dc] = "╎"           # faint trail
            elif phase == h and row == h - 1:
                buf[dc] = "˜"              # splash on landing

    elif mood == "energetic":
        # Single pulsing bar at margin center; height driven by sine
        col = max(0, w // 2)
        bar_h = max(1, int(abs(_math.sin(t * 0.3 + side * 1.8)) * h * 0.7))
        if row >= h - bar_h:
            frac = (row - (h - bar_h)) / max(1, bar_h)
            buf[col] = "▌" if frac < 0.5 else "▎"

    elif mood == "romantic":
        # Sparkle blinks briefly every ~14 ticks, then fades
        period = 14
        seed = (side * 5 + row * 3) % period
        phase = (t + seed) % period
        if phase <= 1 and w > 0:
            col = max(0, min(w - 1, (side * 3 + row) % w))
            buf[col] = "✦" if phase == 0 else "·"

    elif mood == "nostalgic":
        # Sand-painting: particles fall, accumulate into slowly-shifting dune
        base = max(1, h // 3)
        amp  = max(1, h // 5)
        for col in range(w):
            pile_h = (base
                      + int(_math.sin(col * 0.9 + t * 0.015) * amp)
                      + int(_math.sin(col * 0.4 + t * 0.008) * amp * 0.5))
            pile_h = max(1, min(h - 1, pile_h))
            pile_top = h - pile_h          # first row of the pile (0-indexed)
            depth = row - pile_top         # how many rows into the pile
            if row >= pile_top:
                # Pile zone
                if depth == 0:
                    buf[col] = "▒"         # surface
                elif depth < pile_h * 0.5:
                    buf[col] = "▓"         # mid pile
                else:
                    buf[col] = "█"         # deep pile
            else:
                # Particle zone: falling grain 1-2 rows above pile top
                rows_above = pile_top - row
                fall_period = h + 3
                particle_row = (t + col * 3 + side * 11) % fall_period
                if rows_above <= 2 and particle_row == row:
                    buf[col] = "░"

    return "".join(buf)


def _pad_to(label: str, width: int) -> str:
    """Pad label to exactly `width` display columns (CJK-aware)."""
    dw = _cjk_width(label)
    return label + " " * max(0, width - dw)


def _pad_label(label: str) -> str:
    return _pad_to(label, _LABEL_W)


def _lyric_panel_lines(
    lrc: list[tuple[float, str]],
    current_idx: Optional[int],
    panel_h: int,
    lw: int,
    anim_t: int = 0,
    mood: str = "calm",
) -> list[str]:
    """
    Build panel_h ANSI-formatted lyric lines (each exactly lw display cols).
    Current line at row 3 (0-based), highlighted bold sky-blue; context lines dimmed.
    Margin space left/right of each lyric line is filled with sparse mood animation.
    """
    _CURR_ROW = 3  # current line always at this position in the panel

    def _fmt_lrc_line(text: str, style: str, row: int) -> str:
        clean = _clean(text.strip())
        trunc = _truncate(clean, lw - 2) if _cjk_width(clean) > lw - 2 else clean
        tw = _cjk_width(trunc)
        left_w = max(0, (lw - tw) // 2)
        right_w = max(0, lw - tw - left_w)
        left_anim  = _anim_margin_str(mood, anim_t, row, panel_h, left_w, 0)
        right_anim = _anim_margin_str(mood, anim_t, row, panel_h, right_w, 1)
        lyric_part = f"{style}{trunc}{_R}" if style else trunc
        return f"{_D}{left_anim}{_R}{lyric_part}{_D}{right_anim}{_R}"

    lines: list[str] = []
    for row in range(panel_h):
        lrc_i = (current_idx - _CURR_ROW + row) if current_idx is not None else None
        if lrc_i is None or lrc_i < 0 or lrc_i >= len(lrc):
            # Empty row: animation spans the full width
            lines.append(f"{_D}{_anim_margin_str(mood, anim_t, row, panel_h, lw, 0)}{_R}")
        elif lrc_i == current_idx:
            lines.append(_fmt_lrc_line(lrc[lrc_i][1], _PL, row))
        elif lrc_i < current_idx:
            lines.append(_fmt_lrc_line(lrc[lrc_i][1], _D, row))
        else:
            lines.append(_fmt_lrc_line(lrc[lrc_i][1], "", row))
    return lines


def _draw_lyric_panel(
    lrc: list[tuple[float, str]],
    current_idx: Optional[int],
    plw: int,
    lw: int,
    vh: int,
    anim_t: int = 0,
    mood: str = "calm",
) -> None:
    """Redraw the right lyric column in-place using cursor positioning."""
    lyric_lines = _lyric_panel_lines(lrc, current_idx, vh, lw, anim_t, mood)
    col_offset = plw + 2
    buf = []
    for rel in range(vh):
        lines_up = 3 + vh - rel
        buf.append(
            f"\033[s\033[{lines_up}A\r\033[{col_offset}C"
            f"{lyric_lines[rel]}"
            f"\033[u"
        )
    sys.stdout.write("".join(buf))
    sys.stdout.flush()


def _lyric_label(artist: str, lyric: str, off: int) -> str:
    """Build a _LABEL_W-col label: artist_fixed · lyric_marquee."""
    _A_W = 18   # artist column display width
    _S_W = 3    # separator " · "
    _L_W = _LABEL_W - _A_W - _S_W  # lyric marquee width (= 60-18-3 = 39)

    a = _clean(artist.strip())
    a = re.sub(r"\s+", " ", a).strip()
    a_disp = _truncate(a, _A_W + 3) if _cjk_width(a) > _A_W else a
    a_pad = a_disp + " " * max(0, _A_W - _cjk_width(a_disp))

    # CJK-aware marquee slice
    padded = lyric + "    "
    pw = _cjk_width(padded)
    col_off = off % max(1, pw)
    result, rw, cur = "", 0, 0
    for c in (padded + padded):
        cw = 2 if _cjk_width(c) == 2 else 1
        if cur < col_off:
            cur += cw; continue
        if rw + cw > _L_W:
            break
        result += c; rw += cw
    lyric_part = result + " " * max(0, _L_W - rw)

    return a_pad + " · " + lyric_part


def _track_inner_vis(i: int, playing: bool, cursored: bool, tracks: list[Track],
                     lyric_line: Optional[str] = None, lyric_off: int = 0,
                     panel_open: bool = False, label_width: int = _LABEL_W,
                     pos: Optional[float] = None, duration: float = 0) -> str:
    """Visible text (no ANSI) for a track row."""
    num = "▶" if playing else ("›" if cursored else str(i + 1))
    if playing and panel_open and pos is not None and duration > 0:
        # Progress bar stretches to fill available label space
        time_str = f"{_fmt_dur(int(pos))}/{_fmt_dur(int(duration))}"
        title_reserve = min(20, max(6, label_width // 5))
        bar_w = max(8, label_width - len(time_str) - 4 - title_reserve - 2)
        prog = _fmt_progress(pos, duration, bar_w)
        prog_w = len(prog)
        title_w = max(4, label_width - prog_w - 2)
        lbl = _make_label(tracks[i], width=title_w)
        label = prog + "  " + _pad_to(lbl, label_width - prog_w - 2)
    elif playing and lyric_line and not panel_open:
        label = _lyric_label(tracks[i].artist, lyric_line, lyric_off)
    else:
        lbl = _make_label(tracks[i], width=max(10, label_width - 4))
        label = _pad_to(lbl, label_width)
    dur = _fmt_dur(tracks[i].duration_seconds)
    return f"  {num:>3}  {label}  {dur:>8}   "


def _track_inner_disp(i: int, playing: bool, paused: bool, cursored: bool, tracks: list[Track],
                      lyric_line: Optional[str] = None, lyric_off: int = 0,
                      panel_open: bool = False, label_width: int = _LABEL_W,
                      pos: Optional[float] = None, duration: float = 0) -> str:
    """Display text (with ANSI) for a track row."""
    num = "▶" if playing else ("›" if cursored else str(i + 1))
    if playing and panel_open and pos is not None and duration > 0:
        time_str = f"{_fmt_dur(int(pos))}/{_fmt_dur(int(duration))}"
        title_reserve = min(20, max(6, label_width // 5))
        bar_w = max(8, label_width - len(time_str) - 4 - title_reserve - 2)
        prog = _fmt_progress(pos, duration, bar_w)
        prog_w = len(prog)
        title_w = max(4, label_width - prog_w - 2)
        lbl = _make_label(tracks[i], width=title_w)
        label = f"{_D}{prog}{_R}  " + _pad_to(lbl, label_width - prog_w - 2)
    elif playing and lyric_line and not panel_open:
        label = _lyric_label(tracks[i].artist, lyric_line, lyric_off)
    else:
        lbl = _make_label(tracks[i], width=max(10, label_width - 4))
        label = _pad_to(lbl, label_width)
    dur = _fmt_dur(tracks[i].duration_seconds)
    dur_s = f"{_D}{dur:>8}{_R}"

    if playing and paused:
        return f"  {_PP}{num:>3}{_R}  {_PP}{label}{_R}  {dur_s}   "
    elif playing:
        return f"  {_PL}{num:>3}{_R}  {_PL}{label}{_R}  {dur_s}   "
    elif cursored:
        return f"  {_CU}\033[4m{num:>3}{_R}  {_CU}{label}{_R}  {dur_s}   "
    else:
        return f"  {_D}{num:>3}{_R}  {label}  {dur_s}   "


def _box_row(vis: str, disp: str, inner_width: int = _IW) -> str:
    """Wrap content in │...│, padding to inner_width display cols."""
    vis_dw = _cjk_width(vis)
    pad = max(0, inner_width - vis_dw)
    return f"│{disp}{' ' * pad}│"


# ---------------------------------------------------------------------------
# Main player
# ---------------------------------------------------------------------------

def play_playlist(playlists: list[dict], active_idx: int = 0) -> None:
    """Play playlists with tab switching support.

    Each dict in playlists must have: name (str), tracks (list[Track]), prompt (str).
    active_idx selects the initially active playlist.
    """
    if not playlists:
        print("No playlists available.")
        return

    # Unpack active playlist
    playlist_name: str = playlists[active_idx]["name"]
    tracks: list[Track] = list(playlists[active_idx]["tracks"])
    prompt: str = playlists[active_idx]["prompt"]

    if not tracks:
        print("Playlist is empty.")
        return

    n = len(tracks)
    vh = min(_VIEW_H, n)   # actual viewport height
    view_start = [0]        # first visible track index (mutable ref)
    current_idx = 0
    cursor_idx  = 0
    paused      = False
    _lyric: dict = {"line": None, "off": 0, "idx": None, "pos": None,
                    "mood": "calm", "anim_t": 0}   # shared lyric state
    lyric_panel_on: bool = False
    _panel_widths: Optional[tuple[int, int, int]] = None
    _appending = [False]   # True while background append is running
    _switch_tab = [0]      # 0=no switch, -1=prev, +1=next

    # ── viewport helpers ──────────────────────────────────────────────────────

    def _lines_up(rel: int) -> int:
        """Lines from status line up to track at viewport-relative position rel."""
        return 3 + vh - rel

    def _row_for(idx: int) -> Optional[int]:
        """Return viewport-relative row for track idx, or None if off-screen."""
        rel = idx - view_start[0]
        return rel if 0 <= rel < vh else None

    def _draw_track(idx: int, playing: bool, is_paused: bool, cursored: bool) -> None:
        rel = _row_for(idx)
        if rel is None:
            return
        if lyric_panel_on and _panel_widths:
            _, plw, lw = _panel_widths
            lbl_w = max(10, plw - 20)
            p   = _lyric["pos"] if playing else None
            dur = tracks[idx].duration_seconds if playing else 0
            vis  = _track_inner_vis(idx, playing, cursored, tracks, None, 0, True, lbl_w,
                                    p, dur)
            disp = _track_inner_disp(idx, playing, is_paused, cursored, tracks,
                                     None, 0, True, lbl_w, p, dur)
            row_pad = max(0, plw - _cjk_width(vis))
            # Write only the left column; cursor stops at │ so lyric column is untouched
            row = f"│{disp}{' ' * row_pad}│"
        else:
            ll = _lyric["line"] if playing else None
            lo = _lyric["off"]  if playing else 0
            vis  = _track_inner_vis(idx, playing, cursored, tracks, ll, lo, False)
            disp = _track_inner_disp(idx, playing, is_paused, cursored, tracks, ll, lo, False)
            row = _box_row(vis, disp)
        sys.stdout.write(f"\033[s\033[{_lines_up(rel)}A\r{row}\033[u")

    def _redraw_viewport() -> None:
        """Redraw all visible track rows in place."""
        if lyric_panel_on and _panel_widths:
            _, plw, lw = _panel_widths
            _full_repaint(True, plw, lw)
            return
        for rel in range(vh):
            idx = view_start[0] + rel
            _draw_track(idx, idx == current_idx, paused and idx == current_idx,
                        idx == cursor_idx)
        sys.stdout.flush()

    def _scroll_to(idx: int) -> bool:
        """Shift view so idx is visible. Return True if view changed."""
        vs = view_start[0]
        if idx < vs:
            view_start[0] = idx
        elif idx >= vs + vh:
            view_start[0] = idx - vh + 1
        else:
            return False
        return True

    def _update_header() -> None:
        """Rewrite header to show current page range."""
        if lyric_panel_on:
            return  # handled by _full_repaint when panel is open
        nt = len(tracks)
        a, b = view_start[0] + 1, min(nt, view_start[0] + vh)
        page_info = f"{a}-{b}/{nt}" if nt > vh else f"{nt} tracks"
        lft = "  ♫ myplaylist  "
        rgt_vis  = f"  {playlist_name} ({page_info})  "
        rgt_disp = f"  {_YL}{playlist_name}{_R} ({page_info})  "
        hpad = max(0, _IW - len(lft) - _cjk_width(rgt_vis))
        hdr_vis  = f"{lft}{' ' * hpad}{rgt_vis}"
        hdr_disp = f"  {_B}{_CY}♫ myplaylist{_R}  " + " " * hpad + rgt_disp
        lines_up = 3 + vh + 2   # up: _BOT, ctrl, mid, vh tracks, mid, header
        sys.stdout.write(
            f"\033[s\033[{lines_up}A\r{_box_row(hdr_vis, hdr_disp)}\033[u"
        )
        sys.stdout.flush()

    def _full_repaint(panel_open: bool, plw: int, lw: int) -> None:
        """Clear current box area and redraw from scratch."""
        NL = "\033[K\r\n"  # clear-to-EOL + newline (handles width changes)
        total_iw = plw + 1 + lw if panel_open else _IW_NORMAL
        # Move cursor up to the blank line above the box
        # Structure: blank(1)+top(1)+hdr(1)+mid(1)+vh+mid/sep(1)+ctrl(1)+bot(1) = vh+7
        sys.stdout.write(f"\033[{vh + 7}A\r")

        nt = len(tracks)
        a, b = view_start[0] + 1, min(nt, view_start[0] + vh)
        page_info = f"{a}-{b}/{nt}" if nt > vh else f"{nt} tracks"
        lft = "  ♫ myplaylist  "
        rgt_vis  = f"  {playlist_name} ({page_info})  "
        rgt_disp = f"  {_YL}{playlist_name}{_R} ({page_info})  "

        if not panel_open:
            hpad = max(0, _IW_NORMAL - len(lft) - _cjk_width(rgt_vis))
            hdr_vis  = f"{lft}{' ' * hpad}{rgt_vis}"
            hdr_disp = f"  {_B}{_CY}♫ myplaylist{_R}  " + " " * hpad + rgt_disp
            ctrl_vis, ctrl_disp = _ctrl_bar(_IW_NORMAL, False)
            ctrl_pad  = max(0, _IW_NORMAL - _cjk_width(ctrl_vis))
            lines = [
                NL,
                _TOP + NL,
                _box_row(hdr_vis, hdr_disp) + NL,
                _MID + NL,
            ]
            for rel in range(vh):
                idx = view_start[0] + rel
                ll = _lyric["line"] if idx == current_idx else None
                lo = _lyric["off"]  if idx == current_idx else 0
                vis  = _track_inner_vis(idx, idx == current_idx, idx == cursor_idx,
                                        tracks, ll, lo, False)
                disp = _track_inner_disp(idx, idx == current_idx,
                                         paused and idx == current_idx,
                                         idx == cursor_idx, tracks, ll, lo, False)
                lines.append(_box_row(vis, disp) + NL)
            lines += [_MID + NL, f"│{ctrl_disp}{' ' * ctrl_pad}│" + NL, _BOT + NL]
        else:
            lbl_w = max(10, plw - 20)
            hpad = max(0, plw - len(lft) - _cjk_width(rgt_vis))
            hdr_vis  = f"{lft}{' ' * hpad}{rgt_vis}"
            hdr_disp = f"  {_B}{_CY}♫ myplaylist{_R}  " + " " * hpad + rgt_disp
            hdr_pad  = max(0, plw - _cjk_width(hdr_vis))
            # Song title + artist in right-column header
            t = tracks[current_idx]
            title_raw = _clean(t.title.strip())
            artist_raw = _clean(t.artist.strip())
            sep = "  "
            max_title = lw - 4 - _cjk_width(sep) - _cjk_width(artist_raw)
            if max_title < 4:
                # artist too long, truncate it
                max_title = lw // 2 - 4
                artist_raw = _truncate(artist_raw, lw - max_title - 4 - _cjk_width(sep))
            title_short = (_truncate(title_raw, max_title)
                           if _cjk_width(title_raw) > max_title else title_raw)
            title_str = f" ♪ {title_short}{sep}{_D}{artist_raw}{_R}"
            title_vis = f" ♪ {title_short}{sep}{artist_raw}"
            title_pad = max(0, lw - _cjk_width(title_vis))
            # Lyric panel lines (with margin animation)
            lrc_idx = _lyric.get("idx")
            lyric_lines = _lyric_panel_lines(_active_lrc(), lrc_idx, vh, lw,
                                             _lyric["anim_t"], _lyric["mood"])
            ctrl_vis, ctrl_disp = _ctrl_bar(total_iw, True)
            ctrl_pad = max(0, total_iw - _cjk_width(ctrl_vis))
            lines = [
                NL,
                _panel_top(plw, lw) + NL,
                f"│{hdr_disp}{' ' * hdr_pad}│{title_str}{' ' * title_pad}│" + NL,
                _panel_mid(plw, lw) + NL,
            ]
            for rel in range(vh):
                idx = view_start[0] + rel
                is_playing = idx == current_idx
                p   = _lyric["pos"] if is_playing else None
                dur = tracks[idx].duration_seconds if is_playing else 0
                vis  = _track_inner_vis(idx, is_playing, idx == cursor_idx,
                                        tracks, None, 0, True, lbl_w, p, dur)
                disp = _track_inner_disp(idx, is_playing,
                                         paused and is_playing,
                                         idx == cursor_idx, tracks, None, 0, True, lbl_w,
                                         p, dur)
                row_pad = max(0, plw - _cjk_width(vis))
                lines.append(f"│{disp}{' ' * row_pad}│{lyric_lines[rel]}│" + NL)
            lines += [
                _panel_bot(plw, lw) + NL,
                f"│{ctrl_disp}{' ' * ctrl_pad}│" + NL,
                "└" + "─" * total_iw + "┘" + NL,
            ]
        sys.stdout.write("".join(lines))
        sys.stdout.flush()

    def _update_lyric_header() -> None:
        """Rewrite the right-column header (title + artist) in place."""
        if not (lyric_panel_on and _panel_widths):
            return
        _, plw, lw = _panel_widths
        t = tracks[current_idx]
        title_raw = _clean(t.title.strip())
        artist_raw = _clean(t.artist.strip())
        sep = "  "
        max_title = lw - 4 - _cjk_width(sep) - _cjk_width(artist_raw)
        if max_title < 4:
            max_title = lw // 2 - 4
            artist_raw = _truncate(artist_raw, lw - max_title - 4 - _cjk_width(sep))
        title_short = (_truncate(title_raw, max_title)
                       if _cjk_width(title_raw) > max_title else title_raw)
        title_str = f" ♪ {title_short}{sep}{_D}{artist_raw}{_R}"
        title_vis = f" ♪ {title_short}{sep}{artist_raw}"
        title_pad = max(0, lw - _cjk_width(title_vis))
        content = f"{title_str}{' ' * title_pad}"
        lines_up = 3 + vh + 2  # bot + ctrl + panel_bot + vh tracks + mid + header
        col_offset = plw + 2   # right column starts after │plw│
        sys.stdout.write(f"\033[s\033[{lines_up}A\r\033[{col_offset}C{content}\033[u")
        sys.stdout.flush()

    def _do_append() -> None:
        """Background: generate ~10 tracks similar to current song and append."""
        import io, contextlib
        try:
            from autoplaylist import discovery as _disc
            seed = f"{tracks[current_idx].artist} - {tracks[current_idx].title}"
            # Suppress all discovery progress prints so they don't corrupt the TUI
            with contextlib.redirect_stdout(io.StringIO()), \
                 contextlib.redirect_stderr(io.StringIO()):
                raw = _disc.discover_from_seed(seed, count=12)
            # Deduplicate against already-in-playlist tracks
            existing = {t.norm_key() for t in tracks}
            new = [t for t in raw if t.norm_key() not in existing][:10]
            if new:
                tracks.extend(new)
                _status(f"Added {len(new)} tracks  [{len(tracks)} total]")
                if lyric_panel_on and _panel_widths:
                    _, plw, lw = _panel_widths
                    _full_repaint(True, plw, lw)
                else:
                    _update_header()
            else:
                _status("No tracks found — try again later")
        except Exception as e:
            _status(f"Append failed: {str(e)[:60]}")
        finally:
            _appending[0] = False

    # ── initial box ───────────────────────────────────────────────────────────
    a0, b0 = 1, min(n, vh)
    page_info0 = f"{a0}-{b0}/{n}" if n > vh else f"{n} tracks"
    lft = "  ♫ myplaylist  "
    rgt_vis0  = f"  {playlist_name} ({page_info0})  "
    rgt_disp0 = f"  {_YL}{playlist_name}{_R} ({page_info0})  "
    hpad0 = max(0, _IW - len(lft) - _cjk_width(rgt_vis0))
    hdr_vis0  = f"{lft}{' ' * hpad0}{rgt_vis0}"
    hdr_disp0 = f"  {_B}{_CY}♫ myplaylist{_R}  " + " " * hpad0 + rgt_disp0

    ctrl_vis, ctrl_disp = _ctrl_bar(_IW, False)
    ctrl_pad  = max(0, _IW - _cjk_width(ctrl_vis))

    lines = [_NL, _TOP + _NL, _box_row(hdr_vis0, hdr_disp0) + _NL, _MID + _NL]
    for i in range(vh):
        vis  = _track_inner_vis(i, i == 0, i == 0, tracks)
        disp = _track_inner_disp(i, i == 0, False, i == 0, tracks)
        lines.append(_box_row(vis, disp) + _NL)
    lines += [_MID + _NL, f"│{ctrl_disp}{' ' * ctrl_pad}│" + _NL, _BOT + _NL]
    _w("".join(lines))

    # ── playback state ────────────────────────────────────────────────────────
    ytdlp_proc: Optional[subprocess.Popen] = None
    mpv_proc:   Optional[subprocess.Popen] = None
    key_reader  = _KeyReader()
    key_reader.start()

    _orig_sigint = signal.getsignal(signal.SIGINT)

    def stop_current() -> None:
        nonlocal ytdlp_proc, mpv_proc
        _mpv_quit()
        # Send SIGKILL to both first, then wait — avoids serial blocking
        if mpv_proc and mpv_proc.poll() is None:
            mpv_proc.kill()
        if ytdlp_proc and ytdlp_proc.poll() is None:
            ytdlp_proc.kill()
        if mpv_proc:
            mpv_proc.wait()
        if ytdlp_proc:
            ytdlp_proc.wait()
        mpv_proc = ytdlp_proc = None

    def _sigint_handler(signum, frame):
        key_reader.stop(); stop_current(); _restore_terminal()
        signal.signal(signal.SIGINT, _orig_sigint)
        sys.stdout.write(_NL); raise KeyboardInterrupt
    signal.signal(signal.SIGINT, _sigint_handler)

    def _status(text: str) -> None:
        sys.stdout.write(f"\r{_D}♪{_R}  {text:<70}"); sys.stdout.flush()

    def _jump_to(target: int) -> None:
        nonlocal current_idx, cursor_idx, paused
        stop_current()
        old = current_idx
        current_idx = cursor_idx = target
        paused = False
        _lyric["line"] = None; _lyric["off"] = 0; _lyric["idx"] = None; _lyric["pos"] = None; _lyric["mood"] = "calm"; _lyric["anim_t"] = 0
        if _scroll_to(target):
            _redraw_viewport()
            _update_header()
        else:
            _draw_track(old, False, False, old == cursor_idx)
            _draw_track(target, True, False, True)
            sys.stdout.flush()
        _update_lyric_header()

    try:
        while True:
            # ── tab switch ────────────────────────────────────────────────────
            if _switch_tab[0] != 0:
                old_vh = vh
                active_idx = (active_idx + _switch_tab[0]) % len(playlists)
                _switch_tab[0] = 0
                playlist_name = playlists[active_idx]["name"]
                tracks = list(playlists[active_idx]["tracks"])
                prompt = playlists[active_idx]["prompt"]
                n = len(tracks)
                vh = min(_VIEW_H, n)
                view_start[0] = 0
                current_idx = 0
                cursor_idx = 0
                paused = False
                _lyric.update({"line": None, "off": 0, "idx": None,
                               "pos": None, "mood": "calm", "anim_t": 0})
                lyric_panel_on = False
                _panel_widths = None
                _appending[0] = False
                # Repaint: erase old box + redraw new
                NL = "\033[K\r\n"
                sys.stdout.write(f"\033[{old_vh + 7}A\r\033[J")
                nt = n
                a0, b0 = 1, min(nt, vh)
                page_info0 = f"{a0}-{b0}/{nt}" if nt > vh else f"{nt} tracks"
                lft0 = "  ♫ myplaylist  "
                rgt_vis0  = f"  {playlist_name} ({page_info0})  "
                rgt_disp0 = f"  {_YL}{playlist_name}{_R} ({page_info0})  "
                hpad0 = max(0, _IW - len(lft0) - _cjk_width(rgt_vis0))
                hdr_vis0  = f"{lft0}{' ' * hpad0}{rgt_vis0}"
                hdr_disp0 = (f"  {_B}{_CY}♫ myplaylist{_R}  "
                             + " " * hpad0 + rgt_disp0)
                ctrl_vis, ctrl_disp = _ctrl_bar(_IW, False)
                ctrl_pad = max(0, _IW - _cjk_width(ctrl_vis))
                lines = [NL, _TOP + NL, _box_row(hdr_vis0, hdr_disp0) + NL, _MID + NL]
                for i in range(vh):
                    vis  = _track_inner_vis(i, i == 0, i == 0, tracks)
                    disp = _track_inner_disp(i, i == 0, False, i == 0, tracks)
                    lines.append(_box_row(vis, disp) + NL)
                lines += [_MID + NL, f"│{ctrl_disp}{' ' * ctrl_pad}│" + NL, _BOT + NL]
                _w("".join(lines))
                sys.stdout.flush()

            if current_idx >= len(tracks):
                current_idx = 0
                cursor_idx = 0
                _lyric["line"] = None; _lyric["off"] = 0; _lyric["idx"] = None; _lyric["pos"] = None; _lyric["mood"] = "calm"; _lyric["anim_t"] = 0
                if _scroll_to(0):
                    _redraw_viewport(); _update_header()
                _update_lyric_header()
            label = _make_label(tracks[current_idx], 55)
            cursor_idx = current_idx
            _status(f"Loading  {label}")
            ytdlp_proc, mpv_proc = _launch_mpv(tracks[current_idx].youtube_url)

            # Fetch lyrics candidates in background while track loads
            from autoplaylist import lyrics as _lyr
            _lrc_candidates: list[list[tuple[float, str]]] = []
            _lrc_idx = [0]     # index into _lrc_candidates (mutable ref)
            _lrc_ready = [False]

            def _active_lrc() -> list[tuple[float, str]]:
                if _lrc_candidates and _lrc_idx[0] < len(_lrc_candidates):
                    return _lrc_candidates[_lrc_idx[0]]
                return []

            def _fetch_lyrics(artist: str, title: str) -> None:
                candidates = _lyr.fetch_candidates(artist, title)
                _lrc_candidates.clear()
                _lrc_candidates.extend(candidates)
                _lrc_ready[0] = True

            _t = tracks[current_idx]
            _lrc_thread = threading.Thread(
                target=_fetch_lyrics, args=(_t.artist, _t.title), daemon=True
            )
            _lrc_thread.start()

            # Classify mood in background; result written to _lyric["mood"]
            from autoplaylist import llm as _llm_mod
            def _classify_mood_bg(artist: str, title: str) -> None:
                _lyric["mood"] = _llm_mod.classify_mood(artist, title)
            threading.Thread(
                target=_classify_mood_bg, args=(_t.artist, _t.title), daemon=True
            ).start()

            # Poll up to 3 s for mpv to start, but stay key-responsive
            _load_start = time.time()
            _load_skip = False
            _load_key: Optional[str] = None
            while time.time() - _load_start < 3.0:
                time.sleep(0.1)
                _load_key = key_reader.consume()
                if _load_key in ("[", "]", "q"):
                    break
                if mpv_proc.poll() is not None:
                    _load_skip = True
                    break

            if _load_key == "q":
                stop_current(); sys.stdout.write(_NL); return

            if _load_key in ("[", "]"):
                if len(playlists) == 1:
                    _status("Only one playlist")
                else:
                    try:
                        from autoplaylist import playlist as _pl
                        _pl.save(playlist_name, tracks, prompt)
                    except Exception:
                        pass
                    stop_current()
                    _switch_tab[0] = -1 if _load_key == "[" else 1
                continue

            if _load_skip or mpv_proc.poll() is not None:
                _status(f"Skipped  {label}")
                old = current_idx; current_idx += 1
                if current_idx < len(tracks):
                    cursor_idx = current_idx
                    if _scroll_to(current_idx):
                        _redraw_viewport(); _update_header()
                    else:
                        _draw_track(old, False, False, False)
                        _draw_track(current_idx, True, False, True)
                        sys.stdout.flush()
                    _update_lyric_header()
                continue

            _status(f"Playing  [{current_idx + 1}/{len(tracks)}]  {label}")

            # reset lyric state for new track
            _lyric["line"] = None
            _lyric["off"]  = 0
            _lyric["pos"]  = None
            _lyric["mood"] = "calm"
            _lyric["anim_t"] = 0
            num_buf = ""; num_ts = 0.0
            _last_pos_ts  = 0.0   # last mpv query time
            _last_step_ts = 0.0   # last marquee step time
            _prev_lrc_line: Optional[str] = None

            def _tick_lyric() -> None:
                """Advance marquee + update lyric line; redraw playing row."""
                nonlocal _last_pos_ts, _prev_lrc_line
                # Refresh position + lyric line from mpv every ~1 s
                now2 = time.time()
                if now2 - _last_pos_ts >= 1.0:
                    _last_pos_ts = now2
                    pos = _get_mpv_pos()
                    if pos is not None:
                        _lyric["pos"] = pos
                        _lrc = _active_lrc()
                        if _lrc_ready[0] and _lrc:
                            _lyric["line"] = _lyr.current_line(_lrc, pos)
                            # Track current lyric index for the panel
                            _lyric["idx"] = None
                            for j in range(len(_lrc) - 1, -1, -1):
                                if pos >= _lrc[j][0]:
                                    _lyric["idx"] = j
                                    break
                # Advance marquee offset (only when panel closed)
                if _lyric["line"] and not lyric_panel_on:
                    if _lyric["line"] != _prev_lrc_line:
                        _lyric["off"] = 0
                        _prev_lrc_line = _lyric["line"]
                    pw = _cjk_width(_lyric["line"]) + 4
                    _lyric["off"] = (_lyric["off"] + 1) % max(1, pw)
                # Redraw the playing row in-place
                _draw_track(current_idx, True, paused, cursor_idx == current_idx)
                # Update lyric panel column if open
                if lyric_panel_on and _panel_widths:
                    _, plw, lw = _panel_widths
                    _lyric["anim_t"] += 1
                    _draw_lyric_panel(_active_lrc(), _lyric.get("idx"), plw, lw, vh,
                                      _lyric["anim_t"], _lyric["mood"])
                sys.stdout.flush()

            while True:
                time.sleep(0.1)
                now = time.time()

                # Advance lyric marquee every 0.3 s
                if now - _last_step_ts >= 0.3:
                    _last_step_ts = now
                    if not num_buf:
                        _tick_lyric()

                if num_buf and now - num_ts > 1.5:
                    target = int(num_buf) - 1; num_buf = ""
                    if 0 <= target < len(tracks) and target != current_idx:
                        _jump_to(target); break
                    _status(f"Playing  [{current_idx + 1}/{len(tracks)}]  {label}")

                key = key_reader.consume()
                if key == "q":
                    stop_current(); sys.stdout.write(_NL); return

                elif key == "p":
                    paused = not paused; _mpv_pause(paused)
                    state = "Paused " if paused else "Playing"
                    _status(f"{state}  [{current_idx + 1}/{len(tracks)}]  {label}")
                    _draw_track(current_idx, True, paused, cursor_idx == current_idx)
                    sys.stdout.flush()

                elif key == "l":
                    if not lyric_panel_on:
                        pw = _compute_panel_widths()
                        if pw is None:
                            _status("Terminal too narrow for lyrics panel")
                        else:
                            lyric_panel_on = True
                            _panel_widths = pw
                            _, plw, lw = pw
                            _full_repaint(True, plw, lw)
                            _status(f"Playing  [{current_idx + 1}/{len(tracks)}]  {label}")
                    else:
                        lyric_panel_on = False
                        _panel_widths = None
                        _full_repaint(False, _IW_NORMAL, 0)
                        _status(f"Playing  [{current_idx + 1}/{len(tracks)}]  {label}")

                elif key == "+":
                    if _appending[0]:
                        _status("Already fetching…")
                    else:
                        _appending[0] = True
                        _status("Fetching more…")
                        threading.Thread(target=_do_append, daemon=True).start()

                elif key == "d":
                    del_idx = cursor_idx
                    if len(tracks) == 1:
                        stop_current()
                        sys.stdout.write(_NL)
                        print("Playlist is now empty.")
                        return
                    deleted_playing = (del_idx == current_idx)
                    tracks.pop(del_idx)
                    # Fix up indices: any index > del_idx decrements by 1
                    if current_idx > del_idx:
                        current_idx -= 1
                    new_cursor = cursor_idx - 1 if cursor_idx > del_idx else cursor_idx
                    cursor_idx = min(new_cursor, len(tracks) - 1)
                    if deleted_playing:
                        stop_current()
                        current_idx = min(del_idx, len(tracks) - 1)
                        cursor_idx = current_idx
                        paused = False
                        break
                    else:
                        _scroll_to(cursor_idx)
                        _redraw_viewport(); _update_header()
                        _status(f"Deleted  [{len(tracks)} tracks remain]")

                elif key == "s":
                    try:
                        from autoplaylist import playlist as _pl
                        _pl.save(playlist_name, tracks, prompt)
                        _status(f"Saved  {playlist_name}  [{len(tracks)} tracks]")
                    except Exception as e:
                        _status(f"Save failed: {str(e)[:60]}")

                elif key == "y":
                    n_cands = len(_lrc_candidates)
                    if n_cands == 0:
                        _status("No lyrics available")
                    elif n_cands == 1:
                        _status("Lyrics 1/1  (only source)")
                    else:
                        _lrc_idx[0] = (_lrc_idx[0] + 1) % n_cands
                        _lyric["line"] = None
                        _lyric["off"] = 0
                        _lyric["idx"] = None
                        if lyric_panel_on and _panel_widths:
                            _, plw, lw = _panel_widths
                            _draw_lyric_panel(_active_lrc(), None, plw, lw, vh,
                                              _lyric["anim_t"], _lyric["mood"])
                            sys.stdout.flush()
                        _status(f"Lyrics {_lrc_idx[0] + 1}/{n_cands}")

                elif key in ("[", "]"):
                    if len(playlists) == 1:
                        _status("Only one playlist")
                    else:
                        try:
                            from autoplaylist import playlist as _pl
                            _pl.save(playlist_name, tracks, prompt)
                        except Exception:
                            pass
                        stop_current()
                        _switch_tab[0] = -1 if key == "[" else 1
                        break

                elif key == "n":
                    stop_current(); old = current_idx; current_idx += 1; paused = False
                    if current_idx < len(tracks):
                        cursor_idx = current_idx
                        if _scroll_to(current_idx):
                            _redraw_viewport(); _update_header()
                        else:
                            _draw_track(old, False, False, False)
                            _draw_track(current_idx, True, False, True)
                            sys.stdout.flush()
                        _update_lyric_header()
                    break

                elif key == "UP":
                    new_cur = max(0, cursor_idx - 1)
                    if new_cur != cursor_idx:
                        old_cur = cursor_idx; cursor_idx = new_cur
                        if _scroll_to(new_cur):
                            _redraw_viewport(); _update_header()
                        else:
                            _draw_track(old_cur, old_cur == current_idx,
                                        paused and old_cur == current_idx, False)
                            _draw_track(new_cur, new_cur == current_idx,
                                        paused and new_cur == current_idx, True)
                            sys.stdout.flush()
                        _status(f"Select   [{new_cur + 1}/{len(tracks)}]  {_make_label(tracks[new_cur], 55)}")

                elif key == "DOWN":
                    new_cur = min(len(tracks) - 1, cursor_idx + 1)
                    if new_cur != cursor_idx:
                        old_cur = cursor_idx; cursor_idx = new_cur
                        if _scroll_to(new_cur):
                            _redraw_viewport(); _update_header()
                        else:
                            _draw_track(old_cur, old_cur == current_idx,
                                        paused and old_cur == current_idx, False)
                            _draw_track(new_cur, new_cur == current_idx,
                                        paused and new_cur == current_idx, True)
                            sys.stdout.flush()
                        _status(f"Select   [{new_cur + 1}/{len(tracks)}]  {_make_label(tracks[new_cur], 55)}")

                elif key == "RIGHT":
                    new_vs = min(len(tracks) - vh, view_start[0] + vh)
                    new_cur = min(len(tracks) - 1, new_vs)
                    if new_vs != view_start[0]:
                        cursor_idx = new_cur
                        view_start[0] = new_vs
                        _redraw_viewport(); _update_header()
                        _status(f"Select   [{new_cur + 1}/{len(tracks)}]  {_make_label(tracks[new_cur], 55)}")

                elif key == "LEFT":
                    new_vs = max(0, view_start[0] - vh)
                    new_cur = new_vs
                    if new_vs != view_start[0]:
                        cursor_idx = new_cur
                        view_start[0] = new_vs
                        _redraw_viewport(); _update_header()
                        _status(f"Select   [{new_cur + 1}/{len(tracks)}]  {_make_label(tracks[new_cur], 55)}")

                elif key in ("\r", "\n"):
                    if num_buf:
                        target = int(num_buf) - 1; num_buf = ""
                    else:
                        target = cursor_idx
                    if 0 <= target < len(tracks) and target != current_idx:
                        _jump_to(target); break
                    num_buf = ""; _status(f"Playing  [{current_idx + 1}/{len(tracks)}]  {label}")

                elif key and key.isdigit():
                    num_buf = (num_buf + key) if num_buf and now - num_ts < 1.5 else key
                    num_ts = now
                    _status(f"Goto     [{num_buf}]  — add digits or Enter")

                if mpv_proc and mpv_proc.poll() is not None:
                    old = current_idx; current_idx += 1
                    if current_idx < len(tracks):
                        cursor_idx = current_idx
                        if _scroll_to(current_idx):
                            _redraw_viewport(); _update_header()
                        else:
                            _draw_track(old, False, False, False)
                            _draw_track(current_idx, True, False, True)
                            sys.stdout.flush()
                        _update_lyric_header()
                    break

    finally:
        signal.signal(signal.SIGINT, _orig_sigint)
        key_reader.stop()
        stop_current()
        _restore_terminal()
        sys.stdout.write(_NL)

