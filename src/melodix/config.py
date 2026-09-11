"""config.py — persistent user settings for Melodix.

Settings live in ``~/.config/melodix/config.json``. All keys always exist in
the dict returned by :func:`load` (defaults are merged in), so adding new keys
in future versions can never raise ``KeyError``.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

log = logging.getLogger(__name__)

_CONFIG_DIR = os.path.expanduser("~/.config/melodix")
_CONFIG_FILE = os.path.join(_CONFIG_DIR, "config.json")

_DEFAULTS: dict[str, Any] = {
    "volume": 100,
    "shuffle": False,
    "repeat_mode": "none",   # "none" | "track" | "all"
    "browser_root": "",      # empty string = auto-detect ~/Music or ~/
}


def load() -> dict[str, Any]:
    """Load settings from disk, falling back to defaults for any missing key."""
    cfg = dict(_DEFAULTS)
    try:
        with open(_CONFIG_FILE, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            for k in _DEFAULTS:
                if k in data:
                    cfg[k] = data[k]
    except FileNotFoundError:
        pass
    except (OSError, ValueError):
        # Unreadable or corrupt config: fall back to defaults rather than crash.
        log.warning("could not read config %s", _CONFIG_FILE, exc_info=True)
    return cfg


def save(cfg: dict[str, Any]) -> bool:
    """Persist settings to disk atomically.

    Returns ``True`` on success and ``False`` if the write failed (e.g. a
    read-only or full filesystem). Callers should surface failures to the user
    rather than pretending the settings were stored.
    """
    tmp_file = f"{_CONFIG_FILE}.tmp"
    try:
        os.makedirs(_CONFIG_DIR, exist_ok=True)
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
        os.replace(tmp_file, _CONFIG_FILE)
        return True
    except OSError:
        log.warning("could not write config %s", _CONFIG_FILE, exc_info=True)
        try:
            if os.path.exists(tmp_file):
                os.remove(tmp_file)
        except OSError:
            pass
        return False
