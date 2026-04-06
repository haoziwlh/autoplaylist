#!/bin/bash
set -e

echo "🗑  Uninstalling myplaylist..."

# Python package (pipx)
if command -v pipx &>/dev/null && pipx list 2>/dev/null | grep -q "myplaylist"; then
  pipx uninstall myplaylist -q && echo "  ✓ myplaylist removed (pipx)"
else
  echo "  - myplaylist not installed via pipx"
fi

# Homebrew tap install
if command -v brew &>/dev/null && brew list myplaylist &>/dev/null 2>&1; then
  brew uninstall myplaylist && echo "  ✓ myplaylist removed (brew)"
fi

# Data directory
DATA_DIR="$HOME/.myplaylist"
if [ -d "$DATA_DIR" ]; then
  read -rp "  Remove all playlists and config at $DATA_DIR? [y/N] " confirm
  if [[ "$confirm" =~ ^[Yy]$ ]]; then
    rm -rf "$DATA_DIR"
    echo "  ✓ Data directory removed"
  else
    echo "  - Keeping $DATA_DIR"
  fi
fi

echo ""
echo "Done. mpv was not removed (may be used by other apps)."
echo "To remove mpv: brew uninstall mpv"
