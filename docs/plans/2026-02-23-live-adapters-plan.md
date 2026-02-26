# Live Model Adapters Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add OpenAI, Anthropic, and OpenRouter adapters so real LLMs can compete in tournaments, with full error handling and mocked test coverage.

**Architecture:** Each adapter wraps its provider's Python SDK, maps responses to the existing `AdapterResponse` dataclass, and converts all SDK exceptions to a single `AdapterError`. The tournament engine catches `AdapterError` and treats it as a timeout/forfeit. OpenRouterAdapter is a thin subclass of OpenAIAdapter with a different base_url and extra headers.

**Tech Stack:** `openai` SDK, `anthropic` SDK (both optional deps), `unittest.mock` for test mocking.

---

### Task 1: Fix ABC Signature + Add AdapterError

**Files:**
- Modify: `src/llmtourney/core/adapter.py`
- Modify: `tests/test_adapter.py`

**Step 1: Write the failing test**

Add to `tests/test_adapter.py`:

```python
from llmtourney.core.adapter import AdapterError


class TestAdapterError:
    def test_is_exception(self):
        err = AdapterError("timeout", model_id="gpt-4o", details="connection timed out")
        assert isinstance(err, Exception)
        assert err.error_type == "timeout"
        assert err.model_id == "gpt-4o"
        assert "connection timed out" in str(err)

    def test_adapter_error_types(self):
        for etype in ("timeout", "rate_limit", "api_error"):
            err = AdapterError(etype, model_id="test")
            assert err.error_type == etype


class TestContextInABC:
    def test_mock_adapter_accepts_context(self):
        def strategy(messages, context):
            return f'{{"got_context": {bool(context)}}}'

        adapter = MockAdapter(model_id="mock", strategy=strategy)
        resp = adapter.query(
            messages=[{"role": "user", "content": "test"}],
            max_tokens=256,
            timeout_s=30.0,
            context={"key": "value"},
        )
        assert "true" in resp.raw_text.lower()

    def test_mock_adapter_context_defaults_none(self):
        def strategy(messages, context):
            return '{"action": "call"}'

        adapter = MockAdapter(model_id="mock", strategy=strategy)
        # Call without context kwarg — must still work
        resp = adapter.query(
            messages=[{"role": "user", "content": "test"}],
            max_tokens=256,
            timeout_s=30.0,
        )
        assert resp.raw_text == '{"action": "call"}'
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_adapter.py -v`
Expected: FAIL — `ImportError: cannot import name 'AdapterError'`

**Step 3: Update adapter.py**

Add `AdapterError` class and add `context` param to the ABC:

```python
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
```

The `context` parameter is already on `MockAdapter.query()` — now it matches the ABC.

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_adapter.py -v`
Expected: All tests PASS (existing + 4 new).

Run: `pytest tests/ -q`
Expected: All 117 tests PASS (no regressions — the ABC change is backwards-compatible since `context` defaults to `None`).

**Step 5: Commit**

```bash
git add src/llmtourney/core/adapter.py tests/test_adapter.py
git commit -m "feat: add context param to ABC, add AdapterError exception"
```

---

### Task 2: Config Updates

**Files:**
- Modify: `src/llmtourney/config.py`
- Modify: `tests/test_adapter.py` (add config parsing tests at bottom)

**Step 1: Write the failing test**

Add a new test file `tests/test_config.py`:

```python
"""Tests for config loading — especially new api_key_env and base_url fields."""

import os
import pytest
from pathlib import Path
from llmtourney.config import load_config, ModelConfig

EXAMPLE_CONFIG = Path(__file__).resolve().parent.parent / "tournament.yaml.example"


class TestModelConfigFields:
    def test_api_key_env_field_exists(self):
        mc = ModelConfig(
            name="test",
            provider="openai",
            model_id="gpt-4o",
            api_key_env="OPENAI_API_KEY",
        )
        assert mc.api_key_env == "OPENAI_API_KEY"

    def test_base_url_field_exists(self):
        mc = ModelConfig(
            name="test",
            provider="openai",
            model_id="gpt-4o",
            base_url="https://custom.api.com/v1",
        )
        assert mc.base_url == "https://custom.api.com/v1"

    def test_defaults_none(self):
        mc = ModelConfig(name="test", provider="mock")
        assert mc.api_key_env is None
        assert mc.base_url is None

    def test_site_url_and_app_name(self):
        mc = ModelConfig(
            name="test",
            provider="openrouter",
            site_url="https://example.com",
            app_name="llmtourney",
        )
        assert mc.site_url == "https://example.com"
        assert mc.app_name == "llmtourney"


class TestLoadConfigWithNewFields:
    def test_existing_config_still_loads(self):
        config = load_config(EXAMPLE_CONFIG)
        assert config.name == "test-run"
        assert "mock-caller" in config.models
        # Mock models shouldn't have api_key_env
        assert config.models["mock-caller"].api_key_env is None
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_config.py -v`
Expected: FAIL — `TypeError: ModelConfig.__init__() got an unexpected keyword argument 'api_key_env'`

**Step 3: Update config.py**

Add fields to `ModelConfig`:

```python
@dataclass
class ModelConfig:
    name: str
    provider: str  # "mock", "openai", "anthropic", "openrouter"
    model_id: str | None = None
    strategy: str | None = None  # for mock provider
    temperature: float = 0.0
    max_output_tokens: int = 256
    timeout_s: float = 30.0
    api_key_env: str | None = None      # env var name for API key
    base_url: str | None = None         # custom API base URL
    site_url: str | None = None         # OpenRouter attribution
    app_name: str | None = None         # OpenRouter attribution
```

Update `load_config` to parse these new fields:

```python
models[name] = ModelConfig(
    name=name,
    provider=m["provider"],
    model_id=m.get("model_id"),
    strategy=m.get("strategy"),
    temperature=m.get("temperature", 0.0),
    max_output_tokens=m.get(
        "max_output_tokens", compute.get("max_output_tokens", 256)
    ),
    timeout_s=m.get("timeout_s", compute.get("timeout_s", 30.0)),
    api_key_env=m.get("api_key_env"),
    base_url=m.get("base_url"),
    site_url=m.get("site_url"),
    app_name=m.get("app_name"),
)
```

**Step 4: Run tests**

Run: `pytest tests/test_config.py tests/ -q`
Expected: All pass.

**Step 5: Commit**

```bash
git add src/llmtourney/config.py tests/test_config.py
git commit -m "feat: add api_key_env, base_url, openrouter fields to ModelConfig"
```

---

### Task 3: OpenAIAdapter

**Files:**
- Create: `src/llmtourney/core/openai_adapter.py`
- Create: `tests/test_openai_adapter.py`
- Modify: `pyproject.toml` (add optional `openai` dependency)

**Step 1: Update pyproject.toml**

Add openai as an optional dependency:

```toml
[project.optional-dependencies]
live = ["openai>=1.0", "anthropic>=0.40"]
dev = ["pytest>=8.0"]
all = ["llmtourney[live,dev]"]
```

Run: `pip install -e ".[all]"`

**Step 2: Write the failing tests**

```python
"""Tests for OpenAIAdapter — uses mocked SDK, no live API calls."""

import time
from unittest.mock import MagicMock, patch, PropertyMock

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

    @patch("llmtourney.core.openai_adapter.OpenAI")
    def test_rate_limit_retries_then_raises(self, MockOpenAI):
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
        # Should have been called twice (initial + 1 retry)
        assert client.chat.completions.create.call_count == 2

    @patch("llmtourney.core.openai_adapter.OpenAI")
    def test_generic_api_error_raises_adapter_error(self, MockOpenAI):
        import openai
        client = MockOpenAI.return_value

        resp_mock = MagicMock()
        resp_mock.status_code = 500
        resp_mock.headers = {}
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
```

**Step 3: Run tests to verify they fail**

Run: `pytest tests/test_openai_adapter.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'llmtourney.core.openai_adapter'`

**Step 4: Write implementation**

`src/llmtourney/core/openai_adapter.py`:

```python
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
        # Unreachable, but satisfies type checker
        raise AdapterError("api_error", self._model_id, "max retries exceeded")
```

**Step 5: Run tests**

Run: `pytest tests/test_openai_adapter.py -v`
Expected: All 8 tests PASS.

Run: `pytest tests/ -q`
Expected: All existing tests still pass.

**Step 6: Commit**

```bash
git add src/llmtourney/core/openai_adapter.py tests/test_openai_adapter.py pyproject.toml
git commit -m "feat: OpenAIAdapter with timeout, rate-limit retry, and reasoning extraction"
```

---

### Task 4: AnthropicAdapter

**Files:**
- Create: `src/llmtourney/core/anthropic_adapter.py`
- Create: `tests/test_anthropic_adapter.py`

**Step 1: Write the failing tests**

```python
"""Tests for AnthropicAdapter — uses mocked SDK, no live API calls."""

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

    @patch("llmtourney.core.anthropic_adapter.Anthropic")
    def test_rate_limit_retries_then_raises(self, MockAnthropic):
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
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_anthropic_adapter.py -v`
Expected: FAIL — `ModuleNotFoundError`

**Step 3: Write implementation**

`src/llmtourney/core/anthropic_adapter.py`:

```python
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
```

**Step 4: Run tests**

Run: `pytest tests/test_anthropic_adapter.py -v`
Expected: All 8 tests PASS.

**Step 5: Commit**

```bash
git add src/llmtourney/core/anthropic_adapter.py tests/test_anthropic_adapter.py
git commit -m "feat: AnthropicAdapter with thinking extraction and error handling"
```

---

### Task 5: OpenRouterAdapter

**Files:**
- Create: `src/llmtourney/core/openrouter_adapter.py`
- Create: `tests/test_openrouter_adapter.py`

**Step 1: Write the failing tests**

```python
"""Tests for OpenRouterAdapter — thin wrapper over OpenAIAdapter."""

from unittest.mock import MagicMock, patch, call

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
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_openrouter_adapter.py -v`
Expected: FAIL — `ModuleNotFoundError`

**Step 3: Write implementation**

`src/llmtourney/core/openrouter_adapter.py`:

```python
"""OpenRouter adapter — thin subclass of OpenAIAdapter.

Sets base_url to OpenRouter's endpoint and optionally adds
attribution headers (HTTP-Referer, X-Title).
"""

from llmtourney.core.openai_adapter import OpenAIAdapter

_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


class OpenRouterAdapter(OpenAIAdapter):
    """Adapter for OpenRouter — uses the OpenAI-compatible API."""

    def __init__(
        self,
        model_id: str,
        api_key: str,
        temperature: float = 0.0,
        site_url: str | None = None,
        app_name: str | None = None,
    ):
        extra_headers: dict[str, str] = {}
        if site_url:
            extra_headers["HTTP-Referer"] = site_url
        if app_name:
            extra_headers["X-Title"] = app_name

        super().__init__(
            model_id=model_id,
            api_key=api_key,
            base_url=_OPENROUTER_BASE_URL,
            temperature=temperature,
            extra_headers=extra_headers if extra_headers else None,
        )
```

**Step 4: Run tests**

Run: `pytest tests/test_openrouter_adapter.py -v`
Expected: All 4 tests PASS.

**Step 5: Commit**

```bash
git add src/llmtourney/core/openrouter_adapter.py tests/test_openrouter_adapter.py
git commit -m "feat: OpenRouterAdapter with attribution headers"
```

---

### Task 6: Adapter Factory + Tournament Error Handling

**Files:**
- Modify: `src/llmtourney/tournament.py`
- Modify: `tournament.yaml.example`
- Create: `tests/test_adapter_factory.py`

**Step 1: Write the failing tests**

```python
"""Tests for adapter factory and tournament error handling."""

import os
from unittest.mock import patch, MagicMock

import pytest

from llmtourney.config import TournamentConfig, ModelConfig, EventConfig, ComputeCaps
from llmtourney.core.adapter import AdapterError, AdapterResponse
from llmtourney.tournament import TournamentEngine


class TestAdapterFactory:
    def test_mock_provider(self, tmp_path):
        config = _config(tmp_path, provider="mock", strategy="always_call")
        engine = TournamentEngine(config)
        assert "model-a" in engine.adapters

    @patch.dict(os.environ, {"TEST_OPENAI_KEY": "sk-test-123"})
    @patch("llmtourney.core.openai_adapter.OpenAI")
    def test_openai_provider(self, MockOpenAI, tmp_path):
        config = _config(
            tmp_path,
            provider="openai",
            model_id="gpt-4o",
            api_key_env="TEST_OPENAI_KEY",
        )
        engine = TournamentEngine(config)
        assert "model-a" in engine.adapters

    @patch.dict(os.environ, {"TEST_ANTHROPIC_KEY": "sk-ant-test"})
    @patch("llmtourney.core.anthropic_adapter.Anthropic")
    def test_anthropic_provider(self, MockAnthropic, tmp_path):
        config = _config(
            tmp_path,
            provider="anthropic",
            model_id="claude-sonnet-4-20250514",
            api_key_env="TEST_ANTHROPIC_KEY",
        )
        engine = TournamentEngine(config)
        assert "model-a" in engine.adapters

    @patch.dict(os.environ, {"TEST_OR_KEY": "sk-or-test"})
    @patch("llmtourney.core.openai_adapter.OpenAI")
    def test_openrouter_provider(self, MockOpenAI, tmp_path):
        config = _config(
            tmp_path,
            provider="openrouter",
            model_id="deepseek/deepseek-r1",
            api_key_env="TEST_OR_KEY",
        )
        engine = TournamentEngine(config)
        assert "model-a" in engine.adapters

    def test_missing_api_key_env_raises(self, tmp_path):
        config = _config(
            tmp_path,
            provider="openai",
            model_id="gpt-4o",
            api_key_env="NONEXISTENT_KEY_VAR_12345",
        )
        with pytest.raises(ValueError, match="not set"):
            TournamentEngine(config)

    def test_unknown_provider_raises(self, tmp_path):
        config = _config(tmp_path, provider="google")
        with pytest.raises(ValueError, match="Unsupported provider"):
            TournamentEngine(config)


class TestTournamentAdapterErrorHandling:
    def test_adapter_error_treated_as_forfeit(self, tmp_path):
        """When adapter raises AdapterError, engine forfeits that turn."""
        config = _two_model_config(tmp_path)
        engine = TournamentEngine(config)

        # Replace one adapter with one that fails on first call, then works
        call_count = {"n": 0}
        original_adapter = engine.adapters["model-b"]

        class FailingAdapter:
            def query(self, messages, max_tokens, timeout_s, context=None):
                call_count["n"] += 1
                if call_count["n"] <= 2:  # Fail first 2 calls
                    raise AdapterError("timeout", "model-b", "timed out")
                return original_adapter.query(messages, max_tokens, timeout_s, context=context)

        engine.adapters["model-b"] = FailingAdapter()
        result = engine.run()
        # Tournament should complete without crashing
        assert result is not None
        assert len(result.matches) == 1


def _config(tmp_path, provider="mock", **kwargs):
    return TournamentConfig(
        name="test",
        seed=42,
        version="0.1.0",
        models={
            "model-a": ModelConfig(
                name="model-a",
                provider=provider,
                strategy=kwargs.get("strategy"),
                model_id=kwargs.get("model_id"),
                api_key_env=kwargs.get("api_key_env"),
            ),
        },
        events={
            "holdem": EventConfig(name="holdem", weight=3, hands_per_match=5),
        },
        compute_caps=ComputeCaps(),
        output_dir=tmp_path / "output",
    )


def _two_model_config(tmp_path):
    return TournamentConfig(
        name="test",
        seed=42,
        version="0.1.0",
        models={
            "model-a": ModelConfig(name="model-a", provider="mock", strategy="always_call"),
            "model-b": ModelConfig(name="model-b", provider="mock", strategy="always_call"),
        },
        events={
            "holdem": EventConfig(name="holdem", weight=3, hands_per_match=5),
        },
        compute_caps=ComputeCaps(),
        output_dir=tmp_path / "output",
    )
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_adapter_factory.py -v`
Expected: FAIL — OpenAI/Anthropic providers not handled in `_build_adapter`.

**Step 3: Update tournament.py**

Update `_build_adapter` to handle all providers, and wrap adapter calls in the match loop to catch `AdapterError`.

Key changes to `_build_adapter`:

```python
import os
from llmtourney.core.adapter import AdapterError, MockAdapter, ModelAdapter
from llmtourney.core.openai_adapter import OpenAIAdapter
from llmtourney.core.anthropic_adapter import AnthropicAdapter
from llmtourney.core.openrouter_adapter import OpenRouterAdapter

def _build_adapter(self, mcfg: ModelConfig) -> ModelAdapter:
    if mcfg.provider == "mock":
        strategy_fn = _STRATEGY_REGISTRY.get(mcfg.strategy or "")
        if strategy_fn is None:
            raise ValueError(f"Unknown mock strategy: {mcfg.strategy!r}")
        return MockAdapter(model_id=mcfg.name, strategy=strategy_fn)

    # Resolve API key from environment
    api_key = self._resolve_api_key(mcfg)

    if mcfg.provider == "openai":
        return OpenAIAdapter(
            model_id=mcfg.model_id or mcfg.name,
            api_key=api_key,
            base_url=mcfg.base_url,
            temperature=mcfg.temperature,
        )
    if mcfg.provider == "anthropic":
        return AnthropicAdapter(
            model_id=mcfg.model_id or mcfg.name,
            api_key=api_key,
            temperature=mcfg.temperature,
        )
    if mcfg.provider == "openrouter":
        return OpenRouterAdapter(
            model_id=mcfg.model_id or mcfg.name,
            api_key=api_key,
            temperature=mcfg.temperature,
            site_url=mcfg.site_url,
            app_name=mcfg.app_name,
        )
    raise ValueError(f"Unsupported provider: {mcfg.provider!r}")

def _resolve_api_key(self, mcfg: ModelConfig) -> str:
    if not mcfg.api_key_env:
        raise ValueError(f"Model {mcfg.name!r}: api_key_env is required for provider {mcfg.provider!r}")
    key = os.environ.get(mcfg.api_key_env)
    if not key:
        raise ValueError(f"Model {mcfg.name!r}: env var {mcfg.api_key_env!r} is not set")
    return key
```

Key changes to `_run_match` — wrap `adapter.query()` calls to catch `AdapterError`:

In each place where `adapter.query()` is called, wrap it:

```python
try:
    response = adapter.query(...)
except AdapterError:
    # Treat as timeout — create a dummy response and forfeit
    response = AdapterResponse(
        raw_text="",
        reasoning_text=None,
        input_tokens=0,
        output_tokens=0,
        latency_ms=0.0,
        model_id=model_name,
        model_version=model_name,
    )
    referee.record_violation(
        player_id, ViolationKind.TIMEOUT, severity=2,
        details="adapter error",
    )
    event.forfeit_turn(player_id)
    # log the turn...
    continue
```

There are 3 call sites in `_run_match` (initial query, parse-retry query, validation-retry query). Extract a helper method `_safe_query` that wraps the try/except.

**Step 4: Update tournament.yaml.example**

Add commented-out examples for live models:

```yaml
tournament:
  name: "test-run"
  seed: 42
  version: "0.1.0"

models:
  mock-caller:
    provider: mock
    strategy: always_call
  mock-heuristic:
    provider: mock
    strategy: simple_heuristic

  # --- Live model examples (uncomment to use) ---
  # gpt-4o:
  #   provider: openai
  #   model_id: gpt-4o
  #   api_key_env: OPENAI_API_KEY
  #   temperature: 0.0
  #
  # claude-sonnet:
  #   provider: anthropic
  #   model_id: claude-sonnet-4-20250514
  #   api_key_env: ANTHROPIC_API_KEY
  #   temperature: 0.0
  #
  # deepseek-r1:
  #   provider: openrouter
  #   model_id: deepseek/deepseek-r1
  #   api_key_env: OPENROUTER_API_KEY
  #   temperature: 0.0

events:
  holdem:
    weight: 3
    hands_per_match: 100
    starting_stack: 200
    blinds: [1, 2]
    rounds: 1

compute_caps:
  max_output_tokens: 256
  timeout_s: 30.0
```

**Step 5: Run tests**

Run: `pytest tests/test_adapter_factory.py -v`
Expected: All 7 tests PASS.

Run: `pytest tests/ -q`
Expected: ALL tests pass (existing 117 + new tests from tasks 1-6).

**Step 6: Commit**

```bash
git add src/llmtourney/tournament.py tournament.yaml.example tests/test_adapter_factory.py
git commit -m "feat: adapter factory for openai/anthropic/openrouter + error handling in match loop"
```

---

## Final Verification

After all 6 tasks:

Run: `pytest tests/ -v --tb=short`
Expected: All tests pass (~145+ tests).

Run: `python -m llmtourney tournament.yaml.example`
Expected: Works with mock models (same as before).

Verify live adapter usage (manual, not in CI):
```bash
export OPENAI_API_KEY=sk-...
# Edit tournament.yaml to uncomment gpt-4o
python -m llmtourney tournament.yaml
```
