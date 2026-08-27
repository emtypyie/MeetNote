"""AIRouter — tries the primary provider, falls back to the secondary one,
at the granularity of a single request (one analysis call, one notes-
generation call, one rewrite pass), never by switching the whole meeting or
app to "Gemini mode" for everything that follows.
"""

from __future__ import annotations

import logging
import threading

from intelligence.providers.base import CompletionResult, ConnectivityStatus, LLMProvider, ProviderError

logger = logging.getLogger("meetnote.ai")


class AllProvidersFailedError(Exception):
    def __init__(self, attempts: dict[str, str]):
        self.attempts = attempts
        detail = "; ".join(f"{name}: {err}" for name, err in attempts.items())
        super().__init__(f"All AI providers failed — {detail}")


class AIRouter:
    def __init__(self, gemini: LLMProvider, groq: LLMProvider):
        self.gemini = gemini
        self.groq = groq
        self.last_provider_used: str | None = None
        self._lock = threading.Lock()
        # Seeded synchronously from is_configured() so /health never has to
        # lie and say "checking" forever if a background refresh is slow to
        # start — it's upgraded to a real CONFIGURED/AUTH_FAILED/UNAVAILABLE
        # result once refresh_connectivity() has actually run once.
        self._connectivity: dict[str, tuple[ConnectivityStatus, str | None]] = {
            gemini.name: (
                ConnectivityStatus.UNKNOWN if gemini.is_configured() else ConnectivityStatus.NOT_CONFIGURED,
                None,
            ),
            groq.name: (
                ConnectivityStatus.UNKNOWN if groq.is_configured() else ConnectivityStatus.NOT_CONFIGURED,
                None,
            ),
        }

    def refresh_connectivity(self) -> None:
        """Runs each configured provider's cheap live connectivity probe.
        Safe to call from a background thread — provider probes never raise
        (see LLMProvider.test_connection) — and safe to call repeatedly
        (e.g. from a manual "Recheck" action after the user edits .env and
        restarts, or periodically)."""
        for provider in (self.gemini, self.groq):
            with self._lock:
                current_status, _ = self._connectivity[provider.name]
                self._connectivity[provider.name] = (ConnectivityStatus.CHECKING, None)
            status, error = provider.test_connection()
            with self._lock:
                self._connectivity[provider.name] = (status, error)
            logger.info("%s connectivity: %s%s", provider.name, status.value, f" ({error})" if error else "")

    def _is_usable(self, provider: LLMProvider) -> bool:
        if not provider.is_configured():
            return False
        with self._lock:
            status, _ = self._connectivity[provider.name]
        return status in (
            ConnectivityStatus.CONFIGURED,
            ConnectivityStatus.UNKNOWN,
            ConnectivityStatus.CHECKING,
        )

    def _get_active_providers(self) -> tuple[LLMProvider | None, LLMProvider | None]:
        gemini_usable = self._is_usable(self.gemini)
        groq_usable = self._is_usable(self.groq)
        
        if gemini_usable and groq_usable:
            return self.gemini, self.groq
        elif gemini_usable:
            return self.gemini, None
        elif groq_usable:
            return self.groq, None
        return None, None

    def _provider_status(self, provider: LLMProvider) -> dict:
        with self._lock:
            status, error = self._connectivity[provider.name]
        return {
            "name": provider.name,
            "configured": provider.is_configured(),
            "status": status.value,
            "error": error,
        }

    def status(self) -> dict:
        primary, fallback = self._get_active_providers()
        return {
            "gemini": self._provider_status(self.gemini),
            "groq": self._provider_status(self.groq),
            "primary": primary.name if primary else None,
            "fallback": fallback.name if fallback else None,
        }

    def complete(self, system_prompt: str, user_prompt: str, json_mode: bool = False) -> CompletionResult:
        primary, fallback = self._get_active_providers()
        
        active_providers = []
        if primary: active_providers.append(primary)
        if fallback: active_providers.append(fallback)
        
        if not active_providers:
            raise AllProvidersFailedError({"router": "No AI providers configured or available"})

        attempts: dict[str, str] = {}

        for provider in active_providers:
            try:
                result = provider.complete(system_prompt, user_prompt, json_mode=json_mode)
                self.last_provider_used = provider.name
                if provider is fallback:
                    logger.info("Request served by fallback provider (%s)", provider.name)
                return result
            except ProviderError as exc:
                attempts[provider.name] = str(exc)
                logger.error("%s exhausted retries: %s", provider.name, exc)

        raise AllProvidersFailedError(attempts)
