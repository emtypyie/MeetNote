"""App configuration (Settings screen backing store).

Stored as plain JSON at ~/MeetNote/config.json — never holds API keys
(those come only from environment variables / .env, per the product spec's
"never hard-code / never store secrets insecurely" requirement). The
Settings > AI screen only ever shows whether a key is configured, never the
key itself.
"""

from __future__ import annotations

import copy
import json
import threading

from storage.atomic import atomic_write_json
from storage.paths import config_path

DEFAULT_CONFIG = {
    "default_template_id": "standard",
    "startup_behavior": "show_dashboard",
    "audio": {
        "microphone_device_id": None,  # null = automatic (default device)
        "system_audio_device_id": None,  # null = automatic (default output's loopback)
        "input_gain": 1.0,
        "output_gain": 1.0,
        "chunk_seconds": 25,
    },
    "transcription": {
        "hardware_mode": "automatic",
    },
    "ai": {
        "primary_provider": "groq",
        "fallback_provider": "gemini",
        # Groq has no stable "-latest" alias for chat models, so this is a
        # concrete model id that *can* go stale as Groq's catalog changes —
        # that's exactly why the AI connectivity probe (intelligence/
        # providers/groq_provider.py) checks the configured model against
        # the live model list and reports MODEL_NOT_FOUND distinctly rather
        # than only failing the first time a real meeting ends.
        "groq_model": "openai/gpt-oss-120b",
        # Gemini publishes a genuine rolling alias for this — prefer it over
        # a pinned version string, which is what went stale here originally.
        "gemini_model": "gemini-flash-latest",
    },
    "storage": {
        "retention_days": None,  # null = keep forever
    },
}

_lock = threading.Lock()


def _deep_merge(base: dict, override: dict) -> dict:
    result = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _load_config_unlocked() -> dict:
    path = config_path()
    if not path.exists():
        atomic_write_json(path, DEFAULT_CONFIG)
        return copy.deepcopy(DEFAULT_CONFIG)
    try:
        on_disk = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        on_disk = {}
    return _deep_merge(DEFAULT_CONFIG, on_disk)


def load_config() -> dict:
    with _lock:
        return _load_config_unlocked()


def save_config(patch: dict) -> dict:
    with _lock:
        current = _load_config_unlocked()
        merged = _deep_merge(current, patch)
        atomic_write_json(config_path(), merged)
        return merged
