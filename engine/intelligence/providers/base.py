"""LLMProvider interface + request-level retry/fallback.

    LLMProvider
    ├── GroqProvider   (primary)
    └── GeminiProvider (fallback)

Groq is never hard-wired into the rest of the app — everything above this
layer talks to `AIRouter` (router.py), which tries providers in order and
falls back *per request*, not by switching the whole system to "Gemini
mode" for the rest of the meeting.
"""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger("meetnote.ai")


class ConnectivityStatus(str, Enum):
    """Distinguishes *why* a provider isn't usable right now, so the UI never
    has to collapse "no key was ever given" and "the key is wrong" and "Groq
    is down for a minute" into one misleading "Not configured" label.
    """

    NOT_CONFIGURED = "not_configured"  # no API key present at all
    CHECKING = "checking"  # a background connectivity check is in flight
    CONFIGURED = "configured"  # key present and confirmed to work
    AUTH_FAILED = "auth_failed"  # key present but the provider rejected it
    UNAVAILABLE = "unavailable"  # key present, provider unreachable/erroring right now
    MODEL_NOT_FOUND = "model_not_found"  # key works, but the configured model id doesn't exist for it
    UNKNOWN = "unknown"  # key present, never actually checked yet


class ProviderError(Exception):
    """Raised by a provider when a request fails.

    `retryable` distinguishes transient failures (timeout, rate limit,
    5xx, network blip) — worth retrying against the *same* provider a
    couple of times before falling back — from failures that retrying
    won't fix (bad API key, invalid request), which should fall back
    immediately.
    """

    def __init__(self, message: str, retryable: bool):
        super().__init__(message)
        self.retryable = retryable


@dataclass
class CompletionResult:
    text: str
    provider_name: str


class LLMProvider(ABC):
    name: str

    @abstractmethod
    def is_configured(self) -> bool:
        """True if an API key is present. Does not guarantee reachability —
        that's only known after an actual call succeeds or fails."""

    @abstractmethod
    def _call(self, system_prompt: str, user_prompt: str, json_mode: bool) -> str:
        """One raw request. Must raise ProviderError on any failure."""

    @abstractmethod
    def _probe_connection(self) -> tuple[ConnectivityStatus, "str | None"]:
        """A cheap, read-only live call (e.g. listing models — never a full
        completion) that actually exercises the API key, so a wrong/expired
        key is reported as such instead of as "not configured". Must catch
        everything itself and never raise — connectivity checks run in a
        background thread and must never be able to take the engine down.
        """

    def test_connection(self) -> tuple[ConnectivityStatus, "str | None"]:
        if not self.is_configured():
            return ConnectivityStatus.NOT_CONFIGURED, None
        try:
            return self._probe_connection()
        except Exception as exc:  # belt-and-suspenders: _probe_connection must not raise, but never trust that
            logger.exception("%s connectivity probe raised unexpectedly", self.name)
            return ConnectivityStatus.UNAVAILABLE, str(exc)

    def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        json_mode: bool = False,
        max_retries: int = 2,
    ) -> CompletionResult:
        last_error: Exception | None = None
        backoff = 1.0
        for attempt in range(max_retries + 1):
            try:
                text = self._call(system_prompt, user_prompt, json_mode)
                return CompletionResult(text=text, provider_name=self.name)
            except ProviderError as exc:
                last_error = exc
                logger.warning(
                    "%s request failed (attempt %d/%d, retryable=%s): %s",
                    self.name,
                    attempt + 1,
                    max_retries + 1,
                    exc.retryable,
                    exc,
                )
                if not exc.retryable or attempt == max_retries:
                    break
                time.sleep(backoff)
                backoff *= 2
        assert last_error is not None
        raise last_error
