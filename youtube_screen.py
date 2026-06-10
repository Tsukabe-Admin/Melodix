"""
youtube_screen.py — Textual ModalScreen for YouTube → MP3 downloads.

Opens when the user presses 'y'. Accepts a URL, shows live progress,
and dismisses with the path of the finished MP3 on success.
"""
from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, ProgressBar

from downloader import DownloadJob, download_url

# ── Gruvbox colours (mirrors main.py) ─────────────────────────────────────────
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


class YoutubeScreen(ModalScreen[str | None]):
    """
    Modal dialog for downloading a YouTube URL as an MP3.

    Dismisses with:
        str  — absolute path of the downloaded MP3 (success)
        None — user cancelled or an error occurred
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=False),
    ]

    # CSS is defined inline so the screen works even when styles.css
    # doesn't yet have the rules (forward-compatible).
    DEFAULT_CSS = ""

    def __init__(self):
        super().__init__()
        self._job: DownloadJob | None = None
        self._done = False  # guard against double-dismiss

    # ── Layout ─────────────────────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        with Vertical(id="yt-dialog"):
            yield Label(
                f"[bold {_ORG}]󰗃  YouTube → MP3[/]",
                id="yt-title",
            )
            yield Label(
                f"[{_FG3}]Paste a YouTube URL and press [bold {_YEL}]Enter[/] to download.[/]",
                id="yt-subtitle",
            )
            yield Input(
                placeholder="https://www.youtube.com/watch?v=…",
                id="yt-url-input",
            )
            yield Label("", id="yt-status")
            yield ProgressBar(id="yt-progress", show_eta=False, show_percentage=False)
            with Vertical(id="yt-buttons"):
                yield Button("Download", id="yt-btn-download", variant="primary")
                yield Button("Cancel",   id="yt-btn-cancel",  variant="default")

    def on_mount(self) -> None:
        self.query_one("#yt-url-input", Input).focus()
        self._set_progress(0, "")
        pb = self.query_one("#yt-progress", ProgressBar)
        pb.total = 100

    # ── Input / Button events ──────────────────────────────────────────────────

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "yt-url-input":
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
            self.dismiss(None)

    # ── Download logic ─────────────────────────────────────────────────────────

    def _start_download(self) -> None:
        url = self.query_one("#yt-url-input", Input).value.strip()
        if not url:
            self._set_status(f"[{_RED}]Please enter a URL.[/]")
            return

        # Disable input and button while downloading
        self.query_one("#yt-url-input", Input).disabled = True
        self.query_one("#yt-btn-download", Button).disabled = True

        self._set_status(f"[{_BLU}]Starting download…[/]")
        self._set_progress(0, "")

        self._job = download_url(
            url,
            on_progress=self._cb_progress,
            on_done=self._cb_done,
            on_error=self._cb_error,
        )

    # ── Callbacks (called from background thread → must use call_from_thread) ──

    def _cb_progress(self, percent: float, status: str) -> None:
        self.app.call_from_thread(self._set_progress, percent, status)

    def _cb_done(self, path: str) -> None:
        self.app.call_from_thread(self._on_done_ui, path)

    def _cb_error(self, msg: str) -> None:
        self.app.call_from_thread(self._on_error_ui, msg)

    # ── UI updates (always on main thread) ────────────────────────────────────

    def _set_progress(self, percent: float, status_text: str) -> None:
        try:
            pb = self.query_one("#yt-progress", ProgressBar)
            pb.progress = float(percent)
            if status_text:
                self._set_status(f"[{_BLU}]{status_text}[/]")
        except Exception:
            pass

    def _set_status(self, markup: str) -> None:
        try:
            self.query_one("#yt-status", Label).update(markup)
        except Exception:
            pass

    def _on_done_ui(self, path: str) -> None:
        if self._done:
            return
        self._set_progress(100, f"[bold {_GRN}]Done! Added to queue.[/]")
        self._set_status(f"[bold {_GRN}]✓  Saved to:[/] [{_FG3}]{path}[/]")

        # Brief pause so the user can see "Done!" before the modal closes
        self.set_timer(1.2, lambda: self._finish(path))

    def _on_error_ui(self, msg: str) -> None:
        self._set_progress(0, "")
        self._set_status(f"[bold {_RED}]✗  Error:[/] [{_FG}]{msg}[/]")
        # Re-enable input so the user can try again
        try:
            self.query_one("#yt-url-input", Input).disabled = False
            self.query_one("#yt-btn-download", Button).disabled = False
        except Exception:
            pass

    def _finish(self, path: str) -> None:
        if not self._done:
            self._done = True
            self.dismiss(path)
