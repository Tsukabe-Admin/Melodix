"""main.py — Melodix application entry point.

Wires the mpv backend, the queue state machine and the Textual screens
together. Business logic that is not UI-specific lives in sibling modules.
"""
from __future__ import annotations

import logging
import os
import random
import sys
from pathlib import Path

from rich.text import Text
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.coordinate import Coordinate
from textual.reactive import reactive
from textual.widgets import Button, DataTable, DirectoryTree, Label, ProgressBar

from . import __version__
from . import config as _cfg
from .add_to_playlist import AddToPlaylistScreen
from .browser import AudioDirectoryTree
from .change_root_screen import ChangeBrowserRootScreen
from .models import format_time, is_audio_file, make_track
from .player import MpvPlayer
from .playlists_screen import PlaylistScreen
from .theme import (
    AQUA,
    BG2,
    BG3,
    BLUE,
    FG,
    FG1,
    FG3,
    GRAY,
    GREEN,
    ORANGE,
    RED,
    YELLOW,
)
from .visualizer import AudioVisualizer
from .youtube_screen import YoutubeScreen

log = logging.getLogger(__name__)

# Absolute path so the CSS loads correctly from any working directory.
_APP_DIR = Path(__file__).parent


def ascii_bar(value: int, total: int = 100, width: int = 10,
              fill: str = "█", empty: str = "░") -> str:
    """Render a small text progress bar."""
    filled = round(value / total * width) if total else 0
    filled = max(0, min(width, filled))
    return fill * filled + empty * (width - filled)


class MelodixApp(App):
    """Melodix — btop-style terminal music player (Gruvbox theme)."""

    CSS_PATH = _APP_DIR / "styles.css"
    TITLE = f"Melodix {__version__}"

    BINDINGS = [
        ("q",          "quit_app",           "Quit"),
        ("space",      "toggle_play",        "Play/Pause"),
        ("left",       "seek_backward",      "Seek -5s"),
        ("right",      "seek_forward",       "Seek +5s"),
        ("up",         "volume_up",          "Vol +5"),
        ("down",       "volume_down",        "Vol -5"),
        ("+",          "volume_up",          "Vol +5"),
        ("=",          "volume_up",          "Vol +5"),
        ("-",          "volume_down",        "Vol -5"),
        ("n",          "next_track",         "Next"),
        ("p",          "prev_track",         "Prev"),
        ("s",          "toggle_shuffle",     "Shuffle"),
        ("r",          "toggle_repeat",      "Repeat"),
        ("m",          "toggle_mute",        "Mute"),
        ("f",          "focus_browser",      "Browser"),
        ("l",          "focus_queue",        "Queue"),
        ("a",          "add_dir",            "Add Dir"),
        ("delete",     "remove_track",       "Remove"),
        ("b",          "add_to_playlist",    "Add to PL"),
        ("o",          "open_playlists",     "Playlists"),
        ("shift+enter","play_selected",      "Play Selected"),
        ("y",          "youtube_dl",         "YouTube DL"),
        ("ctrl+r",     "refresh_library",    "Refresh Library"),
        ("ctrl+b",     "change_browser_root","Change Root"),
    ]

    # ── Reactives ──────────────────────────────────────────────────────────────
    now_playing_title  = reactive("No track loaded")
    now_playing_artist = reactive("")
    current_time_str   = reactive("00:00")
    total_time_str     = reactive("00:00")
    current_volume     = reactive(100)
    is_muted           = reactive(False)
    play_icon          = reactive("󰐊")
    shuffle_on         = reactive(False)
    repeat_mode        = reactive("none")  # none | track | all

    def __init__(self, **kwargs):
        if "ansi_color" not in kwargs:
            kwargs["ansi_color"] = True
        super().__init__(**kwargs)
        self.player = MpvPlayer()
        self.player.on_property_change = self._mpv_prop_cb
        self.player.on_end_file        = self._mpv_eof_cb
        self.player.on_player_died     = self._mpv_died_cb

        self.queue: list[dict] = []
        self.current_index = -1
        # Guards against an infinite auto-skip loop when every track is broken.
        self._consecutive_failures = 0

        # Load persisted settings and apply them before the first render
        cfg = _cfg.load()
        self.shuffle_on  = cfg["shuffle"]
        self.repeat_mode = cfg["repeat_mode"]

        # Resolve the browser root (saved > ~/Music > ~)
        home  = os.path.expanduser("~")
        music = os.path.join(home, "Music")
        saved_root = cfg.get("browser_root", "")
        if saved_root and os.path.isdir(saved_root):
            self.browser_root = saved_root
        else:
            self.browser_root = music if os.path.isdir(music) else home

    # ── Layout ─────────────────────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        # ── Single-line btop-style header ──────────────────────────────────────
        yield Label("", id="header-bar")

        # ── Main split: Library (left) + Queue (right) ─────────────────────────
        with Horizontal(id="main-pane"):
            with Vertical(id="browser-panel"):
                yield AudioDirectoryTree(self.browser_root, id="dir-tree")

            with Vertical(id="queue-panel"):
                yield DataTable(id="queue-list")

        # ── Bottom player section ───────────────────────────────────────────────
        with Vertical(id="bottom-bar"):
            yield AudioVisualizer(num_bars=80, id="visualizer")

            # Transport buttons + volume
            with Horizontal(id="controls-row"):
                yield Button("󰒮", id="ctrl-prev",       classes="ctrl-btn")
                yield Button("󰐊", id="ctrl-play-pause", classes="ctrl-btn")
                yield Button("󰒭", id="ctrl-next",       classes="ctrl-btn")
                yield Label("│",  classes="ctrl-sep")
                yield Button("󰒝", id="ctrl-shuffle",    classes="ctrl-btn")
                yield Button("󰑖", id="ctrl-repeat",     classes="ctrl-btn")
                yield Label("│",  classes="ctrl-sep")
                yield Button("󰕾", id="ctrl-mute",       classes="ctrl-btn")
                yield Label("vol", classes="ctrl-label")
                yield Label("100%", id="volume-display", classes="ctrl-label")
                yield Label("",     id="vol-bar")

            # Progress / scrub bar
            with Horizontal(id="progress-row"):
                yield Label("00:00", id="label-elapsed",  classes="time-label")
                yield ProgressBar(id="progress-bar", show_eta=False,
                                  show_percentage=False)
                yield Label("00:00", id="label-duration", classes="time-label")

            # One-liner keybindings reference
            yield Label(
                f"[{BG2}]SPC[/{BG2}][{FG3}] play "
                f"[{BG2}]←→[/{BG2}] seek "
                f"[{BG2}]+/-[/{BG2}] vol "
                f"[{BG2}]n/p[/{BG2}] skip "
                f"[{BG2}]s[/{BG2}] shuf "
                f"[{BG2}]r[/{BG2}] rpt "
                f"[{BG2}]a[/{BG2}] add-dir "
                f"[{BG2}]⇧Ent[/{BG2}] play-sel "
                f"[{BG2}]b[/{BG2}] pl+ "
                f"[{BG2}]o[/{BG2}] pl "
                f"[{BG2}]f/l[/{BG2}] focus "
                f"[{BG2}]y[/{BG2}][bold {ORANGE}] YT↓[/] "
                f"[{BG2}]^R[/{BG2}] ref "
                f"[{BG2}]^B[/{BG2}] root "
                f"[{BG2}]q[/{BG2}] quit[/{FG3}]",
                id="keys-hint",
            )

    def on_mount(self) -> None:
        root_name = Path(self.browser_root).name or str(self.browser_root)
        self.query_one("#browser-panel").border_title = f"󰉋 Library  [{GRAY}]{root_name}[/]"
        self.query_one("#queue-panel").border_title   = "󰋖 Queue"
        self.query_one("#bottom-bar").border_title    = "󰓎 Now Playing"

        table = self.query_one("#queue-list", DataTable)
        table.add_columns(" ", "Title", "Artist", "Time")
        table.cursor_type = "row"

        # Apply the saved volume to mpv and the display
        saved_vol = int(_cfg.load().get("volume", 100))
        self.player.set_volume(saved_vol)
        self.current_volume = saved_vol

        # Re-apply reactive-driven UI state (watchers no-op before mount)
        self.watch_shuffle_on(self.shuffle_on)
        self.watch_repeat_mode(self.repeat_mode)

        self._refresh_header()
        self._update_queue_border_title()

    # ── MPV callbacks ──────────────────────────────────────────────────────────

    def _mpv_prop_cb(self, name: str, value) -> None:
        if self.is_running:
            try:
                self.call_from_thread(self._handle_prop, name, value)
            except RuntimeError:
                log.debug("app not accepting mpv callbacks", exc_info=True)

    def _mpv_eof_cb(self, reason: str) -> None:
        if self.is_running:
            try:
                self.call_from_thread(self._handle_eof, reason)
            except RuntimeError:
                log.debug("app not accepting mpv callbacks", exc_info=True)

    def _mpv_died_cb(self) -> None:
        if self.is_running:
            try:
                self.call_from_thread(self._handle_player_died)
            except RuntimeError:
                log.debug("app not accepting mpv callbacks", exc_info=True)

    def _handle_prop(self, name: str, value) -> None:
        try:
            if name == "time-pos" and value is not None:
                self._consecutive_failures = 0
                self.current_time_str = format_time(value)
                if self.player.duration > 0:
                    self.query_one("#progress-bar", ProgressBar).progress = float(value)

            elif name == "duration" and value is not None:
                self.total_time_str = format_time(value)
                self.query_one("#progress-bar", ProgressBar).total = float(value)
                if 0 <= self.current_index < len(self.queue):
                    t = self.queue[self.current_index]
                    if not t.get("duration_sec"):
                        t["duration_sec"] = float(value)
                        t["duration"]     = format_time(value)
                        self._update_cell(self.current_index, 3,
                                          Text(t["duration"], style=AQUA))

            elif name == "metadata" and value and isinstance(value, dict):
                self._apply_metadata(value)

            elif name == "pause":
                self.play_icon = "󰐊" if value else "󰏤"
                self.query_one("#visualizer", AudioVisualizer).set_state(
                    not value, self.player.volume
                )

            elif name == "volume" and value is not None:
                self.current_volume = int(value)
                self.query_one("#visualizer", AudioVisualizer).set_state(
                    not self.player.paused, value
                )

            elif name == "mute":
                self.is_muted = bool(value)

        except Exception:  # noqa: BLE001 - a UI glitch must not kill playback
            log.exception("error handling mpv property %r", name)

    def _handle_eof(self, reason: str) -> None:
        # Handle every end-of-file reason: a failed load reports reason="error",
        # which would otherwise leave the queue frozen on the broken track.
        if reason == "eof":
            if self.repeat_mode == "track":
                self.play_index(self.current_index)
            else:
                self._next()
        elif reason in ("error", "aborted"):
            self._consecutive_failures += 1
            if self._consecutive_failures > max(1, len(self.queue)):
                # Every track failed: stop instead of looping forever.
                self.notify(
                    "All tracks in the queue failed to play.",
                    severity="error",
                    timeout=5,
                )
                self._consecutive_failures = 0
                self._stop_and_reset()
                return
            title = ""
            if 0 <= self.current_index < len(self.queue):
                title = self.queue[self.current_index].get("title", "")
            self.notify(
                f"Failed to play{': ' + title if title else ' track'} — skipping.",
                severity="error",
                timeout=4,
            )
            self._next()

    def _handle_player_died(self) -> None:
        """mpv exited or its socket closed while we were not shutting down."""
        log.warning("audio engine stopped unexpectedly")
        self.notify(
            "Audio engine (mpv) stopped unexpectedly.",
            severity="error",
            timeout=6,
        )
        self._stop_and_reset()

    # ── Metadata ───────────────────────────────────────────────────────────────

    def _apply_metadata(self, meta: dict) -> None:
        def get(*keys):
            for k in keys:
                for variant in (k, k.upper(), k.title()):
                    v = meta.get(variant)
                    if v:
                        return str(v)
            return None

        title  = get("title")
        artist = get("artist")

        if not title and 0 <= self.current_index < len(self.queue):
            path = self.queue[self.current_index]["path"]
            title = os.path.splitext(os.path.basename(path))[0]

        self.now_playing_title  = title  or "Unknown Title"
        self.now_playing_artist = artist or ""

        if 0 <= self.current_index < len(self.queue):
            self.queue[self.current_index]["title"]  = self.now_playing_title
            self.queue[self.current_index]["artist"] = self.now_playing_artist
            idx = self.current_index
            self._update_cell(idx, 1, Text(self.now_playing_title,  style=f"bold {YELLOW}"))
            self._update_cell(idx, 2, Text(self.now_playing_artist, style=FG1))

        self._refresh_header()

    # ── Queue management ───────────────────────────────────────────────────────

    def add_tracks(self, paths: list[str]) -> int:
        """Batch-add audio paths with a single DataTable rebuild."""
        added = 0
        start_play = (self.current_index == -1 and not self.queue)
        first_added_idx = len(self.queue)
        for path in paths:
            if not os.path.exists(path):
                continue
            self.queue.append(make_track(path))
            added += 1
        if added:
            self._rebuild_queue()
            self._update_queue_border_title()
            if start_play:
                self.play_index(first_added_idx)
        return added

    def add_to_queue(self, path: str) -> None:
        if not os.path.exists(path):
            self.notify(
                f"File not found: {os.path.basename(path)}",
                severity="warning", timeout=3,
            )
            return
        self.add_tracks([path])

    def add_directory(self, dir_path: str) -> int:
        tracks = []
        for root, _, files in os.walk(dir_path):
            for fname in sorted(files):
                if is_audio_file(fname):
                    tracks.append(os.path.join(root, fname))
        return self.add_tracks(tracks)

    def play_index(self, index: int) -> None:
        if not self.queue or not (0 <= index < len(self.queue)):
            return
        old_index = self.current_index       # capture before mutating
        self.current_index = index
        self.player.load_file(self.queue[index]["path"])
        self.current_time_str = "00:00"
        self.total_time_str   = "00:00"
        try:
            self.query_one("#progress-bar", ProgressBar).progress = 0
        except Exception:  # noqa: BLE001 - widget lifecycle
            log.debug("could not reset progress bar", exc_info=True)
        self.play_icon = "󰏤"
        try:
            self.query_one("#visualizer", AudioVisualizer).set_state(
                True, self.player.volume
            )
        except Exception:  # noqa: BLE001 - widget lifecycle
            log.debug("could not update visualizer", exc_info=True)
        self._update_queue_playing_row(old_index, index)
        self._refresh_header()

    def _next(self) -> None:
        if not self.queue:
            return
        if self.shuffle_on:
            choices = [i for i in range(len(self.queue)) if i != self.current_index]
            self.play_index(random.choice(choices) if choices else 0)
        else:
            nxt = self.current_index + 1
            if nxt >= len(self.queue):
                if self.repeat_mode == "all":
                    self.play_index(0)
                else:
                    self._stop_and_reset()
            else:
                self.play_index(nxt)

    def _prev(self) -> None:
        if not self.queue:
            return
        # Standard media player UX: restart the track if we're past 3 seconds.
        if self.player.time_pos > 3.0:
            self.player.seek(0, relative=False)
            return
        prv = self.current_index - 1
        if prv < 0:
            prv = len(self.queue) - 1 if self.repeat_mode == "all" else 0
        self.play_index(prv)

    def _stop_and_reset(self) -> None:
        self.player.stop()
        self.current_index      = -1
        self.now_playing_title  = "No track loaded"
        self.now_playing_artist = ""
        self.current_time_str   = "00:00"
        self.total_time_str     = "00:00"
        try:
            self.query_one("#progress-bar", ProgressBar).progress = 0
            self.query_one("#visualizer", AudioVisualizer).set_state(False, self.player.volume)
        except Exception:  # noqa: BLE001 - widget lifecycle
            log.debug("could not reset player widgets", exc_info=True)
        self._rebuild_queue()
        self._refresh_header()

    # ── UI refresh helpers ─────────────────────────────────────────────────────

    def _refresh_header(self) -> None:
        """Single-line btop status bar with track info."""
        try:
            if self.now_playing_artist:
                track_part = (
                    f"[bold {YELLOW}]{self.now_playing_title}[/]"
                    f"  [{BG3}]·[/]  [{FG3}]{self.now_playing_artist}[/]"
                )
            else:
                track_part = f"[{FG3}]{self.now_playing_title}[/]"

            if self.current_index == -1:
                state_badge = f"[{GRAY}]■ STOPPED[/]"
            elif self.player.paused:
                state_badge = f"[{YELLOW}]⏸ PAUSED[/]"
            else:
                state_badge = f"[bold {GREEN}]▶ PLAYING[/]"

            self.query_one("#header-bar", Label).update(
                f"[bold {ORANGE}]󰓎 MELODIX[/]"
                f"  [{BG3}]│[/]  {state_badge}"
                f"  [{BG3}]│[/]  [{BLUE}]󰎆[/]  {track_part}"
            )
        except Exception:  # noqa: BLE001 - widget lifecycle
            log.debug("could not refresh header", exc_info=True)

    def _update_queue_border_title(self) -> None:
        """Queue panel border title with track count and mode icons."""
        try:
            n = len(self.queue)
            s_badge = f"[bold {ORANGE}]󰒝[/]" if self.shuffle_on else f"[{BG3}]󰒝[/]"
            r_badge = {
                "none":  f"[{BG3}]󰑖[/]",
                "track": f"[bold {ORANGE}]󰑘[/]",
                "all":   f"[bold {ORANGE}]󰑖[/]",
            }[self.repeat_mode]
            self.query_one("#queue-panel").border_title = (
                f"󰋖 Queue  [{GRAY}]{n} track{'s' if n != 1 else ''}[/]"
                f"  {s_badge}  {r_badge}"
            )
        except Exception:  # noqa: BLE001 - widget lifecycle
            log.debug("could not update queue title", exc_info=True)

    def _update_bottom_border_title(self) -> None:
        """Bottom panel border title with elapsed/total time."""
        if self.current_index == -1:
            return
        try:
            self.query_one("#bottom-bar").border_title = (
                f"[bold {ORANGE}]󰓎[/]  [{FG3}]{self.current_time_str}"
                f" [bold {YELLOW}]/[/] {self.total_time_str}[/]"
            )
        except Exception:  # noqa: BLE001 - widget lifecycle
            log.debug("could not update bottom title", exc_info=True)

    @staticmethod
    def _marker(idx: int, active: bool) -> Text:
        """Row marker: a play glyph for the active track, else its number."""
        return Text("▶", style=f"bold {GREEN}") if active else Text(str(idx + 1), style=GRAY)

    @staticmethod
    def _row_cells(t: dict, active: bool) -> tuple[Text, Text, Text]:
        """Build the title/artist/duration cells for a queue row."""
        if active:
            return (
                Text(t["title"],    style=f"bold {YELLOW}"),
                Text(t["artist"],   style=FG1),
                Text(t["duration"], style=AQUA),
            )
        return (
            Text(t["title"],    style=FG),
            Text(t["artist"],   style=FG3),
            Text(t["duration"], style=BG3),
        )

    def _rebuild_queue(self) -> None:
        """Full table rebuild — use only for structural changes (add/remove)."""
        try:
            table = self.query_one("#queue-list", DataTable)
            table.clear()
            for idx, t in enumerate(self.queue):
                active = (idx == self.current_index)
                title, artist, dur = self._row_cells(t, active)
                table.add_row(self._marker(idx, active), title, artist, dur, key=str(idx))
        except Exception:  # noqa: BLE001 - widget lifecycle
            log.debug("could not rebuild queue table", exc_info=True)

    def _update_queue_playing_row(self, old_idx: int, new_idx: int) -> None:
        """Targeted update — only touch the two rows whose play state changed."""
        try:
            table = self.query_one("#queue-list", DataTable)
            if table.row_count != len(self.queue):
                self._rebuild_queue()
                return

            if 0 <= old_idx < len(self.queue):
                title, artist, dur = self._row_cells(self.queue[old_idx], False)
                table.update_cell_at(Coordinate(old_idx, 0), self._marker(old_idx, False))
                table.update_cell_at(Coordinate(old_idx, 1), title)
                table.update_cell_at(Coordinate(old_idx, 2), artist)
                table.update_cell_at(Coordinate(old_idx, 3), dur)

            if 0 <= new_idx < len(self.queue):
                title, artist, dur = self._row_cells(self.queue[new_idx], True)
                table.update_cell_at(Coordinate(new_idx, 0), self._marker(new_idx, True))
                table.update_cell_at(Coordinate(new_idx, 1), title)
                table.update_cell_at(Coordinate(new_idx, 2), artist)
                table.update_cell_at(Coordinate(new_idx, 3), dur)
                table.move_cursor(row=new_idx, animate=True)
        except Exception:  # noqa: BLE001 - fall back to a full rebuild
            log.debug("targeted row update failed; rebuilding", exc_info=True)
            self._rebuild_queue()

    def _update_cell(self, row: int, col: int, value: Text) -> None:
        """Safe single-cell update (used for metadata/duration changes)."""
        try:
            self.query_one("#queue-list", DataTable).update_cell_at(
                Coordinate(row, col), value
            )
        except Exception:  # noqa: BLE001 - widget lifecycle
            log.debug("could not update cell (%s,%s)", row, col, exc_info=True)

    # ── Reactive watchers ──────────────────────────────────────────────────────

    def watch_current_time_str(self, v: str) -> None:
        try:
            self.query_one("#label-elapsed", Label).update(v)
            self._update_bottom_border_title()
        except Exception:  # noqa: BLE001 - widget lifecycle
            log.debug("could not update elapsed label", exc_info=True)

    def watch_total_time_str(self, v: str) -> None:
        try:
            self.query_one("#label-duration", Label).update(v)
        except Exception:  # noqa: BLE001 - widget lifecycle
            log.debug("could not update duration label", exc_info=True)

    def watch_current_volume(self, v: int) -> None:
        try:
            bar   = ascii_bar(v, fill="█", empty="░")
            color = f"[{RED}]" if self.is_muted else f"[{AQUA}]"
            self.query_one("#vol-bar", Label).update(f"{color}{bar}[/]")
            self.query_one("#volume-display", Label).update(f"{v:3d}%")
        except Exception:  # noqa: BLE001 - widget lifecycle
            log.debug("could not update volume display", exc_info=True)

    def watch_is_muted(self, v: bool) -> None:
        try:
            icon = "󰝟" if v else ("󰖀" if self.current_volume < 50 else "󰕾")
            self.query_one("#ctrl-mute", Button).label = icon
        except Exception:  # noqa: BLE001 - widget lifecycle
            log.debug("could not update mute icon", exc_info=True)
        self.watch_current_volume(self.current_volume)

    def watch_play_icon(self, icon: str) -> None:
        try:
            self.query_one("#ctrl-play-pause", Button).label = icon
            self._refresh_header()
        except Exception:  # noqa: BLE001 - widget lifecycle
            log.debug("could not update play icon", exc_info=True)

    def watch_shuffle_on(self, v: bool) -> None:
        try:
            btn = self.query_one("#ctrl-shuffle", Button)
            btn.add_class("-on") if v else btn.remove_class("-on")
        except Exception:  # noqa: BLE001 - widget lifecycle
            log.debug("could not update shuffle button", exc_info=True)
        self._update_queue_border_title()

    def watch_repeat_mode(self, mode: str) -> None:
        try:
            btn = self.query_one("#ctrl-repeat", Button)
            btn.label = {"none": "󰑖", "track": "󰑘", "all": "󰑖"}[mode]
            btn.add_class("-on") if mode != "none" else btn.remove_class("-on")
        except Exception:  # noqa: BLE001 - widget lifecycle
            log.debug("could not update repeat button", exc_info=True)
        self._update_queue_border_title()

    # ── Actions ────────────────────────────────────────────────────────────────

    def action_quit_app(self) -> None:
        self.exit()

    def action_toggle_play(self) -> None:
        if self.current_index != -1:
            self.player.toggle_pause()
        elif self.queue:
            self.play_index(0)

    def action_seek_forward(self) -> None:
        if self.current_index != -1:
            self.player.seek(5)

    def action_seek_backward(self) -> None:
        if self.current_index != -1:
            self.player.seek(-5)

    def action_volume_up(self) -> None:
        self.player.set_volume(self.player.volume + 5)

    def action_volume_down(self) -> None:
        self.player.set_volume(self.player.volume - 5)

    def action_next_track(self) -> None:
        self._next()

    def action_prev_track(self) -> None:
        self._prev()

    def action_toggle_mute(self) -> None:
        self.player.toggle_mute()

    def action_focus_browser(self) -> None:
        try:
            self.query_one("#dir-tree").focus()
        except Exception:  # noqa: BLE001 - widget lifecycle
            log.debug("could not focus browser", exc_info=True)

    def action_focus_queue(self) -> None:
        try:
            self.query_one("#queue-list").focus()
        except Exception:  # noqa: BLE001 - widget lifecycle
            log.debug("could not focus queue", exc_info=True)

    def action_toggle_shuffle(self) -> None:
        self.shuffle_on = not self.shuffle_on

    def action_toggle_repeat(self) -> None:
        self.repeat_mode = {"none": "track", "track": "all", "all": "none"}[self.repeat_mode]

    async def action_refresh_library(self) -> None:
        """Reload the directory tree in-place (Ctrl+R) without restarting."""
        try:
            tree = self.query_one("#dir-tree", AudioDirectoryTree)
            panel = self.query_one("#browser-panel")
            panel.border_title = f"[bold {YELLOW}]󰉋 Library  ↻ refreshing…[/]"
            await tree.reload()
            root_name = Path(self.browser_root).name or str(self.browser_root)
            panel.border_title = f"󰉋 Library  [{GRAY}]{root_name}[/]"
        except Exception:  # noqa: BLE001 - widget lifecycle
            log.debug("could not refresh library", exc_info=True)

    def action_add_dir(self) -> None:
        try:
            tree = self.query_one("#dir-tree", AudioDirectoryTree)
            node = tree.cursor_node
            if node and node.data and node.data.path.is_dir():
                count = self.add_directory(str(node.data.path))
                name = node.data.path.name or str(node.data.path)
                if count:
                    self.notify(f"Added {count} track{'s' if count != 1 else ''} from {name}", timeout=3)
                else:
                    self.notify(f"No audio files found in {name}", severity="warning", timeout=3)
            else:
                self.notify(
                    "Focus the Library panel (f) and select a folder, then press a.",
                    severity="warning",
                    timeout=3,
                )
        except Exception:  # noqa: BLE001 - widget lifecycle
            log.debug("could not add directory", exc_info=True)

    def action_change_browser_root(self) -> None:
        """Open the Change Library Root dialog (Ctrl+B)."""
        self.push_screen(ChangeBrowserRootScreen(), self._on_browser_root_changed)

    async def _on_browser_root_changed(self, new_root: str | None) -> None:
        if not new_root:
            return
        self.browser_root = new_root
        if not _cfg.save({**_cfg.load(), "browser_root": new_root}):
            self.notify("Could not save the new library root.", severity="warning", timeout=4)
        try:
            tree = self.query_one("#dir-tree", AudioDirectoryTree)
            panel = self.query_one("#browser-panel")
            panel.border_title = f"[bold {YELLOW}]󰉋 Library  ↻ loading…[/]"
            tree.path = Path(new_root)
            await tree.reload()
            root_name = Path(new_root).name or str(new_root)
            panel.border_title = f"󰉋 Library  [{GRAY}]{root_name}[/]"
            self.notify(f"Library root: {root_name}", timeout=3)
        except Exception:  # noqa: BLE001 - widget lifecycle
            log.debug("could not apply new browser root", exc_info=True)

    def action_youtube_dl(self) -> None:
        """Open the YouTube download modal."""
        self.push_screen(YoutubeScreen(), self._on_yt_download_done)

    def _on_yt_download_done(self, paths: list | None) -> None:
        """Called when the YouTube modal dismisses. Adds downloaded MP3s in batch."""
        if paths:
            self.add_tracks(paths)

    def action_remove_track(self) -> None:
        try:
            table = self.query_one("#queue-list", DataTable)
            if table.cursor_row is None or not self.queue:
                return
            idx = table.cursor_row
            if not (0 <= idx < len(self.queue)):
                return

            was_playing = (idx == self.current_index)
            del self.queue[idx]
            if was_playing:
                self._stop_and_reset()
                if self.queue:
                    self.play_index(min(idx, len(self.queue) - 1))
            else:
                if idx < self.current_index:
                    self.current_index -= 1
                self._rebuild_queue()
                self._update_queue_border_title()

            # Move the cursor to the track after the deleted one.
            new_cursor = min(idx, len(self.queue) - 1)
            if new_cursor >= 0:
                table.move_cursor(row=new_cursor)
        except Exception:  # noqa: BLE001 - widget lifecycle
            log.debug("could not remove track", exc_info=True)

    def action_open_playlists(self) -> None:
        """Open the Playlists Manager modal screen."""
        self.push_screen(PlaylistScreen(self.queue), self._on_playlist_dismissed)

    def _on_playlist_dismissed(self, result: dict | None) -> None:
        """Callback when the Playlists Manager closes; loads/appends tracks."""
        if not result:
            return
        action = result.get("action")
        tracks = result.get("tracks", [])
        if action == "load":
            self._stop_and_reset()
            self.queue = tracks
            self._rebuild_queue()
            self._update_queue_border_title()
            if self.queue:
                self.play_index(0)
        elif action == "append":
            start_play = (len(self.queue) == 0)
            self.queue.extend(tracks)
            self._rebuild_queue()
            self._update_queue_border_title()
            if start_play and self.queue:
                self.play_index(0)

    def action_add_to_playlist(self) -> None:
        """Add the highlighted Library or Queue track to a playlist."""
        track = None
        tree  = self.query_one("#dir-tree", AudioDirectoryTree)
        table = self.query_one("#queue-list", DataTable)

        if tree.has_focus:
            node = tree.cursor_node
            if node and node.data and not node.data.path.is_dir():
                path = str(node.data.path)
                if is_audio_file(path):
                    track = make_track(path)
        elif table.cursor_row is not None and self.queue:
            idx = table.cursor_row
            if 0 <= idx < len(self.queue):
                track = self.queue[idx]

        if track:
            self.push_screen(AddToPlaylistScreen(track))
        else:
            self.notify(
                "No track selected. Highlight a track in the Library or Queue first.",
                severity="warning",
                timeout=3,
            )

    def action_play_selected(self) -> None:
        """Play the highlighted folder or file immediately."""
        try:
            tree = self.query_one("#dir-tree", AudioDirectoryTree)
            table = self.query_one("#queue-list", DataTable)

            if tree.has_focus:
                node = tree.cursor_node
                if node and node.data:
                    path = str(node.data.path)
                    if node.data.path.is_dir():
                        # Collect tracks first so a failure can't lose the queue.
                        tracks_to_add = []
                        for root, _, files in os.walk(path):
                            for fname in sorted(files):
                                if is_audio_file(fname):
                                    tracks_to_add.append(os.path.join(root, fname))

                        if not tracks_to_add:
                            name = node.data.path.name or str(node.data.path)
                            self.notify(f"No audio files found in {name}",
                                        severity="warning", timeout=3)
                            return

                        self._stop_and_reset()
                        self.queue.clear()
                        self.queue.extend(make_track(p) for p in tracks_to_add)
                        self._rebuild_queue()
                        self._update_queue_border_title()
                        self.play_index(0)
                    elif is_audio_file(path):
                        self._stop_and_reset()
                        self.queue.clear()
                        self.add_to_queue(path)
            elif table.has_focus and table.cursor_row is not None and self.queue:
                idx = table.cursor_row
                if 0 <= idx < len(self.queue):
                    self.play_index(idx)
        except Exception:  # noqa: BLE001 - widget lifecycle
            log.debug("could not play selection", exc_info=True)

    # ── Widget events ──────────────────────────────────────────────────────────

    def on_button_pressed(self, event: Button.Pressed) -> None:
        actions = {
            "ctrl-play-pause": self.action_toggle_play,
            "ctrl-next": self.action_next_track,
            "ctrl-prev": self.action_prev_track,
            "ctrl-shuffle": self.action_toggle_shuffle,
            "ctrl-repeat": self.action_toggle_repeat,
            "ctrl-mute": self.action_toggle_mute,
        }
        action = actions.get(event.button.id)
        if action:
            action()

    def on_directory_tree_file_selected(self, event: DirectoryTree.FileSelected) -> None:
        path = str(event.path)
        if is_audio_file(path):
            self.add_to_queue(path)
        event.stop()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        try:
            self.play_index(int(event.row_key.value))
        except (TypeError, ValueError):
            log.debug("could not resolve selected row %r", event.row_key, exc_info=True)
        event.stop()

    def on_unmount(self) -> None:
        # Persist user settings on clean exit so they survive a restart.
        if not _cfg.save({
            "volume":      int(self.player.volume),
            "shuffle":     self.shuffle_on,
            "repeat_mode": self.repeat_mode,
            "browser_root": self.browser_root,
        }):
            log.warning("could not persist settings on exit")
        self.player.close()


def _configure_logging() -> None:
    """Log to ~/.cache/melodix/melodix.log, falling back to silent."""
    logger = logging.getLogger("melodix")
    logger.setLevel(logging.INFO)
    if logger.handlers:
        return
    try:
        log_dir = Path(os.path.expanduser("~/.cache/melodix"))
        log_dir.mkdir(parents=True, exist_ok=True)
        handler: logging.Handler = logging.FileHandler(log_dir / "melodix.log", encoding="utf-8")
        handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s: %(message)s"
        ))
    except OSError:
        handler = logging.NullHandler()
    logger.addHandler(handler)


def _print_help() -> None:
    print(f"Melodix {__version__} — btop-style terminal music player")
    print("\nUsage:")
    print("  melodix [OPTIONS]")
    print("\nOptions:")
    print("  -h, --help     Show this help message and exit")
    print("  -V, --version  Show version information and exit")
    print("\nKeybindings:")
    print("  Space        Play / Pause")
    print("  ← / →        Seek -5s / +5s")
    print("  + / -        Volume Up / Down")
    print("  n / p        Next / Previous track (or restart song if >3s)")
    print("  s / r        Toggle Shuffle / Repeat mode")
    print("  m            Toggle Mute")
    print("  f / l        Focus Library browser / Queue table")
    print("  a            Add highlighted directory to queue")
    print("  Shift+Enter  Play selected directory or track immediately")
    print("  Delete       Remove selected track from queue")
    print("  b            Add track to playlist")
    print("  o            Open playlists manager")
    print("  y            Download YouTube URL (video or playlist) as MP3")
    print("  Ctrl+R       Refresh library file tree")
    print("  Ctrl+B       Change library root directory")
    print("  q            Quit")


def run_app() -> None:
    """Console-script entry point."""
    if "--version" in sys.argv or "-V" in sys.argv:
        print(f"Melodix {__version__}")
        return
    if "--help" in sys.argv or "-h" in sys.argv:
        _print_help()
        return

    _configure_logging()
    try:
        app = MelodixApp()
    except RuntimeError as exc:
        # Most commonly: mpv is not installed.
        print(f"Melodix could not start: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    app.run()


if __name__ == "__main__":
    run_app()
