"""Shared test fixtures for llmtourney."""

import pytest
from pathlib import Path


@pytest.fixture
def tmp_output(tmp_path):
    """Provide a temporary output directory for test runs."""
    return tmp_path / "output"
