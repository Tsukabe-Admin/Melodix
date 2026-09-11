"""models.py — domain types and helpers for Melodix tracks.

A "track" is a plain ``dict`` (it is serialised straight to JSON for playlists),
so ``Track`` is a ``TypedDict`` rather than a class. Always build one with
:func:`make_track` so every producer of tracks agrees on the field set.
"""
from __future__ import annotations

import math
import os
from pathlib import Path
from typing import TypedDict

# Container extensions Melodix treats as playable audio.
AUDIO_EXTS = {
    ".mp3", ".m4a", ".ogg", ".flac", ".wav", ".mp4",
    ".aac", ".webm", ".opus", ".wma",
}


class Track(TypedDict):
    path: str
    title: str
    artist: str
    duration: str
    duration_sec: float


def make_track(
    path: str,
    *,
    title: str | None = None,
    artist: str = "",
    duration: str = "--:--",
    duration_sec: float = 0.0,
) -> Track:
    """Build a normalised track record from a filesystem path."""
    return Track(
        path=path,
        title=title if title is not None else Path(path).stem,
        artist=artist,
        duration=duration,
        duration_sec=duration_sec,
    )


def is_audio_file(path: str | os.PathLike[str]) -> bool:
    """True when the path has a playable audio/container extension."""
    return Path(path).suffix.lower() in AUDIO_EXTS


def format_time(seconds: float | None) -> str:
    """Format a duration in seconds as ``MM:SS`` / ``H:MM:SS``.

    ``None`` and ``NaN`` render as ``00:00``; infinite duration (live streams)
    renders as ``∞``.
    """
    if seconds is None or (isinstance(seconds, float) and math.isnan(seconds)):
        return "00:00"
    if isinstance(seconds, float) and math.isinf(seconds):
        return "∞"
    s = int(max(0, seconds))
    m, sec = divmod(s, 60)
    if m >= 60:
        return f"{m // 60}:{m % 60:02d}:{sec:02d}"
    return f"{m:02d}:{sec:02d}"
