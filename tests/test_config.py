"""Tests for config loading — especially new api_key_env and base_url fields."""

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
        assert config.models["mock-caller"].api_key_env is None
