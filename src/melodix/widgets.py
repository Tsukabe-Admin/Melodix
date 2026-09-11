"""widgets.py — small reusable widgets shared across Melodix screens."""
from __future__ import annotations

from textual.widgets import Label, ListItem


class PlaylistItem(ListItem):
    """ListItem that carries the playlist name directly.

    Storing the name on the widget avoids building invalid DOM ids from
    user-supplied playlist names.
    """

    def __init__(self, playlist_name: str, **kwargs) -> None:
        super().__init__(Label(f"󰎆  {playlist_name}"), **kwargs)
        self.playlist_name = playlist_name
