# myplaylist

[![PyPI version](https://img.shields.io/pypi/v/myplaylist.svg)](https://pypi.org/project/myplaylist/)
[![Python versions](https://img.shields.io/pypi/pyversions/myplaylist.svg)](https://pypi.org/project/myplaylist/)

Generate and play music playlists in your terminal from natural language prompts or seed songs.

![myplaylist TUI — playlist view with lyrics panel and mood animation](assets/screenshot.png)

## Why myplaylist?

- **AI-native, terminal-first** — describe any mood or song in plain language and get a curated playlist instantly, without leaving your terminal
- **Ad-free playback** — streams directly from YouTube via yt-dlp and mpv; no ads, no interruptions
- **You own your playlists** — add, delete, reorder, and save tracks live during playback; export to M3U/CSV/JSON for use anywhere
- **Vast music catalog** — any song on YouTube is fair game, from mainstream hits to obscure jazz recordings and everything in between
- **No account, no tracking** — everything stays local in `~/.myplaylist/`; no sign-up, no cloud sync, no data collection
- **Zero extra subscription** — works with your existing Claude subscription, a free Groq/Qwen/DeepSeek API key, or a local Ollama instance; no music platform membership required
- **Immersive terminal experience** — time-synced lyrics and mood-driven ASCII animations keep the vibe going while you work
- **Background playback** — detach to a headless daemon with `b` or `--detach`; close the terminal and music keeps playing
- **Remote control** — `myplaylist ctl next/pause/quit` from any terminal, or attach a full TUI with `myplaylist attach`
- **Global hotkeys** — system-wide keyboard shortcuts via skhd (macOS); control playback from any app

## Features

- **Natural language prompts**: `myplaylist new "下雨天的 lo-fi jazz"`
- **Seed songs**: `myplaylist new --seed "Norah Jones - Come Away With Me"`
- **Terminal playback** via mpv with a rich TUI (pause / skip / lyrics marquee / progress bar)
- **Headless daemon mode**: `myplaylist play --detach` or press `b` during playback to background
- **Attach TUI**: `myplaylist attach` connects to a running daemon with full keyboard controls
- **Remote control**: `myplaylist ctl pause`, `myplaylist ctl next`, `myplaylist ctl quit`
- **Global hotkeys**: `myplaylist hotkeys` sets up system-wide shortcuts (Ctrl+Alt+P/N/Q/R/A)
- **Lyrics panel**: toggle a side panel showing time-synced lyrics with mood-driven ASCII animations
- **In-session append**: press `+` to fetch ~10 more tracks without interrupting playback
- **Playlist loops**: automatically restarts from track 1 after the last track
- **Local persistence** at `~/.myplaylist/playlists/`
- **Export** to `.m3u`, `.csv`, or `.json`
- **Multiple LLM backends**: Claude Code CLI (zero-config), Gemini, Groq, Qwen (通义千问), DeepSeek, Kimi, Ollama (local/offline), or any OpenAI-compatible endpoint

## Requirements

- Python 3.9+
- macOS or Linux
- One of the following LLM backends (for natural language mode):
  - [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) (`claude`) — zero-config if you have a Claude subscription
  - Gemini API key — set via `myplaylist setup`
  - Groq, Qwen (通义千问), DeepSeek, or Kimi — free API keys, set via `myplaylist setup`
  - [Ollama](https://ollama.com) — fully local, no API key, works offline

## Installation

### macOS — Homebrew (recommended)

```bash
brew tap haoziwlh/autoplaylist https://github.com/haoziwlh/autoplaylist && brew install myplaylist
```

Homebrew handles everything: Python, mpv, and myplaylist itself.

### macOS / Linux — curl one-liner

```bash
curl -fsSL https://raw.githubusercontent.com/haoziwlh/autoplaylist/main/install.sh | bash
```

The script detects your OS, installs pipx, myplaylist, and mpv automatically.

### Manual — pipx

```bash
pipx install myplaylist
```

> mpv is required for playback. Install it separately if needed:
> - macOS: `brew install mpv`
> - Linux: `sudo apt-get install mpv`

On first run, myplaylist will automatically guide you through setup (LLM backend, optional Last.fm key).

## Quick Start

```bash
# Play your most recent playlist instantly
myplaylist

# Natural language prompt
myplaylist new "rainy day lo-fi jazz for working"

# Seed song
myplaylist new --seed "Norah Jones - Come Away With Me"

# Seed from YouTube URL
myplaylist new --seed "https://www.youtube.com/watch?v=..."

# Custom track count (default 20, max 50) and name
myplaylist new "chill beats" --count 30 --name my-chill-list
```

## Commands

| Command | Description |
|---|---|
| `myplaylist` | Play the most recent playlist |
| `myplaylist new "<prompt>"` | Generate playlist from natural language |
| `myplaylist new --seed "<song>"` | Generate playlist from seed song |
| `myplaylist new ... --count <n>` | Set track count (default 20, max 50) |
| `myplaylist list` | List all saved playlists |
| `myplaylist show <name>` | Show track listing |
| `myplaylist play [name]` | Play a playlist (defaults to most recent) |
| `myplaylist export <name> --format m3u\|csv\|json` | Export playlist |
| `myplaylist delete <name>` | Delete a playlist |
| `myplaylist play --detach` | Start playback as a background daemon |
| `myplaylist attach` | Attach TUI to a running daemon |
| `myplaylist ctl status` | Show current playback status |
| `myplaylist ctl pause` | Toggle pause / resume |
| `myplaylist ctl next` | Skip to next track |
| `myplaylist ctl mode [seq\|repeat\|shuffle]` | Cycle or set play mode |
| `myplaylist ctl quit` | Stop the player daemon |
| `myplaylist hotkeys` | Set up global keyboard shortcuts (macOS) |
| `myplaylist hotkeys --show` | Show current hotkey bindings |
| `myplaylist hotkeys --remove` | Remove hotkeys and stop skhd |
| `myplaylist setup` | Choose LLM backend and configure API keys |

## Playback Controls

| Key | Action |
|---|---|
| `p` | Pause / resume |
| `n` | Skip to next track |
| `,` / `.` | Seek ±5 seconds (mpv-style) |
| `<` / `>` | Seek ±30 seconds |
| `↑ / ↓` | Move cursor up / down |
| `← / →` | Page up / page down |
| `Enter` | Jump to selected track |
| `0`–`9` + `Enter` | Jump to track by number |
| `+` | Append ~10 more tracks (background, non-blocking) |
| `r` | Cycle playback mode: sequential →→ / repeat-one ↺ / shuffle ⇄ |
| `l` | Toggle lyrics panel (time-synced lyrics + mood animation) |
| `y` | Cycle to next lyrics source (when multiple candidates available) |
| `[` / `]` | Switch to previous / next playlist |
| `d` | Delete cursor track from live playlist |
| `s` | Save current playlist to disk |
| `b` | Detach to background daemon (music keeps playing) |
| `q` | Quit |

## Background Playback & Global Hotkeys

**Detach to background:** press `b` during playback or start with `myplaylist play --detach`. Music keeps playing after the terminal closes.

**Remote control from any terminal:**

```bash
myplaylist ctl pause      # toggle pause
myplaylist ctl next       # skip track
myplaylist ctl status     # show what's playing
myplaylist attach         # full TUI reconnect
```

**Global hotkeys (macOS):**

```bash
myplaylist hotkeys        # install skhd + configure default bindings
myplaylist hotkeys --show # show current bindings
```

Default bindings (`Ctrl+Alt+…`):

| Shortcut | Action |
|---|---|
| `Ctrl+Alt+P` | Pause / resume |
| `Ctrl+Alt+N` | Next track |
| `Ctrl+Alt+Q` | Quit daemon |
| `Ctrl+Alt+R` | Cycle play mode |
| `Ctrl+Alt+A` | Open attach TUI |

The attach hotkey opens Terminal.app by default. To use **iTerm2** (new tab in existing window), edit `~/.config/skhd/skhdrc`:

```bash
# Replace the ctrl + alt - a line with:
ctrl + alt - a : osascript -e 'tell app "iTerm2"' -e 'if (count of windows) > 0 then' -e 'tell current window to create tab with default profile' -e 'else' -e 'create window with default profile' -e 'end if' -e 'tell current session of current window to write text "myplaylist ctl status >/dev/null 2>&1 || myplaylist play --detach; sleep 1; exec myplaylist attach"' -e 'end tell'
```


## Lyrics Panel

Press `l` during playback to open a side panel with time-synced lyrics. The panel also shows a mood-driven ASCII animation in the margin — determined per track by the LLM (calm, melancholic, energetic, romantic, nostalgic).

Lyrics are fetched in parallel from three sources: [lrclib.net](https://lrclib.net) (up to 3 candidates), [Netease Cloud Music](https://music.163.com), and [Kugou Music](https://www.kugou.com) — improving coverage for Chinese music and tracks not found on lrclib. Press `y` to cycle through available sources (the preferred source is remembered for next time); press `Y` to discard the cached lyrics and re-fetch fresh candidates.

Requires terminal width ≥ 84 columns.

## Last.fm (optional)

Last.fm integration improves similar-song quality — without it, myplaylist falls back to yt-dlp search only.

**Getting a free API key:**

1. Go to <https://www.last.fm/api/account/create> (create a Last.fm account first if needed)
2. Fill in any values for Application name / description (e.g. `myplaylist` / `personal use`)
3. Leave Callback URL blank, submit
4. Copy the **API key** and **Shared secret** from the confirmation page

**Saving the key:**

```bash
myplaylist config --lastfm-key <API key> --lastfm-secret <shared secret>
```

Or re-run setup and enter them interactively:

```bash
myplaylist setup
```

## LLM Backends

Run `myplaylist setup` to choose your backend interactively. You can also switch at any time:

```bash
myplaylist config --llm-backend groq --llm-api-key <key>
myplaylist config --llm-backend qwen --llm-api-key <key>
myplaylist config --llm-backend ollama --ollama-model qwen2.5:7b
```

| Backend | Free? | Notes |
|---|---|---|
| `claude` | With Claude subscription | Zero-config; recommended |
| `gemini` | Free tier | `gemini-2.5-flash` |
| `groq` | Free tier | Fast inference; llama3 |
| `qwen` | Free credits | Best for Chinese music; [get key](https://dashscope.aliyun.com/) |
| `deepseek` | Free credits | Strong reasoning; [get key](https://platform.deepseek.com/) |
| `kimi` | Free credits | Moonshot AI; [get key](https://platform.moonshot.cn/) |
| `ollama` | Free, local | Requires [Ollama](https://ollama.com) + `ollama pull qwen2.5:7b` |
| `openai-compat` | Varies | Any OpenAI-compatible endpoint |

## Troubleshooting

**Playback stuck on "Loading" / tracks all skipped**

YouTube occasionally requires authentication for certain IPs. myplaylist automatically tries to use cookies from your browser (Chrome, Firefox, Edge, or Brave) to work around this. If you still have issues:

1. Run with `--debug` to see what's happening:
   ```bash
   myplaylist play --debug
   cat ~/.myplaylist/player.log
   ```
2. If the log shows `Sign in to confirm you're not a bot`, export a `cookies.txt` file from your browser using an extension such as [Get cookies.txt LOCALLY](https://chromewebstore.google.com/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc) (Chrome) or [cookies.txt](https://addons.mozilla.org/firefox/addon/cookies-txt/) (Firefox), then:
   ```bash
   myplaylist config --cookie-file ~/cookies.txt
   ```

**YouTube signature decryption errors** (e.g. `Some formats may be missing` or `nsig extraction failed`)

YouTube requires a JavaScript runtime to decrypt video signatures. myplaylist passes `--remote-components ejs:github` to fetch the decryption script on the fly — but you still need a local JS runtime. Install one:

```bash
brew install deno           # recommended (macOS)
# or: brew install node / bun
```

Run `myplaylist doctor` to confirm the runtime is detected. The `doctor` output also shows whether `yt-dlp-ejs` is installed locally (reduces per-play network calls).

**`myplaylist` command not found after install**

Open a new terminal, or run:
```bash
source ~/.zshrc   # macOS / zsh
source ~/.bashrc  # Linux / bash
```

## Data Storage

```
~/.myplaylist/
  config.json          # API keys and settings
  playlists/
    <name>.json        # Saved playlists
  cache/
    audio/             # Cached audio files (LRU, default 500 MB)
    lyrics/            # Cached lyrics per track
```

Audio and lyrics are cached on first play for faster subsequent loads and offline listening. When a cached track plays, the status line shows a `⚡` marker (e.g. `⚡ Playing [3/20] …`). Cache size is configurable:

```bash
myplaylist config --cache-max-mb 1000   # increase to 1 GB
myplaylist cache --clear                # clear everything
myplaylist cache --clear-audio          # clear audio only
myplaylist cache --clear-lyrics         # clear lyrics only
```

## Upgrade

```bash
# pipx
pipx upgrade myplaylist

# Homebrew
brew upgrade myplaylist
```

## Uninstall

```bash
# If installed via pipx or the install.sh script:
pipx uninstall myplaylist

# If installed via Homebrew tap:
brew uninstall myplaylist
brew untap haoziwlh/autoplaylist
```

## License

MIT — see [LICENSE](LICENSE).

## Running Tests

```bash
pip install pytest
pytest tests/                     # smoke tests (no network)
pytest tests/ -m slow             # include integration tests (requires network)
```
