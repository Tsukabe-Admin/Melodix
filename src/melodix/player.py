import json
import os
import shutil
import socket
import subprocess
import tempfile
import threading
import time
from typing import Callable, Optional, Dict, Any

class MpvPlayer:
    def __init__(self, workspace_path: str):
        # Use a proper system temp dir so the socket works from any CWD
        # (important when running as an installed package via `melodix`)
        self.tmp_dir = tempfile.mkdtemp(prefix="melodix-")
        self.socket_path = os.path.join(self.tmp_dir, f"mpv_{os.getpid()}.sock")
        self.proc: Optional[subprocess.Popen] = None
        self.client: Optional[socket.socket] = None
        self.running = False
        self.reader_thread: Optional[threading.Thread] = None
        self._send_lock = threading.Lock()  # Serialize socket writes
        
        # Player state cache
        self.time_pos: float = 0.0
        self.duration: float = 0.0
        self.metadata: Dict[str, Any] = {}
        self.paused: bool = True
        self.volume: float = 100.0
        self.mute: bool = False
        self.playing_path: Optional[str] = None
        
        # Event callbacks
        self.on_property_change: Optional[Callable[[str, Any], None]] = None
        self.on_end_file: Optional[Callable[[str], None]] = None
        
        try:
            self.start_mpv()
        except Exception:
            # Clean up tmp_dir so it doesn't accumulate in /tmp on repeated failures
            try:
                shutil.rmtree(self.tmp_dir, ignore_errors=True)
            except Exception:
                pass
            raise

    def start_mpv(self):
        """Launches the mpv subprocess in idle mode and binds IPC server."""
        if os.path.exists(self.socket_path):
            try:
                os.unlink(self.socket_path)
            except OSError:
                pass
                
        # Launch mpv with remote IPC enabled, disabling video window and terminal output
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
            )
        
        # Wait for the Unix socket to be created and accept connections
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
                except (ConnectionRefusedError, FileNotFoundError, OSError):
                    if self.client:
                        try:
                            self.client.close()
                        except Exception:
                            pass
                        self.client = None
            time.sleep(0.1)
            retries -= 1
            
        if not connected or not self.client:
            raise RuntimeError("Failed to start mpv: IPC socket connection failed.")
        
        self.running = True
        self.reader_thread = threading.Thread(target=self._read_loop, daemon=True)
        self.reader_thread.start()
        
        # Observe properties for real-time tracking
        self.observe_property("time-pos")
        self.observe_property("duration")
        self.observe_property("metadata")
        self.observe_property("pause")
        self.observe_property("volume")
        self.observe_property("mute")

    def _send_command(self, *args) -> bool:
        """Helper to send a command to the mpv IPC socket."""
        if not self.client or not self.running:
            return False
        payload = {"command": list(args)}
        try:
            with self._send_lock:
                self.client.sendall((json.dumps(payload) + "\n").encode("utf-8"))
            return True
        except Exception:
            return False

    def observe_property(self, prop_name: str):
        """Sends command to observe a property's changes."""
        # Using the property name as the ID for simpler routing
        self._send_command("observe_property", hash(prop_name) & 0xffffff, prop_name)

    def _read_loop(self):
        """Reads lines of JSON events from the mpv socket."""
        buffer = b""
        while self.running:
            try:
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
                        self._handle_ipc_message(message)
                    except json.JSONDecodeError:
                        pass
            except Exception:
                break
        self.running = False

    def _handle_ipc_message(self, msg: Dict[str, Any]):
        """Parses the JSON message from mpv and updates cache."""
        event = msg.get("event")
        if event == "property-change":
            name = msg.get("name")
            data = msg.get("data")
            
            # Update cache based on property
            if name == "time-pos":
                self.time_pos = float(data) if data is not None else 0.0
            elif name == "duration":
                self.duration = float(data) if data is not None else 0.0
            elif name == "metadata":
                self.metadata = data if isinstance(data, dict) else {}
            elif name == "pause":
                self.paused = bool(data)
            elif name == "volume":
                self.volume = float(data) if data is not None else 100.0
            elif name == "mute":
                self.mute = bool(data)
                
            if self.on_property_change:
                self.on_property_change(name, data)
                
        elif event == "end-file":
            reason = msg.get("reason", "")
            if self.on_end_file:
                self.on_end_file(reason)

    # Public API for Playback Control
    def load_file(self, path: str):
        """Loads and starts playing an audio file immediately."""
        self.playing_path = path
        self.time_pos = 0.0
        self.duration = 0.0
        self.metadata = {}
        self.paused = False  # Optimistically mark as playing
        self._send_command("loadfile", path, "replace")
        # Unpause immediately in sequential FIFO order; avoid race conditions
        # and thread leaks caused by sleeping in detached background threads.
        self._send_command("set_property", "pause", False)

    def play(self):
        """Resumes playback."""
        self._send_command("set_property", "pause", False)

    def pause(self):
        """Pauses playback."""
        self._send_command("set_property", "pause", True)

    def toggle_pause(self):
        """Toggles between play and pause using mpv's native cycle command.
        
        Using 'cycle pause' avoids the race condition where self.paused hasn't
        been updated yet from the IPC event stream.
        """
        self._send_command("cycle", "pause")

    def seek(self, seconds: float, relative: bool = True):
        """Seeks within the track."""
        mode = "relative" if relative else "absolute"
        self._send_command("seek", seconds, mode)

    def set_volume(self, level: float):
        """Sets playback volume (0 to 100)."""
        level = max(0.0, min(100.0, level))
        self.volume = level  # Update cached volume immediately for responsive rapid keypresses
        self._send_command("set_property", "volume", level)

    def toggle_mute(self):
        """Toggles mute state using mpv's native cycle to avoid race conditions."""
        self._send_command("cycle", "mute")

    def stop(self):
        """Stops playback."""
        self.playing_path = None
        self.time_pos = 0.0
        self.duration = 0.0
        self.metadata = {}
        self._send_command("stop")

    def close(self):
        """Terminates connection and kills the mpv subprocess (strictly idempotent)."""
        self.running = False
        client = self.client
        self.client = None
        if client:
            try:
                # Shutdown unblocks the reader thread which is blocked on recv()
                client.shutdown(socket.SHUT_RDWR)
                client.close()
            except Exception:
                pass

        proc = self.proc
        self.proc = None
        if proc:
            try:
                proc.terminate()
                proc.wait(timeout=2)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass

        # Clean up the temporary directory (socket file + dir)
        if self.tmp_dir and os.path.exists(self.tmp_dir):
            try:
                shutil.rmtree(self.tmp_dir, ignore_errors=True)
            except Exception:
                pass
