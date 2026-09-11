"""playlists_screen.py — modal for managing, loading and deleting playlists."""
from __future__ import annotations

import logging

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Input, Label, ListView

from .playlists import (
    delete_playlist,
    list_playlists,
    load_playlist,
    sanitize_playlist_name,
    save_playlist,
)
from .theme import AQUA, FG, FG3
from .widgets import PlaylistItem

log = logging.getLogger(__name__)


class PlaylistScreen(ModalScreen[dict | None]):
    """Modal screen for managing, loading, appending, and deleting playlists."""

    def __init__(self, current_queue: list, **kwargs) -> None:
        super().__init__(**kwargs)
        # Copy the list: don't alias the live queue, so tracks added by a
        # background download after the modal opens are not silently saved.
        self.current_queue = list(current_queue)
        self.selected_playlist: str | None = None
        # Last name the user tried to overwrite, for double-press confirmation.
        self._overwrite_confirm: str | None = None

    # ── Layout ─────────────────────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        with Vertical(id="pl-dialog"):
            yield Label("Playlists Manager", id="pl-title")

            with Horizontal(id="pl-split-view"):
                with Vertical(id="pl-left-panel"):
                    yield Label("Saved Playlists", id="pl-list-label")
                    with ListView(id="pl-list"):
                        for pl in list_playlists():
                            yield PlaylistItem(pl)

                with Vertical(id="pl-right-panel"):
                    yield Label("Tracks Preview", id="pl-preview-label")
                    yield DataTable(id="pl-preview-table")

            with Horizontal(id="pl-save-row"):
                yield Input(placeholder="Save current queue as...", id="pl-save-input")
                yield Button("Save Queue", id="pl-btn-save", variant="primary")

            with Horizontal(id="pl-actions-row"):
                yield Button("Load (Replace Queue)", id="pl-btn-load", variant="success")
                yield Button("Append to Queue", id="pl-btn-append")
                yield Button("Delete Playlist", id="pl-btn-delete")
                yield Button("Close", id="pl-btn-close")

    def on_mount(self) -> None:
        table = self.query_one("#pl-preview-table", DataTable)
        table.add_columns("Title", "Artist", "Time")
        table.cursor_type = "row"

        self.query_one("#pl-list").focus()

        playlists = list_playlists()
        if playlists:
            self._select_index(0, playlists[0])

    # ── Selection helpers ──────────────────────────────────────────────────────
    #
    # The selection is always derived from the ListView itself rather than from
    # a cached field, because rebuilding the list emits a *deferred*
    # Highlighted event for the item that was just removed. Trusting that event
    # could point Load/Append/Delete at a different playlist than the one
    # visibly highlighted — and Delete would remove the wrong file.

    def _playlist_list(self) -> ListView:
        return self.query_one("#pl-list", ListView)

    def _name_at(self, index: int | None) -> str | None:
        if index is None:
            return None
        children = self._playlist_list().children
        if 0 <= index < len(children):
            child = children[index]
            if isinstance(child, PlaylistItem):
                return child.playlist_name
        return None

    def _selected_name(self) -> str | None:
        """The playlist the user actually has highlighted right now."""
        return self._name_at(self._playlist_list().index)

    def _select_index(self, index: int, name: str | None = None) -> None:
        """Highlight a row and show ``name`` (or the row's own name) as preview.

        The name is passed explicitly because ``ListView`` mounts appended
        children asynchronously, so reading them back here can be too early.
        """
        lv = self._playlist_list()
        if lv.children:
            lv.index = index
        shown = name or self._name_at(index)
        if shown:
            self._update_preview(shown)

    # ── Events ─────────────────────────────────────────────────────────────────

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        if not isinstance(event.item, PlaylistItem):
            return
        # ListView posts Highlighted asynchronously, so an event for a row that
        # is no longer (or not yet) the highlighted one can arrive after we have
        # deliberately selected another row. Only trust the live highlight.
        if self._playlist_list().highlighted_child is not event.item:
            return
        self._update_preview(event.item.playlist_name)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        # Enter on a playlist loads it — the most natural terminal UX.
        event.stop()
        self._dispatch_action("load")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "pl-btn-close":
            self.dismiss(None)
        elif bid == "pl-btn-load":
            self._dispatch_action("load")
        elif bid == "pl-btn-append":
            self._dispatch_action("append")
        elif bid == "pl-btn-delete":
            self._delete_selected()
        elif bid == "pl-btn-save":
            self._save_queue()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "pl-save-input":
            self._save_queue()

    # ── Actions ────────────────────────────────────────────────────────────────

    def _update_preview(self, name: str) -> None:
        self.selected_playlist = name
        tracks = load_playlist(name)

        self.query_one("#pl-preview-label", Label).update(
            f"Tracks in '{name}' ({len(tracks)})"
        )

        table = self.query_one("#pl-preview-table", DataTable)
        table.clear()
        for idx, t in enumerate(tracks):
            table.add_row(
                Text(t["title"], style=FG),
                Text(t.get("artist", ""), style=FG3),
                Text(t.get("duration", "--:--"), style=AQUA),
                key=str(idx),
            )

    def _dispatch_action(self, action: str) -> None:
        name = self._selected_name()
        if not name:
            self.app.notify("Select a playlist first.", severity="warning", timeout=3)
            return
        tracks = load_playlist(name)
        if tracks:
            self.dismiss({"action": action, "tracks": tracks})
        else:
            self.app.notify(f"Playlist '{name}' has no tracks.", severity="warning", timeout=3)

    def _delete_selected(self) -> None:
        name = self._selected_name()
        if not name:
            self.app.notify("Select a playlist first.", severity="warning", timeout=3)
            return
        if not delete_playlist(name):
            self.app.notify(f"Could not delete '{name}'.", severity="error", timeout=4)
            return

        lv = self._playlist_list()
        lv.clear()
        playlists = list_playlists()
        for pl in playlists:
            lv.append(PlaylistItem(pl))

        if playlists:
            self._select_index(0, playlists[0])
        else:
            self.selected_playlist = None
            self.query_one("#pl-preview-label", Label).update("Tracks Preview")
            self.query_one("#pl-preview-table", DataTable).clear()

    def _save_queue(self) -> None:
        input_w = self.query_one("#pl-save-input", Input)
        name = input_w.value.strip()
        if not name:
            input_w.focus()
            return
        if not self.current_queue:
            self.app.notify("Queue is empty — nothing to save.", severity="warning", timeout=3)
            return

        # Compare sanitized names: get_playlist_path() sanitizes too, so
        # comparing raw input would bypass the overwrite confirmation.
        safe_name = sanitize_playlist_name(name)
        if safe_name in list_playlists() and self._overwrite_confirm != safe_name:
            self._overwrite_confirm = safe_name
            self.app.notify(
                f"'{safe_name}' already exists. Press Save again to overwrite.",
                severity="warning",
                timeout=4,
            )
            return
        self._overwrite_confirm = None

        if not save_playlist(safe_name, self.current_queue):
            self.app.notify(
                f"Could not save '{safe_name}'. Check that ~/.config is writable.",
                severity="error",
                timeout=5,
            )
            return

        input_w.value = ""

        lv = self._playlist_list()
        lv.clear()
        playlists = list_playlists()
        selected_idx = 0
        for idx, pl in enumerate(playlists):
            lv.append(PlaylistItem(pl))
            if pl == safe_name:
                selected_idx = idx
        if playlists:
            self._select_index(selected_idx, safe_name)
