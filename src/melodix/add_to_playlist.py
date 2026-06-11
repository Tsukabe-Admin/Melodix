from textual.app import ComposeResult
from textual.screen import ModalScreen
from textual.containers import Vertical, Horizontal
from textual.widgets import Label, Button, Input, ListView, ListItem
from .playlists import list_playlists, add_track_to_playlist

class AddToPlaylistScreen(ModalScreen[str | None]):
    """Modal dialog to select a playlist to add a track to, or create a new one."""

    def __init__(self, track: dict, **kwargs):
        super().__init__(**kwargs)
        self.track = track

    def compose(self) -> ComposeResult:
        playlists = list_playlists()
        
        with Vertical(id="add-pl-dialog"):
            yield Label("Add Track to Playlist", id="add-pl-title")
            yield Label(f"Track: {self.track['title']}", id="add-pl-track-info")
            
            yield Label("Choose Playlist:", classes="add-pl-label")
            with ListView(id="add-pl-list"):
                for pl in playlists:
                    yield ListItem(Label(f"󰎆  {pl}"), id=f"pl-{pl}")
            
            yield Label("Or Create New Playlist:", classes="add-pl-label")
            with Horizontal(id="add-pl-new-row"):
                yield Input(placeholder="Playlist Name...", id="add-pl-new-input")
                yield Button("Create", id="add-pl-btn-create", variant="primary")
            
            with Horizontal(id="add-pl-actions"):
                yield Button("Cancel", id="add-pl-btn-cancel")

    def on_mount(self) -> None:
        self.query_one("#add-pl-list").focus()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if event.item and event.item.id:
            playlist_name = event.item.id[3:]  # Strip 'pl-' prefix
            add_track_to_playlist(playlist_name, self.track)
            self.dismiss(playlist_name)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "add-pl-btn-cancel":
            self.dismiss(None)
        elif bid == "add-pl-btn-create":
            self._create_and_add()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "add-pl-new-input":
            self._create_and_add()

    def _create_and_add(self) -> None:
        name_input = self.query_one("#add-pl-new-input", Input)
        name = name_input.value.strip()
        if name:
            add_track_to_playlist(name, self.track)
            self.dismiss(name)
        else:
            name_input.focus()
