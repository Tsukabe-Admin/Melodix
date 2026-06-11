import os
import json
from pathlib import Path
from typing import List, Dict, Any

DEFAULT_PLAYLISTS_DIR = os.path.expanduser("~/.config/melodix/playlists")

def ensure_playlists_dir() -> str:
    os.makedirs(DEFAULT_PLAYLISTS_DIR, exist_ok=True)
    return DEFAULT_PLAYLISTS_DIR

def list_playlists() -> List[str]:
    """Returns a list of playlist names (without the .json extension)."""
    ensure_playlists_dir()
    playlists = []
    if os.path.exists(DEFAULT_PLAYLISTS_DIR):
        for f in os.listdir(DEFAULT_PLAYLISTS_DIR):
            if f.endswith(".json"):
                playlists.append(f[:-5])
    return sorted(playlists)

def get_playlist_path(name: str) -> str:
    ensure_playlists_dir()
    # Sanitize the name to prevent path traversal
    safe_name = "".join([c for c in name if c.isalpha() or c.isdigit() or c in (" ", "-", "_")]).strip()
    if not safe_name:
        safe_name = "untitled"
    return os.path.join(DEFAULT_PLAYLISTS_DIR, f"{safe_name}.json")

def load_playlist(name: str) -> List[Dict[str, Any]]:
    """Loads tracks from a playlist file."""
    path = get_playlist_path(name)
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                return data.get("tracks", [])
            elif isinstance(data, list):
                return data
    except Exception:
        pass
    return []

def save_playlist(name: str, tracks: List[Dict[str, Any]]) -> None:
    """Saves tracks to a playlist file."""
    path = get_playlist_path(name)
    data = {
        "name": name,
        "tracks": [
            {
                "path": t["path"],
                "title": t["title"],
                "artist": t.get("artist", ""),
                "duration": t.get("duration", "--:--"),
                "duration_sec": t.get("duration_sec", 0)
            }
            for t in tracks
        ]
    }
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception:
        pass

def delete_playlist(name: str) -> None:
    """Deletes a playlist file."""
    path = get_playlist_path(name)
    if os.path.exists(path):
        try:
            os.remove(path)
        except Exception:
            pass

def add_track_to_playlist(name: str, track: Dict[str, Any]) -> None:
    """Adds a single track to an existing playlist."""
    tracks = load_playlist(name)
    tracks.append({
        "path": track["path"],
        "title": track["title"],
        "artist": track.get("artist", ""),
        "duration": track.get("duration", "--:--"),
        "duration_sec": track.get("duration_sec", 0)
    })
    save_playlist(name, tracks)
