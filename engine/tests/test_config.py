"""Tests for engine/storage/config.py — load/save semantics and the
lock-ownership fix (save_config() must not re-acquire its own lock via
load_config(), which would deadlock on Python's non-reentrant
threading.Lock)."""

from __future__ import annotations

import json
import threading

from fastapi.testclient import TestClient

from main import app
from storage import config
from storage.paths import config_path, meetings_root, storage_root

client = TestClient(app)


def test_get_config_exposes_meetings_root_alongside_storage_root(isolated_storage):
    """Regression test: the frontend's "Open meetings directory" button
    previously had no authoritative meetings path to open and fell back to
    opening storage_root (the app's root folder, not the meetings
    subfolder) instead. GET /config must expose both, computed the same
    way the engine itself resolves them — never hardcoded or guessed."""
    resp = client.get("/config")
    assert resp.status_code == 200
    body = resp.json()

    assert body["storage_root"] == str(storage_root())
    assert body["meetings_root"] == str(meetings_root())
    # The meetings directory is a real subfolder of the storage root, not a
    # separately-reconstructed path that happens to look similar.
    assert body["meetings_root"].startswith(body["storage_root"])
    # ensure_dirs() creates it at engine startup, before any meeting is ever
    # recorded, so opening it is always safe.
    assert meetings_root().is_dir()


def test_patch_config_response_still_includes_storage_and_meetings_root(isolated_storage):
    """Regression test: POST /config previously returned `engine_state.config`
    directly, which never carries storage_root/meetings_root (those are only
    computed in GET /config's response). Saving any setting therefore wiped
    both fields from the frontend's config state after the very first
    change, breaking the "Open" buttons on the very next click — reachable
    the instant a user changed any other setting first, independently of
    the separate Tauri permission-scope bug. Both endpoints must return the
    same shape."""
    resp = client.post("/config", json={"startup_behavior": "show_new_meeting"})
    assert resp.status_code == 200
    body = resp.json()

    assert body["startup_behavior"] == "show_new_meeting"
    assert body["storage_root"] == str(storage_root())
    assert body["meetings_root"] == str(meetings_root())


def test_load_config_creates_defaults_on_first_call(isolated_storage):
    cfg = config.load_config()
    assert cfg["default_template_id"] == "standard"
    assert cfg["transcription"]["hardware_mode"] == "automatic"
    assert config_path().exists()


def test_save_config_merges_and_persists(isolated_storage):
    config.load_config()
    updated = config.save_config({"startup_behavior": "show_new_meeting"})
    assert updated["startup_behavior"] == "show_new_meeting"

    reloaded = config.load_config()
    assert reloaded["startup_behavior"] == "show_new_meeting"
    # Unrelated defaults must survive an unrelated patch.
    assert reloaded["default_template_id"] == "standard"


def test_save_config_deep_merges_nested_dicts(isolated_storage):
    config.load_config()
    config.save_config({"transcription": {"hardware_mode": "cpu"}})
    updated = config.save_config({"transcription": {"output_language": "en"}})

    # Both nested keys must be present — a shallow merge would have dropped
    # hardware_mode when output_language was patched in separately.
    assert updated["transcription"]["hardware_mode"] == "cpu"
    assert updated["transcription"]["output_language"] == "en"


def test_save_config_does_not_deadlock_on_its_own_lock(isolated_storage):
    """Regression guard: save_config() previously could deadlock by calling
    load_config() (which re-acquires the module's non-reentrant
    threading.Lock) while already holding that same lock. A single call
    completing at all — under a hard timeout via a background thread —
    proves the lock is only ever acquired once per call."""
    config.load_config()

    result: dict = {}

    def _save():
        result["value"] = config.save_config({"startup_behavior": "show_dashboard"})

    t = threading.Thread(target=_save, daemon=True)
    t.start()
    t.join(timeout=5.0)

    assert not t.is_alive(), "save_config() did not return — likely deadlocked on its own lock"
    assert result.get("value", {}).get("startup_behavior") == "show_dashboard"


def test_concurrent_save_config_calls_all_complete_and_leave_valid_json(isolated_storage):
    """Many threads patching config simultaneously must never hang, crash,
    or corrupt the file — atomic_write_json guarantees each individual write
    is all-or-nothing, and the shared lock serializes the read-modify-write
    so concurrent patches don't clobber each other's unrelated keys."""
    config.load_config()
    errors: list[Exception] = []

    def _patch(i: int) -> None:
        try:
            config.save_config({"audio": {"chunk_seconds": 20 + i}})
        except Exception as exc:  # pragma: no cover - failure path only
            errors.append(exc)

    threads = [threading.Thread(target=_patch, args=(i,)) for i in range(16)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10.0)

    assert not any(t.is_alive() for t in threads), "a save_config() call never completed"
    assert not errors

    # The file on disk must still be valid, complete JSON — never a
    # truncated or partially-written result of two writers racing.
    on_disk = json.loads(config_path().read_text(encoding="utf-8"))
    assert "audio" in on_disk and "transcription" in on_disk and "ai" in on_disk
    assert isinstance(on_disk["audio"]["chunk_seconds"], int)

    final = config.load_config()
    assert final["audio"]["chunk_seconds"] == on_disk["audio"]["chunk_seconds"]
