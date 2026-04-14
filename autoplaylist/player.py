from __future__ import annotations

import json
import os
import queue
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
_CTL_SOCK = f"/tmp/myplaylist-{_getpass.getuser()}-ctl.sock"

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
# yt-dlp path + browser cookie detection
# ---------------------------------------------------------------------------

import pathlib
import re
import shutil


def _find_browser() -> str | None:
    """Return a browser name for yt-dlp --cookies-from-browser, or None.

    Even when yt-dlp can't decrypt the cookies (e.g. Chrome v10 on macOS),
    passing --cookies-from-browser changes yt-dlp's client strategy and
    bypasses YouTube bot-check. Firefox is preferred because its cookies
    are readable on macOS (plain SQLite, no Keychain). Safari is excluded
    because macOS sandboxing causes a hard 'Operation not permitted' error.
    """
    system = os.uname().sysname
    if system == "Darwin":
        candidates = [
            ("firefox", "/Applications/Firefox.app"),
            ("chrome",  "/Applications/Google Chrome.app"),
            ("edge",    "/Applications/Microsoft Edge.app"),
            ("brave",   "/Applications/Brave Browser.app"),
            ("chromium","/Applications/Chromium.app"),
        ]
        for name, path in candidates:
            if pathlib.Path(path).exists():
                return name
    else:
        for name, cmd in [
            ("chrome",   "google-chrome"),
            ("chrome",   "google-chrome-stable"),
            ("chromium", "chromium-browser"),
            ("chromium", "chromium"),
            ("firefox",  "firefox"),
            ("edge",     "microsoft-edge"),
        ]:
            if shutil.which(cmd):
                return name
    return None


_browser_cache: str | None | bool = False  # False = not yet probed


def _get_browser() -> str | None:
    global _browser_cache
    if _browser_cache is False:
        _browser_cache = _find_browser()
    return _browser_cache  # type: ignore[return-value]



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

_LOG_FILE = pathlib.Path.home() / ".myplaylist" / "player.log"


def _video_id(url: str) -> str | None:
    """Extract YouTube video ID from a watch or short URL."""
    import re as _re
    m = _re.search(r"[?&]v=([A-Za-z0-9_-]{11})", url)
    if m:
        return m.group(1)
    m = _re.search(r"youtu\.be/([A-Za-z0-9_-]{11})", url)
    if m:
        return m.group(1)
    return None


def _launch_mpv(
    youtube_url: str,
    debug: bool = False,
) -> tuple[subprocess.Popen | None, subprocess.Popen]:
    if os.path.exists(_IPC_SOCK):
        os.unlink(_IPC_SOCK)
    ytdlp_path = _find_ytdlp()

    if debug:
        _LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        log_fh = open(_LOG_FILE, "a")
        import datetime
        log_fh.write(f"\n--- {datetime.datetime.now().isoformat()} ---\n")
        log_fh.write(f"yt-dlp: {ytdlp_path}\n")
        log_fh.write(f"url:    {youtube_url}\n")
        log_fh.flush()
        ytdlp_stderr = log_fh
        mpv_stderr = log_fh
    else:
        log_fh = None
        ytdlp_stderr = subprocess.DEVNULL
        mpv_stderr = subprocess.DEVNULL

    from autoplaylist import config as _cfg
    cookie_file = _cfg.get("cookie_file")
    if cookie_file and pathlib.Path(cookie_file).exists():
        cookie_args = ["--cookies", cookie_file]
        cookie_source = f"file:{cookie_file}"
    else:
        browser = _get_browser()
        cookie_args = ["--cookies-from-browser", browser] if browser else []
        cookie_source = f"browser:{browser}" if browser else "none"

    if debug and log_fh:
        log_fh.write(f"cookies: {cookie_source}\n")

    # ── cache check ──────────────────────────────────────────────────────────
    from autoplaylist import cache as _cache
    _cache_enabled = int(_cfg.get("cache_max_mb", 500)) > 0
    vid = _video_id(youtube_url) if _cache_enabled else None
    cached = _cache.get_cached_audio(vid) if vid else None

    if cached:
        if debug and log_fh:
            log_fh.write(f"cache:  HIT {cached}\n")
            log_fh.flush()
        _cache.touch_audio(vid)
        mpv_proc = subprocess.Popen(
            ["mpv", "--no-video", f"--input-ipc-server={_IPC_SOCK}", str(cached)]
            + ([] if debug else ["--really-quiet"]),
            stdout=log_fh if debug else subprocess.DEVNULL,
            stderr=mpv_stderr,
        )
        if log_fh:
            log_fh.close()
        return None, mpv_proc

    # ── stream (+ background cache write) ───────────────────────────────────
    if debug and log_fh:
        log_fh.write(f"cache:  MISS — streaming\n")
        log_fh.flush()

    ytdlp_proc = subprocess.Popen(
        [ytdlp_path, "-f", "bestaudio/best", "-o", "-", "--no-playlist",
         "--remote-components", "ejs:github"]
        + cookie_args
        + [youtube_url]
        + ([] if debug else ["--quiet"]),
        stdout=subprocess.PIPE,
        stderr=ytdlp_stderr,
    )

    if vid:
        # Tee: write to cache file while simultaneously feeding mpv via pipe
        _cache._ensure_dirs()
        tmp_path  = _cache.tmp_audio_path(vid)
        final_path = _cache.audio_path(vid)
        r_fd, w_fd = os.pipe()

        def _tee_worker() -> None:
            try:
                with open(tmp_path, "wb") as f:
                    while True:
                        data = ytdlp_proc.stdout.read(65536)
                        if not data:
                            break
                        f.write(data)
                        try:
                            os.write(w_fd, data)
                        except OSError:
                            break  # mpv was killed; stop writing
            except Exception:
                pass
            finally:
                try:
                    os.close(w_fd)
                except OSError:
                    pass
            # Finalise: rename if complete, else discard
            try:
                if tmp_path.exists() and tmp_path.stat().st_size >= _cache._MIN_AUDIO_BYTES:
                    tmp_path.rename(final_path)
                    _cache.evict_audio_if_needed()
                else:
                    tmp_path.unlink(missing_ok=True)
            except Exception:
                pass

        import threading as _threading
        _threading.Thread(target=_tee_worker, daemon=True).start()

        r_file = os.fdopen(r_fd, "rb")
        mpv_proc = subprocess.Popen(
            ["mpv", "--no-video", f"--input-ipc-server={_IPC_SOCK}", "-"]
            + ([] if debug else ["--really-quiet"]),
            stdin=r_file,
            stdout=log_fh if debug else subprocess.DEVNULL,
            stderr=mpv_stderr,
        )
        r_file.close()  # parent no longer needs read end; mpv inherited it
        # NOTE: do NOT close ytdlp_proc.stdout here; tee_worker reads from it
    else:
        mpv_proc = subprocess.Popen(
            ["mpv", "--no-video", f"--input-ipc-server={_IPC_SOCK}", "-"]
            + ([] if debug else ["--really-quiet"]),
            stdin=ytdlp_proc.stdout,
            stdout=log_fh if debug else subprocess.DEVNULL,
            stderr=mpv_stderr,
        )
        if ytdlp_proc.stdout:
            ytdlp_proc.stdout.close()

    if log_fh:
        log_fh.close()
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


def _mpv_seek(delta: float) -> None:
    """Send a relative seek to mpv via IPC. Caller is responsible for clamping."""
    _ipc_send(["seek", delta, "relative"])


def _mpv_seek_absolute(pos: float) -> None:
    _ipc_send(["seek", pos, "absolute"])


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
    sys.stdout.write("\033[?7h")  # re-enable auto-wrap
    sys.stdout.flush()
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
                         " [↵] play [q] quit [L] lyrics [+] more [d] del [s] save  [[] prev []] next  [y] lyrics src [Y] refresh  [,.] seek")
_CTRL_VIS_FULL_CLOSE = ("  [p] pause [n] next [↑↓] sel [←→] pg"
                         " [↵] play [q] quit [l] lyrics [+] more [d] del [s] save  [[] prev []] next  [y] lyrics src  [,.] seek")
# compact: symbols only, fits ≤ 80 (panel-closed box)
_CTRL_VIS_SHORT_OPEN  = "  [p]⏸  [n]⏭  [↑↓]  [←→]  [↵]▶  [q]✕  [L]♪  [+]  [d]✗  [s]↓  [[]←  []]→"
_CTRL_VIS_SHORT_CLOSE = "  [p]⏸  [n]⏭  [↑↓]  [←→]  [↵]▶  [q]✕  [l]♪  [+]  [d]✗  [s]↓  [[]←  []]→"


_MODE_ICON = {"seq": "→→", "repeat": "↺", "shuffle": "⇄"}

def _ctrl_bar(avail: int, panel_open: bool, mode: str = "seq") -> tuple[str, str]:
    """Return (ctrl_vis, ctrl_disp) for the control bar, adapting to available width."""
    Ld = f"{_D}[L]{_R}" if panel_open else f"{_D}[l]{_R}"
    icon = _MODE_ICON.get(mode, "→→")
    vis_full  = (_CTRL_VIS_FULL_OPEN  if panel_open else _CTRL_VIS_FULL_CLOSE) + f"  [r]{icon}"
    vis_short = (_CTRL_VIS_SHORT_OPEN if panel_open else _CTRL_VIS_SHORT_CLOSE) + f"  [r]{icon}"
    if avail >= _cjk_width(vis_full):
        vis = vis_full
        disp = (f"  {_D}[p]{_R} pause {_D}[n]{_R} next {_D}[↑↓]{_R} sel {_D}[←→]{_R} pg"
                f" {_D}[↵]{_R} play {_D}[q]{_R} quit {Ld} lyrics {_D}[+]{_R} more"
                f" {_D}[d]{_R} del {_D}[s]{_R} save"
                f"  {_D}[[]" f"{_R} prev {_D}[]]" f"{_R} next"
                f"  {_D}[y]{_R} lyrics src  {_D}[Y]{_R} refresh"
                f"  {_D}[,.]{_R} seek"
                f"  {_D}[r]{_R}{icon}")
    else:
        vis = vis_short
        disp = (f"  {_D}[p]{_R}⏸  {_D}[n]{_R}⏭  {_D}[↑↓]{_R}  {_D}[←→]{_R}"
                f"  {_D}[↵]{_R}▶  {_D}[q]{_R}✕  {Ld}♪  {_D}[+]{_R}  {_D}[d]{_R}✗  {_D}[s]{_R}↓"
                f"  {_D}[[]" f"{_R}←  {_D}[]]" f"{_R}→"
                f"  {_D}[r]{_R}{icon}")
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
        lu = 3 + vh - rel
        buf.append(
            f"\033[{lu}A\r\033[{col_offset}C"
            f"{lyric_lines[rel]}"
            f"\033[{lu}B\r"
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
                     panel_open: bool = False, label_width: int = -1,
                     pos: Optional[float] = None, duration: float = 0) -> str:
    """Visible text (no ANSI) for a track row."""
    if label_width < 0:
        label_width = _LABEL_W
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
                      panel_open: bool = False, label_width: int = -1,
                      pos: Optional[float] = None, duration: float = 0) -> str:
    """Display text (with ANSI) for a track row."""
    if label_width < 0:
        label_width = _LABEL_W
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


def _box_row(vis: str, disp: str, inner_width: int = -1) -> str:
    """Wrap content in │...│, padding to inner_width display cols."""
    if inner_width < 0:
        inner_width = _IW
    vis_dw = _cjk_width(vis)
    pad = max(0, inner_width - vis_dw)
    return f"│{disp}{' ' * pad}│"


# ---------------------------------------------------------------------------
# Player core — pure state container for a playback session.
#
# Step 1 of the decouple-player-core-ui change: migrate all mutable fields
# out of the play_playlist() closure into this class. No event loop, no
# command methods, no subscribers yet — those come in step 2. For now this
# is only a typed bag of state so that ownership of each field is explicit.
# ---------------------------------------------------------------------------

from dataclasses import dataclass, field
from typing import Any, Callable, Tuple


@dataclass(frozen=True)
class PlayerSnapshot:
    """Immutable snapshot of the fields UI rendering needs.

    Returned by ``PlayerCore.snapshot()``. Because the fields are copied
    (not aliased), UI code can hold a snapshot across redraws without
    worrying about core state changing underneath it.
    """
    playlist_name: str
    tracks_count: int
    current_idx: int
    cursor_idx: int
    view_start: int
    paused: bool
    play_mode: str
    vh: int
    lyric_line: Any
    lyric_pos: Any
    lyric_idx: Any
    lyric_mood: str
    lyric_panel_on: bool
    appending: bool
    active_playlist_idx: int


@dataclass
class PlayerCore:
    # ── session / playlist ──
    playlists: list[dict]
    active_idx: int
    debug: bool
    playlist_name: str = ""
    tracks: list = field(default_factory=list)
    prompt: str = ""
    n: int = 0
    vh: int = 0

    # ── playback cursor / ui cursor ──
    current_idx: int = 0
    cursor_idx: int = 0
    view_start: int = 0
    paused: bool = False
    play_mode: str = "seq"   # "seq" | "repeat" | "shuffle"

    # ── lyric state (shared dict, preserved shape for minimal diff) ──
    lyric: dict = field(default_factory=lambda: {
        "line": None, "off": 0, "idx": None, "pos": None,
        "mood": "calm", "anim_t": 0,
    })
    lrc_candidates: list = field(default_factory=list)
    lrc_idx: int = 0
    lrc_ready: bool = False
    last_pos_ts: float = 0.0
    last_step_ts: float = 0.0
    prev_lrc_line: Any = None

    # ── lyric panel ──
    lyric_panel_on: bool = False
    panel_widths: Any = None  # Optional[tuple[int,int,int]]

    # ── async coordination flags ──
    appending: bool = False
    switch_tab: int = 0   # -1 prev, 0 none, +1 next

    # ── playback backend handles ──
    ytdlp_proc: Any = None
    mpv_proc: Any = None

    # ── event loop plumbing (2b) ──
    # _cmd_q carries commands/internal signals into core.run().
    # _ui_q carries events back out to the UI main loop.
    # _watch_active guards the natural-mpv-exit watcher: True only while
    # the UI main loop wants passive auto-advance on current mpv_proc.
    _cmd_q: Any = None
    _ui_q: Any = None
    _stop_ev: Any = None
    _run_thread: Any = None
    _watch_active: bool = False
    _subscribers: Any = None

    def __post_init__(self) -> None:
        self._cmd_q = queue.Queue()
        self._ui_q = queue.Queue()
        self._stop_ev = threading.Event()
        self._subscribers = []

    def snapshot(self) -> PlayerSnapshot:
        """Return an immutable snapshot of UI-visible state.

        Safe to call from any thread; reads are racy (no lock) but each
        field read is atomic in CPython and snapshots are advisory — UI
        redraws on a timer anyway.
        """
        return PlayerSnapshot(
            playlist_name=self.playlist_name,
            tracks_count=len(self.tracks),
            current_idx=self.current_idx,
            cursor_idx=self.cursor_idx,
            view_start=self.view_start,
            paused=self.paused,
            play_mode=self.play_mode,
            vh=self.vh,
            lyric_line=self.lyric.get("line"),
            lyric_pos=self.lyric.get("pos"),
            lyric_idx=self.lyric.get("idx"),
            lyric_mood=self.lyric.get("mood", "calm"),
            lyric_panel_on=self.lyric_panel_on,
            appending=self.appending,
            active_playlist_idx=self.active_idx,
        )

    def subscribe(self, callback: Callable[[Tuple[Any, ...]], None]) -> None:
        """Register a listener for state-change events. Callbacks are
        invoked synchronously from whichever thread mutates state; they
        must be non-blocking and thread-safe (typical use: enqueue into
        a UI-side queue and return).
        """
        self._subscribers.append(callback)

    def _emit(self, event: Tuple[Any, ...]) -> None:
        """Notify all subscribers. Exceptions in callbacks are swallowed
        so one bad listener can't crash playback.
        """
        for cb in self._subscribers:
            try:
                cb(event)
            except Exception:
                pass

    def post(self, msg: Any) -> None:
        """Thread-safe: enqueue a message for core.run() to process."""
        self._cmd_q.put(msg)

    def arm_watcher(self) -> None:
        """Called by UI after launching mpv: enable passive-exit detection."""
        self._watch_active = True

    def disarm_watcher(self) -> None:
        """Called by UI before user-initiated stop_current(): silence watcher."""
        self._watch_active = False

    def start(self) -> None:
        """Spawn core.run() in a background thread."""
        self._run_thread = threading.Thread(target=self.run, daemon=True)
        self._run_thread.start()

    def shutdown(self) -> None:
        """Signal run() to exit and join."""
        self._stop_ev.set()
        self._cmd_q.put(("__stop__",))
        if self._run_thread is not None:
            self._run_thread.join(timeout=0.5)

    def run(self) -> None:
        """Event loop. Single writer for fields touched inside handlers.

        Currently handles:
        - Natural mpv exit detection (passive poll, gated by _watch_active).
          On detection, runs the auto-advance decision and posts a UI event:
            ("repeat",)  → UI should restart the same track
            ("next",)    → UI should break inner loop and load core.current_idx
          Lyric reset for repeat is done here (preserves prior behavior).
        """
        while not self._stop_ev.is_set():
            try:
                msg = self._cmd_q.get(timeout=0.1)
            except queue.Empty:
                msg = None
            if isinstance(msg, tuple) and msg and msg[0] == "__stop__":
                return
            # Passive mpv exit watcher
            if (self._watch_active
                    and self.mpv_proc is not None
                    and self.mpv_proc.poll() is not None):
                self._watch_active = False
                self._handle_track_ended()

    def _handle_track_ended(self) -> None:
        """Runs inside core.run() thread. Decides auto-advance, posts to _ui_q."""
        if self.play_mode == "repeat":
            self.lyric.update({"line": None, "off": 0, "idx": None,
                               "pos": None, "mood": "calm", "anim_t": 0})
            self._ui_q.put(("repeat",))
            return
        prev = self.current_idx
        nxt = self.pick_next_idx()
        if nxt is not None:
            self.current_idx = nxt
        else:
            self.current_idx = len(self.tracks)  # sentinel: seq off end
        self._ui_q.put(("next", prev))

    # ── command methods (2c) ──────────────────────────────────────────────
    # These are the UI's only path to mutate playback state. All are
    # synchronous (not yet queue-dispatched) — the contract is "UI never
    # writes core fields directly". Each method mutates state and issues
    # mpv IPC as needed; rendering is still the UI's job (commands return
    # whatever the UI needs to redraw).

    def stop_current(self) -> None:
        """Kill yt-dlp + mpv for the currently playing track. Disarms the
        passive exit watcher first to avoid a spurious auto-advance event.
        """
        self.disarm_watcher()
        _mpv_quit()
        if self.mpv_proc and self.mpv_proc.poll() is None:
            self.mpv_proc.kill()
        if self.ytdlp_proc and self.ytdlp_proc.poll() is None:
            self.ytdlp_proc.kill()
        if self.mpv_proc:
            self.mpv_proc.wait()
        if self.ytdlp_proc:
            self.ytdlp_proc.wait()
        self.mpv_proc = self.ytdlp_proc = None

    def toggle_pause(self) -> bool:
        """Flip paused state and issue mpv pause IPC. Returns new paused."""
        self.paused = not self.paused
        _mpv_pause(self.paused)
        if not self.paused:
            # Force immediate re-sync of lyric line/idx and reset marquee
            self.last_pos_ts = 0.0
            self.lyric["off"] = 0
            self.prev_lrc_line = None
        self._emit(("Paused" if self.paused else "Resumed",))
        return self.paused

    def set_mode(self, mode: str) -> None:
        """Set play mode. Caller is responsible for validation."""
        if mode in ("seq", "repeat", "shuffle"):
            self.play_mode = mode
            self._emit(("ModeChanged", mode))

    def cycle_mode(self) -> str:
        """Advance play mode seq → repeat → shuffle → seq. Returns new mode."""
        modes = ["seq", "repeat", "shuffle"]
        self.play_mode = modes[(modes.index(self.play_mode) + 1) % 3]
        self._emit(("ModeChanged", self.play_mode))
        return self.play_mode

    def seek_relative(self, delta: float) -> tuple[Optional[float], Optional[float]]:
        """Seek by ``delta`` seconds, clamped to [0, duration-1] to avoid
        auto-advance. Returns (new_pos, duration); either may be None if
        mpv position is unknown.
        """
        duration = None
        if self.tracks and 0 <= self.current_idx < len(self.tracks):
            duration = float(self.tracks[self.current_idx].duration_seconds or 0) or None
        cur_pos = self.lyric.get("pos")
        if cur_pos is None:
            cur_pos = _get_mpv_pos()
        if cur_pos is not None:
            new_pos = cur_pos + delta
            if new_pos < 0:
                new_pos = 0.0
            if duration is not None and new_pos > max(0.0, duration - 1.0):
                new_pos = max(0.0, duration - 1.0)
            _mpv_seek_absolute(new_pos)
        else:
            _mpv_seek(delta)
        # Re-query for a fresh pos (mpv may have clamped internally)
        new_pos_q = _get_mpv_pos()
        if new_pos_q is not None:
            self.lyric["pos"] = new_pos_q
        # Trigger immediate lyric resync on next tick
        self.last_pos_ts = 0.0
        self.prev_lrc_line = None
        return new_pos_q, duration

    def request_switch_tab(self, direction: int) -> None:
        """Request a playlist tab switch (-1 prev / +1 next). Calls
        stop_current() internally so the UI main loop picks it up cleanly.
        """
        self.stop_current()
        self.switch_tab = -1 if direction < 0 else 1
        self._emit(("TabSwitched", self.switch_tab))

    def select(self, target: int) -> int:
        """Move the cursor to ``target`` (clamped). Returns previous cursor.
        Does not touch current_idx.
        """
        old = self.cursor_idx
        if self.tracks:
            self.cursor_idx = max(0, min(len(self.tracks) - 1, target))
        if self.cursor_idx != old:
            self._emit(("CursorMoved", old, self.cursor_idx))
        return old

    def jump_to(self, target: int) -> int:
        """Stop current track and start playing ``target``. Resets paused,
        lyric state, cursor. Returns previous current_idx for redraw.
        """
        self.stop_current()
        old = self.current_idx
        self.current_idx = self.cursor_idx = target
        self.paused = False
        self.lyric["line"] = None
        self.lyric["off"] = 0
        self.lyric["idx"] = None
        self.lyric["pos"] = None
        self.lyric["mood"] = "calm"
        self.lyric["anim_t"] = 0
        self._emit(("TrackStarted", old, target))
        return old

    def next_track(self) -> Optional[int]:
        """Advance to current_idx + 1 unconditionally (the ``n`` key).
        Unlike pick_next_idx(), does not respect play_mode. Returns the
        previous current_idx if advanced, or None if already at the end.
        """
        if not self.tracks:
            return None
        self.stop_current()
        old = self.current_idx
        self.current_idx += 1
        self.paused = False
        if self.current_idx < len(self.tracks):
            self.cursor_idx = self.current_idx
            self._emit(("TrackStarted", old, self.current_idx))
            return old
        return None

    def delete_cursor(self) -> tuple[int, bool, bool]:
        """Delete the track at cursor_idx. Returns
        (deleted_idx, was_playing, empty_now). If empty_now is True, the
        caller should also call stop_current() and exit cleanly.
        """
        del_idx = self.cursor_idx
        if len(self.tracks) == 1:
            return del_idx, del_idx == self.current_idx, True
        was_playing = (del_idx == self.current_idx)
        self.tracks.pop(del_idx)
        if self.current_idx > del_idx:
            self.current_idx -= 1
        new_cursor = self.cursor_idx - 1 if self.cursor_idx > del_idx else self.cursor_idx
        self.cursor_idx = min(new_cursor, len(self.tracks) - 1)
        if was_playing:
            self.stop_current()
            self.current_idx = min(del_idx, len(self.tracks) - 1)
            self.cursor_idx = self.current_idx
            self.paused = False
        return del_idx, was_playing, False

    def begin_append(self) -> bool:
        """Mark an append as in-flight. Returns False if one is already
        running (UI should show a status message)."""
        if self.appending:
            return False
        self.appending = True
        return True

    def end_append(self) -> None:
        """Called by the background append thread when done."""
        self.appending = False

    def request_quit(self) -> None:
        """Stop current playback and signal the UI to exit on next loop."""
        self.stop_current()

    def pick_next_idx(self) -> Optional[int]:
        """Decide the next track index after the current one ends naturally.

        Returns the next index to play, or None if playback should stop
        (i.e. sequential mode ran off the end). Pure function of current
        state; does not mutate self.

        - ``repeat``: returns ``current_idx`` (loop the same track).
        - ``shuffle``: random choice excluding ``current_idx`` when more
          than one track exists; otherwise returns ``current_idx``.
        - ``seq`` (default): ``current_idx + 1`` if in range, else None.
        """
        if not self.tracks:
            return None
        if self.play_mode == "repeat":
            return self.current_idx
        if self.play_mode == "shuffle" and len(self.tracks) > 1:
            import random as _random
            candidates = [i for i in range(len(self.tracks)) if i != self.current_idx]
            return _random.choice(candidates)
        nxt = self.current_idx + 1
        return nxt if nxt < len(self.tracks) else None


# ---------------------------------------------------------------------------
# Control socket server
# ---------------------------------------------------------------------------

class CtlServer:
    """JSON-line control socket server for remote player commands.

    Listens on a Unix domain socket.  Each client connection is handled in
    its own daemon thread: read one JSON line, dispatch to PlayerCore,
    write one JSON response, close.
    """

    def __init__(self, core: PlayerCore, sock_path: str = _CTL_SOCK) -> None:
        self._core = core
        self._sock_path = sock_path
        self._sock: Optional[socket.socket] = None
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._subscribers: list[socket.socket] = []
        self._sub_lock = threading.Lock()

    # ── lifecycle ────────────────────────────────────────────────────────

    def start(self) -> None:
        # Clean up stale socket from a crashed session
        if os.path.exists(self._sock_path):
            probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                probe.connect(self._sock_path)
                probe.close()
                # Another player is actually listening — don't steal it
                return
            except (ConnectionRefusedError, OSError):
                os.unlink(self._sock_path)

        self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._sock.bind(self._sock_path)
        self._sock.listen(4)
        self._sock.settimeout(0.5)
        self._thread = threading.Thread(target=self._accept_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        # Close all subscriber connections
        with self._sub_lock:
            for s in self._subscribers:
                try:
                    s.close()
                except OSError:
                    pass
            self._subscribers.clear()
        if self._sock:
            try:
                self._sock.close()
            except OSError:
                pass
        if self._thread:
            self._thread.join(timeout=1.0)
        try:
            os.unlink(self._sock_path)
        except FileNotFoundError:
            pass

    # ── subscriber management ───────────────────────────────────────────

    def broadcast(self, event: dict) -> None:
        """Send a JSON-line event to all subscribers. Remove dead ones."""
        data = json.dumps(event).encode() + b"\n"
        dead: list[socket.socket] = []
        with self._sub_lock:
            for s in self._subscribers:
                try:
                    s.sendall(data)
                except (BrokenPipeError, ConnectionResetError, OSError):
                    dead.append(s)
            for s in dead:
                self._subscribers.remove(s)
                try:
                    s.close()
                except OSError:
                    pass

    # ── accept loop ─────────────────────────────────────────────────────

    def _accept_loop(self) -> None:
        while not self._stop.is_set():
            try:
                conn, _ = self._sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            threading.Thread(
                target=self._handle_client, args=(conn,), daemon=True
            ).start()

    # ── client handler ──────────────────────────────────────────────────

    def _handle_client(self, conn: socket.socket) -> None:
        is_subscribe = False
        try:
            conn.settimeout(2.0)
            data = b""
            while b"\n" not in data and len(data) < 4096:
                chunk = conn.recv(1024)
                if not chunk:
                    break
                data += chunk
            if not data.strip():
                return
            try:
                req = json.loads(data.strip())
            except (json.JSONDecodeError, ValueError):
                conn.sendall(json.dumps({"ok": False, "error": "invalid request"}).encode() + b"\n")
                return

            # Subscribe: keep connection open, don't close
            if req.get("cmd") == "subscribe":
                is_subscribe = True
                self._handle_subscribe(conn)
                return

            resp = self._dispatch(req)
            conn.sendall(json.dumps(resp).encode() + b"\n")
        except Exception:
            pass
        finally:
            if not is_subscribe:
                try:
                    conn.close()
                except OSError:
                    pass

    # ── command dispatch ────────────────────────────────────────────────

    def _dispatch(self, req: dict) -> dict:
        cmd = req.get("cmd", "")
        arg = req.get("arg")

        if cmd == "status":
            snap = self._core.snapshot()
            track_name = ""
            artist = ""
            if self._core.tracks and 0 <= snap.current_idx < len(self._core.tracks):
                t = self._core.tracks[snap.current_idx]
                track_name = t.title
                artist = t.artist
            return {
                "ok": True,
                "status": {
                    "track": track_name,
                    "artist": artist,
                    "idx": snap.current_idx,
                    "total": snap.tracks_count,
                    "paused": snap.paused,
                    "mode": snap.play_mode,
                },
            }

        if cmd == "next":
            self._core.next_track()
            self._core._ui_q.put(("ctl_next",))
            return {"ok": True}

        if cmd == "pause":
            new_paused = self._core.toggle_pause()
            self._core._ui_q.put(("ctl_pause",))
            return {"ok": True, "paused": new_paused}

        if cmd == "mode":
            if arg and arg in ("seq", "repeat", "shuffle"):
                self._core.set_mode(arg)
            else:
                self._core.cycle_mode()
            self._core._ui_q.put(("ctl_mode",))
            return {"ok": True, "mode": self._core.play_mode}

        if cmd == "seek":
            try:
                delta = float(arg) if arg is not None else 5.0
            except (ValueError, TypeError):
                delta = 5.0
            _mpv_seek(delta)
            return {"ok": True}

        if cmd == "play_track":
            try:
                idx = int(arg) if arg is not None else -1
            except (ValueError, TypeError):
                idx = -1
            if 0 <= idx < len(self._core.tracks):
                self._core.current_idx = idx
                self._core.cursor_idx = idx
                self._core._ui_q.put(("ctl_next",))
                return {"ok": True, "idx": idx}
            return {"ok": False, "error": f"invalid track index: {arg}"}

        if cmd == "quit":
            self._core.request_quit()
            self._core._ui_q.put(("ctl_quit",))
            return {"ok": True}

        return {"ok": False, "error": f"unknown command: {cmd}"}

    # ── subscribe handler ───────────────────────────────────────────────

    def _handle_subscribe(self, conn: socket.socket) -> None:
        """Send initial snapshot, then add to subscriber list.

        The connection stays open — events are pushed via broadcast().
        """
        conn.settimeout(None)  # no timeout for long-lived connection
        # Build snapshot payload
        snap = self._core.snapshot()
        tracks_data = []
        for t in self._core.tracks:
            tracks_data.append({
                "title": t.title,
                "artist": t.artist,
                "duration": t.duration_seconds,
                "url": t.youtube_url,
            })
        # Active LRC lines
        active_lrc = []
        if self._core.lrc_candidates and self._core.lrc_idx < len(self._core.lrc_candidates):
            active_lrc = [
                {"ts": ts, "text": text}
                for ts, text in self._core.lrc_candidates[self._core.lrc_idx]
            ]
        snapshot = {
            "event": "snapshot",
            "data": {
                "playlist_name": snap.playlist_name,
                "tracks": tracks_data,
                "current_idx": snap.current_idx,
                "cursor_idx": snap.cursor_idx,
                "paused": snap.paused,
                "mode": snap.play_mode,
                "lyric_line": snap.lyric_line,
                "lyric_idx": snap.lyric_idx,
                "lyric_pos": snap.lyric_pos,
                "lyric_mood": snap.lyric_mood,
                "active_lrc": active_lrc,
            },
        }
        try:
            conn.sendall(json.dumps(snapshot).encode() + b"\n")
        except (BrokenPipeError, OSError):
            try:
                conn.close()
            except OSError:
                pass
            return
        with self._sub_lock:
            self._subscribers.append(conn)


class _AdoptedProcess:
    """Wrap an OS PID for a process we inherited via fork (not spawned).

    Provides the subset of subprocess.Popen API that PlayerCore / watcher use.
    We can't waitpid() on non-child processes, so poll() uses kill(pid, 0).
    """

    def __init__(self, pid: int):
        self.pid = pid
        self._returncode: int | None = None

    def poll(self) -> int | None:
        if self._returncode is not None:
            return self._returncode
        try:
            os.kill(self.pid, 0)
            return None          # still running
        except ProcessLookupError:
            self._returncode = 0
            return 0             # exited
        except PermissionError:
            return None          # alive (different user edge case)

    def kill(self) -> None:
        try:
            os.kill(self.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass

    def wait(self, timeout: float | None = None) -> int:
        import time as _time
        deadline = _time.time() + (timeout or 30)
        while _time.time() < deadline:
            if self.poll() is not None:
                return self._returncode  # type: ignore[return-value]
            _time.sleep(0.1)
        return 0


# ---------------------------------------------------------------------------
# Headless playback (daemon mode)
# ---------------------------------------------------------------------------

def play_headless(playlists: list[dict], active_idx: int = 0, debug: bool = False,
                   resume_track: int | None = None,
                   resume_mode: str | None = None,
                   adopt_mpv_pid: int | None = None,
                   adopt_ytdlp_pid: int | None = None) -> None:
    """Run playback without any terminal UI — for daemon mode.

    Drives PlayerCore + mpv + CtlServer. Emits events to subscribers.
    *resume_track*: if set, start from this track index instead of 0.
    *resume_mode*: if set, restore this play mode (seq/repeat/shuffle).
    *adopt_mpv_pid/adopt_ytdlp_pid*: adopt a running mpv/ytdlp instead of
        re-launching. The daemon inherits the process after fork.
    """
    if not playlists:
        return

    core = PlayerCore(playlists=playlists, active_idx=active_idx, debug=debug)
    core.playlist_name = playlists[active_idx]["name"]
    core.tracks = list(playlists[active_idx]["tracks"])
    core.prompt = playlists[active_idx]["prompt"]

    if not core.tracks:
        return

    core.n = len(core.tracks)
    core.vh = min(10, core.n)
    print(f"[headless] start: resume_track={resume_track} resume_mode={resume_mode} adopt_mpv={adopt_mpv_pid}", flush=True)
    if resume_track is not None and 0 <= resume_track < core.n:
        core.current_idx = resume_track
        core.cursor_idx = resume_track
    if resume_mode and resume_mode in ("seq", "repeat", "shuffle"):
        core.play_mode = resume_mode

    ctl_server = CtlServer(core)
    ctl_server.start()
    core.start()

    from autoplaylist import lyrics as _lyr
    from autoplaylist import cache as _cache
    from autoplaylist import llm as _llm_mod

    def _fetch_lyrics(artist: str, title: str) -> None:
        candidates = _cache.get_lyrics(artist, title)
        if candidates is None:
            candidates = _lyr.fetch_candidates(artist, title)
            if candidates:
                _cache.save_lyrics(artist, title, candidates)
        core.lrc_candidates = list(candidates or [])
        core.lrc_ready = True

    def _active_lrc() -> list[tuple[float, str]]:
        if core.lrc_candidates and core.lrc_idx < len(core.lrc_candidates):
            return core.lrc_candidates[core.lrc_idx]
        return []

    _adopting = adopt_mpv_pid is not None

    try:
        while True:
            if core.current_idx >= len(core.tracks):
                # Sequential mode finished
                break

            _t = core.tracks[core.current_idx]

            _adopted_this = False
            if _adopting:
                # First iteration: adopt the already-running mpv from the TUI
                core.mpv_proc = _AdoptedProcess(adopt_mpv_pid)
                core.ytdlp_proc = _AdoptedProcess(adopt_ytdlp_pid) if adopt_ytdlp_pid else None
                _adopting = False
                _adopted_this = True
                print(f"[headless] adopted mpv pid={adopt_mpv_pid}", flush=True)
            else:
                # Launch mpv
                core.ytdlp_proc, core.mpv_proc = _launch_mpv(_t.youtube_url, debug=debug)

            # Drain stale events, arm watcher
            while True:
                try:
                    core._ui_q.get_nowait()
                except queue.Empty:
                    break
            core.arm_watcher()

            # Fetch lyrics in background
            core.lrc_candidates = []
            core.lrc_idx = 0
            core.lrc_ready = False
            threading.Thread(target=_fetch_lyrics, args=(_t.artist, _t.title), daemon=True).start()

            # Classify mood in background
            def _classify_mood_bg(artist: str, title: str) -> None:
                core.lyric["mood"] = _llm_mod.classify_mood(artist, title)
            threading.Thread(target=_classify_mood_bg, args=(_t.artist, _t.title), daemon=True).start()

            # Broadcast track_started event
            ctl_server.broadcast({
                "event": "track_started",
                "data": {
                    "idx": core.current_idx,
                    "artist": _t.artist,
                    "title": _t.title,
                    "duration": _t.duration_seconds,
                },
            })

            if not _adopted_this:
                # Wait for mpv to start (up to 3s)
                _load_start = time.time()
                while time.time() - _load_start < 3.0:
                    time.sleep(0.1)
                    if core.mpv_proc.poll() is not None:
                        break

                if core.mpv_proc.poll() is not None:
                    # Track failed to load — skip
                    if not core._watch_active:
                        try:
                            core._ui_q.get_nowait()
                        except queue.Empty:
                            pass
                        continue
                    core.disarm_watcher()
                    old = core.current_idx
                    core.current_idx += 1
                    continue

            # Track is playing — poll until it ends or command received
            last_pos_ts = 0.0
            while True:
                time.sleep(0.2)
                now = time.time()

                # Update position + lyrics every ~1s, broadcast to subscribers
                if now - last_pos_ts >= 1.0:
                    last_pos_ts = now
                    pos = _get_mpv_pos()
                    if pos is not None:
                        core.lyric["pos"] = pos
                        _lrc = _active_lrc()
                        line = None
                        lyric_idx = None
                        if core.lrc_ready and _lrc:
                            line = _lyr.current_line(_lrc, pos)
                            core.lyric["line"] = line
                            for j in range(len(_lrc) - 1, -1, -1):
                                if pos >= _lrc[j][0]:
                                    lyric_idx = j
                                    core.lyric["idx"] = j
                                    break
                        ctl_server.broadcast({
                            "event": "position",
                            "data": {
                                "pos": pos,
                                "line": line,
                                "idx": lyric_idx,
                                "mood": core.lyric.get("mood", "calm"),
                            },
                        })

                # Check for events from core (natural track end)
                try:
                    ev = core._ui_q.get_nowait()
                except queue.Empty:
                    ev = None

                if ev is not None:
                    tag = ev[0] if isinstance(ev, tuple) else ev
                    if tag == "repeat":
                        break
                    if tag == "next":
                        if core.current_idx < len(core.tracks):
                            ctl_server.broadcast({
                                "event": "track_started",
                                "data": {
                                    "idx": core.current_idx,
                                    "artist": core.tracks[core.current_idx].artist,
                                    "title": core.tracks[core.current_idx].title,
                                    "duration": core.tracks[core.current_idx].duration_seconds,
                                },
                            })
                        break
                    if tag == "ctl_quit":
                        ctl_server.broadcast({"event": "stopped"})
                        return
                    if tag == "ctl_next":
                        if core.current_idx < len(core.tracks):
                            core.cursor_idx = core.current_idx
                        break
                    if tag == "ctl_pause":
                        ctl_server.broadcast({
                            "event": "paused",
                            "data": {"paused": core.paused},
                        })
                    if tag == "ctl_mode":
                        ctl_server.broadcast({
                            "event": "mode_changed",
                            "data": {"mode": core.play_mode},
                        })

        # Playlist finished
        ctl_server.broadcast({"event": "stopped"})

    finally:
        core.stop_current()
        ctl_server.stop()
        core.shutdown()
        # Remove PID file if we're the daemon
        from autoplaylist.daemon import remove_pid
        remove_pid()


# ---------------------------------------------------------------------------
# TUI Attach Client
# ---------------------------------------------------------------------------

def attach_tui() -> None:
    """Connect to a running daemon and render a full TUI from subscribe events.

    Keys are forwarded as ctl commands. q/b detach without stopping the daemon.
    """
    # Connect and subscribe
    sub_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sub_sock.connect(_CTL_SOCK)
    except (FileNotFoundError, ConnectionRefusedError, OSError):
        print("No player daemon is running")
        return
    sub_sock.sendall(json.dumps({"cmd": "subscribe"}).encode() + b"\n")
    sub_sock.settimeout(5.0)

    # Read initial snapshot
    buf = b""
    while b"\n" not in buf:
        chunk = sub_sock.recv(4096)
        if not chunk:
            print("Connection closed")
            return
        buf += chunk
    line, buf = buf.split(b"\n", 1)
    snapshot = json.loads(line)
    if snapshot.get("event") != "snapshot":
        print("Unexpected response from daemon")
        return

    data = snapshot["data"]
    tracks_raw = data["tracks"]

    # Build Track objects for rendering
    tracks = []
    for td in tracks_raw:
        tracks.append(Track(
            title=td["title"],
            artist=td["artist"],
            youtube_url=td.get("url", ""),
            duration_seconds=td.get("duration", 0),
        ))

    # Build a minimal core-like state object for rendering
    playlists = [{"name": data["playlist_name"], "tracks": tracks, "prompt": ""}]
    core = PlayerCore(playlists=playlists, active_idx=0, debug=False)
    core.playlist_name = data["playlist_name"]
    core.tracks = tracks
    core.n = len(tracks)
    core.vh = min(_VIEW_H, core.n)
    core.current_idx = data.get("current_idx", 0)
    core.cursor_idx = data.get("cursor_idx", core.current_idx)
    core.paused = data.get("paused", False)
    core.play_mode = data.get("mode", "seq")
    core.lyric["line"] = data.get("lyric_line")
    core.lyric["idx"] = data.get("lyric_idx")
    core.lyric["pos"] = data.get("lyric_pos")
    core.lyric["mood"] = data.get("lyric_mood", "calm")

    # Parse active LRC if provided
    if data.get("active_lrc"):
        core.lrc_candidates = [[(e["ts"], e["text"]) for e in data["active_lrc"]]]
        core.lrc_ready = True

    if not core.tracks:
        print("Playlist is empty")
        return

    # ── Setup terminal ────────────────────────────────────────────────────
    global _IW, _LABEL_W, _TOP, _MID, _BOT
    try:
        term_cols = os.get_terminal_size().columns
    except OSError:
        term_cols = 80
    _IW = min(_IW_NORMAL, max(60, term_cols - 2))
    _LABEL_W = _IW - 20
    _TOP = "┌" + "─" * _IW + "┐"
    _MID = "├" + "─" * _IW + "┤"
    _BOT = "└" + "─" * _IW + "┘"
    sys.stdout.write("\033[?7l")
    sys.stdout.flush()

    # ── viewport helpers (same as play_playlist) ─────────────────────────
    def _lines_up(rel: int) -> int:
        return 3 + core.vh - rel

    def _row_for(idx: int) -> int | None:
        rel = idx - core.view_start
        return rel if 0 <= rel < core.vh else None

    def _draw_track_a(idx: int, playing: bool, is_paused: bool, cursored: bool) -> None:
        rel = _row_for(idx)
        if rel is None:
            return
        ll = core.lyric["line"] if playing else None
        lo = core.lyric["off"] if playing else 0
        vis = _track_inner_vis(idx, playing, cursored, core.tracks, ll, lo, False)
        disp = _track_inner_disp(idx, playing, is_paused, cursored, core.tracks, ll, lo, False)
        row = _box_row(vis, disp)
        lu = _lines_up(rel)
        sys.stdout.write(f"\033[{lu}A\r{row}\033[{lu}B\r")

    def _redraw_viewport_a() -> None:
        for vi in range(core.vh):
            idx = core.view_start + vi
            if idx >= len(core.tracks):
                break
            playing = idx == core.current_idx
            cursored = idx == core.cursor_idx
            _draw_track_a(idx, playing, core.paused and playing, cursored)
        sys.stdout.flush()

    def _scroll_to_a(target: int) -> bool:
        if core.n <= core.vh:
            return False
        new_vs = max(0, min(target, core.n - core.vh))
        if new_vs == core.view_start:
            return False
        core.view_start = new_vs
        return True

    def _update_header_a() -> None:
        a0 = core.view_start + 1
        b0 = min(core.view_start + core.vh, core.n)
        page_info = f"{a0}-{b0}/{core.n}" if core.n > core.vh else f"{core.n} tracks"
        lft = "  ♫ myplaylist  "
        rgt_vis = f"  {core.playlist_name} ({page_info})  "
        rgt_disp = f"  {_YL}{core.playlist_name}{_R} ({page_info})  "
        hpad = max(0, _IW - len(lft) - _cjk_width(rgt_vis))
        hdr_vis = f"{lft}{' ' * hpad}{rgt_vis}"
        hdr_disp = f"  {_B}{_CY}♫ myplaylist{_R}  " + " " * hpad + rgt_disp
        lu = 5 + core.vh
        sys.stdout.write(f"\033[{lu}A\r{_box_row(hdr_vis, hdr_disp)}\033[{lu}B\r")
        sys.stdout.flush()

    # ── Full repaint helper ────────────────────────────────────────────────
    def _full_repaint_a() -> None:
        """Erase old box and redraw everything."""
        NL = "\033[K\r\n"
        sys.stdout.write(f"\033[{core.vh + 7}A\r\033[J")
        a0 = core.view_start + 1
        b0 = min(core.view_start + core.vh, core.n)
        page_info = f"{a0}-{b0}/{core.n}" if core.n > core.vh else f"{core.n} tracks"
        lft_ = "  ♫ myplaylist  "
        rgt_vis_ = f"  {core.playlist_name} ({page_info})  "
        rgt_disp_ = f"  {_YL}{core.playlist_name}{_R} ({page_info})  "
        hpad_ = max(0, _IW - len(lft_) - _cjk_width(rgt_vis_))
        hdr_vis_ = f"{lft_}{' ' * hpad_}{rgt_vis_}"
        hdr_disp_ = f"  {_B}{_CY}♫ myplaylist{_R}  " + " " * hpad_ + rgt_disp_
        ctrl_vis_, ctrl_disp_ = _ctrl_bar(_IW, False, core.play_mode)
        ctrl_pad_ = max(0, _IW - _cjk_width(ctrl_vis_))
        ls = [NL, _TOP + NL, _box_row(hdr_vis_, hdr_disp_) + NL, _MID + NL]
        for vi in range(core.vh):
            idx = core.view_start + vi
            if idx >= len(core.tracks):
                break
            playing = idx == core.current_idx
            cursored = idx == core.cursor_idx
            vis_ = _track_inner_vis(idx, playing, cursored, core.tracks)
            disp_ = _track_inner_disp(idx, playing, core.paused and playing, cursored, core.tracks)
            ls.append(_box_row(vis_, disp_) + NL)
        ls += [_MID + NL, f"│{ctrl_disp_}{' ' * ctrl_pad_}│" + NL, _BOT + NL]
        _w("".join(ls))

    # ── Initial draw ─────────────────────────────────────────────────────
    a0, b0 = 1, min(core.n, core.vh)
    page_info0 = f"{a0}-{b0}/{core.n}" if core.n > core.vh else f"{core.n} tracks"
    lft = "  ♫ myplaylist  "
    rgt_vis0 = f"  {core.playlist_name} ({page_info0})  "
    rgt_disp0 = f"  {_YL}{core.playlist_name}{_R} ({page_info0})  "
    hpad0 = max(0, _IW - len(lft) - _cjk_width(rgt_vis0))
    hdr_vis0 = f"{lft}{' ' * hpad0}{rgt_vis0}"
    hdr_disp0 = f"  {_B}{_CY}♫ myplaylist{_R}  " + " " * hpad0 + rgt_disp0

    ctrl_vis, ctrl_disp = _ctrl_bar(_IW, False, core.play_mode)
    ctrl_pad = max(0, _IW - _cjk_width(ctrl_vis))

    lines = [_NL, _TOP + _NL, _box_row(hdr_vis0, hdr_disp0) + _NL, _MID + _NL]
    for i in range(core.vh):
        idx = core.view_start + i
        playing = idx == core.current_idx
        cursored = idx == core.cursor_idx
        vis = _track_inner_vis(idx, playing, cursored, core.tracks)
        disp = _track_inner_disp(idx, playing, core.paused and playing, cursored, core.tracks)
        lines.append(_box_row(vis, disp) + _NL)
    lines += [_MID + _NL, f"│{ctrl_disp}{' ' * ctrl_pad}│" + _NL, _BOT + _NL]
    _w("".join(lines))

    label = _make_label(core.tracks[core.current_idx], 55) if core.current_idx < len(core.tracks) else ""
    state = "Paused " if core.paused else "Playing"
    sys.stdout.write(f"\r{_D}♪{_R}  {state}  [{core.current_idx + 1}/{core.n}]  {label}")
    sys.stdout.flush()

    # ── Event + key loop ─────────────────────────────────────────────────
    key_reader = _KeyReader()
    key_reader.start()

    _orig_sigint = signal.getsignal(signal.SIGINT)
    def _sigint_handler(signum, frame):
        key_reader.stop()
        _restore_terminal()
        signal.signal(signal.SIGINT, _orig_sigint)
        sys.stdout.write(_NL)
        raise KeyboardInterrupt
    signal.signal(signal.SIGINT, _sigint_handler)

    sub_sock.settimeout(0.05)  # non-blocking-ish for event polling

    def _ctl_cmd(cmd: str, arg: str | None = None) -> None:
        """Send a one-shot ctl command to the daemon (separate connection)."""
        try:
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.settimeout(2.0)
            s.connect(_CTL_SOCK)
            req: dict = {"cmd": cmd}
            if arg is not None:
                req["arg"] = arg
            s.sendall(json.dumps(req).encode() + b"\n")
            s.recv(1024)
            s.close()
        except OSError:
            pass

    def _status_a(text: str) -> None:
        avail = _IW - 3
        tw = _cjk_width(text)
        if tw > avail:
            text = _truncate(text, avail)
            tw = avail
        sys.stdout.write(f"\r{_D}♪{_R}  {text}{' ' * (avail - tw)}")
        sys.stdout.flush()

    num_buf = ""
    num_ts = 0.0

    try:
        while True:
            time.sleep(0.05)

            # Auto-clear digit buffer after timeout
            if num_buf and time.time() - num_ts > 1.5:
                target = int(num_buf) - 1
                num_buf = ""
                if 0 <= target < len(core.tracks) and target != core.current_idx:
                    _ctl_cmd("play_track", str(target))

            # Poll subscribe events
            try:
                while True:
                    chunk = sub_sock.recv(4096)
                    if not chunk:
                        # Daemon closed connection
                        _status_a("Daemon stopped")
                        time.sleep(1)
                        return
                    buf += chunk
                    while b"\n" in buf:
                        line, buf = buf.split(b"\n", 1)
                        if not line.strip():
                            continue
                        try:
                            ev = json.loads(line)
                        except (json.JSONDecodeError, ValueError):
                            continue
                        tag = ev.get("event", "")
                        ed = ev.get("data", {})

                        if tag == "track_started":
                            core.current_idx = ed.get("idx", core.current_idx)
                            core.cursor_idx = core.current_idx
                            core.paused = False
                            core.lyric["line"] = None
                            core.lyric["off"] = 0
                            core.lyric["idx"] = None
                            core.lyric["pos"] = None
                            if _scroll_to_a(core.current_idx):
                                _redraw_viewport_a()
                                _update_header_a()
                            else:
                                _redraw_viewport_a()
                            label = _make_label(core.tracks[core.current_idx], 55) if core.current_idx < len(core.tracks) else ""
                            _status_a(f"Playing  [{core.current_idx + 1}/{core.n}]  {label}")

                        elif tag == "paused":
                            core.paused = ed.get("paused", core.paused)
                            state = "Paused " if core.paused else "Playing"
                            label = _make_label(core.tracks[core.current_idx], 55) if core.current_idx < len(core.tracks) else ""
                            _status_a(f"{state}  [{core.current_idx + 1}/{core.n}]  {label}")
                            _draw_track_a(core.current_idx, True, core.paused, core.cursor_idx == core.current_idx)
                            sys.stdout.flush()

                        elif tag == "position":
                            core.lyric["pos"] = ed.get("pos")
                            core.lyric["line"] = ed.get("line")
                            core.lyric["idx"] = ed.get("idx")
                            core.lyric["mood"] = ed.get("mood", "calm")
                            # Update marquee offset
                            if core.lyric["line"]:
                                pw = _cjk_width(core.lyric["line"]) + 4
                                core.lyric["off"] = (core.lyric["off"] + 1) % max(1, pw)
                            _draw_track_a(core.current_idx, True, core.paused, core.cursor_idx == core.current_idx)
                            sys.stdout.flush()

                        elif tag == "mode_changed":
                            core.play_mode = ed.get("mode", core.play_mode)
                            _full_repaint_a()
                            _status_a(f"Mode: {core.play_mode}")

                        elif tag == "stopped":
                            _status_a("Daemon stopped")
                            time.sleep(1)
                            return
            except socket.timeout:
                pass
            except OSError:
                _status_a("Daemon connection lost")
                time.sleep(1)
                return

            # Process key input
            key = key_reader.consume()
            if key is None:
                continue

            if key in ("q", "b"):
                return

            elif key == "p":
                _ctl_cmd("pause")

            elif key == "n":
                _ctl_cmd("next")

            elif key == "r":
                _ctl_cmd("mode")

            elif key == ",":
                _ctl_cmd("seek", "-5")
            elif key == ".":
                _ctl_cmd("seek", "5")
            elif key == "<":
                _ctl_cmd("seek", "-30")
            elif key == ">":
                _ctl_cmd("seek", "30")

            elif key == "UP":
                old_cur = core.cursor_idx
                core.cursor_idx = max(0, core.cursor_idx - 1)
                if core.cursor_idx != old_cur:
                    if _scroll_to_a(core.cursor_idx):
                        _redraw_viewport_a()
                        _update_header_a()
                    else:
                        _draw_track_a(old_cur, old_cur == core.current_idx,
                                      core.paused and old_cur == core.current_idx, False)
                        _draw_track_a(core.cursor_idx, core.cursor_idx == core.current_idx,
                                      core.paused and core.cursor_idx == core.current_idx, True)
                        sys.stdout.flush()

            elif key == "DOWN":
                old_cur = core.cursor_idx
                core.cursor_idx = min(len(core.tracks) - 1, core.cursor_idx + 1)
                if core.cursor_idx != old_cur:
                    if _scroll_to_a(core.cursor_idx):
                        _redraw_viewport_a()
                        _update_header_a()
                    else:
                        _draw_track_a(old_cur, old_cur == core.current_idx,
                                      core.paused and old_cur == core.current_idx, False)
                        _draw_track_a(core.cursor_idx, core.cursor_idx == core.current_idx,
                                      core.paused and core.cursor_idx == core.current_idx, True)

            elif key == "LEFT":
                new_vs = max(0, core.view_start - core.vh)
                if new_vs != core.view_start:
                    core.view_start = new_vs
                    core.cursor_idx = core.view_start
                    _redraw_viewport_a()
                    _update_header_a()

            elif key == "RIGHT":
                max_vs = max(0, len(core.tracks) - core.vh)
                new_vs = min(max_vs, core.view_start + core.vh)
                if new_vs != core.view_start:
                    core.view_start = new_vs
                    core.cursor_idx = core.view_start
                    _redraw_viewport_a()
                    _update_header_a()

            elif key in ("\r", "\n"):
                if num_buf:
                    target = int(num_buf) - 1
                    num_buf = ""
                else:
                    target = core.cursor_idx
                if 0 <= target < len(core.tracks) and target != core.current_idx:
                    _ctl_cmd("play_track", str(target))
                else:
                    _status_a(f"Playing  [{core.current_idx + 1}/{core.n}]")

            elif key and key.isdigit():
                now_t = time.time()
                num_buf = (num_buf + key) if num_buf and now_t - num_ts < 1.5 else key
                num_ts = now_t
                _status_a(f"Goto     [{num_buf}]  — add digits or Enter")

    finally:
        signal.signal(signal.SIGINT, _orig_sigint)
        key_reader.stop()
        try:
            sub_sock.close()
        except OSError:
            pass
        _restore_terminal()
        sys.stdout.write(_NL)


# ---------------------------------------------------------------------------
# Main player (TUI)
# ---------------------------------------------------------------------------

def play_playlist(playlists: list[dict], active_idx: int = 0, debug: bool = False) -> None:
    """Play playlists with tab switching support.

    Each dict in playlists must have: name (str), tracks (list[Track]), prompt (str).
    active_idx selects the initially active playlist.
    """
    if not playlists:
        print("No playlists available.")
        return

    if debug:
        _LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        print(f"[debug] player log: {_LOG_FILE}")
        print(f"[debug] yt-dlp:   {_find_ytdlp()}")
        print(f"[debug] browser:  {_get_browser() or 'none detected'}")

    # Unpack active playlist into a PlayerCore state container.
    # Step 1 of decouple-player-core-ui: all mutable session state lives on
    # `core` from here on. Render helpers and the main loop read/write
    # `core.<field>` directly — no event loop yet.
    core = PlayerCore(playlists=playlists, active_idx=active_idx, debug=debug)
    core.playlist_name = playlists[active_idx]["name"]
    core.tracks = list(playlists[active_idx]["tracks"])
    core.prompt = playlists[active_idx]["prompt"]

    if not core.tracks:
        print("Playlist is empty.")
        return

    # ── Adapt box to terminal width ───────────────────────────────────────────
    # _IW=80 means each row is 82 cols (│ + 80 + │). In the default macOS
    # Terminal (80 cols) rows wrap, corrupting cursor-position tracking.
    # Detect actual width, shrink the box to fit, and disable auto-wrap as
    # a safety net so stray long strings never break the layout.
    global _IW, _LABEL_W, _TOP, _MID, _BOT
    try:
        term_cols = os.get_terminal_size().columns
    except OSError:
        term_cols = 80
    # Inner width: leave 2 cols for the │ borders; floor at 60 for usability
    _IW = min(_IW_NORMAL, max(60, term_cols - 2))
    _LABEL_W = _IW - 20   # track row = 20 fixed cols + label
    _TOP = "┌" + "─" * _IW + "┐"
    _MID = "├" + "─" * _IW + "┤"
    _BOT = "└" + "─" * _IW + "┘"
    sys.stdout.write("\033[?7l")   # disable terminal auto-wrap for TUI session
    sys.stdout.flush()

    core.n = len(core.tracks)
    core.vh = min(_VIEW_H, core.n)   # actual viewport height
    # All other fields (view_start, current_idx, cursor_idx, paused, lyric,
    # lyric_panel_on, panel_widths, appending, switch_tab, play_mode,
    # lrc_* and last_* timers) use dataclass defaults.

    # ── viewport helpers ──────────────────────────────────────────────────────

    def _lines_up(rel: int) -> int:
        """Lines from status line up to track at viewport-relative position rel."""
        return 3 + core.vh - rel

    def _row_for(idx: int) -> Optional[int]:
        """Return viewport-relative row for track idx, or None if off-screen."""
        rel = idx - core.view_start
        return rel if 0 <= rel < core.vh else None

    def _draw_track(idx: int, playing: bool, is_paused: bool, cursored: bool) -> None:
        rel = _row_for(idx)
        if rel is None:
            return
        if core.lyric_panel_on and core.panel_widths:
            _, plw, lw = core.panel_widths
            lbl_w = max(10, plw - 20)
            p   = core.lyric["pos"] if playing else None
            dur = core.tracks[idx].duration_seconds if playing else 0
            vis  = _track_inner_vis(idx, playing, cursored, core.tracks, None, 0, True, lbl_w,
                                    p, dur)
            disp = _track_inner_disp(idx, playing, is_paused, cursored, core.tracks,
                                     None, 0, True, lbl_w, p, dur)
            row_pad = max(0, plw - _cjk_width(vis))
            # Write only the left column; cursor stops at │ so lyric column is untouched
            row = f"│{disp}{' ' * row_pad}│"
        else:
            ll = core.lyric["line"] if playing else None
            lo = core.lyric["off"]  if playing else 0
            vis  = _track_inner_vis(idx, playing, cursored, core.tracks, ll, lo, False)
            disp = _track_inner_disp(idx, playing, is_paused, cursored, core.tracks, ll, lo, False)
            row = _box_row(vis, disp)
        # Use up/down instead of save/restore cursor (\033[s/\033[u) — Terminal.app
        # does not always implement save/restore reliably, causing rows to be drawn
        # outside the box after multiple operations.
        lu = _lines_up(rel)
        sys.stdout.write(f"\033[{lu}A\r{row}\033[{lu}B\r")

    def _redraw_viewport() -> None:
        """Redraw all visible track rows in place."""
        if core.lyric_panel_on and core.panel_widths:
            _, plw, lw = core.panel_widths
            _full_repaint(True, plw, lw)
            return
        for rel in range(core.vh):
            idx = core.view_start + rel
            _draw_track(idx, idx == core.current_idx, core.paused and idx == core.current_idx,
                        idx == core.cursor_idx)
        sys.stdout.flush()

    def _scroll_to(idx: int) -> bool:
        """Shift view so idx is visible. Return True if view changed."""
        vs = core.view_start
        if idx < vs:
            core.view_start = idx
        elif idx >= vs + core.vh:
            core.view_start = idx - core.vh + 1
        else:
            return False
        return True

    def _update_header() -> None:
        """Rewrite header to show current page range."""
        if core.lyric_panel_on:
            return  # handled by _full_repaint when panel is open
        nt = len(core.tracks)
        a, b = core.view_start + 1, min(nt, core.view_start + core.vh)
        page_info = f"{a}-{b}/{nt}" if nt > core.vh else f"{nt} tracks"
        lft = "  ♫ myplaylist  "
        rgt_vis  = f"  {core.playlist_name} ({page_info})  "
        rgt_disp = f"  {_YL}{core.playlist_name}{_R} ({page_info})  "
        hpad = max(0, _IW - len(lft) - _cjk_width(rgt_vis))
        hdr_vis  = f"{lft}{' ' * hpad}{rgt_vis}"
        hdr_disp = f"  {_B}{_CY}♫ myplaylist{_R}  " + " " * hpad + rgt_disp
        lines_up = 3 + core.vh + 2   # up: _BOT, ctrl, mid, vh tracks, mid, header
        sys.stdout.write(f"\033[{lines_up}A\r{_box_row(hdr_vis, hdr_disp)}\033[{lines_up}B\r")
        sys.stdout.flush()

    def _full_repaint(panel_open: bool, plw: int, lw: int) -> None:
        """Clear current box area and redraw from scratch."""
        NL = "\033[K\r\n"  # clear-to-EOL + newline (handles width changes)
        total_iw = plw + 1 + lw if panel_open else _IW_NORMAL
        # Move cursor up to the blank line above the box
        # Structure: blank(1)+top(1)+hdr(1)+mid(1)+vh+mid/sep(1)+ctrl(1)+bot(1) = vh+7
        sys.stdout.write(f"\033[{core.vh + 7}A\r")

        nt = len(core.tracks)
        a, b = core.view_start + 1, min(nt, core.view_start + core.vh)
        page_info = f"{a}-{b}/{nt}" if nt > core.vh else f"{nt} tracks"
        lft = "  ♫ myplaylist  "
        rgt_vis  = f"  {core.playlist_name} ({page_info})  "
        rgt_disp = f"  {_YL}{core.playlist_name}{_R} ({page_info})  "

        if not panel_open:
            hpad = max(0, _IW_NORMAL - len(lft) - _cjk_width(rgt_vis))
            hdr_vis  = f"{lft}{' ' * hpad}{rgt_vis}"
            hdr_disp = f"  {_B}{_CY}♫ myplaylist{_R}  " + " " * hpad + rgt_disp
            ctrl_vis, ctrl_disp = _ctrl_bar(_IW_NORMAL, False, core.play_mode)
            ctrl_pad  = max(0, _IW_NORMAL - _cjk_width(ctrl_vis))
            lines = [
                NL,
                _TOP + NL,
                _box_row(hdr_vis, hdr_disp) + NL,
                _MID + NL,
            ]
            for rel in range(core.vh):
                idx = core.view_start + rel
                ll = core.lyric["line"] if idx == core.current_idx else None
                lo = core.lyric["off"]  if idx == core.current_idx else 0
                vis  = _track_inner_vis(idx, idx == core.current_idx, idx == core.cursor_idx,
                                        core.tracks, ll, lo, False)
                disp = _track_inner_disp(idx, idx == core.current_idx,
                                         core.paused and idx == core.current_idx,
                                         idx == core.cursor_idx, core.tracks, ll, lo, False)
                lines.append(_box_row(vis, disp) + NL)
            lines += [_MID + NL, f"│{ctrl_disp}{' ' * ctrl_pad}│" + NL, _BOT + NL]
        else:
            lbl_w = max(10, plw - 20)
            hpad = max(0, plw - len(lft) - _cjk_width(rgt_vis))
            hdr_vis  = f"{lft}{' ' * hpad}{rgt_vis}"
            hdr_disp = f"  {_B}{_CY}♫ myplaylist{_R}  " + " " * hpad + rgt_disp
            hdr_pad  = max(0, plw - _cjk_width(hdr_vis))
            # Song title + artist in right-column header
            t = core.tracks[core.current_idx]
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
            lrc_idx = core.lyric.get("idx")
            lyric_lines = _lyric_panel_lines(_active_lrc(), lrc_idx, core.vh, lw,
                                             core.lyric["anim_t"], core.lyric["mood"])
            ctrl_vis, ctrl_disp = _ctrl_bar(total_iw, True, core.play_mode)
            ctrl_pad = max(0, total_iw - _cjk_width(ctrl_vis))
            lines = [
                NL,
                _panel_top(plw, lw) + NL,
                f"│{hdr_disp}{' ' * hdr_pad}│{title_str}{' ' * title_pad}│" + NL,
                _panel_mid(plw, lw) + NL,
            ]
            for rel in range(core.vh):
                idx = core.view_start + rel
                is_playing = idx == core.current_idx
                p   = core.lyric["pos"] if is_playing else None
                dur = core.tracks[idx].duration_seconds if is_playing else 0
                vis  = _track_inner_vis(idx, is_playing, idx == core.cursor_idx,
                                        core.tracks, None, 0, True, lbl_w, p, dur)
                disp = _track_inner_disp(idx, is_playing,
                                         core.paused and is_playing,
                                         idx == core.cursor_idx, core.tracks, None, 0, True, lbl_w,
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
        if not (core.lyric_panel_on and core.panel_widths):
            return
        _, plw, lw = core.panel_widths
        t = core.tracks[core.current_idx]
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
        lines_up = 3 + core.vh + 2  # bot + ctrl + panel_bot + vh tracks + mid + header
        col_offset = plw + 2   # right column starts after │plw│
        sys.stdout.write(f"\033[{lines_up}A\r\033[{col_offset}C{content}\033[{lines_up}B\r")
        sys.stdout.flush()

    def _do_append() -> None:
        """Background: generate ~10 tracks similar to current song and append."""
        import traceback, datetime
        def _log(msg: str) -> None:
            try:
                _LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
                with open(_LOG_FILE, "a") as _f:
                    _f.write(f"[append {datetime.datetime.now().strftime('%H:%M:%S')}] {msg}\n")
            except Exception:
                pass
        try:
            from autoplaylist import discovery as _disc
            seed = f"{core.tracks[core.current_idx].artist} - {core.tracks[core.current_idx].title}"
            _log(f"starting append for: {seed}")
            raw = _disc.discover_from_seed(seed, count=12, allow_yt_fallback=False, quiet=True)
            _log(f"raw results: {len(raw)} tracks")
            # Deduplicate against already-in-playlist tracks
            existing = {t.norm_key() for t in core.tracks}
            new = [t for t in raw if t.norm_key() not in existing][:10]
            if new:
                core.tracks.extend(new)
                _status(f"Added {len(new)} tracks  [{len(core.tracks)} total]")
                if core.lyric_panel_on and core.panel_widths:
                    _, plw, lw = core.panel_widths
                    _full_repaint(True, plw, lw)
                else:
                    _update_header()
            elif raw:
                _status("No new tracks found — all recommendations already in playlist")
            else:
                _status("No recommendations — check LLM/Last.fm config or try again")
        except Exception as e:
            tb = traceback.format_exc()
            _log(f"exception: {e}\n{tb}")
            _status(f"Append failed: {str(e)[:60]}")
        finally:
            core.end_append()

    # ── initial box ───────────────────────────────────────────────────────────
    a0, b0 = 1, min(core.n, core.vh)
    page_info0 = f"{a0}-{b0}/{core.n}" if core.n > core.vh else f"{core.n} tracks"
    lft = "  ♫ myplaylist  "
    rgt_vis0  = f"  {core.playlist_name} ({page_info0})  "
    rgt_disp0 = f"  {_YL}{core.playlist_name}{_R} ({page_info0})  "
    hpad0 = max(0, _IW - len(lft) - _cjk_width(rgt_vis0))
    hdr_vis0  = f"{lft}{' ' * hpad0}{rgt_vis0}"
    hdr_disp0 = f"  {_B}{_CY}♫ myplaylist{_R}  " + " " * hpad0 + rgt_disp0

    ctrl_vis, ctrl_disp = _ctrl_bar(_IW, False, core.play_mode)
    ctrl_pad  = max(0, _IW - _cjk_width(ctrl_vis))

    lines = [_NL, _TOP + _NL, _box_row(hdr_vis0, hdr_disp0) + _NL, _MID + _NL]
    for i in range(core.vh):
        vis  = _track_inner_vis(i, i == 0, i == 0, core.tracks)
        disp = _track_inner_disp(i, i == 0, False, i == 0, core.tracks)
        lines.append(_box_row(vis, disp) + _NL)
    lines += [_MID + _NL, f"│{ctrl_disp}{' ' * ctrl_pad}│" + _NL, _BOT + _NL]
    _w("".join(lines))

    # ── playback state ────────────────────────────────────────────────────────
    key_reader  = _KeyReader()
    key_reader.start()
    core.start()  # spawn core.run() event loop thread
    ctl_server = CtlServer(core)
    ctl_server.start()

    _orig_sigint = signal.getsignal(signal.SIGINT)

    # stop_current() now lives on core (core.stop_current); local alias
    # kept only so existing closure call-sites read naturally.
    stop_current = core.stop_current

    def _sigint_handler(signum, frame):
        key_reader.stop(); stop_current(); ctl_server.stop(); _restore_terminal()
        signal.signal(signal.SIGINT, _orig_sigint)
        sys.stdout.write(_NL); raise KeyboardInterrupt
    signal.signal(signal.SIGINT, _sigint_handler)

    def _status(text: str) -> None:
        # Use visual width to avoid wrapping: CJK chars are 2 cols wide, so
        # {text:<70} (Python char count) can exceed terminal width and corrupt
        # the cursor position that _draw_track() relies on.
        avail = _IW - 3  # 80 - 3 cols reserved for "♪  "
        tw = _cjk_width(text)
        if tw > avail:
            text = _truncate(text, avail)
            tw = avail
        sys.stdout.write(f"\r{_D}♪{_R}  {text}{' ' * (avail - tw)}")
        sys.stdout.flush()

    def _jump_to(target: int) -> None:
        old = core.jump_to(target)
        if _scroll_to(target):
            _redraw_viewport()
            _update_header()
        else:
            _draw_track(old, False, False, old == core.cursor_idx)
            _draw_track(target, True, False, True)
            sys.stdout.flush()
        _update_lyric_header()

    detached = False
    try:
        while True:
            # ── tab switch ────────────────────────────────────────────────────
            if core.switch_tab != 0:
                old_vh = core.vh
                core.active_idx = (core.active_idx + core.switch_tab) % len(core.playlists)
                core.switch_tab = 0
                core.playlist_name = core.playlists[core.active_idx]["name"]
                core.tracks = list(core.playlists[core.active_idx]["tracks"])
                core.prompt = core.playlists[core.active_idx]["prompt"]
                core.n = len(core.tracks)
                core.vh = min(_VIEW_H, core.n)
                core.view_start = 0
                core.current_idx = 0
                core.cursor_idx = 0
                core.paused = False
                core.lyric.update({"line": None, "off": 0, "idx": None,
                                   "pos": None, "mood": "calm", "anim_t": 0})
                core.lyric_panel_on = False
                core.panel_widths = None
                core.appending = False
                # Repaint: erase old box + redraw new
                NL = "\033[K\r\n"
                sys.stdout.write(f"\033[{old_vh + 7}A\r\033[J")
                nt = core.n
                a0, b0 = 1, min(nt, core.vh)
                page_info0 = f"{a0}-{b0}/{nt}" if nt > core.vh else f"{nt} tracks"
                lft0 = "  ♫ myplaylist  "
                rgt_vis0  = f"  {core.playlist_name} ({page_info0})  "
                rgt_disp0 = f"  {_YL}{core.playlist_name}{_R} ({page_info0})  "
                hpad0 = max(0, _IW - len(lft0) - _cjk_width(rgt_vis0))
                hdr_vis0  = f"{lft0}{' ' * hpad0}{rgt_vis0}"
                hdr_disp0 = (f"  {_B}{_CY}♫ myplaylist{_R}  "
                             + " " * hpad0 + rgt_disp0)
                ctrl_vis, ctrl_disp = _ctrl_bar(_IW, False, core.play_mode)
                ctrl_pad = max(0, _IW - _cjk_width(ctrl_vis))
                lines = [NL, _TOP + NL, _box_row(hdr_vis0, hdr_disp0) + NL, _MID + NL]
                for i in range(core.vh):
                    vis  = _track_inner_vis(i, i == 0, i == 0, core.tracks)
                    disp = _track_inner_disp(i, i == 0, False, i == 0, core.tracks)
                    lines.append(_box_row(vis, disp) + NL)
                lines += [_MID + NL, f"│{ctrl_disp}{' ' * ctrl_pad}│" + NL, _BOT + NL]
                _w("".join(lines))
                sys.stdout.flush()

            if core.current_idx >= len(core.tracks):
                core.current_idx = 0
                core.cursor_idx = 0
                core.lyric["line"] = None; core.lyric["off"] = 0; core.lyric["idx"] = None; core.lyric["pos"] = None; core.lyric["mood"] = "calm"; core.lyric["anim_t"] = 0
                if _scroll_to(0):
                    _redraw_viewport(); _update_header()
                _update_lyric_header()
            label = _make_label(core.tracks[core.current_idx], 55)
            core.cursor_idx = core.current_idx
            _status(f"Loading  {label}")
            core.ytdlp_proc, core.mpv_proc = _launch_mpv(core.tracks[core.current_idx].youtube_url, debug=core.debug)
            _cache_mark = "⚡ " if core.ytdlp_proc is None else ""
            # Drain any stale ui events from prior track, then arm watcher.
            while True:
                try:
                    core._ui_q.get_nowait()
                except queue.Empty:
                    break
            core.arm_watcher()

            # Fetch lyrics candidates in background while track loads.
            # Per-track state lives on `core` too — reset at each track load.
            from autoplaylist import lyrics as _lyr
            core.lrc_candidates = []
            core.lrc_idx = 0
            core.lrc_ready = False

            def _active_lrc() -> list[tuple[float, str]]:
                if core.lrc_candidates and core.lrc_idx < len(core.lrc_candidates):
                    return core.lrc_candidates[core.lrc_idx]
                return []

            def _fetch_lyrics(artist: str, title: str) -> None:
                from autoplaylist import cache as _cache
                candidates = _cache.get_lyrics(artist, title)
                if candidates is None:
                    candidates = _lyr.fetch_candidates(artist, title)
                    if candidates:
                        _cache.save_lyrics(artist, title, candidates)
                core.lrc_candidates = list(candidates or [])
                core.lrc_ready = True

            _t = core.tracks[core.current_idx]
            _lrc_thread = threading.Thread(
                target=_fetch_lyrics, args=(_t.artist, _t.title), daemon=True
            )
            _lrc_thread.start()

            # Classify mood in background; result written to core.lyric["mood"]
            from autoplaylist import llm as _llm_mod
            def _classify_mood_bg(artist: str, title: str) -> None:
                core.lyric["mood"] = _llm_mod.classify_mood(artist, title)
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
                if core.mpv_proc.poll() is not None:
                    _load_skip = True
                    break

            if _load_key == "q":
                core.request_quit(); sys.stdout.write(_NL); return

            if _load_key in ("[", "]"):
                if len(core.playlists) == 1:
                    _status("Only one playlist")
                else:
                    try:
                        from autoplaylist import playlist as _pl
                        _pl.save(core.playlist_name, core.tracks, core.prompt)
                    except Exception:
                        pass
                    core.request_switch_tab(-1 if _load_key == "[" else 1)
                continue

            if _load_skip or core.mpv_proc.poll() is not None:
                # Cache-miss / launch failure. If the watcher already fired
                # (core.run() saw the exit first), it will have advanced
                # current_idx and posted ("next",). In that case, drain the
                # ui event and continue — don't double-advance.
                if not core._watch_active:
                    try:
                        core._ui_q.get_nowait()
                    except queue.Empty:
                        pass
                    _status(f"Skipped  {label}")
                    continue
                core.disarm_watcher()
                _status(f"Skipped  {label}")
                old = core.current_idx; core.current_idx += 1
                if core.current_idx < len(core.tracks):
                    core.cursor_idx = core.current_idx
                    if _scroll_to(core.current_idx):
                        _redraw_viewport(); _update_header()
                    else:
                        _draw_track(old, False, False, False)
                        _draw_track(core.current_idx, True, False, True)
                        sys.stdout.flush()
                    _update_lyric_header()
                continue

            _status(f"{_cache_mark}Playing  [{core.current_idx + 1}/{len(core.tracks)}]  {label}")

            # reset lyric state for new track
            core.lyric["line"] = None
            core.lyric["off"]  = 0
            core.lyric["pos"]  = None
            core.lyric["mood"] = "calm"
            core.lyric["anim_t"] = 0
            num_buf = ""; num_ts = 0.0
            core.last_pos_ts  = 0.0   # last mpv query time
            core.last_step_ts = 0.0   # last marquee step time
            core.prev_lrc_line = None

            def _tick_lyric() -> None:
                """Advance marquee + update lyric line; redraw playing row."""
                # Refresh position + lyric line from mpv every ~1 s
                now2 = time.time()
                if now2 - core.last_pos_ts >= 1.0:
                    core.last_pos_ts = now2
                    pos = _get_mpv_pos()
                    if pos is not None:
                        core.lyric["pos"] = pos
                        _lrc = _active_lrc()
                        if core.lrc_ready and _lrc:
                            core.lyric["line"] = _lyr.current_line(_lrc, pos)
                            # Track current lyric index for the panel
                            core.lyric["idx"] = None
                            for j in range(len(_lrc) - 1, -1, -1):
                                if pos >= _lrc[j][0]:
                                    core.lyric["idx"] = j
                                    break
                # Advance marquee offset (only when panel closed)
                if core.lyric["line"] and not core.lyric_panel_on:
                    if core.lyric["line"] != core.prev_lrc_line:
                        core.lyric["off"] = 0
                        core.prev_lrc_line = core.lyric["line"]
                    pw = _cjk_width(core.lyric["line"]) + 4
                    core.lyric["off"] = (core.lyric["off"] + 1) % max(1, pw)
                # Redraw the playing row in-place
                _draw_track(core.current_idx, True, core.paused, core.cursor_idx == core.current_idx)
                # Update lyric panel column if open
                if core.lyric_panel_on and core.panel_widths:
                    _, plw, lw = core.panel_widths
                    core.lyric["anim_t"] += 1
                    _draw_lyric_panel(_active_lrc(), core.lyric.get("idx"), plw, lw, core.vh,
                                      core.lyric["anim_t"], core.lyric["mood"])
                sys.stdout.flush()

            while True:
                time.sleep(0.1)
                now = time.time()

                # Advance lyric marquee every 0.3 s
                if now - core.last_step_ts >= 0.3:
                    core.last_step_ts = now
                    if not num_buf and not core.paused:
                        _tick_lyric()

                if num_buf and now - num_ts > 1.5:
                    target = int(num_buf) - 1; num_buf = ""
                    if 0 <= target < len(core.tracks) and target != core.current_idx:
                        _jump_to(target); break
                    _status(f"{_cache_mark}Playing  [{core.current_idx + 1}/{len(core.tracks)}]  {label}")

                key = key_reader.consume()
                if key == "q":
                    core.request_quit(); sys.stdout.write(_NL); return

                elif key == "b":
                    # Detach: fork playback into daemon, exit TUI
                    from autoplaylist.daemon import is_daemon_alive, daemonize
                    if is_daemon_alive():
                        _status("Daemon already running")
                    else:
                        # Stop the TUI's ctl server so daemon can bind it
                        ctl_server.stop()
                        key_reader.stop()
                        _restore_terminal()
                        sys.stdout.write(_NL)
                        # Grab mpv/ytdlp PIDs so daemon can adopt them
                        _mpv_pid = core.mpv_proc.pid if core.mpv_proc else None
                        _ytdlp_pid = core.ytdlp_proc.pid if core.ytdlp_proc else None
                        core.disarm_watcher()
                        # Mark detached — don't kill mpv or delete socket in finally
                        detached = True
                        # Fork: grandchild adopts running mpv, zero interruption
                        from autoplaylist.player import play_headless
                        pid = daemonize(
                            play_headless,
                            core.playlists, core.active_idx, core.debug,
                            resume_track=core.current_idx,
                            resume_mode=core.play_mode,
                            adopt_mpv_pid=_mpv_pid,
                            adopt_ytdlp_pid=_ytdlp_pid,
                        )
                        print(f"Detached to daemon (PID {pid})")
                        return

                elif key == "p":
                    new_paused = core.toggle_pause()
                    state = "Paused " if new_paused else "Playing"
                    _status(f"{_cache_mark}{state}  [{core.current_idx + 1}/{len(core.tracks)}]  {label}")
                    if not new_paused:
                        _tick_lyric()
                    else:
                        _draw_track(core.current_idx, True, new_paused, core.cursor_idx == core.current_idx)
                    sys.stdout.flush()

                elif key in (",", ".", "<", ">"):
                    delta = {",": -5.0, ".": +5.0, "<": -30.0, ">": +30.0}[key]
                    new_pos_q, duration = core.seek_relative(delta)
                    arrow = "⏩" if delta > 0 else "⏪"
                    sign = "+" if delta > 0 else ""
                    if new_pos_q is not None:
                        if duration and duration > 0:
                            hint = f"{arrow} {sign}{int(delta)}s → {_fmt_dur(int(new_pos_q))} / {_fmt_dur(int(duration))}"
                        else:
                            hint = f"{arrow} {sign}{int(delta)}s → {_fmt_dur(int(new_pos_q))}"
                    else:
                        hint = f"{arrow} {sign}{int(delta)}s"
                    _status(hint)
                    _tick_lyric()

                elif key == "l":
                    if not core.lyric_panel_on:
                        pw = _compute_panel_widths()
                        if pw is None:
                            _status("Terminal too narrow for lyrics panel")
                        else:
                            core.lyric_panel_on = True
                            core.panel_widths = pw
                            _, plw, lw = pw
                            _full_repaint(True, plw, lw)
                            _status(f"{_cache_mark}Playing  [{core.current_idx + 1}/{len(core.tracks)}]  {label}")
                    else:
                        core.lyric_panel_on = False
                        core.panel_widths = None
                        _full_repaint(False, _IW_NORMAL, 0)
                        _status(f"{_cache_mark}Playing  [{core.current_idx + 1}/{len(core.tracks)}]  {label}")

                elif key == "+":
                    if not core.begin_append():
                        _status("Already fetching…")
                    else:
                        _status("Fetching more…")
                        threading.Thread(target=_do_append, daemon=True).start()

                elif key == "d":
                    del_idx, deleted_playing, empty_now = core.delete_cursor()
                    if empty_now:
                        core.stop_current()
                        sys.stdout.write(_NL)
                        print("Playlist is now empty.")
                        return
                    if deleted_playing:
                        break
                    _scroll_to(core.cursor_idx)
                    _redraw_viewport(); _update_header()
                    _status(f"Deleted  [{len(core.tracks)} tracks remain]")

                elif key == "s":
                    try:
                        from autoplaylist import playlist as _pl
                        _pl.save(core.playlist_name, core.tracks, core.prompt)
                        _status(f"Saved  {core.playlist_name}  [{len(core.tracks)} tracks]")
                    except Exception as e:
                        _status(f"Save failed: {str(e)[:60]}")

                elif key == "y":
                    n_cands = len(core.lrc_candidates)
                    if n_cands == 0:
                        _status("No lyrics available")
                    elif n_cands == 1:
                        _status("Lyrics 1/1  (only source)")
                    else:
                        core.lrc_idx = (core.lrc_idx + 1) % n_cands
                        core.lyric["line"] = None
                        core.lyric["off"] = 0
                        core.lyric["idx"] = None
                        if core.lyric_panel_on and core.panel_widths:
                            _, plw, lw = core.panel_widths
                            _draw_lyric_panel(_active_lrc(), None, plw, lw, core.vh,
                                              core.lyric["anim_t"], core.lyric["mood"])
                            sys.stdout.flush()
                        _status(f"Lyrics {core.lrc_idx + 1}/{n_cands}")
                        # Persist preference: put selected candidate first in cache,
                        # but keep in-memory list/index untouched so subsequent `y`
                        # presses can continue advancing past 2/N.
                        _t = core.tracks[core.current_idx]
                        idx = core.lrc_idx
                        if idx != 0 and core.lrc_candidates:
                            from autoplaylist import cache as _cache
                            reordered = core.lrc_candidates[idx:] + core.lrc_candidates[:idx]
                            _cache.save_lyrics(_t.artist, _t.title, reordered)

                elif key == "Y":
                    # Clear cached lyrics for current track and re-fetch
                    _t = core.tracks[core.current_idx]
                    from autoplaylist import cache as _cache
                    _cache.save_lyrics(_t.artist, _t.title, [])
                    core.lrc_candidates = []
                    core.lrc_ready = False
                    core.lrc_idx = 0
                    core.lyric.update({"line": None, "off": 0, "idx": None})
                    # Immediately blank the lyrics panel
                    if core.lyric_panel_on and core.panel_widths:
                        _, plw, lw = core.panel_widths
                        _draw_lyric_panel([], None, plw, lw, core.vh,
                                          core.lyric["anim_t"], core.lyric["mood"])
                        sys.stdout.flush()
                    _status("Refreshing lyrics…")
                    def _refresh_and_notify(artist: str, title: str) -> None:
                        _fetch_lyrics(artist, title)
                        n = len(core.lrc_candidates)
                        if n > 0:
                            _status(f"Lyrics {n} source(s) found — press [y] to cycle")
                        else:
                            _status("No lyrics found for this track")
                    _lrc_thread2 = threading.Thread(
                        target=_refresh_and_notify, args=(_t.artist, _t.title), daemon=True
                    )
                    _lrc_thread2.start()

                elif key == "r":
                    core.cycle_mode()
                    mode_names = {"seq": "Sequential →→", "repeat": "Repeat one ↺", "shuffle": "Shuffle ⇄"}
                    if core.lyric_panel_on and core.panel_widths:
                        _, plw, lw = core.panel_widths
                        _full_repaint(True, plw, lw)
                    else:
                        _full_repaint(False, _IW, 0)
                    _status(f"Mode: {mode_names[core.play_mode]}")

                elif key in ("[", "]"):
                    if len(core.playlists) == 1:
                        _status("Only one playlist")
                    else:
                        try:
                            from autoplaylist import playlist as _pl
                            _pl.save(core.playlist_name, core.tracks, core.prompt)
                        except Exception:
                            pass
                        core.request_switch_tab(-1 if key == "[" else 1)
                        break

                elif key == "n":
                    old = core.next_track()
                    if old is not None:
                        if _scroll_to(core.current_idx):
                            _redraw_viewport(); _update_header()
                        else:
                            _draw_track(old, False, False, False)
                            _draw_track(core.current_idx, True, False, True)
                            sys.stdout.flush()
                        _update_lyric_header()
                    break

                elif key == "UP":
                    old_cur = core.select(core.cursor_idx - 1)
                    new_cur = core.cursor_idx
                    if new_cur != old_cur:
                        if _scroll_to(new_cur):
                            _redraw_viewport(); _update_header()
                        else:
                            _draw_track(old_cur, old_cur == core.current_idx,
                                        core.paused and old_cur == core.current_idx, False)
                            _draw_track(new_cur, new_cur == core.current_idx,
                                        core.paused and new_cur == core.current_idx, True)
                            sys.stdout.flush()
                        _status(f"Select   [{new_cur + 1}/{len(core.tracks)}]  {_make_label(core.tracks[new_cur], 55)}")

                elif key == "DOWN":
                    old_cur = core.select(core.cursor_idx + 1)
                    new_cur = core.cursor_idx
                    if new_cur != old_cur:
                        if _scroll_to(new_cur):
                            _redraw_viewport(); _update_header()
                        else:
                            _draw_track(old_cur, old_cur == core.current_idx,
                                        core.paused and old_cur == core.current_idx, False)
                            _draw_track(new_cur, new_cur == core.current_idx,
                                        core.paused and new_cur == core.current_idx, True)
                            sys.stdout.flush()
                        _status(f"Select   [{new_cur + 1}/{len(core.tracks)}]  {_make_label(core.tracks[new_cur], 55)}")

                elif key == "RIGHT":
                    new_vs = min(len(core.tracks) - core.vh, core.view_start + core.vh)
                    new_cur = min(len(core.tracks) - 1, new_vs)
                    if new_vs != core.view_start:
                        core.select(new_cur)
                        core.view_start = new_vs
                        _redraw_viewport(); _update_header()
                        _status(f"Select   [{new_cur + 1}/{len(core.tracks)}]  {_make_label(core.tracks[new_cur], 55)}")

                elif key == "LEFT":
                    new_vs = max(0, core.view_start - core.vh)
                    new_cur = new_vs
                    if new_vs != core.view_start:
                        core.select(new_cur)
                        core.view_start = new_vs
                        _redraw_viewport(); _update_header()
                        _status(f"Select   [{new_cur + 1}/{len(core.tracks)}]  {_make_label(core.tracks[new_cur], 55)}")

                elif key in ("\r", "\n"):
                    if num_buf:
                        target = int(num_buf) - 1; num_buf = ""
                    else:
                        target = core.cursor_idx
                    if 0 <= target < len(core.tracks) and target != core.current_idx:
                        _jump_to(target); break
                    num_buf = ""; _status(f"{_cache_mark}Playing  [{core.current_idx + 1}/{len(core.tracks)}]  {label}")

                elif key and key.isdigit():
                    num_buf = (num_buf + key) if num_buf and now - num_ts < 1.5 else key
                    num_ts = now
                    _status(f"Goto     [{num_buf}]  — add digits or Enter")

                # Poll core event queue for natural-exit notifications.
                # core.run() detects mpv exit + runs pick_next_idx() and posts:
                #   ("repeat",) — same track restart (lyric state already reset)
                #   ("next",)   — core.current_idx is already advanced; repaint + break
                try:
                    ev = core._ui_q.get_nowait()
                except queue.Empty:
                    ev = None
                if ev is not None:
                    tag = ev[0] if isinstance(ev, tuple) else ev
                    if tag == "repeat":
                        break
                    if tag == "next":
                        old = ev[1]
                        if core.current_idx < len(core.tracks):
                            core.cursor_idx = core.current_idx
                            if _scroll_to(core.current_idx):
                                _redraw_viewport(); _update_header()
                            else:
                                _draw_track(old, False, False, False)
                                _draw_track(core.current_idx, True, False, True)
                                sys.stdout.flush()
                            _update_lyric_header()
                        break
                    if tag == "ctl_quit":
                        sys.stdout.write(_NL)
                        return
                    if tag == "ctl_next":
                        # Remote next — core already advanced; repaint + break
                        if core.current_idx < len(core.tracks):
                            core.cursor_idx = core.current_idx
                            if _scroll_to(core.current_idx):
                                _redraw_viewport(); _update_header()
                            _update_lyric_header()
                        break
                    if tag in ("ctl_pause", "ctl_mode"):
                        # Remote pause/mode — redraw status + controls
                        state = "Paused " if core.paused else "Playing"
                        _status(f"{_cache_mark}{state}  [{core.current_idx + 1}/{len(core.tracks)}]  {label}")
                        _draw_track(core.current_idx, True, core.paused, core.cursor_idx == core.current_idx)
                        if core.lyric_panel_on and core.panel_widths:
                            _, plw, lw = core.panel_widths
                            _full_repaint(True, plw, lw)
                        else:
                            _full_repaint(False, _IW, 0)
                        sys.stdout.flush()

    finally:
        signal.signal(signal.SIGINT, _orig_sigint)
        key_reader.stop()
        if not detached:
            stop_current()
            ctl_server.stop()
        # detached: mpv already killed before fork; socket left for daemon
        core.shutdown()
        _restore_terminal()
        sys.stdout.write(_NL)

