from textual.app import ComposeResult
from textual.screen import ModalScreen
from textual.containers import Horizontal, Vertical
from textual.widgets import Label, Button, Input, ListView, ListItem, DataTable
from rich.text import Text
from .playlists import list_playlists, load_playlist, save_playlist, delete_playlist


class PlaylistItem(ListItem):
    """Custom ListItem that stores the playlist name directly, avoiding invalid DOM IDs."""

    def __init__(self, playlist_name: str, **kwargs):
        super().__init__(Label(f"󰎆  {playlist_name}"), **kwargs)
        self.playlist_name = playlist_name


class PlaylistScreen(ModalScreen[dict | None]):
    """Modal screen for managing, loading, appending, and deleting playlists."""

    def __init__(self, current_queue: list, **kwargs):
        super().__init__(**kwargs)
        # L4: Copy the list — don't hold an alias to the live queue so that
        # tracks added by a background download after the modal opens are NOT
        # silently included in a Save Queue operation.
        self.current_queue = list(current_queue)
        self.selected_playlist = None
        # H4: Track the last name the user tried to overwrite for double-press confirm
        self._overwrite_confirm: str | None = None

    def compose(self) -> ComposeResult:
        playlists = list_playlists()

        with Vertical(id="pl-dialog"):
            yield Label("Playlists Manager", id="pl-title")

            # Split view: List of playlists on left, track preview on right
            with Horizontal(id="pl-split-view"):
                with Vertical(id="pl-left-panel"):
                    yield Label("Saved Playlists", id="pl-list-label")
                    with ListView(id="pl-list"):
                        for pl in playlists:
                            yield PlaylistItem(pl)

                with Vertical(id="pl-right-panel"):
                    yield Label("Tracks Preview", id="pl-preview-label")
                    yield DataTable(id="pl-preview-table")

            # Save Current Queue section
            with Horizontal(id="pl-save-row"):
                yield Input(placeholder="Save current queue as...", id="pl-save-input")
                yield Button("Save Queue", id="pl-btn-save", variant="primary")

            # Action buttons
            with Horizontal(id="pl-actions-row"):
                yield Button("Load (Replace Queue)", id="pl-btn-load", variant="success")
                yield Button("Append to Queue", id="pl-btn-append")
                yield Button("Delete Playlist", id="pl-btn-delete")
                yield Button("Close", id="pl-btn-close")

    def on_mount(self) -> None:
        table = self.query_one("#pl-preview-table", DataTable)
        table.add_columns("Title", "Artist", "Time")
        table.cursor_type = "row"

        # Focus list on launch
        self.query_one("#pl-list").focus()

        # Load first playlist preview if available
        playlists = list_playlists()
        if playlists:
            self._update_preview(playlists[0])

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        if isinstance(event.item, PlaylistItem):
            self._update_preview(event.item.playlist_name)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        # H1: Enter on a playlist triggers the Load action — the most natural
        # terminal UX. Previously we stopped the event (did nothing).
        event.stop()
        self._dispatch_action("load")

    def _update_preview(self, name: str) -> None:
        self.selected_playlist = name
        tracks = load_playlist(name)

        # Update preview label
        self.query_one("#pl-preview-label", Label).update(f"Tracks in '{name}' ({len(tracks)})")

        table = self.query_one("#pl-preview-table", DataTable)
        table.clear()
        for idx, t in enumerate(tracks):
            title  = Text(t["title"],              style="#ebdbb2")
            artist = Text(t.get("artist", ""),     style="#a89984")
            dur    = Text(t.get("duration", "--:--"), style="#8ec07c")
            table.add_row(title, artist, dur, key=str(idx))

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

    def _dispatch_action(self, action: str) -> None:
        if self.selected_playlist:
            tracks = load_playlist(self.selected_playlist)
            if tracks:
                self.dismiss({"action": action, "tracks": tracks})
            else:
                self.app.notify(f"Playlist '{self.selected_playlist}' has no tracks.", severity="warning", timeout=3)

    def _delete_selected(self) -> None:
        if self.selected_playlist:
            delete_playlist(self.selected_playlist)

            # Refresh list
            lv = self.query_one("#pl-list", ListView)
            lv.clear()
            playlists = list_playlists()
            for pl in playlists:
                lv.append(PlaylistItem(pl))

            # Clear preview or load next
            if playlists:
                self._update_preview(playlists[0])
                lv.index = 0
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

        # H4: Overwrite protection — first press warns, second press confirms.
        if name in list_playlists():
            if self._overwrite_confirm != name:
                self._overwrite_confirm = name
                self.app.notify(
                    f"'{name}' already exists. Press Save again to overwrite.",
                    severity="warning",
                    timeout=4,
                )
                return
        # Either name is new, or user confirmed overwrite with a second press
        self._overwrite_confirm = None

        save_playlist(name, self.current_queue)
        input_w.value = ""

        # Refresh list and select the newly saved playlist
        lv = self.query_one("#pl-list", ListView)
        lv.clear()
        playlists = list_playlists()

        selected_idx = 0
        for idx, pl in enumerate(playlists):
            lv.append(PlaylistItem(pl))
            if pl == name:
                selected_idx = idx

        # C2: lv.index is a settable reactive
        if playlists:
            lv.index = selected_idx
            self._update_preview(name)
