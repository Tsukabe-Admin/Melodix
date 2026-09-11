"""playlists.py — persistent, user-named track playlists stored as JSON.

Playlist names are sanitised before they touch the filesystem so a name can
never escape the playlists directory. All mutating helpers return ``bool`` so
the UI can tell the user when a write did not happen.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from .models import make_track

log = logging.getLogger(__name__)

DEFAULT_PLAYLISTS_DIR = os.path.expanduser("~/.config/melodix/playlists")


def ensure_playlists_dir() -> str:
    os.makedirs(DEFAULT_PLAYLISTS_DIR, exist_ok=True)
    return DEFAULT_PLAYLISTS_DIR


def list_playlists() -> list[str]:
    """Return playlist names (without the ``.json`` extension), sorted."""
    try:
        ensure_playlists_dir()
        names = [
            f[:-5] for f in os.listdir(DEFAULT_PLAYLISTS_DIR) if f.endswith(".json")
        ]
    except OSError:
        log.warning("could not list playlists in %s", DEFAULT_PLAYLISTS_DIR, exc_info=True)
        return []
    return sorted(names)


def sanitize_playlist_name(name: str) -> str:
    """Return the safe on-disk playlist name (without extension)."""
    safe_name = "".join(
        c for c in name if c.isalpha() or c.isdigit() or c in (" ", "-", "_")
    ).strip()
    return safe_name or "untitled"


def get_playlist_path(name: str) -> str:
    ensure_playlists_dir()
    return os.path.join(DEFAULT_PLAYLISTS_DIR, f"{sanitize_playlist_name(name)}.json")


def _coerce_track(raw: Any) -> dict[str, Any] | None:
    """Validate one raw playlist entry, returning ``None`` if it is unusable."""
    if not isinstance(raw, dict):
        return None
    track_path = raw.get("path")
    if not isinstance(track_path, str) or not track_path:
        return None
    try:
        duration_sec = float(raw.get("duration_sec") or 0)
    except (TypeError, ValueError):
        duration_sec = 0.0
    return make_track(
        track_path,
        title=str(raw.get("title") or Path(track_path).stem),
        artist=str(raw.get("artist") or ""),
        duration=str(raw.get("duration") or "--:--"),
        duration_sec=duration_sec,
    )


def load_playlist(name: str) -> list[dict[str, Any]]:
    """Load and validate a playlist, skipping individual corrupt entries."""
    path = get_playlist_path(name)
    if not os.path.exists(path):
        return []
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        log.warning("could not read playlist %s", path, exc_info=True)
        return []

    if isinstance(data, dict):
        raw_tracks = data.get("tracks", [])
    elif isinstance(data, list):
        raw_tracks = data
    else:
        return []

    validated = []
    for raw in raw_tracks:
        track = _coerce_track(raw)
        if track is None:
            log.debug("skipping malformed track in playlist %s: %r", name, raw)
            continue
        validated.append(track)
    return validated


def save_playlist(name: str, tracks: list[dict[str, Any]]) -> bool:
    """Atomically save tracks to a playlist. Returns ``True`` on success."""
    path = get_playlist_path(name)
    data = {
        "name": name,
        "tracks": [
            {
                "path": t["path"],
                "title": t["title"],
                "artist": t.get("artist", ""),
                "duration": t.get("duration", "--:--"),
                "duration_sec": t.get("duration_sec", 0),
            }
            for t in tracks
        ],
    }
    tmp_path = f"{path}.tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp_path, path)
        return True
    except OSError:
        log.warning("could not save playlist %s", path, exc_info=True)
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except OSError:
            pass
        return False


def delete_playlist(name: str) -> bool:
    """Delete a playlist file. Returns ``True`` if it no longer exists."""
    path = get_playlist_path(name)
    try:
        os.remove(path)
        return True
    except FileNotFoundError:
        return True
    except OSError:
        log.warning("could not delete playlist %s", path, exc_info=True)
        return False


def add_track_to_playlist(name: str, track: dict[str, Any]) -> bool:
    """Append a single track to a playlist, creating it if necessary."""
    tracks = load_playlist(name)
    tracks.append({
        "path": track["path"],
        "title": track["title"],
        "artist": track.get("artist", ""),
        "duration": track.get("duration", "--:--"),
        "duration_sec": track.get("duration_sec", 0),
    })
    return save_playlist(name, tracks)
