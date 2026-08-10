"""
config.py — Persistent user settings for Melodix.

Settings are stored in ~/.config/melodix/config.json and loaded/saved
automatically. All keys always exist in the returned dict (defaults are
merged on load so new keys added in future versions never cause KeyError).
"""
import json
import os
from typing import Any, Dict

_CONFIG_DIR  = os.path.expanduser("~/.config/melodix")
_CONFIG_FILE = os.path.join(_CONFIG_DIR, "config.json")

_DEFAULTS: Dict[str, Any] = {
    "volume":       100,
    "shuffle":      False,
    "repeat_mode":  "none",   # "none" | "track" | "all"
    "browser_root": "",       # empty string = auto-detect ~/Music or ~/
}


def load() -> Dict[str, Any]:
    """Load settings from disk, falling back to defaults for any missing key."""
    cfg = dict(_DEFAULTS)
    try:
        with open(_CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            for k in _DEFAULTS:
                if k in data:
                    cfg[k] = data[k]
    except Exception:
        pass
    return cfg


def save(cfg: Dict[str, Any]) -> None:
    """Persist the given settings dict to disk (best-effort, never raises)."""
    try:
        os.makedirs(_CONFIG_DIR, exist_ok=True)
        with open(_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
    except Exception:
        pass
