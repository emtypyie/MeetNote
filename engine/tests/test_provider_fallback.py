from intelligence.providers.base import ConnectivityStatus, CompletionResult, LLMProvider, ProviderError
from intelligence.router import AIRouter, AllProvidersFailedError


class FakeProvider(LLMProvider):
    def __init__(self, name: str, configured: bool = True, fail_times: int = 0, retryable: bool = True):
        self.name = name
        self._configured = configured
        self.fail_times = fail_times
        self.retryable = retryable
        self.calls = 0

    def is_configured(self) -> bool:
        return self._configured

    def _call(self, system_prompt: str, user_prompt: str, json_mode: bool) -> str:
        self.calls += 1
        if self.calls <= self.fail_times:
            raise ProviderError(f"{self.name} simulated failure", retryable=self.retryable)
        return f"response from {self.name}"

    def _probe_connection(self):
        return ConnectivityStatus.CONFIGURED, None


def test_primary_success_no_fallback_used():
    primary = FakeProvider("groq")
    fallback = FakeProvider("gemini")
    router = AIRouter(primary, fallback)

    result = router.complete("sys", "user")

    assert result.provider_name == "groq"
    assert fallback.calls == 0
    assert router.last_provider_used == "groq"


def test_primary_fails_falls_back_to_secondary():
    # Fails more times than complete()'s internal retry budget, so it must
    # exhaust the primary and fall through to the fallback provider.
    primary = FakeProvider("groq", fail_times=99)
    fallback = FakeProvider("gemini")
    router = AIRouter(primary, fallback)

    result = router.complete("sys", "user")

    assert result.provider_name == "gemini"
    assert router.last_provider_used == "gemini"


def test_unconfigured_primary_skips_straight_to_fallback():
    primary = FakeProvider("groq", configured=False)
    fallback = FakeProvider("gemini")
    router = AIRouter(primary, fallback)

    result = router.complete("sys", "user")

    assert result.provider_name == "gemini"
    assert primary.calls == 0


def test_both_providers_failing_raises():
    primary = FakeProvider("groq", fail_times=99)
    fallback = FakeProvider("gemini", fail_times=99)
    router = AIRouter(primary, fallback)

    try:
        router.complete("sys", "user")
        assert False, "expected AllProvidersFailedError"
    except AllProvidersFailedError as exc:
        assert "groq" in exc.attempts
        assert "gemini" in exc.attempts


def test_non_retryable_failure_does_not_retry_same_provider():
    primary = FakeProvider("groq", fail_times=1, retryable=False)
    fallback = FakeProvider("gemini")
    router = AIRouter(primary, fallback)

    router.complete("sys", "user")

    # non-retryable -> exactly one call attempted before falling back
    assert primary.calls == 1


class ProbingFakeProvider(FakeProvider):
    """A FakeProvider whose connectivity probe result is controllable, to
    test AIRouter's connectivity-status handling distinctly from its
    request-fallback handling above."""

    def __init__(self, name: str, configured: bool, probe_result):
        super().__init__(name, configured=configured)
        self.probe_result = probe_result
        self.probe_calls = 0

    def _probe_connection(self):
        self.probe_calls += 1
        return self.probe_result


def test_unconfigured_provider_status_is_not_configured_without_probing():
    primary = ProbingFakeProvider("groq", configured=False, probe_result=(ConnectivityStatus.CONFIGURED, None))
    fallback = ProbingFakeProvider("gemini", configured=False, probe_result=(ConnectivityStatus.CONFIGURED, None))
    router = AIRouter(primary, fallback)

    status = router.status()

    assert status["primary"]["status"] == ConnectivityStatus.NOT_CONFIGURED.value
    assert status["primary"]["configured"] is False
    # test_connection() short-circuits before ever calling _probe_connection
    # for an unconfigured provider — there's no key to test.
    router.refresh_connectivity()
    assert primary.probe_calls == 0


def test_configured_but_invalid_key_reports_auth_failed_not_unconfigured():
    primary = ProbingFakeProvider(
        "groq", configured=True, probe_result=(ConnectivityStatus.AUTH_FAILED, "invalid api key")
    )
    fallback = ProbingFakeProvider("gemini", configured=False, probe_result=(ConnectivityStatus.CONFIGURED, None))
    router = AIRouter(primary, fallback)

    router.refresh_connectivity()
    status = router.status()

    assert status["primary"]["configured"] is True
    assert status["primary"]["status"] == ConnectivityStatus.AUTH_FAILED.value
    assert status["primary"]["error"] == "invalid api key"


def test_configured_and_working_key_reports_configured():
    primary = ProbingFakeProvider("groq", configured=True, probe_result=(ConnectivityStatus.CONFIGURED, None))
    fallback = ProbingFakeProvider("gemini", configured=True, probe_result=(ConnectivityStatus.CONFIGURED, None))
    router = AIRouter(primary, fallback)

    router.refresh_connectivity()
    status = router.status()

    assert status["primary"]["status"] == ConnectivityStatus.CONFIGURED.value
    assert status["fallback"]["status"] == ConnectivityStatus.CONFIGURED.value


def test_provider_that_raises_during_probe_reports_unavailable_not_a_crash():
    class ExplodingProvider(FakeProvider):
        def _probe_connection(self):
            raise RuntimeError("boom")

    primary = ExplodingProvider("groq", configured=True)
    fallback = FakeProvider("gemini", configured=False)
    router = AIRouter(primary, fallback)

    # Must not raise — a broken/crashing probe must degrade to UNAVAILABLE,
    # never take the caller (and by extension the engine) down with it.
    router.refresh_connectivity()
    status = router.status()
    assert status["primary"]["status"] == ConnectivityStatus.UNAVAILABLE.value
