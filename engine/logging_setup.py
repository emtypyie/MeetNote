"""Structured logging, kept separate from meeting transcript data on disk
(product spec section 27): everything here goes to storage/logs/engine.log,
never into a meeting's own folder. Application code must never log full
transcript text or API keys — only chunk indices, error messages and
metadata are logged; see transcription/pipeline.py and
intelligence/providers/*.py for the call sites this matters at.
"""

from __future__ import annotations

import logging
import logging.handlers

from storage.paths import logs_dir


def setup_logging(level: int = logging.INFO) -> None:
    logs_dir().mkdir(parents=True, exist_ok=True)
    log_path = logs_dir() / "engine.log"

    formatter = logging.Formatter(
        fmt="%(asctime)s %(levelname)-8s %(name)s: %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )

    file_handler = logging.handlers.RotatingFileHandler(
        log_path, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(level)
    root.addHandler(file_handler)
    root.addHandler(console_handler)

    # Quiet down noisy third-party loggers so engine.log stays readable.
    for noisy in ("uvicorn.access", "httpx", "httpcore", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
