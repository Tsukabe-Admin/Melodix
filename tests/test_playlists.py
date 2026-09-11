"""Tests for the playlist store (melodix.playlists)."""
from __future__ import annotations

import json
import os

from melodix import playlists
from melodix.models import make_track


def test_sanitize_strips_path_separators_and_keeps_readable_names():
    assert playlists.sanitize_playlist_name("My Faves") == "My Faves"
    assert playlists.sanitize_playlist_name("a/b") == "ab"
    assert playlists.sanitize_playlist_name("../../etc/passwd") == "etcpasswd"
    assert playlists.sanitize_playlist_name("   ") == "untitled"
    assert playlists.sanitize_playlist_name("") == "untitled"


def test_get_playlist_path_cannot_escape_the_playlist_dir():
    path = playlists.get_playlist_path("../../etc/passwd")
    assert os.path.dirname(path) == os.path.abspath(playlists.DEFAULT_PLAYLISTS_DIR)
    assert ".." not in path


def test_save_then_load_round_trip():
    tracks = [make_track("/a/x.mp3", artist="X"), make_track("/a/y.mp3")]
    assert playlists.save_playlist("round-trip", tracks) is True
    loaded = playlists.load_playlist("round-trip")
    assert [t["path"] for t in loaded] == ["/a/x.mp3", "/a/y.mp3"]
    assert loaded[0]["artist"] == "X"
    playlists.delete_playlist("round-trip")
    assert playlists.load_playlist("round-trip") == []


def test_load_missing_playlist_returns_empty():
    assert playlists.load_playlist("does-not-exist") == []


def test_load_rejects_malformed_entries(tmp_path, monkeypatch):
    path_obj = tmp_path / "malformed.json"
    path_obj.write_text(json.dumps({
        "tracks": [
            "not-a-dict",
            {"title": "no path"},
            {"path": 123},
            {"path": "/ok/a.mp3"},
        ]
    }))
    monkeypatch.setattr(playlists, "get_playlist_path", lambda _n: str(path_obj))
    loaded = playlists.load_playlist("malformed")
    assert len(loaded) == 1
    assert loaded[0]["path"] == "/ok/a.mp3"
    assert loaded[0]["title"] == "a"


def test_load_accepts_bare_list_format(tmp_path, monkeypatch):
    path_obj = tmp_path / "bare.json"
    path_obj.write_text(json.dumps([{"path": "/a/b.mp3"}]))
    monkeypatch.setattr(playlists, "get_playlist_path", lambda _n: str(path_obj))
    assert len(playlists.load_playlist("bare")) == 1


def test_load_returns_empty_on_invalid_json(tmp_path, monkeypatch):
    path_obj = tmp_path / "broken.json"
    path_obj.write_text("{not json")
    monkeypatch.setattr(playlists, "get_playlist_path", lambda _n: str(path_obj))
    assert playlists.load_playlist("broken") == []


def test_add_track_to_playlist_appends():
    name = "append-test"
    playlists.delete_playlist(name)
    playlists.add_track_to_playlist(name, make_track("/a/1.mp3"))
    playlists.add_track_to_playlist(name, make_track("/a/2.mp3"))
    assert [t["path"] for t in playlists.load_playlist(name)] == ["/a/1.mp3", "/a/2.mp3"]
    playlists.delete_playlist(name)


def test_list_playlists_is_sorted_and_excludes_non_json():
    playlists.save_playlist("zzz", [])
    playlists.save_playlist("aaa", [])
    names = playlists.list_playlists()
    assert names == sorted(names)
    assert "aaa" in names and "zzz" in names
    playlists.delete_playlist("zzz")
    playlists.delete_playlist("aaa")


def test_one_bad_duration_does_not_discard_the_playlist(tmp_path, monkeypatch):
    """A single corrupt duration_sec must not lose every other track."""
    path_obj = tmp_path / "mixed.json"
    path_obj.write_text(json.dumps({"tracks": [
        {"path": "/a/good.mp3", "duration_sec": 12},
        {"path": "/a/bad.mp3", "duration_sec": "not-a-number"},
        {"path": "/a/also-good.mp3", "duration_sec": 30},
    ]}))
    monkeypatch.setattr(playlists, "get_playlist_path", lambda _n: str(path_obj))
    loaded = playlists.load_playlist("mixed")
    assert [t["path"] for t in loaded] == ["/a/good.mp3", "/a/bad.mp3", "/a/also-good.mp3"]
    assert loaded[1]["duration_sec"] == 0.0


def test_delete_playlist_is_idempotent():
    assert playlists.delete_playlist("never-existed") is True
