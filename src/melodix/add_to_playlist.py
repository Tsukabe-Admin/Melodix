"""add_to_playlist.py — modal to add a track to an existing or new playlist."""
from __future__ import annotations

import logging

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, ListView

from .playlists import add_track_to_playlist, list_playlists
from .widgets import PlaylistItem

log = logging.getLogger(__name__)


class AddToPlaylistScreen(ModalScreen[str | None]):
    """Modal dialog to select a playlist to add a track to, or create a new one."""

    BINDINGS = [Binding("escape", "cancel", "Cancel", show=False)]

    def __init__(self, track: dict, **kwargs) -> None:
        super().__init__(**kwargs)
        self.track = track

    def compose(self) -> ComposeResult:
        with Vertical(id="add-pl-dialog"):
            yield Label("Add Track to Playlist", id="add-pl-title")
            yield Label(f"Track: {self.track['title']}", id="add-pl-track-info")

            yield Label("Choose Playlist:", classes="add-pl-label")
            with ListView(id="add-pl-list"):
                for pl in list_playlists():
                    yield PlaylistItem(pl)

            yield Label("Or Create New Playlist:", classes="add-pl-label")
            with Horizontal(id="add-pl-new-row"):
                yield Input(placeholder="Playlist Name...", id="add-pl-new-input")
                yield Button("Create", id="add-pl-btn-create", variant="primary")

            with Horizontal(id="add-pl-actions"):
                yield Button("Cancel", id="add-pl-btn-cancel")

    def on_mount(self) -> None:
        self.query_one("#add-pl-list").focus()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if isinstance(event.item, PlaylistItem):
            self._add_to(event.item.playlist_name)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "add-pl-btn-cancel":
            self.dismiss(None)
        elif bid == "add-pl-btn-create":
            self._create_and_add()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "add-pl-new-input":
            self._create_and_add()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def _add_to(self, playlist_name: str) -> None:
        if add_track_to_playlist(playlist_name, self.track):
            self.dismiss(playlist_name)
        else:
            self.app.notify(
                f"Could not add to '{playlist_name}'. Check that ~/.config is writable.",
                severity="error",
                timeout=5,
            )

    def _create_and_add(self) -> None:
        name_input = self.query_one("#add-pl-new-input", Input)
        name = name_input.value.strip()
        if not name:
            name_input.focus()
            return
        self._add_to(name)
