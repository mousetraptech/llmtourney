"""Tests for AnthropicAdapter -- uses mocked SDK, no live API calls."""

from unittest.mock import MagicMock, patch

import pytest

from llmtourney.core.adapter import AdapterError, AdapterResponse
from llmtourney.core.anthropic_adapter import AnthropicAdapter


def _mock_message(
    text="",
    model="claude-sonnet-4-20250514",
    input_tokens=10,
    output_tokens=5,
    thinking_text=None,
):
    """Build a mock Anthropic Message response."""
    content_blocks = []
    if thinking_text:
        thinking_block = MagicMock()
        thinking_block.type = "thinking"
        thinking_block.thinking = thinking_text
        content_blocks.append(thinking_block)

    text_block = MagicMock()
    text_block.type = "text"
    text_block.text = text
    content_blocks.append(text_block)

    usage = MagicMock()
    usage.input_tokens = input_tokens
    usage.output_tokens = output_tokens

    msg = MagicMock()
    msg.content = content_blocks
    msg.model = model
    msg.usage = usage
    return msg


class TestAnthropicAdapterSuccess:
    @patch("llmtourney.core.anthropic_adapter.Anthropic")
    def test_basic_query(self, MockAnthropic):
        client = MockAnthropic.return_value
        client.messages.create.return_value = _mock_message(
            text='{"action": "fold"}',
            model="claude-sonnet-4-20250514",
            input_tokens=50,
            output_tokens=8,
        )

        adapter = AnthropicAdapter(model_id="claude-sonnet-4-20250514", api_key="test-key")
        resp = adapter.query(
            messages=[{"role": "user", "content": "Your turn"}],
            max_tokens=256,
            timeout_s=30.0,
        )

        assert resp.raw_text == '{"action": "fold"}'
        assert resp.model_id == "claude-sonnet-4-20250514"
        assert resp.model_version == "claude-sonnet-4-20250514"
        assert resp.input_tokens == 50
        assert resp.output_tokens == 8
        assert resp.reasoning_text is None
        assert isinstance(resp, AdapterResponse)

    @patch("llmtourney.core.anthropic_adapter.Anthropic")
    def test_thinking_text_extracted(self, MockAnthropic):
        client = MockAnthropic.return_value
        client.messages.create.return_value = _mock_message(
            text='{"action": "raise", "amount": 10}',
            thinking_text="The pot odds suggest a raise here...",
        )

        adapter = AnthropicAdapter(model_id="claude-opus-4-6", api_key="test-key")
        resp = adapter.query(
            messages=[{"role": "user", "content": "go"}],
            max_tokens=256,
            timeout_s=30.0,
        )

        assert resp.reasoning_text == "The pot odds suggest a raise here..."
        assert resp.raw_text == '{"action": "raise", "amount": 10}'

    @patch("llmtourney.core.anthropic_adapter.Anthropic")
    def test_passes_temperature(self, MockAnthropic):
        client = MockAnthropic.return_value
        client.messages.create.return_value = _mock_message(text='{"action": "fold"}')

        adapter = AnthropicAdapter(
            model_id="claude-sonnet-4-20250514", api_key="test-key", temperature=0.7
        )
        adapter.query(
            messages=[{"role": "user", "content": "go"}],
            max_tokens=256,
            timeout_s=30.0,
        )

        create_kwargs = client.messages.create.call_args[1]
        assert create_kwargs["temperature"] == 0.7


class TestAnthropicAdapterErrors:
    @patch("llmtourney.core.anthropic_adapter.Anthropic")
    def test_timeout_raises_adapter_error(self, MockAnthropic):
        import anthropic

        client = MockAnthropic.return_value
        client.messages.create.side_effect = anthropic.APITimeoutError(
            request=MagicMock()
        )

        adapter = AnthropicAdapter(model_id="claude-sonnet-4-20250514", api_key="test-key")
        with pytest.raises(AdapterError) as exc_info:
            adapter.query(
                messages=[{"role": "user", "content": "go"}],
                max_tokens=256,
                timeout_s=5.0,
            )
        assert exc_info.value.error_type == "timeout"

    @patch("llmtourney.core.anthropic_adapter.time.sleep")
    @patch("llmtourney.core.anthropic_adapter.Anthropic")
    def test_rate_limit_retries_then_raises(self, MockAnthropic, mock_sleep):
        import anthropic

        client = MockAnthropic.return_value

        resp_mock = MagicMock()
        resp_mock.status_code = 429
        resp_mock.headers = {}
        client.messages.create.side_effect = anthropic.RateLimitError(
            message="rate limited",
            response=resp_mock,
            body=None,
        )

        adapter = AnthropicAdapter(model_id="claude-sonnet-4-20250514", api_key="test-key")
        with pytest.raises(AdapterError) as exc_info:
            adapter.query(
                messages=[{"role": "user", "content": "go"}],
                max_tokens=256,
                timeout_s=30.0,
            )
        assert exc_info.value.error_type == "rate_limit"
        assert client.messages.create.call_count == 2

    @patch("llmtourney.core.anthropic_adapter.Anthropic")
    def test_generic_api_error_raises_adapter_error(self, MockAnthropic):
        import anthropic

        client = MockAnthropic.return_value
        client.messages.create.side_effect = anthropic.APIError(
            message="server error",
            request=MagicMock(),
            body=None,
        )

        adapter = AnthropicAdapter(model_id="claude-sonnet-4-20250514", api_key="test-key")
        with pytest.raises(AdapterError) as exc_info:
            adapter.query(
                messages=[{"role": "user", "content": "go"}],
                max_tokens=256,
                timeout_s=30.0,
            )
        assert exc_info.value.error_type == "api_error"

    @patch("llmtourney.core.anthropic_adapter.Anthropic")
    def test_no_raw_sdk_exception_propagates(self, MockAnthropic):
        client = MockAnthropic.return_value
        client.messages.create.side_effect = ConnectionError("network down")

        adapter = AnthropicAdapter(model_id="claude-sonnet-4-20250514", api_key="test-key")
        with pytest.raises(AdapterError) as exc_info:
            adapter.query(
                messages=[{"role": "user", "content": "go"}],
                max_tokens=256,
                timeout_s=30.0,
            )
        assert exc_info.value.error_type == "api_error"
