import math
import os
import random
from pathlib import Path
from typing import Iterable, List, Dict, Any

# Absolute path so the CSS loads correctly from any working directory
_APP_DIR = Path(__file__).parent

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Label, DirectoryTree, DataTable, ProgressBar
from textual.reactive import reactive
from rich.text import Text

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
    if seconds is None or math.isnan(seconds):
        return "00:00"
    s = int(max(0, seconds))
    return f"{s // 60:02d}:{s % 60:02d}"

def _ascii_bar(value: int, total: int = 100, width: int = 10,
               fill: str = "█", empty: str = "░") -> str:
    filled = round(value / total * width) if total else 0
    return fill * filled + empty * (width - filled)

# ── AudioDirectoryTree ─────────────────────────────────────────────────────────

class AudioDirectoryTree(DirectoryTree):
    """DirectoryTree filtered to show only directories + audio files."""

    def filter_paths(self, paths: Iterable[Path]) -> Iterable[Path]:
        return [p for p in paths if p.is_dir() or p.suffix.lower() in AUDIO_EXTS]

# ── Main App ───────────────────────────────────────────────────────────────────

class MelodixApp(App):
    """Melodix — btop-style terminal music player (Gruvbox theme)."""

    CSS_PATH = _APP_DIR / "styles.css"
    TITLE    = "Melodix"

    BINDINGS = [
        ("q",      "quit_app",       "Quit"),
        ("space",  "toggle_play",    "Play/Pause"),
        ("left",   "seek_backward",  "Seek -5s"),
        ("right",  "seek_forward",   "Seek +5s"),
        ("up",     "volume_up",      "Vol +5"),
        ("down",   "volume_down",    "Vol -5"),
        ("n",      "next_track",     "Next"),
        ("p",      "prev_track",     "Prev"),
        ("s",      "toggle_shuffle", "Shuffle"),
        ("r",      "toggle_repeat",  "Repeat"),
        ("m",      "toggle_mute",    "Mute"),
        ("f",      "focus_browser",  "Browser"),
        ("l",      "focus_queue",    "Queue"),
        ("a",      "add_dir",        "Add Dir"),
        ("delete", "remove_track",   "Remove"),
        ("b",      "add_to_playlist", "Add to PL"),
        ("o",      "open_playlists", "Playlists"),
        ("shift+enter", "play_selected", "Play Selected"),
        ("y",      "youtube_dl",     "YouTube DL"),
        ("ctrl+r", "refresh_library", "Refresh Library"),
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
        super().__init__(**kwargs)
        self.player = MpvPlayer(os.path.abspath(os.path.dirname(__file__)))
        self.player.on_property_change = self._mpv_prop_cb
        self.player.on_end_file        = self._mpv_eof_cb

        self.queue: List[Dict[str, Any]] = []
        self.current_index = -1

        home  = os.path.expanduser("~")
        music = os.path.join(home, "Music")
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
                yield Label("00:00", id="label-elapsed", classes="time-label")
                yield ProgressBar(id="progress-bar", show_eta=False,
                                  show_percentage=False)
                yield Label("00:00", id="label-duration", classes="time-label")

            # One-liner keybindings reference
            yield Label(
                f"[{_BG2}]SPC[/{_BG2}][{_FG3}] play  [{_BG2}]←→[/{_BG2}] seek"
                f"  [{_BG2}]↑↓[/{_BG2}] vol  [{_BG2}]n/p[/{_BG2}] skip"
                f"  [{_BG2}]s[/{_BG2}] shuffle  [{_BG2}]r[/{_BG2}] repeat"
                f"  [{_BG2}]a[/{_BG2}] add-dir  [{_BG2}]⇧Ent[/{_BG2}] play-selected"
                f"  [{_BG2}]b[/{_BG2}] add-to-pl  [{_BG2}]o[/{_BG2}] playlists"
                f"  [{_BG2}]f/l[/{_BG2}] focus  [{_BG2}]y[/{_BG2}][bold {_ORG}] YT↓[/]"
                f"  [{_BG2}]^R[/{_BG2}] refresh  [{_BG2}]q[/{_BG2}] quit[/{_FG3}]",
                id="keys-hint",
            )

    def on_mount(self) -> None:
        # ── Panel border titles (btop style: ── Title ──) ─────────────────────
        self.query_one("#browser-panel").border_title = "󰉋 Library"
        self.query_one("#queue-panel").border_title   = "󰋖 Queue"
        self.query_one("#bottom-bar").border_title    = "󰓎 Now Playing"

        # ── Queue DataTable setup ──────────────────────────────────────────────
        table = self.query_one("#queue-list", DataTable)
        table.add_columns(" ", "Title", "Artist", "Time")
        table.cursor_type = "row"

        # ── Initial sync ───────────────────────────────────────────────────────
        self.current_volume = int(self.player.volume)
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
                        self._refresh_queue()

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
        if reason == "eof":
            if self.repeat_mode == "track":
                self.play_index(self.current_index)
            else:
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
            self._refresh_queue()

        self._refresh_header()

    # ── Queue management ───────────────────────────────────────────────────────

    def add_to_queue(self, path: str) -> None:
        title = os.path.splitext(os.path.basename(path))[0]
        self.queue.append({
            "path": path, "title": title,
            "artist": "", "duration": "--:--", "duration_sec": 0,
        })
        self._refresh_queue()
        self._update_queue_border_title()
        if self.current_index == -1:
            self.play_index(len(self.queue) - 1)

    def add_directory(self, dir_path: str) -> None:
        for root, _, files in os.walk(dir_path):
            for fname in sorted(files):
                if Path(fname).suffix.lower() in AUDIO_EXTS:
                    self.add_to_queue(os.path.join(root, fname))

    def play_index(self, index: int) -> None:
        if not self.queue or not (0 <= index < len(self.queue)):
            return
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
        self._refresh_queue()
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
        self._refresh_queue()
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
        try:
            self.query_one("#bottom-bar").border_title = (
                f"[bold {_ORG}]󰓎[/]  [{_FG3}]{self.current_time_str}"
                f" [bold {_YEL}]/[/] {self.total_time_str}[/]"
            )
        except Exception:
            pass

    def _refresh_queue(self) -> None:
        try:
            table = self.query_one("#queue-list", DataTable)
            table.clear()
            for idx, t in enumerate(self.queue):
                active = (idx == self.current_index)
                if active:
                    marker = Text("▶",       style=f"bold {_GRN}")
                    title  = Text(t["title"], style=f"bold {_YEL}")
                    artist = Text(t["artist"],style=f"{_FG1}")
                    dur    = Text(t["duration"], style=f"{_AQU}")
                else:
                    marker = Text(str(idx + 1), style=_GRY)
                    title  = Text(t["title"],   style=_FG)
                    artist = Text(t["artist"],  style=_FG3)
                    dur    = Text(t["duration"],style=_BG3)
                table.add_row(marker, title, artist, dur, key=str(idx))
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

    def action_quit_app(self)       -> None: self.player.close(); self.exit()
    def action_toggle_play(self)    -> None:
        if self.current_index != -1: self.player.toggle_pause()
    def action_seek_forward(self)   -> None:
        if self.current_index != -1: self.player.seek(5)
    def action_seek_backward(self)  -> None:
        if self.current_index != -1: self.player.seek(-5)
    def action_volume_up(self)      -> None: self.player.set_volume(self.player.volume + 5)
    def action_volume_down(self)    -> None: self.player.set_volume(self.player.volume - 5)
    def action_next_track(self)     -> None: self._next()
    def action_prev_track(self)     -> None: self._prev()
    def action_toggle_mute(self)    -> None: self.player.toggle_mute()
    def action_focus_browser(self)  -> None:
        try: self.query_one("#dir-tree").focus()
        except Exception: pass
    def action_focus_queue(self)    -> None:
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
            panel.border_title = "󰉋 Library"
        except Exception:
            pass

    def action_add_dir(self) -> None:
        try:
            tree = self.query_one("#dir-tree", AudioDirectoryTree)
            node = tree.cursor_node
            if node and node.data and node.data.path.is_dir():
                self.add_directory(str(node.data.path))
        except Exception:
            pass

    def action_youtube_dl(self) -> None:
        """Open the YouTube download modal."""
        self.push_screen(YoutubeScreen(), self._on_yt_download_done)

    def _on_yt_download_done(self, paths: list | None) -> None:
        """Called when the YouTube modal dismisses. Adds each downloaded MP3 to queue."""
        if paths:
            for path in paths:
                self.add_to_queue(path)

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
                    elif idx < self.current_index:
                        self.current_index -= 1
                    self._refresh_queue()
                    self._update_queue_border_title()
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
            self.queue = tracks
            self._refresh_queue()
            self._update_queue_border_title()
            if self.queue:
                self.play_index(0)
        elif action == "append":
            start_play = (len(self.queue) == 0)
            self.queue.extend(tracks)
            self._refresh_queue()
            self._update_queue_border_title()
            if start_play and self.queue:
                self.play_index(0)

    def action_add_to_playlist(self) -> None:
        """Add the currently highlighted song (Library browser or Queue list) to a playlist."""
        track = None
        tree = self.query_one("#dir-tree", AudioDirectoryTree)
        table = self.query_one("#queue-list", DataTable)

        if tree.has_focus:
            node = tree.cursor_node
            if node and node.data and not node.data.path.is_dir():
                path = str(node.data.path)
                if Path(path).suffix.lower() in AUDIO_EXTS:
                    title = os.path.splitext(os.path.basename(path))[0]
                    track = {
                        "path": path,
                        "title": title,
                        "artist": "",
                        "duration": "--:--",
                        "duration_sec": 0
                    }
        else:
            # Default fallback to queue list selection
            if table.cursor_row is not None and self.queue:
                idx = table.cursor_row
                if 0 <= idx < len(self.queue):
                    track = self.queue[idx]

        if track:
            self.push_screen(AddToPlaylistScreen(track))

    def action_play_selected(self) -> None:
        """Play the currently highlighted folder or file immediately."""
        try:
            tree = self.query_one("#dir-tree", AudioDirectoryTree)
            if tree.has_focus:
                node = tree.cursor_node
                if node and node.data:
                    path = str(node.data.path)
                    if node.data.path.is_dir():
                        # Play folder: Clear queue, walk/add all tracks, play first
                        self._stop_and_reset()
                        self.queue.clear()
                        self._refresh_queue()

                        tracks_to_add = []
                        for root, _, files in os.walk(path):
                            for fname in sorted(files):
                                if Path(fname).suffix.lower() in AUDIO_EXTS:
                                    tracks_to_add.append(os.path.join(root, fname))

                        if tracks_to_add:
                            for track_path in tracks_to_add:
                                title = os.path.splitext(os.path.basename(track_path))[0]
                                self.queue.append({
                                    "path": track_path, "title": title,
                                    "artist": "", "duration": "--:--", "duration_sec": 0,
                                })
                            self._refresh_queue()
                            self._update_queue_border_title()
                            self.play_index(0)
                    else:
                        # Play file: Clear queue, add track, play it
                        if Path(path).suffix.lower() in AUDIO_EXTS:
                            self._stop_and_reset()
                            self.queue.clear()
                            self._refresh_queue()
                            self.add_to_queue(path)
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
        self.player.close()


def run_app():
    MelodixApp().run()


if __name__ == "__main__":
    run_app()
