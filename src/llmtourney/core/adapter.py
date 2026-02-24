"""ModelAdapter — uniform interface for LLM API calls.

Provides ABC and concrete implementations:
- MockAdapter: deterministic, offline, for testing
- OpenAIAdapter / AnthropicAdapter: stubs for future live API use
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Callable
import time


class AdapterError(Exception):
    """Raised by adapters on API failures. Never let raw SDK exceptions propagate."""

    def __init__(
        self,
        error_type: str,
        model_id: str,
        details: str = "",
    ):
        self.error_type = error_type  # "timeout", "rate_limit", "api_error"
        self.model_id = model_id
        self.details = details
        super().__init__(f"{error_type} from {model_id}: {details}")


@dataclass(frozen=True)
class AdapterResponse:
    """Immutable response from a model query."""

    raw_text: str
    reasoning_text: str | None
    input_tokens: int
    output_tokens: int
    latency_ms: float
    model_id: str
    model_version: str


class ModelAdapter(ABC):
    """Abstract base for all model adapters."""

    @abstractmethod
    def query(
        self,
        messages: list[dict[str, str]],
        max_tokens: int,
        timeout_s: float,
        context: dict[str, Any] | None = None,
    ) -> AdapterResponse:
        """Send messages to the model and return its response."""


# Approximate chars per token for mock truncation
_CHARS_PER_TOKEN = 4


class MockAdapter(ModelAdapter):
    """Deterministic adapter for offline testing.

    Takes a strategy callable that receives (messages, context) and returns
    a raw text string.
    """

    def __init__(
        self,
        model_id: str,
        strategy: Callable[[list[dict[str, str]], dict[str, Any]], str],
    ):
        self._model_id = model_id
        self._strategy = strategy

    def query(
        self,
        messages: list[dict[str, str]],
        max_tokens: int,
        timeout_s: float,
        context: dict[str, Any] | None = None,
    ) -> AdapterResponse:
        start = time.monotonic()
        raw = self._strategy(messages, context or {})

        # Enforce token cap via character approximation
        max_chars = max_tokens * _CHARS_PER_TOKEN
        if len(raw) > max_chars:
            raw = raw[:max_chars]

        elapsed_ms = (time.monotonic() - start) * 1000

        return AdapterResponse(
            raw_text=raw,
            reasoning_text=None,
            input_tokens=0,
            output_tokens=max(1, len(raw) // _CHARS_PER_TOKEN),
            latency_ms=elapsed_ms,
            model_id=self._model_id,
            model_version=self._model_id,
        )
