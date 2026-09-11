"""Integration tests for the mpv IPC backend."""
from __future__ import annotations

import os
import shutil
import threading
import time

import pytest

pytestmark = pytest.mark.skipif(shutil.which("mpv") is None, reason="mpv not installed")


@pytest.fixture
def player():
    from melodix.player import MpvPlayer

    p = MpvPlayer()
    try:
        yield p
    finally:
        p.close()


def test_observe_property_ids_are_unique(player):
    ids = list(player._observed.values())
    assert ids, "expected observed properties"
    assert all(i > 0 for i in ids)
    assert len(ids) == len(set(ids)), f"duplicate observer ids: {ids}"


def test_observe_property_is_idempotent(player):
    before = dict(player._observed)
    player.observe_property("time-pos")
    assert player._observed == before


def test_close_is_idempotent_and_cleans_up():
    from melodix.player import MpvPlayer

    p = MpvPlayer()
    tmp_dir = p.tmp_dir
    p.close()
    p.close()  # second close must be a no-op
    assert p.proc is None
    assert p.client is None
    assert not os.path.exists(tmp_dir)


def test_player_died_callback_fires_when_mpv_killed(player):
    fired = threading.Event()
    player.on_player_died = fired.set

    player.proc.kill()

    assert fired.wait(5), "on_player_died was not fired after mpv was killed"
    assert player.running is False


def test_close_does_not_fire_player_died():
    from melodix.player import MpvPlayer

    p = MpvPlayer()
    fired = threading.Event()
    p.on_player_died = fired.set
    p.close()
    assert not fired.wait(0.3), "on_player_died must not fire on a deliberate close"


def test_load_file_populates_duration_and_metadata(player, sample_audio):
    player.load_file(sample_audio)
    deadline = time.time() + 15
    while time.time() < deadline and player.duration == 0:
        time.sleep(0.1)
    assert player.duration > 0
    assert player.paused is False


def test_volume_is_clamped(player):
    player.set_volume(150)
    assert player.volume == 100.0
    player.set_volume(-20)
    assert player.volume == 0.0


def test_send_command_after_close_returns_false(player):
    player.close()
    assert player._send_command("cycle", "pause") is False
