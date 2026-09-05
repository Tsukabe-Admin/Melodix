import math
import os
import random
import sys
from pathlib import Path
from typing import Iterable, List, Dict, Any

# Absolute path so the CSS loads correctly from any working directory
_APP_DIR = Path(__file__).parent

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.coordinate import Coordinate
from textual.widgets import Button, Label, DirectoryTree, DataTable, ProgressBar, Input
from textual.reactive import reactive
from textual.screen import ModalScreen
from rich.text import Text

from . import config as _cfg
from .__init__ import __version__
from .player import MpvPlayer
from .visualizer import AudioVisualizer
from .youtube_screen import YoutubeScreen
from .add_to_playlist import AddToPlaylistScreen
from .playlists_screen import PlaylistScreen

# ── Gruvbox palette constants (for Rich markup) ────────────────────────────────
_YEL  = "#fabd2f"   # yellow  – primary accent / active
_BLU  = "#83a598"   # blue    – info / secondary
_GRN  = "#b8bb26"   # green   – playing / positive
_RED  = "#fb4934"   # red     – alert / peak
_ORG  = "#fe8019"   # orange  – toggles / warnings
_AQU  = "#8ec07c"   # aqua    – volume / progress
_FG   = "#ebdbb2"   # fg      – primary text
_FG1  = "#d5c4a1"   # fg1     – secondary text
_FG3  = "#a89984"   # fg3     – dimmed / labels
_BG2  = "#504945"   # bg2     – separators
_BG3  = "#665c54"   # bg3     – inactive borders
_PUR  = "#d3869b"   # purple  – metadata accent
_GRY  = "#928374"   # gray    – muted

AUDIO_EXTS = {".mp3", ".m4a", ".ogg", ".flac", ".wav", ".mp4",
              ".aac", ".webm", ".opus", ".wma"}


def format_time(seconds: float) -> str:
    # Handle None, NaN, and infinite duration (e.g. live streams)
    if seconds is None or math.isnan(seconds):
        return "00:00"
    if math.isinf(seconds):
        return "∞"
    s = int(max(0, seconds))
    m = s // 60
    sec = s % 60
    if m >= 60:
        return f"{m // 60}:{m % 60:02d}:{sec:02d}"
    return f"{m:02d}:{sec:02d}"


def _ascii_bar(value: int, total: int = 100, width: int = 10,
               fill: str = "█", empty: str = "░") -> str:
    filled = round(value / total * width) if total else 0
    return fill * filled + empty * (width - filled)


# ── AudioDirectoryTree ─────────────────────────────────────────────────────────

class AudioDirectoryTree(DirectoryTree):
    """DirectoryTree filtered to show only directories + audio files."""

    def filter_paths(self, paths: Iterable[Path]) -> Iterable[Path]:
        return [p for p in paths if p.is_dir() or p.suffix.lower() in AUDIO_EXTS]


# ── ChangeBrowserRootScreen ────────────────────────────────────────────────────

class ChangeBrowserRootScreen(ModalScreen[str | None]):
    """M4: Modal that lets the user type a new library root directory."""

    BINDINGS = [("escape", "cancel", "Cancel")]

    def compose(self) -> ComposeResult:
        with Vertical(id="chroot-dialog"):
            yield Label("Change Library Root", id="chroot-title")
            yield Label(
                "Enter an absolute or ~ path to a directory:",
                id="chroot-subtitle",
            )
            yield Input(placeholder="~/Music  or  /mnt/nas/audio", id="chroot-input")
            with Horizontal(id="chroot-buttons"):
                yield Button("Change", id="chroot-btn-ok", variant="primary")
                yield Button("Cancel", id="chroot-btn-cancel")

    def on_mount(self) -> None:
        self.query_one("#chroot-input", Input).focus()

    def on_input_submitted(self, _: Input.Submitted) -> None:
        self._confirm()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "chroot-btn-ok":
            self._confirm()
        else:
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)

    def _confirm(self) -> None:
        raw = self.query_one("#chroot-input", Input).value.strip()
        if not raw:
            self.dismiss(None)
            return
        expanded = os.path.abspath(os.path.expanduser(raw))
        if os.path.isdir(expanded):
            self.dismiss(expanded)
        else:
            self.app.notify(f"Directory not found: {expanded}", severity="error", timeout=4)


# ── Main App ───────────────────────────────────────────────────────────────────

class MelodixApp(App):
    """Melodix — btop-style terminal music player (Gruvbox theme)."""

    CSS_PATH = _APP_DIR / "styles.css"
    TITLE    = f"Melodix {__version__}"

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
        ("ctrl+b",     "change_browser_root","Change Root"),   # M4
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
        self.player = MpvPlayer(os.path.abspath(os.path.dirname(__file__)))
        self.player.on_property_change = self._mpv_prop_cb
        self.player.on_end_file        = self._mpv_eof_cb

        self.queue: List[Dict[str, Any]] = []
        self.current_index = -1

        # M3: Load persisted settings and apply them before the first render
        cfg = _cfg.load()
        self.shuffle_on  = cfg["shuffle"]
        self.repeat_mode = cfg["repeat_mode"]

        # M3/M4: Resolve browser root (saved > ~/Music > ~/)
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
                f"[{_BG2}]SPC[/{_BG2}][{_FG3}] play "
                f"[{_BG2}]←→[/{_BG2}] seek "
                f"[{_BG2}]+/-[/{_BG2}] vol "
                f"[{_BG2}]n/p[/{_BG2}] skip "
                f"[{_BG2}]s[/{_BG2}] shuf "
                f"[{_BG2}]r[/{_BG2}] rpt "
                f"[{_BG2}]a[/{_BG2}] add-dir "
                f"[{_BG2}]⇧Ent[/{_BG2}] play-sel "
                f"[{_BG2}]b[/{_BG2}] pl+ "
                f"[{_BG2}]o[/{_BG2}] pl "
                f"[{_BG2}]f/l[/{_BG2}] focus "
                f"[{_BG2}]y[/{_BG2}][bold {_ORG}] YT↓[/] "
                f"[{_BG2}]^R[/{_BG2}] ref "
                f"[{_BG2}]^B[/{_BG2}] root "
                f"[{_BG2}]q[/{_BG2}] quit[/{_FG3}]",
                id="keys-hint",
            )

    def on_mount(self) -> None:
        # ── Panel border titles (btop style: ── Title ──) ─────────────────────
        root_name = Path(self.browser_root).name or str(self.browser_root)
        self.query_one("#browser-panel").border_title = f"󰉋 Library  [{_GRY}]{root_name}[/]"
        self.query_one("#queue-panel").border_title   = "󰋖 Queue"
        self.query_one("#bottom-bar").border_title    = "󰓎 Now Playing"

        # ── Queue DataTable setup ──────────────────────────────────────────────
        table = self.query_one("#queue-list", DataTable)
        table.add_columns(" ", "Title", "Artist", "Time")
        table.cursor_type = "row"

        # ── M3: Apply saved volume to mpv and display ──────────────────────────
        cfg = _cfg.load()
        saved_vol = int(cfg.get("volume", 100))
        self.player.set_volume(saved_vol)
        self.current_volume = saved_vol

        # ── Re-apply reactive-driven UI state (watchers may have no-op'd in __init__)
        self.watch_shuffle_on(self.shuffle_on)
        self.watch_repeat_mode(self.repeat_mode)

        self._refresh_header()
        self._update_queue_border_title()

    # ── MPV callbacks ──────────────────────────────────────────────────────────

    def _mpv_prop_cb(self, name: str, value: Any) -> None:
        if self.is_running:
            try:
                self.call_from_thread(self._handle_prop, name, value)
            except RuntimeError:
                pass

    def _mpv_eof_cb(self, reason: str) -> None:
        if self.is_running:
            try:
                self.call_from_thread(self._handle_eof, reason)
            except RuntimeError:
                pass

    def _handle_prop(self, name: str, value: Any) -> None:
        try:
            if name == "time-pos" and value is not None:
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
                        # H2: Targeted cell update — don't rebuild whole table for one value
                        self._update_cell(self.current_index, 3,
                                          Text(t["duration"], style=f"{_AQU}"))

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

        except Exception:
            pass

    def _handle_eof(self, reason: str) -> None:
        # C1: Handle ALL end-of-file reasons, not just clean "eof".
        # When mpv fails to load a file it sends reason="error", which previously
        # left the queue permanently frozen on the broken track.
        if reason == "eof":
            if self.repeat_mode == "track":
                self.play_index(self.current_index)
            else:
                self._next()
        elif reason in ("error", "aborted"):
            # Auto-skip broken track and notify the user
            title = ""
            if 0 <= self.current_index < len(self.queue):
                title = self.queue[self.current_index].get("title", "")
            self.notify(
                f"Failed to play{': ' + title if title else ' track'} — skipping.",
                severity="error",
                timeout=4,
            )
            self._next()

    # ── Metadata ───────────────────────────────────────────────────────────────

    def _apply_metadata(self, meta: Dict[str, Any]) -> None:
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
            # H2: Update only the two cells that changed, not the whole table
            idx = self.current_index
            self._update_cell(idx, 1, Text(self.now_playing_title,  style=f"bold {_YEL}"))
            self._update_cell(idx, 2, Text(self.now_playing_artist, style=f"{_FG1}"))

        self._refresh_header()

    # ── Queue management ───────────────────────────────────────────────────────

    def add_tracks(self, paths: List[str]) -> int:
        """Batch-add multiple audio paths with a single DataTable rebuild (O(N) vs O(N^2))."""
        added = 0
        start_play = (self.current_index == -1 and not self.queue)
        first_added_idx = len(self.queue)
        for path in paths:
            if not os.path.exists(path):
                continue
            title = os.path.splitext(os.path.basename(path))[0]
            self.queue.append({
                "path": path, "title": title,
                "artist": "", "duration": "--:--", "duration_sec": 0,
            })
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
                if Path(fname).suffix.lower() in AUDIO_EXTS:
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
        except Exception:
            pass
        self.play_icon = "󰏤"
        try:
            self.query_one("#visualizer", AudioVisualizer).set_state(
                True, self.player.volume
            )
        except Exception:
            pass
        # H2: Targeted row update instead of full table rebuild
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
        # Standard media player UX: restart current track from beginning if > 3s in
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
        except Exception:
            pass
        self._rebuild_queue()
        self._refresh_header()

    # ── UI refresh helpers ─────────────────────────────────────────────────────

    def _refresh_header(self) -> None:
        """Single-line btop status bar with track info."""
        try:
            if self.now_playing_artist:
                track_part = (
                    f"[bold {_YEL}]{self.now_playing_title}[/]"
                    f"  [{_BG3}]·[/]  [{_FG3}]{self.now_playing_artist}[/]"
                )
            else:
                track_part = f"[{_FG3}]{self.now_playing_title}[/]"

            # State badge
            if self.current_index == -1:
                state_badge = f"[{_GRY}]■ STOPPED[/]"
            elif self.player.paused:
                state_badge = f"[{_YEL}]⏸ PAUSED[/]"
            else:
                state_badge = f"[bold {_GRN}]▶ PLAYING[/]"

            self.query_one("#header-bar", Label).update(
                f"[bold {_ORG}]󰓎 MELODIX[/]"
                f"  [{_BG3}]│[/]  {state_badge}"
                f"  [{_BG3}]│[/]  [{_BLU}]󰎆[/]  {track_part}"
            )
        except Exception:
            pass

    def _update_queue_border_title(self) -> None:
        """Updates the queue panel's border title with track count and mode icons."""
        try:
            n = len(self.queue)
            s_badge = f"[bold {_ORG}]󰒝[/]" if self.shuffle_on else f"[{_BG3}]󰒝[/]"
            r_badge = {
                "none":  f"[{_BG3}]󰑖[/]",
                "track": f"[bold {_ORG}]󰑘[/]",
                "all":   f"[bold {_ORG}]󰑖[/]",
            }[self.repeat_mode]
            self.query_one("#queue-panel").border_title = (
                f"󰋖 Queue  [{_GRY}]{n} track{'s' if n != 1 else ''}[/]"
                f"  {s_badge}  {r_badge}"
            )
        except Exception:
            pass

    def _update_bottom_border_title(self) -> None:
        """Updates the bottom panel's border title with elapsed/total time."""
        # L2: Skip the update when nothing is playing — avoids constant string
        # rebuilds every second while stopped.
        if self.current_index == -1:
            return
        try:
            self.query_one("#bottom-bar").border_title = (
                f"[bold {_ORG}]󰓎[/]  [{_FG3}]{self.current_time_str}"
                f" [bold {_YEL}]/[/] {self.total_time_str}[/]"
            )
        except Exception:
            pass

    def _rebuild_queue(self) -> None:
        """Full table rebuild — use only for structural changes (add/remove)."""
        try:
            table = self.query_one("#queue-list", DataTable)
            table.clear()
            for idx, t in enumerate(self.queue):
                active = (idx == self.current_index)
                if active:
                    marker = Text("▶",        style=f"bold {_GRN}")
                    title  = Text(t["title"],  style=f"bold {_YEL}")
                    artist = Text(t["artist"], style=f"{_FG1}")
                    dur    = Text(t["duration"], style=f"{_AQU}")
                else:
                    marker = Text(str(idx + 1), style=_GRY)
                    title  = Text(t["title"],   style=_FG)
                    artist = Text(t["artist"],  style=_FG3)
                    dur    = Text(t["duration"], style=_BG3)
                table.add_row(marker, title, artist, dur, key=str(idx))
        except Exception:
            pass

    def _update_queue_playing_row(self, old_idx: int, new_idx: int) -> None:
        """H2: Targeted update — only touch the two rows whose play state changed.

        Avoids the O(n) full table rebuild that previously fired on every track
        change (including metadata events), which caused visible lag on large queues.
        Falls back to _rebuild_queue() on any error.
        """
        try:
            table = self.query_one("#queue-list", DataTable)
            if table.row_count != len(self.queue):
                # Table is stale (e.g. after load) — need full rebuild
                self._rebuild_queue()
                return

            # Restore old playing row to normal style
            if 0 <= old_idx < len(self.queue):
                t = self.queue[old_idx]
                table.update_cell_at(Coordinate(old_idx, 0), Text(str(old_idx + 1), style=_GRY))
                table.update_cell_at(Coordinate(old_idx, 1), Text(t["title"],  style=_FG))
                table.update_cell_at(Coordinate(old_idx, 2), Text(t["artist"], style=_FG3))
                table.update_cell_at(Coordinate(old_idx, 3), Text(t["duration"], style=_BG3))

            # Highlight new playing row
            if 0 <= new_idx < len(self.queue):
                t = self.queue[new_idx]
                table.update_cell_at(Coordinate(new_idx, 0), Text("▶",         style=f"bold {_GRN}"))
                table.update_cell_at(Coordinate(new_idx, 1), Text(t["title"],  style=f"bold {_YEL}"))
                table.update_cell_at(Coordinate(new_idx, 2), Text(t["artist"], style=f"{_FG1}"))
                table.update_cell_at(Coordinate(new_idx, 3), Text(t["duration"], style=f"{_AQU}"))
                table.move_cursor(row=new_idx, animate=True)
        except Exception:
            # Fallback: full rebuild on any unexpected error
            self._rebuild_queue()

    def _update_cell(self, row: int, col: int, value: Text) -> None:
        """H2: Safe single-cell update helper (used for metadata/duration changes)."""
        try:
            self.query_one("#queue-list", DataTable).update_cell_at(
                Coordinate(row, col), value
            )
        except Exception:
            pass

    # ── Reactive watchers ──────────────────────────────────────────────────────

    def watch_current_time_str(self, v: str) -> None:
        try:
            self.query_one("#label-elapsed", Label).update(v)
            self._update_bottom_border_title()
        except Exception:
            pass

    def watch_total_time_str(self, v: str) -> None:
        try:
            self.query_one("#label-duration", Label).update(v)
        except Exception:
            pass

    def watch_current_volume(self, v: int) -> None:
        try:
            bar   = _ascii_bar(v, fill="█", empty="░")
            color = f"[{_RED}]" if self.is_muted else f"[{_AQU}]"
            self.query_one("#vol-bar", Label).update(f"{color}{bar}[/]")
            self.query_one("#volume-display", Label).update(f"{v:3d}%")
        except Exception:
            pass

    def watch_is_muted(self, v: bool) -> None:
        try:
            icon = "󰝟" if v else ("󰖀" if self.current_volume < 50 else "󰕾")
            self.query_one("#ctrl-mute", Button).label = icon
        except Exception:
            pass
        self.watch_current_volume(self.current_volume)

    def watch_play_icon(self, icon: str) -> None:
        try:
            self.query_one("#ctrl-play-pause", Button).label = icon
            self._refresh_header()
        except Exception:
            pass

    def watch_shuffle_on(self, v: bool) -> None:
        try:
            btn = self.query_one("#ctrl-shuffle", Button)
            btn.add_class("-on") if v else btn.remove_class("-on")
        except Exception:
            pass
        self._update_queue_border_title()

    def watch_repeat_mode(self, mode: str) -> None:
        try:
            btn = self.query_one("#ctrl-repeat", Button)
            btn.label = {"none": "󰑖", "track": "󰑘", "all": "󰑖"}[mode]
            btn.add_class("-on") if mode != "none" else btn.remove_class("-on")
        except Exception:
            pass
        self._update_queue_border_title()

    # ── Actions ────────────────────────────────────────────────────────────────

    def action_quit_app(self) -> None:
        self.exit()

    def action_toggle_play(self) -> None:
        if self.current_index != -1:
            self.player.toggle_pause()
        elif self.queue:
            self.play_index(0)

    def action_seek_forward(self)  -> None:
        if self.current_index != -1: self.player.seek(5)

    def action_seek_backward(self) -> None:
        if self.current_index != -1: self.player.seek(-5)

    def action_volume_up(self)     -> None: self.player.set_volume(self.player.volume + 5)
    def action_volume_down(self)   -> None: self.player.set_volume(self.player.volume - 5)
    def action_next_track(self)    -> None: self._next()
    def action_prev_track(self)    -> None: self._prev()
    def action_toggle_mute(self)   -> None: self.player.toggle_mute()

    def action_focus_browser(self) -> None:
        try: self.query_one("#dir-tree").focus()
        except Exception: pass

    def action_focus_queue(self) -> None:
        try: self.query_one("#queue-list").focus()
        except Exception: pass

    def action_toggle_shuffle(self) -> None:
        self.shuffle_on = not self.shuffle_on

    def action_toggle_repeat(self) -> None:
        self.repeat_mode = {"none": "track", "track": "all", "all": "none"}[self.repeat_mode]

    async def action_refresh_library(self) -> None:
        """Reload the directory tree in-place (Ctrl+R) without restarting."""
        try:
            tree = self.query_one("#dir-tree", AudioDirectoryTree)
            panel = self.query_one("#browser-panel")
            panel.border_title = f"[bold {_YEL}]󰉋 Library  ↻ refreshing…[/]"
            await tree.reload()
            root_name = Path(self.browser_root).name or str(self.browser_root)
            panel.border_title = f"󰉋 Library  [{_GRY}]{root_name}[/]"
        except Exception:
            pass

    def action_add_dir(self) -> None:
        # M1: Give the user clear feedback when there's nothing to add
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
        except Exception:
            pass

    # M4: Change browser root at runtime ───────────────────────────────────────

    def action_change_browser_root(self) -> None:
        """Open the Change Library Root dialog (Ctrl+B)."""
        self.push_screen(ChangeBrowserRootScreen(), self._on_browser_root_changed)

    async def _on_browser_root_changed(self, new_root: str | None) -> None:
        if not new_root:
            return
        self.browser_root = new_root
        _cfg.save({**_cfg.load(), "browser_root": new_root})
        try:
            tree = self.query_one("#dir-tree", AudioDirectoryTree)
            panel = self.query_one("#browser-panel")
            panel.border_title = f"[bold {_YEL}]󰉋 Library  ↻ loading…[/]"
            tree.path = Path(new_root)
            await tree.reload()
            root_name = Path(new_root).name or str(new_root)
            panel.border_title = f"󰉋 Library  [{_GRY}]{root_name}[/]"
            self.notify(f"Library root: {root_name}", timeout=3)
        except Exception:
            pass

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
            if table.cursor_row is not None and self.queue:
                idx = table.cursor_row
                if 0 <= idx < len(self.queue):
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

                    # Move cursor to the track after the deleted one (not back to row 0)
                    try:
                        new_cursor = min(idx, len(self.queue) - 1)
                        if new_cursor >= 0:
                            table.move_cursor(row=new_cursor)
                    except Exception:
                        pass
        except Exception:
            pass

    def action_open_playlists(self) -> None:
        """Open the Playlists Manager modal screen."""
        self.push_screen(PlaylistScreen(self.queue), self._on_playlist_dismissed)

    def _on_playlist_dismissed(self, result: dict | None) -> None:
        """Callback when the Playlists Manager is closed. Loads/appends tracks."""
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
        """Add the currently highlighted song (Library browser or Queue list) to a playlist."""
        track = None
        tree  = self.query_one("#dir-tree", AudioDirectoryTree)
        table = self.query_one("#queue-list", DataTable)

        if tree.has_focus:
            node = tree.cursor_node
            if node and node.data and not node.data.path.is_dir():
                path = str(node.data.path)
                if Path(path).suffix.lower() in AUDIO_EXTS:
                    title = os.path.splitext(os.path.basename(path))[0]
                    track = {
                        "path": path, "title": title,
                        "artist": "", "duration": "--:--", "duration_sec": 0,
                    }
        elif table.has_focus or not tree.has_focus:
            if table.cursor_row is not None and self.queue:
                idx = table.cursor_row
                if 0 <= idx < len(self.queue):
                    track = self.queue[idx]

        if track:
            self.push_screen(AddToPlaylistScreen(track))
        else:
            self.notify("No track selected. Highlight a track in the Library or Queue first.", severity="warning", timeout=3)

    def action_play_selected(self) -> None:
        """Play the currently highlighted folder or file immediately."""
        try:
            tree = self.query_one("#dir-tree", AudioDirectoryTree)
            table = self.query_one("#queue-list", DataTable)

            if tree.has_focus:
                node = tree.cursor_node
                if node and node.data:
                    path = str(node.data.path)
                    if node.data.path.is_dir():
                        # Collect tracks FIRST before clearing queue to prevent data loss
                        tracks_to_add = []
                        for root, _, files in os.walk(path):
                            for fname in sorted(files):
                                if Path(fname).suffix.lower() in AUDIO_EXTS:
                                    tracks_to_add.append(os.path.join(root, fname))

                        if not tracks_to_add:
                            name = node.data.path.name or str(node.data.path)
                            self.notify(f"No audio files found in {name}", severity="warning", timeout=3)
                            return

                        self._stop_and_reset()
                        self.queue.clear()
                        for track_path in tracks_to_add:
                            title = os.path.splitext(os.path.basename(track_path))[0]
                            self.queue.append({
                                "path": track_path, "title": title,
                                "artist": "", "duration": "--:--", "duration_sec": 0,
                            })
                        self._rebuild_queue()
                        self._update_queue_border_title()
                        self.play_index(0)
                    else:
                        # Play file: clear queue, add track, play it
                        if Path(path).suffix.lower() in AUDIO_EXTS:
                            self._stop_and_reset()
                            self.queue.clear()
                            self.add_to_queue(path)
            elif table.has_focus and table.cursor_row is not None and self.queue:
                idx = table.cursor_row
                if 0 <= idx < len(self.queue):
                    self.play_index(idx)
        except Exception:
            pass

    # ── Widget events ──────────────────────────────────────────────────────────

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if   bid == "ctrl-play-pause": self.action_toggle_play()
        elif bid == "ctrl-next":       self.action_next_track()
        elif bid == "ctrl-prev":       self.action_prev_track()
        elif bid == "ctrl-shuffle":    self.action_toggle_shuffle()
        elif bid == "ctrl-repeat":     self.action_toggle_repeat()
        elif bid == "ctrl-mute":       self.action_toggle_mute()

    def on_directory_tree_file_selected(
        self, event: DirectoryTree.FileSelected
    ) -> None:
        path = str(event.path)
        if Path(path).suffix.lower() in AUDIO_EXTS:
            self.add_to_queue(path)
        event.stop()

    def on_data_table_row_selected(
        self, event: DataTable.RowSelected
    ) -> None:
        try:
            self.play_index(int(event.row_key.value))
        except Exception:
            pass
        event.stop()

    def on_unmount(self) -> None:
        # M3: Persist user settings on clean exit so they survive restart
        _cfg.save({
            "volume":      int(self.player.volume),
            "shuffle":     self.shuffle_on,
            "repeat_mode": self.repeat_mode,
            "browser_root": self.browser_root,
        })
        self.player.close()


def run_app() -> None:
    # M6: Support --version / -V flag without launching the TUI
    if "--version" in sys.argv or "-V" in sys.argv:
        print(f"Melodix {__version__}")
        return
    if "--help" in sys.argv or "-h" in sys.argv:
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
        return
    MelodixApp().run()


if __name__ == "__main__":
    run_app()
