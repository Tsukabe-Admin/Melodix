"""Tests for the pure helpers in melodix.models."""
from __future__ import annotations

import pytest

from melodix.models import AUDIO_EXTS, format_time, is_audio_file, make_track


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [
        (0, "00:00"),
        (5, "00:05"),
        (59, "00:59"),
        (60, "01:00"),
        (182.4, "03:02"),
        (3599, "59:59"),
        (3600, "1:00:00"),
        (3661, "1:01:01"),
        (None, "00:00"),
        (float("nan"), "00:00"),
        (float("inf"), "∞"),
        (-5, "00:00"),
    ],
)
def test_format_time(seconds, expected):
    assert format_time(seconds) == expected


def test_format_time_accepts_int_and_float():
    assert format_time(90) == "01:30"
    assert format_time(90.9) == "01:30"


def test_make_track_derives_title_from_stem():
    t = make_track("/music/Some Song.mp3")
    assert t["path"] == "/music/Some Song.mp3"
    assert t["title"] == "Some Song"
    assert t["artist"] == ""
    assert t["duration"] == "--:--"
    assert t["duration_sec"] == 0.0


def test_make_track_honours_explicit_values():
    t = make_track("/music/a.mp3", title="T", artist="A", duration="01:00", duration_sec=60.0)
    assert (t["title"], t["artist"], t["duration"], t["duration_sec"]) == ("T", "A", "01:00", 60.0)


def test_make_track_returns_json_serialisable_dict():
    import json

    assert json.loads(json.dumps(make_track("/a/b.mp3")))["title"] == "b"


@pytest.mark.parametrize("name", ["a.mp3", "a.MP3", "a.flac", "a.opus", "a.m4a"])
def test_is_audio_file_true(name):
    assert is_audio_file(f"/x/{name}")


@pytest.mark.parametrize("name", ["a.txt", "a.jpg", "a", "a.mp3.txt"])
def test_is_audio_file_false(name):
    assert not is_audio_file(f"/x/{name}")


def test_audio_exts_are_lowercase_dotted():
    assert all(e.startswith(".") and e == e.lower() for e in AUDIO_EXTS)
