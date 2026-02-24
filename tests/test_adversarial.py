"""Adversarial mock tests: garbage output, injection attempts, illegal moves."""

import json
from pathlib import Path
import pytest
from llmtourney.tournament import TournamentEngine
from llmtourney.config import TournamentConfig, ModelConfig, EventConfig, ComputeCaps


class TestAdversarialMock:
    def test_garbage_output_handled(self, tmp_path):
        """A mock that produces garbage should trigger violations but match still completes."""
        config = _make_config(
            tmp_path,
            strategy_a="always_call",
            strategy_b="garbage",
        )
        engine = TournamentEngine(config)
        result = engine.run()
        assert result is not None
        assert len(result.matches) == 1
        # Garbage player should have violations
        for match in result.matches:
            jsonl_file = list(result.telemetry_dir.glob("*.jsonl"))[0]
            lines = jsonl_file.read_text().strip().split("\n")
            summary = json.loads(lines[-1])
            fidelity = summary["fidelity_report"]
            total_violations = sum(
                p.get("total_violations", 0) for p in fidelity.values()
            )
            assert total_violations > 0

    def test_injection_attempt_flagged(self, tmp_path):
        """A mock that injects should have injection_attempts > 0."""
        config = _make_config(
            tmp_path,
            strategy_a="always_call",
            strategy_b="injector",
        )
        engine = TournamentEngine(config)
        result = engine.run()
        for match in result.matches:
            jsonl_file = list(result.telemetry_dir.glob("*.jsonl"))[0]
            lines = jsonl_file.read_text().strip().split("\n")
            summary = json.loads(lines[-1])
            fidelity = summary["fidelity_report"]
            total_injections = sum(
                p.get("injection_attempts", 0) for p in fidelity.values()
            )
            assert total_injections > 0

    def test_match_still_produces_valid_scores(self, tmp_path):
        """Even with violations, scores should sum to total chips."""
        config = _make_config(
            tmp_path,
            strategy_a="always_call",
            strategy_b="garbage",
        )
        engine = TournamentEngine(config)
        result = engine.run()
        for match in result.matches:
            total = sum(match.scores.values())
            assert total == 400


def _make_config(tmp_path, strategy_a, strategy_b):
    """Build a config with custom strategy names."""
    return TournamentConfig(
        name="test-adversarial",
        seed=42,
        version="0.1.0",
        models={
            "model-a": ModelConfig(name="model-a", provider="mock", strategy=strategy_a),
            "model-b": ModelConfig(name="model-b", provider="mock", strategy=strategy_b),
        },
        events={
            "holdem": EventConfig(
                name="holdem",
                weight=3,
                hands_per_match=20,  # Shorter for test speed
                starting_stack=200,
                blinds=(1, 2),
                rounds=1,
            ),
        },
        compute_caps=ComputeCaps(max_output_tokens=256, timeout_s=30.0),
        output_dir=tmp_path / "output",
    )
