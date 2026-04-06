# myplaylist

[![PyPI version](https://img.shields.io/pypi/v/myplaylist.svg)](https://pypi.org/project/myplaylist/)
[![Python versions](https://img.shields.io/pypi/pyversions/myplaylist.svg)](https://pypi.org/project/myplaylist/)

Generate and play music playlists in your terminal from natural language prompts or seed songs.

## Features

- **Natural language prompts**: `myplaylist new "下雨天的 lo-fi jazz"`
- **Seed songs**: `myplaylist new --seed "Norah Jones - Come Away With Me"`
- **Terminal playback** via mpv with a rich TUI (pause / skip / lyrics marquee)
- **Local persistence** at `~/.myplaylist/playlists/`
- **Export** to `.m3u`, `.csv`, or `.json`
- **Zero-config LLM**: uses your existing Claude subscription via `claude -p`

## Requirements

- Python 3.9+
- [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) (`claude`) — for natural language mode
- macOS or Linux

## Installation

### Option 1 — curl one-liner (recommended)

```bash
curl -fsSL https://raw.githubusercontent.com/eddie/autoplaylist/main/install.sh | bash
```

The script will:
1. Detect macOS / Linux
2. Check for Python 3.9+
3. Install `pipx` if missing (and guide PATH setup)
4. Install `myplaylist` via `pipx`
5. Install `mpv` (Homebrew on macOS, apt on Linux)

### Option 2 — Homebrew tap

```bash
brew tap eddie/myplaylist
brew install myplaylist
```

### Option 3 — pipx (manual)

```bash
pipx install myplaylist
```

> mpv is required for playback. Install it separately if needed:
> - macOS: `brew install mpv`
> - Linux: `sudo apt-get install mpv`

On first run, `myplaylist` will walk you through the optional Last.fm API key setup.

## Quick Start

```bash
# Natural language prompt
myplaylist new "rainy day lo-fi jazz for working"

# Seed song
myplaylist new --seed "Norah Jones - Come Away With Me"

# Seed from YouTube URL
myplaylist new --seed "https://www.youtube.com/watch?v=..."

# Custom track count and name
myplaylist new "chill beats" --count 20 --name my-chill-list
```

## Commands

| Command | Description |
|---|---|
| `myplaylist new "<prompt>"` | Generate playlist from natural language |
| `myplaylist new --seed "<song>"` | Generate playlist from seed song |
| `myplaylist list` | List all saved playlists |
| `myplaylist show <name>` | Show track listing |
| `myplaylist play <name>` | Play in terminal |
| `myplaylist export <name> --format m3u\|csv\|json` | Export playlist |
| `myplaylist delete <name>` | Delete a playlist |
| `myplaylist setup` | Re-run first-time setup |

## Playback Controls

| Key | Action |
|---|---|
| `p` | Pause / resume |
| `n` | Skip to next track |
| `↑ / ↓` | Move cursor up / down |
| `← / →` | Page up / page down |
| `Enter` | Jump to selected track |
| `q` | Quit |

## Last.fm (optional)

Last.fm integration improves similar-song quality. Get a free API key at <https://www.last.fm/api/account/create> and enter it during first-run setup. You can skip this and run in yt-dlp-only mode.

## Data Storage

```
~/.myplaylist/
  config.json          # API keys and settings
  playlists/
    <name>.json        # Saved playlists
```

## Uninstall

```bash
# If installed via pipx or the install.sh script:
pipx uninstall myplaylist

# If installed via Homebrew tap:
brew uninstall myplaylist
brew untap eddie/myplaylist
```

## Running Tests

```bash
pip install pytest
pytest tests/                     # smoke tests (no network)
pytest tests/ -m slow             # include integration tests (requires network)
```
