"""OpenAI-compatible adapter.

Works with OpenAI API (GPT-4o, o1, o3) and any OpenAI-compatible
endpoint (OpenRouter, local models) via base_url override.
"""

import time
from typing import Any

from llmtourney.core.adapter import AdapterError, AdapterResponse, ModelAdapter

try:
    from openai import OpenAI
    import openai as _openai_module
except ImportError:
    OpenAI = None
    _openai_module = None

_RATE_LIMIT_BACKOFF_S = 5.0


class OpenAIAdapter(ModelAdapter):
    """Adapter for OpenAI-compatible APIs."""

    def __init__(
        self,
        model_id: str,
        api_key: str,
        base_url: str | None = None,
        temperature: float = 0.0,
        extra_headers: dict[str, str] | None = None,
    ):
        if OpenAI is None:
            raise ImportError(
                "openai package required: pip install llmtourney[live]"
            )
        self._model_id = model_id
        self._temperature = temperature

        client_kwargs: dict[str, Any] = {"api_key": api_key}
        if base_url:
            client_kwargs["base_url"] = base_url
        if extra_headers:
            client_kwargs["default_headers"] = extra_headers
        self._client = OpenAI(**client_kwargs)

    def query(
        self,
        messages: list[dict[str, str]],
        max_tokens: int,
        timeout_s: float,
        context: dict[str, Any] | None = None,
    ) -> AdapterResponse:
        start = time.monotonic()
        completion = self._call_api(messages, max_tokens, timeout_s)
        elapsed_ms = (time.monotonic() - start) * 1000

        choice = completion.choices[0]
        raw_text = choice.message.content or ""
        reasoning_text = getattr(choice.message, "reasoning_content", None)

        return AdapterResponse(
            raw_text=raw_text,
            reasoning_text=reasoning_text,
            input_tokens=completion.usage.prompt_tokens,
            output_tokens=completion.usage.completion_tokens,
            latency_ms=elapsed_ms,
            model_id=self._model_id,
            model_version=completion.model,
        )

    def _call_api(self, messages, max_tokens, timeout_s):
        """Call the API with one rate-limit retry."""
        for attempt in range(2):
            try:
                return self._client.chat.completions.create(
                    model=self._model_id,
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=self._temperature,
                    timeout=timeout_s,
                )
            except _openai_module.APITimeoutError as e:
                raise AdapterError("timeout", self._model_id, str(e)) from e
            except _openai_module.RateLimitError as e:
                if attempt == 0:
                    time.sleep(_RATE_LIMIT_BACKOFF_S)
                    continue
                raise AdapterError("rate_limit", self._model_id, str(e)) from e
            except _openai_module.APIError as e:
                raise AdapterError("api_error", self._model_id, str(e)) from e
            except Exception as e:
                raise AdapterError("api_error", self._model_id, str(e)) from e
        raise AdapterError("api_error", self._model_id, "max retries exceeded")
