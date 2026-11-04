"""Rate-limit retry wrapper: 429s are retried, other errors are not."""

import asyncio
import time

import pytest

from src.rate_limit_retry import RateLimitRetryClient, _retry_after


class Fake429(Exception):
    status_code = 429

    def __init__(self, message: str = "rate_limit_exceeded"):
        super().__init__(message)
        self.response = None


class Fake500(Exception):
    status_code = 500


class FakeClient:
    def __init__(self, fail_times: int, error: type[Exception] = Fake429):
        self.calls = 0
        self.fail_times = fail_times
        self.error = error

    async def create(self, messages):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise self.error("upstream blew up" if self.error is Fake500 else "rate_limit_exceeded")
        return f"ok after {self.calls} calls"

    @property
    def model_info(self):
        return {"function_calling": True}


def test_retry_after_from_groq_message():
    msg = "Rate limit reached. Please try again in 1.319999999s."
    assert _retry_after(Exception(msg)) == pytest.approx(1.32)


def test_retry_after_from_header():
    class Resp:
        headers = {"Retry-After": "3"}

    exc = Fake429()
    exc.response = Resp()
    assert _retry_after(exc) == 3.0


def test_429_is_retried_and_succeeds():
    inner = FakeClient(fail_times=2)
    client = RateLimitRetryClient(inner, max_retries=4, base_delay=0.01)
    result = asyncio.run(client.create([]))
    assert result == "ok after 3 calls"
    assert inner.calls == 3


def test_non_rate_limit_error_propagates_immediately():
    inner = FakeClient(fail_times=10, error=Fake500)
    client = RateLimitRetryClient(inner, max_retries=3, base_delay=0.01)
    with pytest.raises(Fake500):
        asyncio.run(client.create([]))
    assert inner.calls == 1


def test_retries_are_exhausted_then_raised():
    inner = FakeClient(fail_times=10)
    client = RateLimitRetryClient(inner, max_retries=3, base_delay=0.01)
    with pytest.raises(Fake429):
        asyncio.run(client.create([]))
    assert inner.calls == 3


def test_backoff_is_bounded():
    inner = FakeClient(fail_times=1)
    client = RateLimitRetryClient(inner, max_retries=2, base_delay=0.01)
    start = time.time()
    asyncio.run(client.create([]))
    assert time.time() - start < 1.0
