"""Shared pytest fixtures.

HOME is redirected to a throw-away directory *before* any ``melodix`` module is
imported, because ``melodix.config`` and ``melodix.playlists`` compute their
paths at import time. This keeps tests from touching the real user config.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

_TMP_HOME = Path(tempfile.mkdtemp(prefix="melodix-test-home-"))
os.environ["HOME"] = str(_TMP_HOME)
os.environ["XDG_CONFIG_HOME"] = str(_TMP_HOME / ".config")

import pytest  # noqa: E402


@pytest.fixture(scope="session")
def sample_audio() -> str:
    """Absolute path to the bundled sample track."""
    path = _ROOT / "sample_music" / "sample.mp3"
    if not path.exists():
        pytest.skip("sample_music/sample.mp3 is missing")
    return str(path)
