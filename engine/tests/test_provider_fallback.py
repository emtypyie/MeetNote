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


def test_both_configured_gemini_is_primary_and_succeeds():
    gemini = FakeProvider("gemini")
    groq = FakeProvider("groq")
    router = AIRouter(gemini=gemini, groq=groq)

    result = router.complete("sys", "user")

    assert result.provider_name == "gemini"
    assert groq.calls == 0
    assert router.last_provider_used == "gemini"


def test_gemini_fails_falls_back_to_groq():
    gemini = FakeProvider("gemini", fail_times=99)
    groq = FakeProvider("groq")
    router = AIRouter(gemini=gemini, groq=groq)

    result = router.complete("sys", "user")

    assert result.provider_name == "groq"
    assert router.last_provider_used == "groq"


def test_gemini_unconfigured_skips_straight_to_groq():
    gemini = FakeProvider("gemini", configured=False)
    groq = FakeProvider("groq")
    router = AIRouter(gemini=gemini, groq=groq)

    result = router.complete("sys", "user")

    assert result.provider_name == "groq"
    assert gemini.calls == 0


def test_groq_only_succeeds():
    gemini = FakeProvider("gemini", configured=False)
    groq = FakeProvider("groq", configured=True)
    router = AIRouter(gemini=gemini, groq=groq)

    result = router.complete("sys", "user")
    assert result.provider_name == "groq"


def test_gemini_only_succeeds():
    gemini = FakeProvider("gemini", configured=True)
    groq = FakeProvider("groq", configured=False)
    router = AIRouter(gemini=gemini, groq=groq)

    result = router.complete("sys", "user")
    assert result.provider_name == "gemini"


def test_both_providers_failing_raises():
    gemini = FakeProvider("gemini", fail_times=99)
    groq = FakeProvider("groq", fail_times=99)
    router = AIRouter(gemini=gemini, groq=groq)

    try:
        router.complete("sys", "user")
        assert False, "expected AllProvidersFailedError"
    except AllProvidersFailedError as exc:
        assert "gemini" in exc.attempts
        assert "groq" in exc.attempts


def test_neither_configured_raises():
    gemini = FakeProvider("gemini", configured=False)
    groq = FakeProvider("groq", configured=False)
    router = AIRouter(gemini=gemini, groq=groq)

    try:
        router.complete("sys", "user")
        assert False, "expected AllProvidersFailedError"
    except AllProvidersFailedError as exc:
        pass


def test_non_retryable_failure_does_not_retry_same_provider():
    gemini = FakeProvider("gemini", fail_times=1, retryable=False)
    groq = FakeProvider("groq")
    router = AIRouter(gemini=gemini, groq=groq)

    router.complete("sys", "user")

    # non-retryable -> exactly one call attempted before falling back
    assert gemini.calls == 1


class ProbingFakeProvider(FakeProvider):
    def __init__(self, name: str, configured: bool, probe_result):
        super().__init__(name, configured=configured)
        self.probe_result = probe_result
        self.probe_calls = 0

    def _probe_connection(self):
        self.probe_calls += 1
        return self.probe_result


def test_unconfigured_provider_status_is_not_configured_without_probing():
    gemini = ProbingFakeProvider("gemini", configured=False, probe_result=(ConnectivityStatus.CONFIGURED, None))
    groq = ProbingFakeProvider("groq", configured=False, probe_result=(ConnectivityStatus.CONFIGURED, None))
    router = AIRouter(gemini=gemini, groq=groq)

    status = router.status()

    assert status["gemini"]["status"] == ConnectivityStatus.NOT_CONFIGURED.value
    assert status["gemini"]["configured"] is False
    # test_connection() short-circuits before ever calling _probe_connection
    # for an unconfigured provider — there's no key to test.
    router.refresh_connectivity()
    assert gemini.probe_calls == 0


def test_configured_but_invalid_key_reports_auth_failed_not_unconfigured():
    gemini = ProbingFakeProvider(
        "gemini", configured=True, probe_result=(ConnectivityStatus.AUTH_FAILED, "invalid api key")
    )
    groq = ProbingFakeProvider("groq", configured=False, probe_result=(ConnectivityStatus.CONFIGURED, None))
    router = AIRouter(gemini=gemini, groq=groq)

    router.refresh_connectivity()
    status = router.status()

    assert status["gemini"]["configured"] is True
    assert status["gemini"]["status"] == ConnectivityStatus.AUTH_FAILED.value
    assert status["gemini"]["error"] == "invalid api key"


def test_configured_and_working_key_reports_configured():
    gemini = ProbingFakeProvider("gemini", configured=True, probe_result=(ConnectivityStatus.CONFIGURED, None))
    groq = ProbingFakeProvider("groq", configured=True, probe_result=(ConnectivityStatus.CONFIGURED, None))
    router = AIRouter(gemini=gemini, groq=groq)

    router.refresh_connectivity()
    status = router.status()

    assert status["gemini"]["status"] == ConnectivityStatus.CONFIGURED.value
    assert status["groq"]["status"] == ConnectivityStatus.CONFIGURED.value


def test_provider_that_raises_during_probe_reports_unavailable_not_a_crash():
    class ExplodingProvider(FakeProvider):
        def _probe_connection(self):
            raise RuntimeError("boom")

    gemini = ExplodingProvider("gemini", configured=True)
    groq = FakeProvider("groq", configured=False)
    router = AIRouter(gemini=gemini, groq=groq)

    router.refresh_connectivity()
    status = router.status()
    assert status["gemini"]["status"] == ConnectivityStatus.UNAVAILABLE.value
