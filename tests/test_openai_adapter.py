"""Tests for OpenAIAdapter --- uses mocked SDK, no live API calls."""

import time
from unittest.mock import MagicMock, patch

import pytest

from llmtourney.core.adapter import AdapterError, AdapterResponse
from llmtourney.core.openai_adapter import OpenAIAdapter


def _mock_completion(
    content="",
    model="gpt-4o",
    input_tokens=10,
    output_tokens=5,
    reasoning_content=None,
):
    """Build a mock ChatCompletion response object."""
    choice = MagicMock()
    choice.message.content = content
    choice.message.reasoning_content = reasoning_content

    usage = MagicMock()
    usage.prompt_tokens = input_tokens
    usage.completion_tokens = output_tokens

    completion = MagicMock()
    completion.choices = [choice]
    completion.usage = usage
    completion.model = model
    return completion


class TestOpenAIAdapterSuccess:
    @patch("llmtourney.core.openai_adapter.OpenAI")
    def test_basic_query(self, MockOpenAI):
        client = MockOpenAI.return_value
        client.chat.completions.create.return_value = _mock_completion(
            content='{"action": "fold"}',
            model="gpt-4o-2024-08-06",
            input_tokens=50,
            output_tokens=8,
        )

        adapter = OpenAIAdapter(
            model_id="gpt-4o",
            api_key="test-key",
        )
        resp = adapter.query(
            messages=[{"role": "user", "content": "Your turn"}],
            max_tokens=256,
            timeout_s=30.0,
        )

        assert resp.raw_text == '{"action": "fold"}'
        assert resp.model_id == "gpt-4o"
        assert resp.model_version == "gpt-4o-2024-08-06"
        assert resp.input_tokens == 50
        assert resp.output_tokens == 8
        assert resp.reasoning_text is None
        assert resp.latency_ms >= 0
        assert isinstance(resp, AdapterResponse)

    @patch("llmtourney.core.openai_adapter.OpenAI")
    def test_reasoning_text_extracted(self, MockOpenAI):
        """o1/o3 models return reasoning_content."""
        client = MockOpenAI.return_value
        client.chat.completions.create.return_value = _mock_completion(
            content='{"action": "call"}',
            reasoning_content="Let me think about this carefully...",
        )

        adapter = OpenAIAdapter(model_id="o3", api_key="test-key")
        resp = adapter.query(
            messages=[{"role": "user", "content": "go"}],
            max_tokens=256,
            timeout_s=30.0,
        )

        assert resp.reasoning_text == "Let me think about this carefully..."
        assert resp.raw_text == '{"action": "call"}'

    @patch("llmtourney.core.openai_adapter.OpenAI")
    def test_custom_base_url(self, MockOpenAI):
        """base_url is passed through to the SDK client."""
        OpenAIAdapter(
            model_id="gpt-4o",
            api_key="test-key",
            base_url="https://custom.api.com/v1",
        )
        MockOpenAI.assert_called_once()
        call_kwargs = MockOpenAI.call_args[1]
        assert call_kwargs["base_url"] == "https://custom.api.com/v1"

    @patch("llmtourney.core.openai_adapter.OpenAI")
    def test_passes_temperature(self, MockOpenAI):
        client = MockOpenAI.return_value
        client.chat.completions.create.return_value = _mock_completion(
            content='{"action": "fold"}'
        )

        adapter = OpenAIAdapter(
            model_id="gpt-4o", api_key="test-key", temperature=0.5
        )
        adapter.query(
            messages=[{"role": "user", "content": "go"}],
            max_tokens=256,
            timeout_s=30.0,
        )

        create_kwargs = client.chat.completions.create.call_args[1]
        assert create_kwargs["temperature"] == 0.5


class TestOpenAIAdapterErrors:
    @patch("llmtourney.core.openai_adapter.OpenAI")
    def test_timeout_raises_adapter_error(self, MockOpenAI):
        import openai

        client = MockOpenAI.return_value
        client.chat.completions.create.side_effect = openai.APITimeoutError(
            request=MagicMock()
        )

        adapter = OpenAIAdapter(model_id="gpt-4o", api_key="test-key")
        with pytest.raises(AdapterError) as exc_info:
            adapter.query(
                messages=[{"role": "user", "content": "go"}],
                max_tokens=256,
                timeout_s=5.0,
            )
        assert exc_info.value.error_type == "timeout"

    @patch("llmtourney.core.openai_adapter.time.sleep")
    @patch("llmtourney.core.openai_adapter.OpenAI")
    def test_rate_limit_retries_then_raises(self, MockOpenAI, mock_sleep):
        import openai

        client = MockOpenAI.return_value

        resp_mock = MagicMock()
        resp_mock.status_code = 429
        resp_mock.headers = {}
        rate_err = openai.RateLimitError(
            message="rate limited",
            response=resp_mock,
            body=None,
        )
        client.chat.completions.create.side_effect = rate_err

        adapter = OpenAIAdapter(model_id="gpt-4o", api_key="test-key")
        with pytest.raises(AdapterError) as exc_info:
            adapter.query(
                messages=[{"role": "user", "content": "go"}],
                max_tokens=256,
                timeout_s=30.0,
            )
        assert exc_info.value.error_type == "rate_limit"
        assert client.chat.completions.create.call_count == 2

    @patch("llmtourney.core.openai_adapter.OpenAI")
    def test_generic_api_error_raises_adapter_error(self, MockOpenAI):
        import openai

        client = MockOpenAI.return_value

        client.chat.completions.create.side_effect = openai.APIError(
            message="server error",
            request=MagicMock(),
            body=None,
        )

        adapter = OpenAIAdapter(model_id="gpt-4o", api_key="test-key")
        with pytest.raises(AdapterError) as exc_info:
            adapter.query(
                messages=[{"role": "user", "content": "go"}],
                max_tokens=256,
                timeout_s=30.0,
            )
        assert exc_info.value.error_type == "api_error"

    @patch("llmtourney.core.openai_adapter.OpenAI")
    def test_no_raw_sdk_exception_propagates(self, MockOpenAI):
        """Any unexpected exception is wrapped in AdapterError."""
        client = MockOpenAI.return_value
        client.chat.completions.create.side_effect = ConnectionError("network down")

        adapter = OpenAIAdapter(model_id="gpt-4o", api_key="test-key")
        with pytest.raises(AdapterError) as exc_info:
            adapter.query(
                messages=[{"role": "user", "content": "go"}],
                max_tokens=256,
                timeout_s=30.0,
            )
        assert exc_info.value.error_type == "api_error"
