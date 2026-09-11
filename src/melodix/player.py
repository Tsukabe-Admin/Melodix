"""player.py — mpv backend driven over its JSON IPC socket.

mpv runs as a child process in idle mode. Commands are written to a Unix
socket and events are read from it on a dedicated daemon thread, which keeps
a local cache of the properties the UI cares about.
"""
from __future__ import annotations

import contextlib
import json
import logging
import os
import shutil
import socket
import subprocess
import tempfile
import threading
import time
from collections.abc import Callable
from typing import Any

log = logging.getLogger(__name__)

# Properties the UI subscribes to, in observation order.
_OBSERVED_PROPERTIES = (
    "time-pos",
    "duration",
    "metadata",
    "pause",
    "volume",
    "mute",
)


class MpvPlayer:
    """Owns the mpv subprocess and exposes a small playback API."""

    def __init__(self) -> None:
        # A system temp dir keeps the socket path short and independent of CWD,
        # which matters when running as an installed package.
        self.tmp_dir = tempfile.mkdtemp(prefix="melodix-")
        self.socket_path = os.path.join(self.tmp_dir, f"mpv_{os.getpid()}.sock")
        self.proc: subprocess.Popen | None = None
        self.client: socket.socket | None = None
        self.running = False
        self.reader_thread: threading.Thread | None = None
        self._send_lock = threading.Lock()  # Serialize socket writes
        self._closing = False
        self._observe_id = 0
        self._observed: dict[str, int] = {}

        # Player state cache
        self.time_pos: float = 0.0
        self.duration: float = 0.0
        self.metadata: dict[str, Any] = {}
        self.paused: bool = True
        self.volume: float = 100.0
        self.mute: bool = False
        self.playing_path: str | None = None

        # Event callbacks. on_player_died fires if the mpv process/socket goes
        # away while it was not deliberately shut down.
        self.on_property_change: Callable[[str, Any], None] | None = None
        self.on_end_file: Callable[[str], None] | None = None
        self.on_player_died: Callable[[], None] | None = None

        try:
            self.start_mpv()
        except Exception:
            # Don't leave an orphaned mpv process or temp dir behind when mpv
            # is missing or fails to come up.
            self._kill_process()
            shutil.rmtree(self.tmp_dir, ignore_errors=True)
            raise

    def _kill_process(self) -> None:
        """Terminate the mpv child process, if any (best effort)."""
        proc = self.proc
        self.proc = None
        if proc is None:
            return
        try:
            proc.terminate()
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            with contextlib.suppress(OSError):
                proc.kill()
        except OSError:
            pass

    # ── Startup ────────────────────────────────────────────────────────────────

    def start_mpv(self) -> None:
        """Launch the mpv subprocess in idle mode and connect to its IPC socket."""
        if os.path.exists(self.socket_path):
            with contextlib.suppress(OSError):
                os.unlink(self.socket_path)

        try:
            self.proc = subprocess.Popen(
                [
                    "mpv",
                    "--idle",
                    "--no-video",
                    f"--input-ipc-server={self.socket_path}",
                    "--input-terminal=no",
                    "--terminal=no",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError:
            raise RuntimeError(
                "mpv not found. Please install it first:\n"
                "  Arch:   sudo pacman -S mpv\n"
                "  Debian: sudo apt install mpv"
            ) from None

        # Wait for the Unix socket to be created and accept connections.
        retries = 30
        connected = False
        while retries > 0:
            if self.proc.poll() is not None:
                raise RuntimeError(
                    f"mpv exited unexpectedly (code {self.proc.returncode}) "
                    "before creating the IPC socket."
                )
            if os.path.exists(self.socket_path):
                try:
                    self.client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                    self.client.connect(self.socket_path)
                    connected = True
                    break
                except OSError:
                    if self.client:
                        with contextlib.suppress(OSError):
                            self.client.close()
                        self.client = None
            time.sleep(0.1)
            retries -= 1

        if not connected or not self.client:
            raise RuntimeError("Failed to start mpv: IPC socket connection failed.")

        self.running = True
        self.reader_thread = threading.Thread(
            target=self._read_loop, name="mpv-ipc-reader", daemon=True
        )
        self.reader_thread.start()

        for prop in _OBSERVED_PROPERTIES:
            self.observe_property(prop)

    # ── IPC plumbing ───────────────────────────────────────────────────────────

    def _send_command(self, *args: Any) -> bool:
        """Send a command to mpv. Returns ``False`` if it could not be delivered."""
        if not self.client or not self.running:
            return False
        payload = {"command": list(args)}
        try:
            with self._send_lock:
                self.client.sendall((json.dumps(payload) + "\n").encode("utf-8"))
            return True
        except OSError:
            log.debug("failed to send mpv command %r", args, exc_info=True)
            return False

    def observe_property(self, prop_name: str) -> None:
        """Ask mpv to push updates for ``prop_name``.

        mpv requires each observer to have a unique numeric id; a monotonic
        counter is used rather than ``hash()`` (which is randomised per process
        and can collide).
        """
        if prop_name in self._observed:
            return
        self._observe_id += 1
        self._observed[prop_name] = self._observe_id
        self._send_command("observe_property", self._observe_id, prop_name)

    def _read_loop(self) -> None:
        """Read newline-delimited JSON events from the mpv socket."""
        buffer = b""
        while self.running:
            try:
                if not self.client:
                    break
                data = self.client.recv(4096)
                if not data:
                    break
                buffer += data
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    if not line:
                        continue
                    try:
                        message = json.loads(line.decode("utf-8", errors="ignore"))
                    except json.JSONDecodeError:
                        log.debug("ignoring malformed mpv message: %r", line)
                        continue
                    self._handle_ipc_message(message)
            except OSError:
                break
            except Exception:  # pragma: no cover - defensive
                log.exception("unexpected error in mpv reader thread")
                break

        self.running = False
        if not self._closing:
            log.warning("mpv connection ended unexpectedly")
            self._safe_callback(self.on_player_died)

    @staticmethod
    def _safe_callback(callback: Callable[..., None] | None, *args: Any) -> None:
        """Invoke a user callback without letting it kill the reader thread."""
        if callback is None:
            return
        try:
            callback(*args)
        except Exception:  # noqa: BLE001 - callbacks are user/UI code
            log.exception("error in mpv callback %r", callback)

    @staticmethod
    def _as_float(value: Any, default: float = 0.0) -> float:
        """Best-effort numeric coercion; mpv occasionally sends null/strings."""
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _handle_ipc_message(self, msg: dict[str, Any]) -> None:
        """Update the property cache and fan out to the registered callbacks."""
        event = msg.get("event")
        if event == "property-change":
            name = msg.get("name")
            data = msg.get("data")

            if name == "time-pos":
                self.time_pos = self._as_float(data)
            elif name == "duration":
                self.duration = self._as_float(data)
            elif name == "metadata":
                self.metadata = data if isinstance(data, dict) else {}
            elif name == "pause":
                self.paused = bool(data)
            elif name == "volume":
                self.volume = self._as_float(data, 100.0)
            elif name == "mute":
                self.mute = bool(data)

            self._safe_callback(self.on_property_change, name, data)

        elif event == "end-file":
            self._safe_callback(self.on_end_file, msg.get("reason", ""))

    # ── Public playback API ────────────────────────────────────────────────────

    def load_file(self, path: str) -> None:
        """Load and start playing an audio file immediately."""
        self.playing_path = path
        self.time_pos = 0.0
        self.duration = 0.0
        self.metadata = {}
        self.paused = False  # optimistic; corrected by the next mpv event
        self._send_command("loadfile", path, "replace")
        self._send_command("set_property", "pause", False)

    def play(self) -> None:
        """Resume playback."""
        self._send_command("set_property", "pause", False)

    def pause(self) -> None:
        """Pause playback."""
        self._send_command("set_property", "pause", True)

    def toggle_pause(self) -> None:
        """Toggle play/pause via mpv's own state (avoids a stale-cache race)."""
        self._send_command("cycle", "pause")

    def seek(self, seconds: float, relative: bool = True) -> None:
        """Seek within the current track."""
        mode = "relative" if relative else "absolute"
        self._send_command("seek", seconds, mode)

    def set_volume(self, level: float) -> None:
        """Set playback volume, clamped to 0–100."""
        level = max(0.0, min(100.0, level))
        self.volume = level  # update cache immediately for responsive keypresses
        self._send_command("set_property", "volume", level)

    def toggle_mute(self) -> None:
        """Toggle mute via mpv's own state."""
        self._send_command("cycle", "mute")

    def stop(self) -> None:
        """Stop playback and clear the cached track state."""
        self.playing_path = None
        self.time_pos = 0.0
        self.duration = 0.0
        self.metadata = {}
        self._send_command("stop")

    def close(self) -> None:
        """Terminate the connection and the mpv subprocess (idempotent)."""
        self._closing = True
        self.running = False

        client = self.client
        self.client = None
        if client:
            try:
                # shutdown() unblocks the reader thread's recv().
                client.shutdown(socket.SHUT_RDWR)
                client.close()
            except OSError:
                pass

        thread = self.reader_thread
        self.reader_thread = None
        self._kill_process()
        if thread and thread.is_alive():
            thread.join(timeout=1)

        shutil.rmtree(self.tmp_dir, ignore_errors=True)
