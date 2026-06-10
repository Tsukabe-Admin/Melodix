"""
downloader.py — YouTube → MP3 backend using yt-dlp + ffmpeg.

Runs entirely in a daemon thread so the Textual UI stays responsive.
Calls progress/done/error callbacks which must be thread-safe
(caller is responsible for using call_from_thread if needed).
"""
import os
import re
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Callable, Optional


# Default output directory
DEFAULT_MUSIC_DIR = str(Path.home() / "Music" / "Melodix")


def _find_ytdlp() -> str:
    """Returns the path to yt-dlp, raising RuntimeError if not found."""
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
    """Represents a single active download. Call .cancel() to abort."""

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
    on_progress: Optional[Callable[[float, str], None]] = None,
    on_done: Optional[Callable[[str], None]] = None,
    on_error: Optional[Callable[[str], None]] = None,
) -> DownloadJob:
    """
    Start a background download of a YouTube URL as MP3.

    Args:
        url:         YouTube URL (video or playlist item).
        output_dir:  Directory to save the MP3 file.
        on_progress: Called with (percent: float, status_text: str).
                     percent is 0.0–100.0; status_text is a human-readable stage.
        on_done:     Called with the absolute path of the finished MP3.
        on_error:    Called with an error message string.

    Returns:
        A DownloadJob handle; call .cancel() to abort.
    """
    job = DownloadJob()
    thread = threading.Thread(
        target=_run_download,
        args=(url, output_dir, on_progress, on_done, on_error, job),
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
    on_error: Optional[Callable],
    job: DownloadJob,
):
    try:
        ytdlp = _find_ytdlp()
        _find_ffmpeg()  # just validate it exists; yt-dlp calls it internally

        os.makedirs(output_dir, exist_ok=True)

        _notify(on_progress, 0.0, "Fetching info…")

        # yt-dlp command:
        # --newline          → one progress line per update (easier to parse)
        # --progress         → enable progress reporting
        # --no-playlist      → only download the single video, not a whole playlist
        # -x / --audio-format mp3 → extract audio and convert to mp3
        # --audio-quality 0  → best quality
        # -o template        → output filename template
        cmd = [
            ytdlp,
            "--newline",
            "--progress",
            "--no-playlist",
            "-x",
            "--audio-format", "mp3",
            "--audio-quality", "0",
            "--embed-thumbnail",
            "--add-metadata",
            "--parse-metadata", "%(title)s:%(meta_title)s",
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

        output_path: Optional[str] = None
        converting = False

        for raw_line in job._proc.stdout:
            if job.cancelled:
                break

            line = raw_line.strip()

            # Detect the output filename yt-dlp announces
            # "[ExtractAudio] Destination: /path/to/file.mp3"
            dest_match = re.search(
                r"\[(?:ExtractAudio|ffmpeg|Merger)\] Destination: (.+\.mp3)",
                line,
            )
            if dest_match:
                output_path = dest_match.group(1).strip()

            # "[download] /path/to/file.mp3 has already been downloaded"
            already_match = re.search(
                r"\[download\] (.+\.mp3) has already been downloaded",
                line,
            )
            if already_match:
                output_path = already_match.group(1).strip()

            # Download progress lines look like:
            # "[download]  45.2% of    4.32MiB at    1.20MiB/s ETA 00:03"
            pct_match = re.search(r"\[download\]\s+([\d.]+)%", line)
            if pct_match:
                pct = float(pct_match.group(1))
                # Scale download to 0–85% (leave 85–100 for conversion)
                _notify(on_progress, pct * 0.85, f"Downloading… {pct:.0f}%")
                continue

            # Conversion stage
            if "[ExtractAudio]" in line or "[ffmpeg]" in line:
                if not converting:
                    converting = True
                    _notify(on_progress, 88.0, "Converting to MP3…")
                continue

            if "[Metadata]" in line or "Adding metadata" in line:
                _notify(on_progress, 95.0, "Writing metadata…")
                continue

        job._proc.wait()

        if job.cancelled:
            _notify(on_error, "Download cancelled.")
            return

        if job._proc.returncode != 0:
            _notify(on_error, f"yt-dlp exited with code {job._proc.returncode}.")
            return

        if not output_path or not os.path.exists(output_path):
            # Fallback: find the most recently created mp3 in the output dir
            mp3s = sorted(
                Path(output_dir).glob("*.mp3"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            if mp3s:
                output_path = str(mp3s[0])
            else:
                _notify(on_error, "Download finished but MP3 file not found.")
                return

        _notify(on_progress, 100.0, "Done!")
        _notify(on_done, output_path)

    except Exception as exc:
        _notify(on_error, str(exc))


def _notify(cb: Optional[Callable], *args):
    if cb:
        try:
            cb(*args)
        except Exception:
            pass
