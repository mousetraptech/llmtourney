"""Tests for MongoDB integration in TournamentEngine."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from llmtourney.config import (
    TournamentConfig,
    ModelConfig,
    EventConfig,
    ComputeCaps,
)
from llmtourney.tournament import TournamentEngine


def _minimal_config(tmp_path: Path) -> TournamentConfig:
    """Build a minimal TournamentConfig with mock models."""
    return TournamentConfig(
        name="test-mongo",
        seed=42,
        version="1.0",
        models={
            "mock-a": ModelConfig(
                name="mock-a", provider="mock", strategy="always_call",
            ),
            "mock-b": ModelConfig(
                name="mock-b", provider="mock", strategy="always_call",
            ),
        },
        events={
            "tictactoe": EventConfig(name="tictactoe", weight=1, games_per_match=1),
        },
        compute_caps=ComputeCaps(),
        output_dir=tmp_path / "output",
    )


class TestMongoSinkInit:
    """TournamentEngine creates / skips MongoSink based on env."""

    def test_no_sink_when_uri_not_set(self, tmp_path):
        """Without TOURNEY_MONGO_URI, _mongo_sink should be None."""
        with patch.dict("os.environ", {}, clear=False):
            # Make sure the var is absent
            import os
            os.environ.pop("TOURNEY_MONGO_URI", None)
            engine = TournamentEngine(_minimal_config(tmp_path))
        assert engine._mongo_sink is None

    def test_sink_created_when_uri_set(self, tmp_path):
        """With TOURNEY_MONGO_URI, engine should instantiate MongoSink."""
        mock_sink = MagicMock()
        with patch.dict("os.environ", {"TOURNEY_MONGO_URI": "mongodb://localhost:27017/test"}):
            with patch(
                "llmtourney.core.mongo_sink.MongoSink",
                return_value=mock_sink,
            ) as MockClass:
                engine = TournamentEngine(_minimal_config(tmp_path))
        assert engine._mongo_sink is mock_sink
        MockClass.assert_called_once_with("mongodb://localhost:27017/test", "llmtourney")

    def test_sink_failure_does_not_prevent_init(self, tmp_path):
        """If MongoSink raises, engine still initialises with sink=None."""
        with patch.dict("os.environ", {"TOURNEY_MONGO_URI": "mongodb://bad:27017/x"}):
            with patch(
                "llmtourney.core.mongo_sink.MongoSink",
                side_effect=Exception("connection refused"),
            ):
                engine = TournamentEngine(_minimal_config(tmp_path))
        assert engine._mongo_sink is None


class TestLoggerReceivesSink:
    """The TelemetryLogger gets mongo_sink and tournament_context."""

    def test_logger_created_with_sink_and_context(self, tmp_path):
        mock_sink = MagicMock()
        with patch.dict("os.environ", {"TOURNEY_MONGO_URI": "mongodb://localhost:27017/test"}):
            with patch(
                "llmtourney.core.mongo_sink.MongoSink",
                return_value=mock_sink,
            ):
                engine = TournamentEngine(_minimal_config(tmp_path))

        # Patch TelemetryLogger to capture instantiation args
        with patch("llmtourney.tournament.TelemetryLogger") as MockLogger:
            mock_logger_instance = MagicMock()
            MockLogger.return_value = mock_logger_instance
            # finalize_match returns nothing
            mock_logger_instance.finalize_match.return_value = None

            engine.run()

        # At least one call should have been made
        assert MockLogger.call_count >= 1
        # Check that the first call includes sink and context kwargs
        _, kwargs = MockLogger.call_args_list[0]
        assert kwargs.get("mongo_sink") is mock_sink
        ctx = kwargs.get("tournament_context")
        assert ctx is not None
        assert ctx["tournament_name"] == "test-mongo"
        assert ctx["event_type"] == "tictactoe"


class TestRunCleanup:
    """run() closes MongoSink in a finally block."""

    def test_sink_closed_after_run(self, tmp_path):
        mock_sink = MagicMock()
        with patch.dict("os.environ", {"TOURNEY_MONGO_URI": "mongodb://localhost:27017/test"}):
            with patch(
                "llmtourney.core.mongo_sink.MongoSink",
                return_value=mock_sink,
            ):
                engine = TournamentEngine(_minimal_config(tmp_path))

        engine.run()
        mock_sink.close.assert_called_once()

    def test_sink_closed_even_on_error(self, tmp_path):
        mock_sink = MagicMock()
        with patch.dict("os.environ", {"TOURNEY_MONGO_URI": "mongodb://localhost:27017/test"}):
            with patch(
                "llmtourney.core.mongo_sink.MongoSink",
                return_value=mock_sink,
            ):
                engine = TournamentEngine(_minimal_config(tmp_path))

        # Force an error inside run()
        with patch.object(engine, "_run_match", side_effect=RuntimeError("boom")):
            with pytest.raises(RuntimeError, match="boom"):
                engine.run()

        # Sink should still be closed
        mock_sink.close.assert_called_once()
