"""change_root_screen.py — modal for changing the library root directory."""
from __future__ import annotations

import os

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label


class ChangeBrowserRootScreen(ModalScreen[str | None]):
    """Modal that lets the user type a new library root directory."""

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
