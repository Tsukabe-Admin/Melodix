"""Headless integration tests driving MelodixApp with Textual's Pilot.

These exercise the queue state machine, transport actions and modal screens.
They require ``mpv`` on PATH; they are skipped otherwise.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(shutil.which("mpv") is None, reason="mpv not installed")


async def test_app_starts_with_expected_widgets(sample_audio):
    from textual.widgets import DataTable, ProgressBar

    from melodix.main import MelodixApp

    app = MelodixApp()
    async with app.run_test(size=(120, 45)) as pilot:
        await pilot.pause()
        table = app.query_one("#queue-list", DataTable)
        assert len(table.columns) == 4
        assert app.query_one("#progress-bar", ProgressBar) is not None
        assert app.query_one("#visualizer") is not None


async def test_adding_tracks_populates_queue_and_table(sample_audio):
    from textual.widgets import DataTable

    from melodix.main import MelodixApp

    app = MelodixApp()
    async with app.run_test(size=(120, 45)) as pilot:
        await pilot.pause()
        app.add_tracks([sample_audio, sample_audio])
        await pilot.pause()
        table = app.query_one("#queue-list", DataTable)
        assert len(app.queue) == 2
        assert table.row_count == 2
        assert app.current_index == 0  # first add auto-plays


async def test_transport_actions_are_safe(sample_audio):
    from melodix.main import MelodixApp

    app = MelodixApp()
    async with app.run_test(size=(120, 45)) as pilot:
        await pilot.pause()
        app.add_tracks([sample_audio])
        await pilot.pause()

        app.action_toggle_play()
        app.action_seek_forward()
        app.action_seek_backward()
        app.action_volume_up()
        app.action_volume_down()
        app.action_toggle_mute()
        app.action_toggle_shuffle()
        await pilot.pause()
        assert app.shuffle_on is True

        app.action_toggle_repeat()
        assert app.repeat_mode == "track"
        app.action_toggle_repeat()
        assert app.repeat_mode == "all"
        app.action_toggle_repeat()
        assert app.repeat_mode == "none"
        await pilot.pause()


async def test_removing_a_track_keeps_table_in_sync(sample_audio):
    from textual.widgets import DataTable

    from melodix.main import MelodixApp

    app = MelodixApp()
    async with app.run_test(size=(120, 45)) as pilot:
        await pilot.pause()
        app.add_tracks([sample_audio, sample_audio, sample_audio])
        await pilot.pause()
        app.action_remove_track()
        await pilot.pause()
        table = app.query_one("#queue-list", DataTable)
        assert len(app.queue) == 2
        assert table.row_count == 2


async def test_operations_on_an_empty_queue_do_not_raise(sample_audio):
    from melodix.main import MelodixApp

    app = MelodixApp()
    async with app.run_test(size=(120, 45)) as pilot:
        await pilot.pause()
        app._next()
        app._prev()
        app.action_remove_track()
        app.action_toggle_play()
        app.action_seek_forward()
        await pilot.pause()


async def test_change_root_modal(sample_audio):
    from textual.widgets import Input

    from melodix.change_root_screen import ChangeBrowserRootScreen
    from melodix.main import MelodixApp

    app = MelodixApp()
    async with app.run_test(size=(120, 45)) as pilot:
        await pilot.pause()
        app.action_change_browser_root()
        await pilot.pause()
        assert isinstance(app.screen, ChangeBrowserRootScreen)
        app.screen.query_one("#chroot-input", Input).value = str(Path(sample_audio).parent)
        await pilot.press("enter")
        await pilot.pause()
        assert app.browser_root.endswith("sample_music")


async def test_youtube_modal_opens_and_cancels(sample_audio):
    from melodix.main import MelodixApp
    from melodix.youtube_screen import YoutubeScreen

    app = MelodixApp()
    async with app.run_test(size=(120, 45)) as pilot:
        await pilot.pause()
        app.action_youtube_dl()
        await pilot.pause()
        assert isinstance(app.screen, YoutubeScreen)
        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, YoutubeScreen)


async def test_youtube_retry_resets_progress_state(sample_audio, monkeypatch):
    """A retry after an error must not carry over the previous attempt's state."""
    from textual.widgets import Input

    import melodix.youtube_screen as yt
    from melodix.main import MelodixApp

    class DummyJob:
        def cancel(self):
            pass

    monkeypatch.setattr(
        yt, "download_url",
        lambda *a, **k: DummyJob(),
    )

    app = MelodixApp()
    async with app.run_test(size=(120, 45)) as pilot:
        await pilot.pause()
        app.action_youtube_dl()
        await pilot.pause()
        screen = app.screen

        # Simulate a previous, partially successful attempt.
        screen._completed_items = 2
        screen._total_items = 5
        screen._all_paths = ["/old/a.mp3", "/old/b.mp3"]

        screen.query_one("#yt-url-input", Input).value = "https://example.com/x"
        screen._start_download()
        await pilot.pause()

        assert screen._completed_items == 0
        assert screen._total_items == 0
        assert screen._all_paths == []


async def test_mpv_death_is_surfaced_and_resets_player(sample_audio):
    """Killing mpv must not leave the UI stuck on 'PLAYING'."""
    import asyncio

    from melodix.main import MelodixApp

    app = MelodixApp()
    async with app.run_test(size=(120, 45)) as pilot:
        await pilot.pause()
        app.add_tracks([sample_audio])
        for _ in range(10):
            await asyncio.sleep(0.1)
            await pilot.pause()
        assert app.current_index == 0

        app.player.proc.kill()
        for _ in range(25):
            await asyncio.sleep(0.1)
            await pilot.pause()

        assert app.current_index == -1, "app should reset after mpv died"
        assert app.now_playing_title == "No track loaded"


async def test_repeated_load_failures_stop_the_queue():
    """Broken tracks must not cause an infinite auto-skip loop.

    Uses paths that do not exist so mpv genuinely fails every load and the
    consecutive-failure guard is what stops the cycle.
    """
    from melodix.main import MelodixApp
    from melodix.models import make_track

    app = MelodixApp()
    async with app.run_test(size=(120, 45)) as pilot:
        await pilot.pause()
        app.queue = [make_track("/nonexistent/a.mp3"), make_track("/nonexistent/b.mp3")]
        app.current_index = 0
        app._rebuild_queue()
        app.repeat_mode = "all"
        app.play_index(0)
        await pilot.pause()

        for _ in range(8):
            app._handle_eof("error")
            await pilot.pause()

        assert app.current_index == -1, "queue should stop after repeated failures"
