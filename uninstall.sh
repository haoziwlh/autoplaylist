#!/bin/bash
set -e

echo "🗑  Uninstalling autoplaylist..."

# Python package
pip uninstall autoplaylist -y -q 2>/dev/null && echo "  ✓ Python package removed" || echo "  - Package not installed via pip"

# Data directory
DATA_DIR="$HOME/.autoplaylist"
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
