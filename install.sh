#!/usr/bin/env bash
# myplaylist installer
# Usage: curl -fsSL https://raw.githubusercontent.com/eddie/autoplaylist/main/install.sh | bash

set -euo pipefail

# ── helpers ──────────────────────────────────────────────────────────────────
LOG_FILE="${TMPDIR:-/tmp}/myplaylist-install.log"
_info()  { printf '\033[1;32m==>\033[0m %s\n' "$*"; }
_warn()  { printf '\033[1;33mwarn:\033[0m %s\n' "$*"; }
_error() { printf '\033[1;31merror:\033[0m %s\n' "$*" >&2; exit 1; }

# Run a command silently, log output; on failure print log and exit
_run() {
  if ! "$@" >>"$LOG_FILE" 2>&1; then
    printf '\033[1;31merror:\033[0m Command failed: %s\n' "$*" >&2
    printf 'See full log: %s\n' "$LOG_FILE" >&2
    exit 1
  fi
}

# Initialize log
: >"$LOG_FILE"
_info "Install log: $LOG_FILE"

# ── 1. OS detection ───────────────────────────────────────────────────────────
OS="$(uname -s)"
case "$OS" in
  Darwin) ;;
  Linux)  ;;
  *) _error "Unsupported operating system: $OS (only macOS and Linux are supported)" ;;
esac

# ── 2. Python 3.9+ detection ─────────────────────────────────────────────────
_python=""
for cmd in python3 python; do
  if command -v "$cmd" &>/dev/null; then
    major="$("$cmd" -c 'import sys; print(sys.version_info.major)' 2>/dev/null || true)"
    minor="$("$cmd" -c 'import sys; print(sys.version_info.minor)' 2>/dev/null || true)"
    if [ -n "$major" ] && [ "$major" -ge 3 ] && [ "$minor" -ge 9 ]; then
      _python="$cmd"
      break
    fi
  fi
done

if [ -z "$_python" ]; then
  if [ "$OS" = "Darwin" ]; then
    _error "Python 3.9+ not found. Install it with: brew install python"
  else
    _error "Python 3.9+ not found. Install it with: sudo apt-get install -y python3"
  fi
fi

_info "Using $("$_python" --version)"

# ── 3. pipx detection & install ──────────────────────────────────────────────
if ! command -v pipx &>/dev/null; then
  _info "Installing pipx..."
  if [ "$OS" = "Darwin" ] && command -v brew &>/dev/null; then
    HOMEBREW_NO_AUTO_UPDATE=1 HOMEBREW_NO_ENV_HINTS=1 _run brew install pipx
    _run pipx ensurepath
  else
    _run "$_python" -m pip install --user pipx
    export PATH="$HOME/.local/bin:$PATH"
  fi

  if ! command -v pipx &>/dev/null; then
    _warn "pipx installed but not found in PATH."
    _warn "Add the following to your shell profile and restart your terminal:"
    if [ "$OS" = "Darwin" ]; then
      _warn "  echo 'export PATH=\"\$HOME/.local/bin:\$PATH\"' >> ~/.zshrc && source ~/.zshrc"
    else
      _warn "  echo 'export PATH=\"\$HOME/.local/bin:\$PATH\"' >> ~/.bashrc && source ~/.bashrc"
    fi
    _warn "Then re-run this installer."
    exit 1
  fi
fi

_info "pipx $(pipx --version)"

# ── 4. idempotency check ─────────────────────────────────────────────────────
if pipx list 2>/dev/null | grep -q "myplaylist"; then
  installed_ver="$(pipx list 2>/dev/null | grep myplaylist | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1 || true)"
  _info "myplaylist ${installed_ver:-already} is already installed. Skipping."
  echo ""
  echo "  To upgrade:   pipx upgrade myplaylist"
  echo "  To uninstall: pipx uninstall myplaylist"
  echo ""
  exit 0
fi

# ── 5. install myplaylist ─────────────────────────────────────────────────────
_info "Installing myplaylist via pipx..."
_run pipx install myplaylist

# ── 6. mpv detection & install ───────────────────────────────────────────────
if command -v mpv &>/dev/null; then
  _info "mpv already installed: $(mpv --version | head -1)"
else
  _info "Installing mpv..."
  if [ "$OS" = "Darwin" ]; then
    if ! command -v brew &>/dev/null; then
      _warn "Homebrew not found. Please install mpv manually: https://mpv.io/installation/"
    else
      HOMEBREW_NO_AUTO_UPDATE=1 HOMEBREW_NO_ENV_HINTS=1 _run brew install mpv
    fi
  else
    if command -v apt-get &>/dev/null; then
      _run sudo apt-get install -y mpv
    else
      _warn "apt-get not found. Please install mpv manually: https://mpv.io/installation/"
    fi
  fi
fi

# ── 7. success message ────────────────────────────────────────────────────────
printf '\033[1;32m✓ myplaylist installed! Create your first playlist:\033[0m\n'
echo ""
echo '    myplaylist new "chill lo-fi beats"'
echo '    myplaylist new --seed "后来 - 刘若英"'
echo ""
echo "  All commands:"
echo "    myplaylist new     — create a new playlist from prompt or seed song"
echo "    myplaylist list    — list saved playlists"
echo "    myplaylist play    — play a saved playlist"
echo "    myplaylist setup   — re-run first-time setup"
echo ""
