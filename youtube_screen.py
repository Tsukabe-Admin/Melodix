"""
youtube_screen.py — Textual ModalScreen for YouTube → MP3 downloads.

Supports single videos and full playlists. Opens with 'y'.
Tracks are added to the queue one-by-one as each finishes.
"""
from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, ProgressBar

from downloader import DownloadJob, download_url

# ── Gruvbox colours ────────────────────────────────────────────────────────────
_YEL = "#fabd2f"
_BLU = "#83a598"
_GRN = "#b8bb26"
_RED = "#fb4934"
_ORG = "#fe8019"
_FG  = "#ebdbb2"
_FG3 = "#a89984"
_BG  = "#282828"
_BG1 = "#3c3836"
_BG2 = "#504945"
_BG3 = "#665c54"


class YoutubeScreen(ModalScreen[list[str] | None]):
    """
    Modal dialog for downloading YouTube URLs (videos or playlists) as MP3s.

    Dismisses with:
        list[str] — absolute paths of all downloaded MP3s (success)
        None      — user cancelled or fatal error
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=False),
    ]

    def __init__(self):
        super().__init__()
        self._job: DownloadJob | None = None
        self._done = False
        self._total_items = 0       # 0 = unknown (single video)
        self._completed_items = 0
        self._all_paths: list[str] = []

    # ── Layout ─────────────────────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        with Vertical(id="yt-dialog"):
            yield Label(
                f"[bold {_ORG}]󰗃  YouTube → MP3[/]",
                id="yt-title",
            )
            yield Label(f"[{_FG3}]Video / Playlist URL:[/]", id="yt-url-label")
            yield Input(
                placeholder="https://www.youtube.com/watch?v=…  or  playlist?list=…",
                id="yt-url-input",
            )
            yield Label(f"[{_FG3}]Save Directory:[/]", id="yt-dir-label")
            yield Input(
                value="~/Music/Melodix",
                placeholder="~/Music/Melodix",
                id="yt-dir-input",
            )

            # Per-track progress (always visible)
            yield Label("", id="yt-track-label")
            yield ProgressBar(id="yt-track-progress", show_eta=False,
                              show_percentage=False)

            # Overall playlist progress (hidden until playlist detected)
            yield Label("", id="yt-overall-label")
            yield ProgressBar(id="yt-overall-progress", show_eta=False,
                              show_percentage=False)

            yield Label("", id="yt-status")

            with Horizontal(id="yt-buttons"):
                yield Button("Download", id="yt-btn-download", variant="primary")
                yield Button("Cancel",   id="yt-btn-cancel",  variant="default")

    def on_mount(self) -> None:
        self.query_one("#yt-url-input", Input).focus()
        # Hide overall progress until we know it's a playlist
        self._set_overall_visible(False)
        pb = self.query_one("#yt-track-progress", ProgressBar)
        pb.total = 100
        overall = self.query_one("#yt-overall-progress", ProgressBar)
        overall.total = 100

    # ── Input / Button events ──────────────────────────────────────────────────

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._start_download()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "yt-btn-download":
            self._start_download()
        elif event.button.id == "yt-btn-cancel":
            self.action_cancel()

    # ── Actions ────────────────────────────────────────────────────────────────

    def action_cancel(self) -> None:
        if self._job:
            self._job.cancel()
        if not self._done:
            self._done = True
            self.dismiss(self._all_paths if self._all_paths else None)

    # ── Download logic ─────────────────────────────────────────────────────────

    def _start_download(self) -> None:
        url = self.query_one("#yt-url-input", Input).value.strip()
        if not url:
            self._set_status(f"[{_RED}]Please enter a URL.[/]")
            return

        out_dir = self.query_one("#yt-dir-input", Input).value.strip()
        if not out_dir:
            self._set_status(f"[{_RED}]Please enter a save directory.[/]")
            return

        self.query_one("#yt-url-input", Input).disabled = True
        self.query_one("#yt-dir-input", Input).disabled = True
        self.query_one("#yt-btn-download", Button).disabled = True
        self._set_status(f"[{_BLU}]Starting…[/]")
        self._set_track_progress(0, "Fetching info…")

        self._job = download_url(
            url,
            output_dir=out_dir,
            on_progress=self._cb_progress,
            on_done=self._cb_item_done,
            on_all_done=self._cb_all_done,
            on_error=self._cb_error,
        )

    # ── Callbacks (background thread → must use call_from_thread) ──────────────

    def _cb_progress(self, percent: float, status: str,
                     item_num: int, total_items: int) -> None:
        self.app.call_from_thread(
            self._on_progress_ui, percent, status, item_num, total_items
        )

    def _cb_item_done(self, path: str) -> None:
        self.app.call_from_thread(self._on_item_done_ui, path)

    def _cb_all_done(self, paths: list[str]) -> None:
        self.app.call_from_thread(self._on_all_done_ui, paths)

    def _cb_error(self, msg: str) -> None:
        self.app.call_from_thread(self._on_error_ui, msg)

    # ── UI updates (always on main thread) ────────────────────────────────────

    def _on_progress_ui(self, percent: float, status: str,
                        item_num: int, total_items: int) -> None:
        # Show/hide the overall progress bar once we know it's a playlist
        if total_items > 1 and self._total_items == 0:
            self._total_items = total_items
            self._set_overall_visible(True)
            try:
                self.query_one("#yt-overall-progress", ProgressBar).total = float(total_items)
            except Exception:
                pass

        if total_items > 1:
            self._total_items = total_items

        self._set_track_progress(percent, status)

        # Update overall bar based on completed + in-progress fraction
        if self._total_items > 1:
            overall_pct = (
                self._completed_items + (percent / 100)
            ) / self._total_items * 100
            self._set_overall_progress(overall_pct, item_num, total_items)

    def _on_item_done_ui(self, path: str) -> None:
        self._completed_items += 1
        self._all_paths.append(path)

        if self._total_items > 1:
            self._set_overall_progress(
                self._completed_items / self._total_items * 100,
                self._completed_items,
                self._total_items,
            )
            self._set_status(
                f"[{_GRN}]✓  {self._completed_items}/{self._total_items} saved[/]"
                f"  [{_FG3}]{_short_path(path)}[/]"
            )
        else:
            self._set_status(
                f"[{_GRN}]✓  Saved:[/]  [{_FG3}]{_short_path(path)}[/]"
            )

    def _on_all_done_ui(self, paths: list[str]) -> None:
        if self._done:
            return
        count = len(paths)
        if count == 1:
            summary = "1 track downloaded."
        else:
            summary = f"{count} tracks downloaded."
        self._set_track_progress(100, f"[bold {_GRN}]Done! {summary}[/]")
        if self._total_items > 1:
            self._set_overall_progress(100, count, count)
        # Brief pause so the user sees the Done state before the modal closes
        self.set_timer(1.4, lambda: self._finish(paths))

    def _on_error_ui(self, msg: str) -> None:
        self._set_track_progress(0, "")
        self._set_status(f"[bold {_RED}]✗  Error:[/]  [{_FG}]{msg}[/]")
        # Re-enable so the user can correct the URL/dir and try again
        try:
            self.query_one("#yt-url-input", Input).disabled = False
            self.query_one("#yt-dir-input", Input).disabled = False
            self.query_one("#yt-btn-download", Button).disabled = False
        except Exception:
            pass

    def _finish(self, paths: list[str]) -> None:
        if not self._done:
            self._done = True
            self.dismiss(paths if paths else None)

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _set_track_progress(self, percent: float, label: str) -> None:
        try:
            self.query_one("#yt-track-progress", ProgressBar).progress = float(percent)
            if label:
                self.query_one("#yt-track-label", Label).update(
                    f"[{_BLU}]{label}[/]"
                )
        except Exception:
            pass

    def _set_overall_progress(self, percent: float,
                               done: int, total: int) -> None:
        try:
            pb = self.query_one("#yt-overall-progress", ProgressBar)
            pb.progress = float(percent)
            self.query_one("#yt-overall-label", Label).update(
                f"[{_FG3}]Overall  [{_YEL}]{done}[/] / [{_YEL}]{total}[/] tracks[/]"
            )
        except Exception:
            pass

    def _set_status(self, markup: str) -> None:
        try:
            self.query_one("#yt-status", Label).update(markup)
        except Exception:
            pass

    def _set_overall_visible(self, visible: bool) -> None:
        try:
            display = "block" if visible else "none"
            self.query_one("#yt-overall-label", Label).styles.display = display
            self.query_one("#yt-overall-progress", ProgressBar).styles.display = display
        except Exception:
            pass


def _short_path(path: str, max_len: int = 48) -> str:
    """Trim a path for display in the status line."""
    import os
    name = os.path.basename(path)
    return name if len(name) <= max_len else name[:max_len - 1] + "…"
