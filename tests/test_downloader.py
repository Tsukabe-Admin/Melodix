"""Tests for the yt-dlp output-parsing state machine in melodix.downloader.

The real subprocess is replaced with a scripted fake so the parser can be
driven through playlist, single-video, retry and failure scenarios.
"""
from __future__ import annotations

import os
import subprocess

from melodix import downloader as D


class _LineStream:
    """Iterable stand-in for ``Popen.stdout`` that also supports close()."""

    def __init__(self, lines):
        self._it = iter(lines)

    def __iter__(self):
        return self._it

    def close(self):
        pass


class FakeProc:
    def __init__(self, lines, returncode=0):
        self.stdout = _LineStream(lines)
        self.returncode = returncode

    def wait(self, timeout=None):
        return self.returncode

    def poll(self):
        return self.returncode

    def terminate(self):
        pass

    def kill(self):
        pass


class FakeSubprocess:
    """Stand-in module so we never patch the real (shared) subprocess module."""

    PIPE = subprocess.PIPE
    STDOUT = subprocess.STDOUT

    def __init__(self, lines, returncode=0):
        self._lines = lines
        self._returncode = returncode

    def Popen(self, *args, **kwargs):  # noqa: N802 - mirrors subprocess API
        return FakeProc(self._lines, self._returncode)


def run_download(monkeypatch, lines, out_dir, returncode=0):
    completed, all_done, errors, progress = [], [], [], []

    monkeypatch.setattr(D, "_find_ytdlp", lambda: "yt-dlp")
    monkeypatch.setattr(D, "_find_ffmpeg", lambda: "ffmpeg")
    monkeypatch.setattr(D, "subprocess", FakeSubprocess(lines, returncode))
    # tmp_path lives outside the test HOME, so point the security clamp at it.
    monkeypatch.setattr(D, "DEFAULT_MUSIC_DIR", str(out_dir))

    job = D.DownloadJob()
    D._run_download(
        "https://example.com/playlist",
        str(out_dir),
        lambda p, s, i, t: progress.append((p, s, i, t)),
        completed.append,
        all_done.append,
        errors.append,
        job,
    )
    return completed, all_done, errors, progress


def make_playlist_lines(out_dir, names):
    lines = []
    for i, name in enumerate(names, 1):
        lines += [
            f"[download] Downloading item {i} of {len(names)}",
            f"[download] Destination: {out_dir / (name + '.webm')}",
            "[download]  50.0% of 3.00MiB at 1.00MiB/s ETA 00:01",
            "[download] 100% of 3.00MiB in 00:02",
            f"[ExtractAudio] Destination: {out_dir / (name + '.mp3')}",
            f'[Metadata] Adding metadata to "{out_dir / (name + ".mp3")}"',
        ]
    return lines


def test_playlist_reports_every_track(tmp_path, monkeypatch):
    names = ["Song A", "Song B", "Song C"]
    for n in names:
        (tmp_path / f"{n}.mp3").write_bytes(b"x")

    completed, all_done, errors, progress = run_download(
        monkeypatch, make_playlist_lines(tmp_path, names), tmp_path)

    assert sorted(p.split("/")[-1] for p in completed) == [f"{n}.mp3" for n in names]
    assert len(all_done) == 1 and len(all_done[0]) == 3
    assert errors == []
    assert any(p[0] == 100.0 for p in progress)
    assert any("Track 2/3" in p[1] for p in progress)


def test_single_video_is_detected(tmp_path, monkeypatch):
    (tmp_path / "Solo.mp3").write_bytes(b"x")
    lines = [
        "[youtube] Extracting URL",
        f"[download] Destination: {tmp_path / 'Solo.webm'}",
        "[download] 100% of 3.00MiB in 00:02",
        f"[ExtractAudio] Destination: {tmp_path / 'Solo.mp3'}",
        "[Metadata] Adding metadata",
    ]
    completed, all_done, errors, _ = run_download(monkeypatch, lines, tmp_path)
    assert len(completed) == 1 and completed[0].endswith("Solo.mp3")
    assert errors == []
    assert all_done and len(all_done[0]) == 1


def test_already_downloaded_file_is_reported(tmp_path, monkeypatch):
    (tmp_path / "Old.mp3").write_bytes(b"x")
    lines = [
        "[download] Downloading item 1 of 1",
        f"[download] {tmp_path / 'Old.mp3'} has already been downloaded",
    ]
    completed, all_done, errors, _ = run_download(monkeypatch, lines, tmp_path)
    assert completed and completed[0].endswith("Old.mp3")
    assert errors == []


def test_mp3_source_without_extract_audio_stage(tmp_path, monkeypatch):
    """When the source is already mp3 yt-dlp emits no ExtractAudio stage."""
    names = ["One", "Two", "Three"]
    for n in names:
        (tmp_path / f"{n}.mp3").write_bytes(b"x")

    lines = []
    for i, n in enumerate(names, 1):
        lines += [
            f"[download] Downloading item {i} of 3",
            f"[download] Destination: {tmp_path / (n + '.mp3')}",
            "[download] 100% of 1.00MiB in 00:01",
        ]

    completed, all_done, errors, _ = run_download(monkeypatch, lines, tmp_path)
    assert sorted(os.path.basename(p) for p in completed) == ["One.mp3", "Three.mp3", "Two.mp3"]
    assert errors == []
    assert all_done and len(all_done[0]) == 3


def test_partial_failure_is_surfaced(tmp_path, monkeypatch):
    (tmp_path / "one.mp3").write_bytes(b"x")
    lines = [
        "[download] Downloading item 1 of 3",
        f"[download] Destination: {tmp_path / 'one.mp3'}",
        "[download] 100% of 1.00MiB in 00:01",
        "[download] Downloading item 2 of 3",
        "ERROR: unable to download video data: HTTP Error 403",
    ]
    completed, all_done, errors, _ = run_download(
        monkeypatch, lines, tmp_path, returncode=1)

    assert completed == [str(tmp_path / "one.mp3")]
    assert all_done and all_done[0] == [str(tmp_path / "one.mp3")]
    assert errors and "some items may have failed" in errors[0]


def test_destination_line_from_download_is_tracked(tmp_path, monkeypatch):
    """The broadened Destination regex must catch the plain [download] line."""
    (tmp_path / "Track.mp3").write_bytes(b"x")
    lines = [
        f"[download] Destination: {tmp_path / 'Track.mp3'}",
        "[download] 100% of 1.00MiB in 00:01",
    ]
    completed, _all_done, errors, _ = run_download(monkeypatch, lines, tmp_path)
    assert completed and completed[0].endswith("Track.mp3")
    assert errors == []


def test_failure_is_reported(tmp_path, monkeypatch):
    completed, all_done, errors, _ = run_download(
        monkeypatch, ["ERROR: Unable to download webpage"], tmp_path, returncode=1)
    assert errors and "code 1" in errors[0]
    assert all_done == []


def test_prerecorded_file_is_not_falsely_claimed(tmp_path, monkeypatch):
    """A stale MP3 from an earlier run must not be reported as this download."""
    stale = tmp_path / "stale.mp3"
    stale.write_bytes(b"old")
    import os
    import time
    old = time.time() - 3600
    os.utime(stale, (old, old))

    completed, all_done, errors, _ = run_download(monkeypatch, [], tmp_path)
    assert completed == []
    assert errors and "no mp3" in errors[0].lower()


def test_unsupported_scheme_is_rejected(tmp_path, monkeypatch):
    errors = []
    monkeypatch.setattr(D, "_find_ytdlp", lambda: "yt-dlp")
    monkeypatch.setattr(D, "_find_ffmpeg", lambda: "ffmpeg")
    job = D.DownloadJob()
    D._run_download("file:///etc/passwd", str(tmp_path), None, None, None, errors.append, job)
    assert errors and "http" in errors[0].lower()


def test_cancel_marks_job(tmp_path, monkeypatch):
    job = D.DownloadJob()
    assert job.cancelled is False
    job.cancel()
    assert job.cancelled is True
