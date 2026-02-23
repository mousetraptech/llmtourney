"""Tests for TelemetryLogger — JSONL match logging."""

import json
from pathlib import Path

import pytest
from llmtourney.core.telemetry import TelemetryLogger, TelemetryEntry


@pytest.fixture
def logger(tmp_path):
    return TelemetryLogger(output_dir=tmp_path, match_id="test-match-001")


class TestTelemetryLogger:
    def test_log_turn_creates_file(self, logger, tmp_path):
        entry = _make_entry(turn_number=1)
        logger.log_turn(entry)
        log_file = tmp_path / "test-match-001.jsonl"
        assert log_file.exists()

    def test_log_turn_writes_valid_jsonl(self, logger, tmp_path):
        logger.log_turn(_make_entry(turn_number=1))
        logger.log_turn(_make_entry(turn_number=2))
        log_file = tmp_path / "test-match-001.jsonl"
        lines = log_file.read_text().strip().split("\n")
        assert len(lines) == 2
        for line in lines:
            parsed = json.loads(line)
            assert "turn_number" in parsed
            assert "schema_version" in parsed

    def test_log_turn_contains_all_fields(self, logger, tmp_path):
        entry = _make_entry(turn_number=1)
        logger.log_turn(entry)
        log_file = tmp_path / "test-match-001.jsonl"
        parsed = json.loads(log_file.read_text().strip())
        required_fields = [
            "schema_version", "match_id", "turn_number", "player_id",
            "model_id", "model_version", "prompt", "raw_output",
            "parsed_action", "parse_success", "validation_result",
            "input_tokens", "output_tokens", "latency_ms",
            "timestamp", "engine_version",
        ]
        for field in required_fields:
            assert field in parsed, f"Missing field: {field}"

    def test_finalize_match_appends_summary(self, logger, tmp_path):
        logger.log_turn(_make_entry(turn_number=1))
        logger.finalize_match(
            scores={"player_a": 220, "player_b": 180},
            fidelity={"player_a": {"total_violations": 0}, "player_b": {"total_violations": 0}},
        )
        log_file = tmp_path / "test-match-001.jsonl"
        lines = log_file.read_text().strip().split("\n")
        assert len(lines) == 2
        summary = json.loads(lines[-1])
        assert summary["record_type"] == "match_summary"
        assert summary["final_scores"]["player_a"] == 220

    def test_match_id_in_every_line(self, logger, tmp_path):
        logger.log_turn(_make_entry(turn_number=1))
        logger.log_turn(_make_entry(turn_number=2))
        log_file = tmp_path / "test-match-001.jsonl"
        for line in log_file.read_text().strip().split("\n"):
            assert json.loads(line)["match_id"] == "test-match-001"


def _make_entry(turn_number: int = 1) -> TelemetryEntry:
    return TelemetryEntry(
        turn_number=turn_number,
        hand_number=1,
        street="preflop",
        player_id="player_a",
        model_id="mock-v1",
        model_version="mock-v1",
        prompt="Your turn",
        raw_output='{"action": "call"}',
        reasoning_output=None,
        parsed_action={"action": "call"},
        parse_success=True,
        validation_result="ok",
        violation=None,
        ruling=None,
        state_snapshot={"pot": 4},
        input_tokens=50,
        output_tokens=5,
        latency_ms=12.3,
        engine_version="0.1.0",
        prompt_version="holdem-v1",
    )
