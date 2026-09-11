"""downloader.py — YouTube → MP3 backend built on yt-dlp + ffmpeg.

Supports single videos and playlists. Runs entirely in a daemon thread.

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
      Called on fatal error, or on cancellation after a partial download.
      Download stops.
"""
from __future__ import annotations

import logging
import os
import re
import shutil
import signal
import subprocess
import threading
import time
from collections.abc import Callable
from pathlib import Path

log = logging.getLogger(__name__)

# Default output directory
DEFAULT_MUSIC_DIR = str(Path.home() / "Music" / "Melodix")

# Kernel inode timestamps can lag the wall clock by up to one tick, so a file
# this download just wrote can look older than its start time. Allow slack.
_MTIME_SLACK_SECONDS = 2.0

ProgressCallback = Callable[[float, str, int, int], None]
DoneCallback = Callable[[str], None]
AllDoneCallback = Callable[[list[str]], None]
ErrorCallback = Callable[[str], None]


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


def _terminate_proc(proc: subprocess.Popen | None) -> None:
    """Terminate a yt-dlp process *and its children* (e.g. ffmpeg).

    yt-dlp is started in its own session, so signalling the process group
    avoids orphaning an in-flight ffmpeg that is still writing a file.
    """
    if proc is None or proc.poll() is not None:
        return
    try:
        if hasattr(os, "killpg"):
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        else:  # pragma: no cover - non-POSIX
            proc.terminate()
    except (ProcessLookupError, PermissionError, OSError):
        try:
            proc.terminate()
        except OSError:
            log.debug("could not terminate yt-dlp", exc_info=True)


class DownloadJob:
    """Handle for an active download session. Call :meth:`cancel` to abort."""

    def __init__(self) -> None:
        self._proc: subprocess.Popen | None = None
        self._cancelled = threading.Event()

    def cancel(self) -> None:
        self._cancelled.set()
        _terminate_proc(self._proc)

    @property
    def cancelled(self) -> bool:
        return self._cancelled.is_set()


def download_url(
    url: str,
    output_dir: str = DEFAULT_MUSIC_DIR,
    on_progress: ProgressCallback | None = None,
    on_done: DoneCallback | None = None,
    on_all_done: AllDoneCallback | None = None,
    on_error: ErrorCallback | None = None,
) -> DownloadJob:
    """Start a background download of a YouTube URL (video or playlist) as MP3(s).

    Returns a :class:`DownloadJob`; call ``.cancel()`` to abort mid-download.
    """
    job = DownloadJob()
    thread = threading.Thread(
        target=_run_download,
        args=(url, output_dir, on_progress, on_done, on_all_done, on_error, job),
        name="melodix-download",
        daemon=True,
    )
    thread.start()
    return job


# ── Internal ───────────────────────────────────────────────────────────────────

def _resolve_output_dir(output_dir: str) -> str:
    """Expand the output dir and clamp it to within the user's home directory."""
    resolved = os.path.abspath(os.path.expanduser(output_dir))
    home_dir = os.path.abspath(os.path.expanduser("~"))
    if not resolved.startswith(home_dir + os.sep) and resolved != home_dir:
        log.warning("output dir %s is outside %s; using default", resolved, home_dir)
        return DEFAULT_MUSIC_DIR
    return resolved


def _build_command(ytdlp: str, output_dir: str, url: str) -> list[str]:
    return [
        ytdlp,
        "--newline",
        "--progress",
        # Download ONLY the best audio stream (much faster than video).
        "-f", "bestaudio/best",
        # Four concurrent fragments speeds up the download.
        "-N", "4",
        # Extract audio to mp3.
        "-x",
        "--audio-format", "mp3",
        "--audio-quality", "0",
        "--embed-thumbnail",
        "--add-metadata",
        "--parse-metadata", "%(title)s:%(meta_title)s",
        # --windows-filenames strips truly dangerous characters (/ \ : * ? " < > |)
        # without turning spaces into underscores.
        "--windows-filenames",
        "-o", os.path.join(output_dir, "%(title)s.%(ext)s"),
        url,
    ]


def _run_download(
    url: str,
    output_dir: str,
    on_progress: ProgressCallback | None,
    on_done: DoneCallback | None,
    on_all_done: AllDoneCallback | None,
    on_error: ErrorCallback | None,
    job: DownloadJob,
) -> None:
    try:
        ytdlp = _find_ytdlp()
        _find_ffmpeg()

        output_dir = _resolve_output_dir(output_dir)
        os.makedirs(output_dir, exist_ok=True)

        # Only files modified after this point belong to *this* download. The
        # slack absorbs the kernel's coarse inode-timestamp granularity.
        start_time = time.time() - _MTIME_SLACK_SECONDS

        _notify(on_progress, 0.0, "Fetching info…", 0, 0)

        url = url.strip()
        if not url.lower().startswith(("https://", "http://")):
            _notify(on_error, "Only http:// and https:// URLs are supported.")
            return

        cmd = _build_command(ytdlp, output_dir, url)
        log.debug("starting yt-dlp: %s", " ".join(cmd))

        if job.cancelled:  # cancelled while we were still setting up
            _notify(on_error, "Download cancelled.")
            return

        job._proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            # Own session so cancel() can signal yt-dlp's ffmpeg children too.
            start_new_session=hasattr(os, "killpg"),
        )

        current_item = 0        # 1-based; 0 = single video / unknown
        total_items = 0         # 0 = single video / unknown
        current_path: str | None = None
        converting = False
        completed: list[str] = []

        for raw_line in job._proc.stdout:
            if job.cancelled:
                break
            line = raw_line.strip()

            # "Playlist Foo: Downloading 12 items of 12"
            pl_total = re.search(r"Playlist .+?: Downloading (\d+) items? of \d+", line)
            if pl_total:
                total_items = int(pl_total.group(1))

            # "[download] Downloading item 3 of 12"
            item_match = re.search(r"\[download\] Downloading item (\d+) of (\d+)", line)
            if item_match:
                new_item = int(item_match.group(1))
                total_items = int(item_match.group(2))

                # Moving on to a new item means the previous one is finished.
                if current_path and new_item > current_item:
                    _fire_item_done(current_path, completed, on_done)
                    current_path = None
                    converting = False

                current_item = new_item
                _notify(
                    on_progress, 0.0,
                    f"Track {current_item}/{total_items}  •  fetching info…",
                    current_item, total_items,
                )
                continue

            # Any bracketed postprocessor/download "Destination" line. Only the
            # final .mp3 path is tracked. Matching `[download]` as well is
            # important: when the bestaudio stream is already mp3, yt-dlp does
            # not run ExtractAudio and this is the only line naming the file.
            dest_match = re.search(r"\[[^\]]+\] Destination: (.+)", line)
            if dest_match:
                dest_path = dest_match.group(1).strip()
                if dest_path.lower().endswith(".mp3"):
                    current_path = dest_path

            # "[download] /path/file.mp3 has already been downloaded"
            already_match = re.search(
                r"\[download\] (.+\.mp3) has already been downloaded", line
            )
            if already_match:
                _fire_item_done(already_match.group(1).strip(), completed, on_done)
                current_path = None
                converting = False
                continue

            # Per-track download progress, scaled to 0–85 (the rest is conversion).
            pct_match = re.search(r"\[download\]\s+([\d.]+)%", line)
            if pct_match:
                pct = float(pct_match.group(1))
                if total_items > 1:
                    label = f"Track {current_item}/{total_items}  •  {pct:.0f}%"
                else:
                    label = f"Downloading… {pct:.0f}%"
                _notify(on_progress, pct * 0.85, label, current_item, total_items)
                continue

            # Conversion / metadata stages.
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

        proc = job._proc
        if job.cancelled:
            _terminate_proc(proc)
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            log.warning("yt-dlp did not exit; killing it")
            _terminate_proc(proc)
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:  # pragma: no cover - unkillable
                log.error("yt-dlp could not be killed")
        finally:
            # Drain/close the pipe so the fd is not retained until GC.
            try:
                if proc.stdout:
                    proc.stdout.close()
            except OSError:
                pass

        returncode = proc.returncode

        if job.cancelled:
            _notify(on_error, f"Download cancelled. ({len(completed)} track(s) saved.)")
            return

        if returncode != 0 and not completed:
            _notify(on_error, f"yt-dlp exited with code {returncode}.")
            return

        # Fire on_done for the final item.
        fired_last = False
        if current_path and os.path.exists(current_path):
            fired_last = _fire_item_done(current_path, completed, on_done)

        if not fired_last:
            # The destination line may have been missing or stale (e.g. a file
            # that was renamed). Fall back to the newest MP3 created by *this*
            # download that we have not already reported.
            _claim_newest_new_mp3(output_dir, start_time, completed, on_done)

        if not completed:
            _notify(on_error, "Download finished but no MP3 files were found.")
            return

        # A nonzero exit after some tracks were saved means the batch was only
        # partially successful — deliver what we have, but say so.
        partial_failure = returncode != 0
        if partial_failure:
            _notify(on_all_done, list(completed))
            _notify(
                on_error,
                f"{len(completed)} track(s) saved, but yt-dlp exited with code "
                f"{returncode} — some items may have failed.",
            )
            return

        count = len(completed)
        if count == 1:
            _notify(on_progress, 100.0, "Done!", 1, 1)
        else:
            _notify(on_progress, 100.0, f"Done! {count} tracks downloaded.", count, count)

        _notify(on_all_done, list(completed))

    except Exception as exc:  # noqa: BLE001 - reported to the UI, never raised
        log.exception("download failed")
        _notify(on_error, str(exc))


def _claim_newest_new_mp3(
    output_dir: str,
    start_time: float,
    completed: list[str],
    on_done: DoneCallback | None,
) -> str | None:
    """Report the most recent MP3 created after ``start_time`` and not yet claimed."""
    try:
        candidates = sorted(
            Path(output_dir).glob("*.mp3"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
    except OSError:
        log.debug("could not scan %s for downloaded mp3s", output_dir, exc_info=True)
        return None

    for mp3 in candidates:
        if str(mp3) in completed:
            continue
        try:
            if mp3.stat().st_mtime < start_time:
                continue
        except OSError:
            continue
        _fire_item_done(str(mp3), completed, on_done)
        return str(mp3)
    return None


def _fire_item_done(
    path: str, completed: list[str], on_done: DoneCallback | None
) -> bool:
    """Record a completed track and fire ``on_done``. Returns ``True`` if fired."""
    if path and os.path.exists(path) and path not in completed:
        completed.append(path)
        _notify(on_done, path)
        return True
    return False


def _notify(cb: Callable[..., None] | None, *args: object) -> None:
    if cb is None:
        return
    try:
        cb(*args)
    except Exception:  # noqa: BLE001 - callbacks are UI code
        log.exception("error in download callback %r", cb)
