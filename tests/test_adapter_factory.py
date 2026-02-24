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

    @patch.dict(os.environ, {"TEST_GOOGLE_KEY": "gk-test-123"})
    def test_unknown_provider_raises(self, tmp_path):
        config = _config(tmp_path, provider="google", api_key_env="TEST_GOOGLE_KEY")
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
                if call_count["n"] <= 2:
                    raise AdapterError("timeout", "model-b", "timed out")
                return original_adapter.query(messages, max_tokens, timeout_s, context=context)

        engine.adapters["model-b"] = FailingAdapter()
        result = engine.run()
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
