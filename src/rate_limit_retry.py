"""Retry wrapper for rate-limited providers.

Groq's free tier caps every model at 8000 tokens/minute. A multi-agent
pipeline that streams several turns a minute hits `429 rate_limit_exceeded`
even with a perfectly valid key, and AutoGen surfaces it as a group-chat
error that kills the run.

:class:`RateLimitRetryClient` sits in front of a ChatCompletionClient and
retries 429s with backoff, honouring the server's `Retry-After` header when
present.
"""

from __future__ import annotations

import logging
import time
from typing import Any, AsyncGenerator, Optional

from autogen_core.models import CreateResult

logger = logging.getLogger(__name__)


def _retry_after(exc: Exception) -> Optional[float]:
    """Pull Retry-After (or Groq's 'try again in N seconds') out of the error."""
    headers = getattr(getattr(exc, "response", None), "headers", None)
    if headers:
        try:
            value = headers.get("retry-after") or headers.get("Retry-After")
            if value:
                return float(value)
        except (TypeError, ValueError):
            pass
    text = str(exc)
    marker = "try again in "
    if marker in text:
        rest = text.split(marker, 1)[1]
        number = ""
        for ch in rest:
            if ch.isdigit() or ch == ".":
                number += ch
            else:
                break
        if number:
            return float(number)
    return None


class RateLimitRetryClient:
    """ChatCompletionClient wrapper that backs off on 429s.

    Only ``create`` / ``create_stream`` are intercepted; everything else is
    delegated to the wrapped client.
    """

    def __init__(self, inner, max_retries: int = 5, base_delay: float = 5.0):
        self._inner = inner
        self._max_retries = max_retries
        self._base_delay = base_delay

    @property
    def model_info(self) -> dict[str, Any]:
        return self._inner.model_info

    def _sleep(self, attempt: int, exc: Exception) -> None:
        delay = _retry_after(exc)
        if delay is None:
            delay = min(self._base_delay * (2 ** (attempt - 1)), 60.0)
        logger.warning(
            "Rate limited (attempt %d/%d): sleeping %.1f s before retrying.",
            attempt,
            self._max_retries,
            delay,
        )
        time.sleep(delay)

    async def create(self, *args: Any, **kwargs: Any) -> CreateResult:
        for attempt in range(1, self._max_retries + 1):
            try:
                return await self._inner.create(*args, **kwargs)
            except Exception as exc:
                if not _is_rate_limit(exc) or attempt == self._max_retries:
                    raise
                self._sleep(attempt, exc)
        raise RuntimeError("unreachable")

    async def create_stream(self, *args: Any, **kwargs: Any) -> AsyncGenerator[Any, None]:
        for attempt in range(1, self._max_retries + 1):
            try:
                async for chunk in self._inner.create_stream(*args, **kwargs):
                    yield chunk
                return
            except Exception as exc:
                if not _is_rate_limit(exc) or attempt == self._max_retries:
                    raise
                self._sleep(attempt, exc)

    def __getattr__(self, name: str) -> Any:
        if name.startswith("__") and name.endswith("__"):
            raise AttributeError(name)
        return getattr(self._inner, name)


def _is_rate_limit(exc: Exception) -> bool:
    """True for 429s from the openai SDK or any HTTP-ish wrapper."""
    status = getattr(exc, "status_code", None)
    if status == 429:
        return True
    name = type(exc).__name__
    return name in ("RateLimitError", "TooManyRequests") or "rate_limit" in str(exc).lower()
