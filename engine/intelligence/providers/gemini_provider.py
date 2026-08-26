from __future__ import annotations

import os

from intelligence.providers.base import ConnectivityStatus, LLMProvider, ProviderError


class GeminiProvider(LLMProvider):
    name = "gemini"

    def __init__(self, model: str = "gemini-1.5-flash"):
        self.model_name = model
        self._api_key = os.environ.get("GEMINI_API_KEY", "").strip()
        self._configured = False

    def is_configured(self) -> bool:
        return bool(self._api_key)

    def _ensure_configured(self):
        import google.generativeai as genai

        if not self._configured:
            genai.configure(api_key=self._api_key)
            self._configured = True
        return genai

    def _call(self, system_prompt: str, user_prompt: str, json_mode: bool) -> str:
        if not self.is_configured():
            raise ProviderError("GEMINI_API_KEY is not set", retryable=False)

        from google.api_core.exceptions import (
            DeadlineExceeded,
            GoogleAPICallError,
            InternalServerError,
            ResourceExhausted,
            ServiceUnavailable,
        )

        try:
            genai = self._ensure_configured()
            model = genai.GenerativeModel(self.model_name, system_instruction=system_prompt)
            generation_config = {"temperature": 0.2}
            if json_mode:
                generation_config["response_mime_type"] = "application/json"
            response = model.generate_content(
                user_prompt,
                generation_config=generation_config,
                request_options={"timeout": 45},
            )
            text = getattr(response, "text", None)
            if not text or not text.strip():
                raise ProviderError("Gemini returned an empty response", retryable=True)
            return text
        except (DeadlineExceeded, ServiceUnavailable, InternalServerError, ResourceExhausted) as exc:
            raise ProviderError(f"Gemini transient failure: {exc}", retryable=True) from exc
        except GoogleAPICallError as exc:
            raise ProviderError(f"Gemini API error: {exc}", retryable=False) from exc
        except ProviderError:
            raise
        except Exception as exc:
            raise ProviderError(f"Gemini request failed: {exc}", retryable=True) from exc

    def _probe_connection(self) -> tuple[ConnectivityStatus, "str | None"]:
        """Lists models — a cheap, read-only call that exercises the API key
        without spending generation tokens."""
        from google.api_core.exceptions import (
            GoogleAPICallError,
            PermissionDenied,
            Unauthenticated,
        )

        try:
            genai = self._ensure_configured()
            models = list(genai.list_models())
            configured_name = self.model_name if self.model_name.startswith("models/") else f"models/{self.model_name}"
            supports_generate = {
                m.name for m in models if "generateContent" in getattr(m, "supported_generation_methods", [])
            }
            if configured_name not in supports_generate:
                sample = ", ".join(sorted(n.removeprefix("models/") for n in supports_generate)[:6])
                return (
                    ConnectivityStatus.MODEL_NOT_FOUND,
                    f"Configured model '{self.model_name}' not found for this key. Available models "
                    f"include: {sample}",
                )
            return ConnectivityStatus.CONFIGURED, None
        except (Unauthenticated, PermissionDenied) as exc:
            return ConnectivityStatus.AUTH_FAILED, str(exc)
        except GoogleAPICallError as exc:
            return ConnectivityStatus.UNAVAILABLE, str(exc)
        except Exception as exc:  # pragma: no cover - defensive catch-all
            # The SDK raises plain ValueError for a malformed/invalid key
            # before it ever reaches the network — treat that as an auth
            # failure rather than a generic outage.
            message = str(exc)
            if "API key not valid" in message or "API_KEY_INVALID" in message:
                return ConnectivityStatus.AUTH_FAILED, message
            return ConnectivityStatus.UNAVAILABLE, message
