"""
downloader.py — YouTube → MP3 backend using yt-dlp + ffmpeg.

Supports single videos AND playlists. Runs entirely in a daemon thread.

Callback contract:
  on_progress(pct, status, item_num, total_items)
      pct         — 0–100 float, per-track progress
      status      — human-readable stage string
      item_num    — 1-based current track index (0 if unknown / single video)
      total_items — total tracks in the batch (0 if unknown / single video)

  on_done(path)
      Called once for EVERY completed MP3 (fired N times for an N-track playlist).

  on_all_done(paths)
      Called once at the very end with the list of all downloaded paths.

  on_error(msg)
      Called on fatal error. Download stops.
"""
import os
import re
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Callable, List, Optional


# Default output directory
DEFAULT_MUSIC_DIR = str(Path.home() / "Music" / "Melodix")


def _find_ytdlp() -> str:
    path = shutil.which("yt-dlp")
    if not path:
        raise RuntimeError(
            "yt-dlp not found. Install it with:\n"
            "  sudo pacman -S yt-dlp   (Arch)\n"
            "  sudo apt install yt-dlp  (Debian/Ubuntu)\n"
            "  pip install yt-dlp"
        )
    return path


def _find_ffmpeg() -> str:
    path = shutil.which("ffmpeg")
    if not path:
        raise RuntimeError(
            "ffmpeg not found. Install it with:\n"
            "  sudo pacman -S ffmpeg\n"
            "  sudo apt install ffmpeg"
        )
    return path


class DownloadJob:
    """Represents an active download session. Call .cancel() to abort."""

    def __init__(self):
        self._proc: Optional[subprocess.Popen] = None
        self._cancelled = threading.Event()

    def cancel(self):
        self._cancelled.set()
        if self._proc and self._proc.poll() is None:
            try:
                self._proc.terminate()
            except Exception:
                pass

    @property
    def cancelled(self) -> bool:
        return self._cancelled.is_set()


def download_url(
    url: str,
    output_dir: str = DEFAULT_MUSIC_DIR,
    on_progress: Optional[Callable[[float, str, int, int], None]] = None,
    on_done: Optional[Callable[[str], None]] = None,
    on_all_done: Optional[Callable[[List[str]], None]] = None,
    on_error: Optional[Callable[[str], None]] = None,
) -> DownloadJob:
    """
    Start a background download of a YouTube URL (video or playlist) as MP3(s).

    Returns a DownloadJob handle; call .cancel() to abort mid-download.
    """
    job = DownloadJob()
    thread = threading.Thread(
        target=_run_download,
        args=(url, output_dir, on_progress, on_done, on_all_done, on_error, job),
        daemon=True,
    )
    thread.start()
    return job


# ── Internal ───────────────────────────────────────────────────────────────────

def _run_download(
    url: str,
    output_dir: str,
    on_progress: Optional[Callable],
    on_done: Optional[Callable],
    on_all_done: Optional[Callable],
    on_error: Optional[Callable],
    job: DownloadJob,
):
    try:
        ytdlp = _find_ytdlp()
        _find_ffmpeg()

        output_dir = os.path.abspath(os.path.expanduser(output_dir))

        # ── Security: clamp output directory to within the user's home ──────────
        home_dir = os.path.abspath(os.path.expanduser("~"))
        if not output_dir.startswith(home_dir + os.sep) and output_dir != home_dir:
            output_dir = DEFAULT_MUSIC_DIR

        os.makedirs(output_dir, exist_ok=True)

        _notify(on_progress, 0.0, "Fetching info…", 0, 0)

        # ── Security: only allow http(s) URLs ────────────────────────────────
        url_lower = url.lower().lstrip()
        if not (url_lower.startswith("https://") or url_lower.startswith("http://")):
            _notify(on_error, "Only http:// and https:// URLs are supported.")
            return

        cmd = [
            ytdlp,
            "--newline",
            "--progress",
            # Download ONLY the best audio stream (much faster than downloading video)
            "-f", "bestaudio/best",
            # Use 4 concurrent fragments to speed up download speed
            "-N", "4",
            # Extract audio to mp3
            "-x",
            "--audio-format", "mp3",
            "--audio-quality", "0",
            "--embed-thumbnail",
            "--add-metadata",
            "--parse-metadata", "%(title)s:%(meta_title)s",
            # Restrict filenames to ASCII to prevent path traversal via video titles
            "--restrict-filenames",
            # Simple flat template: ~/Music/Melodix/<Title>.ext
            # For playlists, each track's title is unique so there's no collision.
            "-o", os.path.join(output_dir, "%(title)s.%(ext)s"),
            url,
        ]

        job._proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )

        # ── State machine ──────────────────────────────────────────────────────
        current_item: int = 0       # 1-based; 0 = single video / unknown
        total_items:  int = 0       # 0 = single video / unknown
        current_path: Optional[str] = None
        converting:   bool = False
        completed:    List[str] = []

        for raw_line in job._proc.stdout:
            if job.cancelled:
                break

            line = raw_line.strip()

            # ── Playlist detection ─────────────────────────────────────────────
            # "Playlist Foo: Downloading 12 items of 12"
            pl_total = re.search(r"Playlist .+?: Downloading (\d+) items? of \d+", line)
            if pl_total:
                total_items = int(pl_total.group(1))

            # "[download] Downloading item 3 of 12"
            item_match = re.search(r"\[download\] Downloading item (\d+) of (\d+)", line)
            if item_match:
                new_item  = int(item_match.group(1))
                total_items = int(item_match.group(2))

                # If we just finished the previous item, fire on_done for it
                if current_path and new_item > current_item:
                    _fire_item_done(current_path, completed, on_done)
                    current_path = None
                    converting   = False

                current_item = new_item
                _notify(on_progress, 0.0,
                        f"Track {current_item}/{total_items}  •  fetching info…",
                        current_item, total_items)
                continue

            # ── Destination detection ──────────────────────────────────────────
            # "[ExtractAudio] Destination: /path/to/file.mp3"
            dest_match = re.search(
                r"\[(?:ExtractAudio|ffmpeg|Merger)\] Destination: (.+\.mp3)",
                line,
            )
            if dest_match:
                current_path = dest_match.group(1).strip()

            # "[download] /path/file.mp3 has already been downloaded"
            already_match = re.search(
                r"\[download\] (.+\.mp3) has already been downloaded",
                line,
            )
            if already_match:
                path = already_match.group(1).strip()
                _fire_item_done(path, completed, on_done)
                current_path = None
                converting   = False
                continue

            # ── Per-track download progress ────────────────────────────────────
            pct_match = re.search(r"\[download\]\s+([\d.]+)%", line)
            if pct_match:
                pct = float(pct_match.group(1))
                # Scale raw pct to 0–85 (reserve 85–100 for conversion phase)
                scaled = pct * 0.85
                if total_items > 1:
                    label = f"Track {current_item}/{total_items}  •  {pct:.0f}%"
                else:
                    label = f"Downloading… {pct:.0f}%"
                _notify(on_progress, scaled, label, current_item, total_items)
                continue

            # ── Conversion / metadata stages ───────────────────────────────────
            if "[ExtractAudio]" in line or "[ffmpeg]" in line:
                if not converting:
                    converting = True
                    if total_items > 1:
                        label = f"Track {current_item}/{total_items}  •  converting…"
                    else:
                        label = "Converting to MP3…"
                    _notify(on_progress, 88.0, label, current_item, total_items)
                continue

            if "[Metadata]" in line or "Adding metadata" in line:
                if total_items > 1:
                    label = f"Track {current_item}/{total_items}  •  writing tags…"
                else:
                    label = "Writing metadata…"
                _notify(on_progress, 95.0, label, current_item, total_items)
                continue

        job._proc.wait()

        if job.cancelled:
            _notify(on_error, f"Download cancelled. ({len(completed)} track(s) saved.)")
            return

        if job._proc.returncode != 0 and not completed:
            _notify(on_error, f"yt-dlp exited with code {job._proc.returncode}.")
            return

        # Fire on_done for the last item (or only item for single videos)
        if current_path and os.path.exists(current_path):
            _fire_item_done(current_path, completed, on_done)
        elif not current_path:
            # Fallback: pick the most recently modified MP3 not already completed
            mp3s = sorted(
                Path(output_dir).rglob("*.mp3"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            for mp3 in mp3s:
                if str(mp3) not in completed:
                    _fire_item_done(str(mp3), completed, on_done)
                    break

        if not completed:
            _notify(on_error, "Download finished but no MP3 files were found.")
            return

        count = len(completed)
        if count == 1:
            _notify(on_progress, 100.0, "Done!", 1, 1)
        else:
            _notify(on_progress, 100.0, f"Done! {count} tracks downloaded.", count, count)

        _notify(on_all_done, completed)

    except Exception as exc:
        _notify(on_error, str(exc))


def _fire_item_done(path: str, completed: List[str], on_done: Optional[Callable]):
    """Add path to completed list and fire on_done callback."""
    if path and os.path.exists(path) and path not in completed:
        completed.append(path)
        _notify(on_done, path)


def _notify(cb: Optional[Callable], *args):
    if cb:
        try:
            cb(*args)
        except Exception:
            pass
