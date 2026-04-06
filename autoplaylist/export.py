from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any


def export_m3u(playlist: dict[str, Any], path: Path) -> None:
    """Export playlist as extended M3U."""
    lines = ["#EXTM3U", ""]
    for t in playlist.get("tracks", []):
        dur = t.get("duration_seconds", -1)
        artist = t.get("artist", "")
        title = t.get("title", "")
        url = t.get("youtube_url", "")
        lines.append(f"#EXTINF:{dur},{artist} - {title}")
        lines.append(url)
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def export_csv(playlist: dict[str, Any], path: Path) -> None:
    """Export playlist as CSV."""
    fieldnames = ["title", "artist", "duration_seconds", "youtube_url", "source"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for t in playlist.get("tracks", []):
            writer.writerow({k: t.get(k, "") for k in fieldnames})


def export_json(playlist: dict[str, Any], path: Path) -> None:
    """Export playlist as pretty-printed JSON (same schema as internal storage)."""
    path.write_text(json.dumps(playlist, indent=2, ensure_ascii=False), encoding="utf-8")
