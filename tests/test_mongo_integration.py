"""Tests for TelemetryLogger + MongoSink integration.

Verifies that TelemetryLogger optionally delegates to a MongoSink
while keeping JSONL writing completely intact.
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, call

import pytest

from llmtourney.core.telemetry import TelemetryLogger, TelemetryEntry


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


_TOURNAMENT_CONTEXT = {
    "event_type": "holdem",
    "tournament_name": "test-tourney",
    "tier": "midtier",
    "round": 1,
}


class TestLogTurnDelegation:
    def test_log_turn_delegates_to_sink(self, tmp_path):
        sink = MagicMock()
        logger = TelemetryLogger(
            output_dir=tmp_path,
            match_id="m-001",
            mongo_sink=sink,
            tournament_context=_TOURNAMENT_CONTEXT,
        )
        entry = _make_entry()
        logger.log_turn(entry)

        sink.log_turn.assert_called_once_with("m-001", entry, _TOURNAMENT_CONTEXT)

    def test_log_turn_passes_correct_args(self, tmp_path):
        sink = MagicMock()
        ctx = {"event_type": "tictactoe", "tournament_name": "t2", "tier": "heavy", "round": 3}
        logger = TelemetryLogger(
            output_dir=tmp_path,
            match_id="m-002",
            mongo_sink=sink,
            tournament_context=ctx,
        )
        entry = _make_entry(turn_number=7)
        logger.log_turn(entry)

        sink.log_turn.assert_called_once_with("m-002", entry, ctx)


class TestFinalizeMatchDelegation:
    def test_finalize_delegates_to_sink_with_player_models(self, tmp_path):
        sink = MagicMock()
        logger = TelemetryLogger(
            output_dir=tmp_path,
            match_id="m-001",
            mongo_sink=sink,
            tournament_context=_TOURNAMENT_CONTEXT,
        )

        scores = {"player_a": 10, "player_b": 5}
        fidelity = {"player_a": {"total_violations": 0}}
        player_models = {"player_a": "gpt-4o", "player_b": "claude-sonnet-4.5"}
        extra = {"player_models": player_models, "some_other": "data"}

        logger.finalize_match(scores=scores, fidelity=fidelity, extra=extra)

        sink.finalize_match.assert_called_once_with(
            "m-001",
            scores,
            fidelity,
            player_models,
            _TOURNAMENT_CONTEXT,
            extra=extra,
        )

    def test_finalize_extracts_player_models_from_extra(self, tmp_path):
        """player_models must be extracted from extra and passed as a separate arg."""
        sink = MagicMock()
        logger = TelemetryLogger(
            output_dir=tmp_path,
            match_id="m-003",
            mongo_sink=sink,
            tournament_context=_TOURNAMENT_CONTEXT,
        )

        pm = {"player_a": "model-x", "player_b": "model-y"}
        logger.finalize_match(
            scores={"player_a": 1, "player_b": 0},
            fidelity={},
            extra={"player_models": pm},
        )

        # The 4th positional arg to sink.finalize_match should be player_models
        args, kwargs = sink.finalize_match.call_args
        assert args[3] == pm  # positional: match_id, scores, fidelity, player_models

    def test_finalize_empty_player_models_when_not_in_extra(self, tmp_path):
        """If extra has no player_models key, pass empty dict."""
        sink = MagicMock()
        logger = TelemetryLogger(
            output_dir=tmp_path,
            match_id="m-004",
            mongo_sink=sink,
            tournament_context=_TOURNAMENT_CONTEXT,
        )

        logger.finalize_match(
            scores={"player_a": 1, "player_b": 0},
            fidelity={},
            extra={"some_key": "some_val"},
        )

        args, kwargs = sink.finalize_match.call_args
        assert args[3] == {}  # no player_models in extra -> empty dict

    def test_finalize_no_extra_at_all(self, tmp_path):
        """If extra is None, player_models defaults to empty dict."""
        sink = MagicMock()
        logger = TelemetryLogger(
            output_dir=tmp_path,
            match_id="m-005",
            mongo_sink=sink,
            tournament_context=_TOURNAMENT_CONTEXT,
        )

        logger.finalize_match(
            scores={"player_a": 1, "player_b": 0},
            fidelity={},
        )

        args, kwargs = sink.finalize_match.call_args
        assert args[3] == {}  # extra is None -> empty dict


class TestJSONLStillWritten:
    def test_jsonl_written_when_sink_present(self, tmp_path):
        sink = MagicMock()
        logger = TelemetryLogger(
            output_dir=tmp_path,
            match_id="m-001",
            mongo_sink=sink,
            tournament_context=_TOURNAMENT_CONTEXT,
        )

        logger.log_turn(_make_entry(turn_number=1))
        logger.log_turn(_make_entry(turn_number=2))
        logger.finalize_match(
            scores={"player_a": 10, "player_b": 5},
            fidelity={},
        )

        log_file = tmp_path / "m-001.jsonl"
        assert log_file.exists()
        lines = log_file.read_text().strip().split("\n")
        assert len(lines) == 3  # 2 turns + 1 summary
        for line in lines:
            json.loads(line)  # valid JSON

    def test_jsonl_content_unchanged_by_sink(self, tmp_path):
        """JSONL output should be identical whether or not a sink is present."""
        # Without sink
        logger_no_sink = TelemetryLogger(output_dir=tmp_path / "no_sink", match_id="m-001")
        entry = _make_entry()
        logger_no_sink.log_turn(entry)

        # With sink
        sink = MagicMock()
        logger_with_sink = TelemetryLogger(
            output_dir=tmp_path / "with_sink",
            match_id="m-001",
            mongo_sink=sink,
            tournament_context=_TOURNAMENT_CONTEXT,
        )
        logger_with_sink.log_turn(entry)

        no_sink_data = json.loads((tmp_path / "no_sink" / "m-001.jsonl").read_text().strip())
        with_sink_data = json.loads((tmp_path / "with_sink" / "m-001.jsonl").read_text().strip())

        # Same fields (timestamps may differ, so check structural equality minus timestamp)
        no_sink_data.pop("timestamp")
        with_sink_data.pop("timestamp")
        assert no_sink_data == with_sink_data


class TestBackwardCompatibility:
    def test_works_without_sink(self, tmp_path):
        """Original usage (no mongo_sink) still works."""
        logger = TelemetryLogger(output_dir=tmp_path, match_id="m-001")
        logger.log_turn(_make_entry())
        logger.finalize_match(
            scores={"player_a": 10, "player_b": 5},
            fidelity={},
        )

        log_file = tmp_path / "m-001.jsonl"
        assert log_file.exists()
        lines = log_file.read_text().strip().split("\n")
        assert len(lines) == 2

    def test_default_tournament_context_is_empty_dict(self, tmp_path):
        """tournament_context defaults to {} when not provided."""
        sink = MagicMock()
        logger = TelemetryLogger(
            output_dir=tmp_path, match_id="m-001", mongo_sink=sink,
        )
        entry = _make_entry()
        logger.log_turn(entry)

        sink.log_turn.assert_called_once_with("m-001", entry, {})


class TestSinkErrorSafety:
    def test_log_turn_sink_error_does_not_break_jsonl(self, tmp_path):
        sink = MagicMock()
        sink.log_turn.side_effect = RuntimeError("mongo exploded")

        logger = TelemetryLogger(
            output_dir=tmp_path,
            match_id="m-001",
            mongo_sink=sink,
            tournament_context=_TOURNAMENT_CONTEXT,
        )

        # Should not raise
        logger.log_turn(_make_entry())

        # JSONL should still be written
        log_file = tmp_path / "m-001.jsonl"
        assert log_file.exists()
        data = json.loads(log_file.read_text().strip())
        assert data["turn_number"] == 1

    def test_finalize_sink_error_does_not_break_jsonl(self, tmp_path):
        sink = MagicMock()
        sink.finalize_match.side_effect = RuntimeError("mongo exploded")

        logger = TelemetryLogger(
            output_dir=tmp_path,
            match_id="m-001",
            mongo_sink=sink,
            tournament_context=_TOURNAMENT_CONTEXT,
        )

        # Should not raise
        logger.finalize_match(
            scores={"player_a": 10, "player_b": 5},
            fidelity={},
            extra={"player_models": {"player_a": "gpt-4o", "player_b": "claude-sonnet-4.5"}},
        )

        # JSONL should still be written
        log_file = tmp_path / "m-001.jsonl"
        assert log_file.exists()
        data = json.loads(log_file.read_text().strip())
        assert data["record_type"] == "match_summary"
