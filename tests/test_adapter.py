"""Tests for ModelAdapter ABC and MockAdapter."""

import pytest
from llmtourney.core.adapter import (
    AdapterResponse,
    MockAdapter,
    ModelAdapter,
)


class TestAdapterResponse:
    def test_frozen(self):
        r = AdapterResponse(
            raw_text='{"action": "fold"}',
            reasoning_text=None,
            input_tokens=100,
            output_tokens=10,
            latency_ms=50.0,
            model_id="mock-v1",
            model_version="mock-v1",
        )
        with pytest.raises(AttributeError):
            r.raw_text = "changed"


class TestMockAdapter:
    def test_returns_strategy_output(self):
        def strategy(messages, context):
            return '{"action": "call"}'

        adapter = MockAdapter(
            model_id="mock-always-call",
            strategy=strategy,
        )
        resp = adapter.query(
            messages=[{"role": "user", "content": "Your turn"}],
            max_tokens=256,
            timeout_s=30.0,
        )
        assert resp.raw_text == '{"action": "call"}'
        assert resp.model_id == "mock-always-call"
        assert resp.reasoning_text is None
        assert resp.input_tokens == 0
        assert resp.output_tokens > 0
        assert resp.latency_ms >= 0

    def test_strategy_receives_messages(self):
        received = {}

        def strategy(messages, context):
            received["messages"] = messages
            return '{"action": "fold"}'

        adapter = MockAdapter(model_id="mock", strategy=strategy)
        msgs = [{"role": "user", "content": "prompt text"}]
        adapter.query(msgs, max_tokens=256, timeout_s=30.0)
        assert received["messages"] == msgs

    def test_output_truncated_to_max_tokens(self):
        """Mock respects max_tokens by character approximation."""
        def strategy(messages, context):
            return "x" * 10000

        adapter = MockAdapter(model_id="mock", strategy=strategy)
        resp = adapter.query(
            messages=[{"role": "user", "content": "go"}],
            max_tokens=10,
            timeout_s=30.0,
        )
        # Rough approximation: 10 tokens ~ 40 chars
        assert len(resp.raw_text) <= 10 * 4

    def test_is_model_adapter_subclass(self):
        def strategy(messages, context):
            return ""

        adapter = MockAdapter(model_id="mock", strategy=strategy)
        assert isinstance(adapter, ModelAdapter)
