"""browser.py — the filtered library directory tree."""
from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from textual.widgets import DirectoryTree

from .models import AUDIO_EXTS


class AudioDirectoryTree(DirectoryTree):
    """DirectoryTree filtered to show only directories + audio files."""

    def filter_paths(self, paths: Iterable[Path]) -> Iterable[Path]:
        return [p for p in paths if p.is_dir() or p.suffix.lower() in AUDIO_EXTS]
