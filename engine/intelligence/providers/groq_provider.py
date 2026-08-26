from __future__ import annotations

import os

from intelligence.providers.base import ConnectivityStatus, LLMProvider, ProviderError


class GroqProvider(LLMProvider):
    name = "groq"

    def __init__(self, model: str = "llama-3.3-70b-versatile"):
        self.model = model
        self._api_key = os.environ.get("GROQ_API_KEY", "").strip()
        self._client = None

    def is_configured(self) -> bool:
        return bool(self._api_key)

    def _get_client(self):
        if self._client is None:
            from groq import Groq

            self._client = Groq(api_key=self._api_key)
        return self._client

    def _call(self, system_prompt: str, user_prompt: str, json_mode: bool) -> str:
        if not self.is_configured():
            raise ProviderError("GROQ_API_KEY is not set", retryable=False)

        from groq import APIConnectionError, APIStatusError, APITimeoutError, RateLimitError

        try:
            client = self._get_client()
            kwargs = {}
            if json_mode:
                kwargs["response_format"] = {"type": "json_object"}
            response = client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.2,
                timeout=45,
                **kwargs,
            )
            content = response.choices[0].message.content
            if not content or not content.strip():
                raise ProviderError("Groq returned an empty response", retryable=True)
            return content
        except (APITimeoutError, APIConnectionError, RateLimitError) as exc:
            raise ProviderError(f"Groq transient failure: {exc}", retryable=True) from exc
        except APIStatusError as exc:
            retryable = exc.status_code is not None and exc.status_code >= 500
            raise ProviderError(f"Groq API error ({exc.status_code}): {exc}", retryable=retryable) from exc
        except ProviderError:
            raise
        except Exception as exc:  # unexpected shape, malformed response, etc.
            raise ProviderError(f"Groq request failed: {exc}", retryable=True) from exc

    def _probe_connection(self) -> tuple[ConnectivityStatus, "str | None"]:
        """Lists models — a cheap, read-only call that exercises the API key
        without spending completion tokens — to tell "key is wrong" apart
        from "key was never set" and from "Groq is briefly unreachable"."""
        from groq import (
            APIConnectionError,
            AuthenticationError,
            GroqError,
            PermissionDeniedError,
            RateLimitError,
        )

        try:
            client = self._get_client()
            available = client.models.list()
            model_ids = {m.id for m in available.data}
            if self.model not in model_ids:
                sample = ", ".join(sorted(model_ids)[:6])
                return (
                    ConnectivityStatus.MODEL_NOT_FOUND,
                    f"Configured model '{self.model}' not found for this key. Available models "
                    f"include: {sample}",
                )
            return ConnectivityStatus.CONFIGURED, None
        except (AuthenticationError, PermissionDeniedError) as exc:
            return ConnectivityStatus.AUTH_FAILED, str(exc)
        except RateLimitError as exc:
            # A wrong key never gets far enough to be rate-limited — being
            # rate-limited confirms the key itself is valid.
            return ConnectivityStatus.CONFIGURED, str(exc)
        except (APIConnectionError, GroqError) as exc:
            return ConnectivityStatus.UNAVAILABLE, str(exc)
        except Exception as exc:  # pragma: no cover - defensive catch-all
            return ConnectivityStatus.UNAVAILABLE, str(exc)
