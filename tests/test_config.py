"""Tests for the config store (melodix.config)."""
from __future__ import annotations

import json
import os

from melodix import config


def test_load_returns_defaults_on_first_run(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "_CONFIG_FILE", str(tmp_path / "missing.json"))
    cfg = config.load()
    assert cfg["volume"] == 100
    assert cfg["shuffle"] is False
    assert cfg["repeat_mode"] == "none"
    assert cfg["browser_root"] == ""


def test_save_then_load_round_trip(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "_CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(config, "_CONFIG_FILE", str(tmp_path / "config.json"))
    assert config.save({
        "volume": 42, "shuffle": True,
        "repeat_mode": "track", "browser_root": "/music",
    }) is True
    cfg = config.load()
    assert cfg == {
        "volume": 42, "shuffle": True,
        "repeat_mode": "track", "browser_root": "/music",
    }


def test_load_merges_defaults_for_unknown_and_missing_keys(monkeypatch, tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"volume": 7, "future_key": "ignored"}))
    monkeypatch.setattr(config, "_CONFIG_FILE", str(path))
    cfg = config.load()
    assert cfg["volume"] == 7
    assert cfg["repeat_mode"] == "none"   # default filled in
    assert "future_key" not in cfg


def test_load_survives_corrupt_file(monkeypatch, tmp_path):
    path = tmp_path / "config.json"
    path.write_text("{ this is not json")
    monkeypatch.setattr(config, "_CONFIG_FILE", str(path))
    assert config.load()["volume"] == 100


def test_load_survives_non_dict_json(monkeypatch, tmp_path):
    path = tmp_path / "config.json"
    path.write_text("[1, 2, 3]")
    monkeypatch.setattr(config, "_CONFIG_FILE", str(path))
    assert config.load()["volume"] == 100


def test_save_is_atomic(monkeypatch, tmp_path):
    """A .tmp file is used and then replaced, so a crash can't truncate config."""
    monkeypatch.setattr(config, "_CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(config, "_CONFIG_FILE", str(tmp_path / "config.json"))
    config.save({"volume": 1, "shuffle": False, "repeat_mode": "none", "browser_root": ""})
    assert os.path.exists(tmp_path / "config.json")
    assert not os.path.exists(tmp_path / "config.json.tmp")


def test_save_returns_false_when_unwritable(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "_CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(config, "_CONFIG_FILE", str(tmp_path / "config.json"))
    monkeypatch.setattr(config.os, "replace", lambda *a, **k: (_ for _ in ()).throw(OSError("nope")))
    assert config.save({"volume": 1}) is False
