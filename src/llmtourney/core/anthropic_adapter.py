"""Anthropic API adapter for Claude models.

Handles extended thinking blocks: extracts thinking content as reasoning_text,
text content as raw_text.
"""

import time
from typing import Any

from llmtourney.core.adapter import AdapterError, AdapterResponse, ModelAdapter

try:
    from anthropic import Anthropic
    import anthropic as _anthropic_module
except ImportError:
    Anthropic = None
    _anthropic_module = None

_RATE_LIMIT_BACKOFF_S = 5.0


class AnthropicAdapter(ModelAdapter):
    """Adapter for the Anthropic Messages API."""

    def __init__(
        self,
        model_id: str,
        api_key: str,
        temperature: float = 0.0,
    ):
        if Anthropic is None:
            raise ImportError(
                "anthropic package required: pip install llmtourney[live]"
            )
        self._model_id = model_id
        self._temperature = temperature
        self._client = Anthropic(api_key=api_key)

    def query(
        self,
        messages: list[dict[str, str]],
        max_tokens: int,
        timeout_s: float,
        context: dict[str, Any] | None = None,
    ) -> AdapterResponse:
        start = time.monotonic()
        msg = self._call_api(messages, max_tokens, timeout_s)
        elapsed_ms = (time.monotonic() - start) * 1000

        raw_text = ""
        reasoning_text = None
        for block in msg.content:
            if block.type == "thinking":
                reasoning_text = block.thinking
            elif block.type == "text":
                raw_text = block.text

        return AdapterResponse(
            raw_text=raw_text,
            reasoning_text=reasoning_text,
            input_tokens=msg.usage.input_tokens,
            output_tokens=msg.usage.output_tokens,
            latency_ms=elapsed_ms,
            model_id=self._model_id,
            model_version=msg.model,
        )

    def _call_api(self, messages, max_tokens, timeout_s):
        """Call the API with one rate-limit retry."""
        for attempt in range(2):
            try:
                return self._client.messages.create(
                    model=self._model_id,
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=self._temperature,
                    timeout=timeout_s,
                )
            except _anthropic_module.APITimeoutError as e:
                raise AdapterError("timeout", self._model_id, str(e)) from e
            except _anthropic_module.RateLimitError as e:
                if attempt == 0:
                    time.sleep(_RATE_LIMIT_BACKOFF_S)
                    continue
                raise AdapterError("rate_limit", self._model_id, str(e)) from e
            except _anthropic_module.APIError as e:
                raise AdapterError("api_error", self._model_id, str(e)) from e
            except Exception as e:
                raise AdapterError("api_error", self._model_id, str(e)) from e
        raise AdapterError("api_error", self._model_id, "max retries exceeded")
