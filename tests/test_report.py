"""Tests for scripts.telemetry_report — console model performance report."""

import json
from io import StringIO
from unittest.mock import MagicMock, patch

import pytest

from scripts.telemetry_report import print_report


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _mock_db():
    """Return a MagicMock that behaves like pymongo.database.Database."""
    return MagicMock()


def _sample_win_rates():
    return [
        {"_id": {"model": "gpt-4o", "event_type": "tictactoe"},
         "wins": 12, "losses": 3, "draws": 1, "total": 16, "win_rate": 0.75},
        {"_id": {"model": "claude-sonnet-4.5", "event_type": "tictactoe"},
         "wins": 9, "losses": 5, "draws": 2, "total": 16, "win_rate": 0.5625},
    ]


def _sample_violations():
    return [
        {"_id": {"model_id": "haiku", "violation": "illegal_move"}, "count": 12},
        {"_id": {"model_id": "gpt-4o", "violation": "malformed_json"}, "count": 3},
    ]


def _sample_fidelity():
    return [
        {"_id": "gpt-4o", "total_matches": 16, "total_violations": 2,
         "clean_matches": 14, "clean_pct": 87.5},
        {"_id": "haiku", "total_matches": 16, "total_violations": 15,
         "clean_matches": 5, "clean_pct": 31.25},
    ]


def _sample_latency():
    return [
        {"_id": {"model_id": "gpt-4o", "event_type": "tictactoe"},
         "avg_ms": 2400.0, "min_ms": 800.0, "max_ms": 5000.0},
        {"_id": {"model_id": "claude-sonnet-4.5", "event_type": "tictactoe"},
         "avg_ms": 3100.0, "min_ms": 1200.0, "max_ms": 6000.0},
    ]


# ------------------------------------------------------------------
# Leaderboard
# ------------------------------------------------------------------


class TestLeaderboard:
    @patch("scripts.telemetry_report.mongo_queries")
    def test_prints_model_names_and_win_rates(self, mock_mq):
        mock_mq.win_rates.return_value = _sample_win_rates()
        mock_mq.violation_frequency.return_value = []
        mock_mq.fidelity_scores.return_value = []
        mock_mq.avg_latency.return_value = []

        db = _mock_db()
        buf = StringIO()
        print_report(db, file=buf)
        output = buf.getvalue()

        assert "gpt-4o" in output
        assert "claude-sonnet-4.5" in output
        assert "75.0%" in output
        assert "56.2%" in output

    @patch("scripts.telemetry_report.mongo_queries")
    def test_leaderboard_shows_wins_losses_draws(self, mock_mq):
        mock_mq.win_rates.return_value = _sample_win_rates()
        mock_mq.violation_frequency.return_value = []
        mock_mq.fidelity_scores.return_value = []
        mock_mq.avg_latency.return_value = []

        db = _mock_db()
        buf = StringIO()
        print_report(db, file=buf)
        output = buf.getvalue()

        # gpt-4o: W=12, L=3, D=1
        assert "12" in output
        assert "16" in output  # total games


# ------------------------------------------------------------------
# JSON mode
# ------------------------------------------------------------------


class TestJsonMode:
    @patch("scripts.telemetry_report.mongo_queries")
    def test_json_flag_outputs_valid_json(self, mock_mq):
        mock_mq.win_rates.return_value = _sample_win_rates()
        mock_mq.violation_frequency.return_value = _sample_violations()
        mock_mq.fidelity_scores.return_value = _sample_fidelity()
        mock_mq.avg_latency.return_value = _sample_latency()

        db = _mock_db()
        buf = StringIO()
        print_report(db, as_json=True, file=buf)
        output = buf.getvalue()

        data = json.loads(output)
        assert "leaderboard" in data
        assert "violations" in data
        assert "fidelity" in data
        assert "latency" in data

    @patch("scripts.telemetry_report.mongo_queries")
    def test_json_leaderboard_has_expected_fields(self, mock_mq):
        mock_mq.win_rates.return_value = _sample_win_rates()
        mock_mq.violation_frequency.return_value = []
        mock_mq.fidelity_scores.return_value = []
        mock_mq.avg_latency.return_value = []

        db = _mock_db()
        buf = StringIO()
        print_report(db, as_json=True, file=buf)
        data = json.loads(buf.getvalue())

        assert len(data["leaderboard"]) == 2
        entry = data["leaderboard"][0]
        assert "model" in entry
        assert "wins" in entry
        assert "win_rate" in entry


# ------------------------------------------------------------------
# Empty data
# ------------------------------------------------------------------


class TestEmptyData:
    @patch("scripts.telemetry_report.mongo_queries")
    def test_empty_data_handled_gracefully(self, mock_mq):
        mock_mq.win_rates.return_value = []
        mock_mq.violation_frequency.return_value = []
        mock_mq.fidelity_scores.return_value = []
        mock_mq.avg_latency.return_value = []

        db = _mock_db()
        buf = StringIO()
        # Should not raise
        print_report(db, file=buf)
        output = buf.getvalue()
        assert "Report" in output

    @patch("scripts.telemetry_report.mongo_queries")
    def test_empty_json_has_all_keys(self, mock_mq):
        mock_mq.win_rates.return_value = []
        mock_mq.violation_frequency.return_value = []
        mock_mq.fidelity_scores.return_value = []
        mock_mq.avg_latency.return_value = []

        db = _mock_db()
        buf = StringIO()
        print_report(db, as_json=True, file=buf)
        data = json.loads(buf.getvalue())

        assert data["leaderboard"] == []
        assert data["violations"] == []
        assert data["fidelity"] == []
        assert data["latency"] == []


# ------------------------------------------------------------------
# Filters passed through
# ------------------------------------------------------------------


class TestFilterPassthrough:
    @patch("scripts.telemetry_report.mongo_queries")
    def test_event_filter_passed_to_queries(self, mock_mq):
        mock_mq.win_rates.return_value = []
        mock_mq.violation_frequency.return_value = []
        mock_mq.fidelity_scores.return_value = []
        mock_mq.avg_latency.return_value = []

        db = _mock_db()
        buf = StringIO()
        print_report(db, event_type="holdem", file=buf)

        mock_mq.win_rates.assert_called_once_with(db, event_type="holdem")
        mock_mq.fidelity_scores.assert_called_once_with(db, event_type="holdem")
        mock_mq.avg_latency.assert_called_once_with(db, event_type="holdem")

    @patch("scripts.telemetry_report.mongo_queries")
    def test_model_filter_passed_to_violations(self, mock_mq):
        mock_mq.win_rates.return_value = []
        mock_mq.violation_frequency.return_value = []
        mock_mq.fidelity_scores.return_value = []
        mock_mq.avg_latency.return_value = []

        db = _mock_db()
        buf = StringIO()
        print_report(db, model_id="gpt-4o", file=buf)

        mock_mq.violation_frequency.assert_called_once_with(db, model_id="gpt-4o")
