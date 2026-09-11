"""Regression tests for the playlist manager and add-to-playlist modals."""
from __future__ import annotations

import shutil

import pytest

from melodix import playlists

pytestmark = pytest.mark.skipif(shutil.which("mpv") is None, reason="mpv not installed")


def _cleanup(*names: str) -> None:
    for name in names:
        playlists.delete_playlist(name)


async def test_selection_stays_in_sync_when_saving_twice(sample_audio):
    """Saving a second playlist must leave the newly saved one selected.

    Regression: rebuilding the ListView emitted a deferred Highlighted event
    carrying the *old* item, so `selected_playlist` reverted to it and a
    subsequent Delete removed the wrong playlist.
    """
    from textual.widgets import Button, Input

    from melodix.main import MelodixApp

    _cleanup("Alpha", "Beta")

    app = MelodixApp()
    async with app.run_test(size=(120, 45)) as pilot:
        await pilot.pause()
        app.add_tracks([sample_audio])
        await pilot.pause()

        app.action_open_playlists()
        await pilot.pause()
        screen = app.screen

        screen.query_one("#pl-save-input", Input).value = "Alpha"
        screen.query_one("#pl-btn-save", Button).press()
        await pilot.pause()

        screen.query_one("#pl-save-input", Input).value = "Beta"
        screen.query_one("#pl-btn-save", Button).press()
        # Let any deferred ListView events settle.
        await pilot.pause()
        await pilot.pause()

        assert screen.selected_playlist == "Beta", (
            f"selected={screen.selected_playlist!r} while Beta is highlighted"
        )

        screen.query_one("#pl-btn-delete", Button).press()
        await pilot.pause()
        await pilot.pause()

        remaining = playlists.list_playlists()
        assert "Beta" not in remaining, f"delete removed the wrong playlist: {remaining}"
        assert "Alpha" in remaining, f"Alpha should have survived: {remaining}"

    _cleanup("Alpha", "Beta")


async def test_escape_dismisses_add_to_playlist_modal(sample_audio):
    from melodix.add_to_playlist import AddToPlaylistScreen
    from melodix.main import MelodixApp

    app = MelodixApp()
    async with app.run_test(size=(120, 45)) as pilot:
        await pilot.pause()
        app.add_tracks([sample_audio])
        await pilot.pause()
        app.query_one("#queue-list").focus()
        await pilot.pause()
        app.action_add_to_playlist()
        await pilot.pause()
        assert isinstance(app.screen, AddToPlaylistScreen)

        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, AddToPlaylistScreen)
