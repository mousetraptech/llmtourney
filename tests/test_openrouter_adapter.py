"""Tests for OpenRouterAdapter -- thin wrapper over OpenAIAdapter."""

from unittest.mock import MagicMock, patch

import pytest

from llmtourney.core.adapter import AdapterResponse
from llmtourney.core.openrouter_adapter import OpenRouterAdapter


class TestOpenRouterAdapter:
    @patch("llmtourney.core.openai_adapter.OpenAI")
    def test_uses_openrouter_base_url(self, MockOpenAI):
        OpenRouterAdapter(
            model_id="deepseek/deepseek-r1",
            api_key="test-key",
        )
        call_kwargs = MockOpenAI.call_args[1]
        assert call_kwargs["base_url"] == "https://openrouter.ai/api/v1"

    @patch("llmtourney.core.openai_adapter.OpenAI")
    def test_sets_attribution_headers(self, MockOpenAI):
        OpenRouterAdapter(
            model_id="deepseek/deepseek-r1",
            api_key="test-key",
            site_url="https://example.com",
            app_name="llmtourney",
        )
        call_kwargs = MockOpenAI.call_args[1]
        headers = call_kwargs.get("default_headers", {})
        assert headers.get("HTTP-Referer") == "https://example.com"
        assert headers.get("X-Title") == "llmtourney"

    @patch("llmtourney.core.openai_adapter.OpenAI")
    def test_query_delegates_to_parent(self, MockOpenAI):
        client = MockOpenAI.return_value
        choice = MagicMock()
        choice.message.content = '{"action": "call"}'
        choice.message.reasoning_content = None
        usage = MagicMock()
        usage.prompt_tokens = 20
        usage.completion_tokens = 5
        completion = MagicMock()
        completion.choices = [choice]
        completion.usage = usage
        completion.model = "deepseek/deepseek-r1"
        client.chat.completions.create.return_value = completion

        adapter = OpenRouterAdapter(
            model_id="deepseek/deepseek-r1",
            api_key="test-key",
        )
        resp = adapter.query(
            messages=[{"role": "user", "content": "go"}],
            max_tokens=256,
            timeout_s=30.0,
        )

        assert resp.raw_text == '{"action": "call"}'
        assert resp.model_id == "deepseek/deepseek-r1"
        assert isinstance(resp, AdapterResponse)

    @patch("llmtourney.core.openai_adapter.OpenAI")
    def test_default_headers_without_attribution(self, MockOpenAI):
        """Without site_url/app_name, no extra headers."""
        OpenRouterAdapter(
            model_id="test/model",
            api_key="test-key",
        )
        call_kwargs = MockOpenAI.call_args[1]
        headers = call_kwargs.get("default_headers", {})
        assert "HTTP-Referer" not in headers
        assert "X-Title" not in headers
