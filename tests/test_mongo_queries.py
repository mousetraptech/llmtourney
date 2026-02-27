"""Tests for mongo_queries — aggregation pipeline helpers."""

from unittest.mock import MagicMock, patch

import pytest

from llmtourney.core.mongo_queries import (
    avg_latency,
    fidelity_scores,
    get_db,
    head_to_head,
    latency_by_phase,
    token_efficiency,
    violation_frequency,
    win_rates,
)


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _mock_db():
    """Return a MagicMock that behaves like pymongo.database.Database."""
    db = MagicMock()
    return db


def _set_aggregate(db, collection_name, results):
    """Configure db[collection].aggregate() to return results."""
    db[collection_name].aggregate.return_value = iter(results)


def _set_find(db, collection_name, results):
    """Configure db[collection].find() to return results."""
    db[collection_name].find.return_value = iter(results)


# ------------------------------------------------------------------
# get_db
# ------------------------------------------------------------------


class TestGetDb:
    def test_returns_database(self):
        with patch("pymongo.MongoClient") as MockClient:
            mock_client = MagicMock()
            MockClient.return_value = mock_client
            mock_db = MagicMock()
            mock_client.__getitem__ = MagicMock(return_value=mock_db)

            result = get_db(uri="mongodb://localhost:27017", db_name="testdb")
            MockClient.assert_called_once_with("mongodb://localhost:27017")
            mock_client.__getitem__.assert_called_once_with("testdb")
            assert result is mock_db

    def test_falls_back_to_env_var(self):
        with patch("pymongo.MongoClient") as MockClient, \
             patch.dict("os.environ", {"TOURNEY_MONGO_URI": "mongodb://env:27017"}):
            mock_client = MagicMock()
            MockClient.return_value = mock_client
            mock_db = MagicMock()
            mock_client.__getitem__ = MagicMock(return_value=mock_db)

            result = get_db()
            MockClient.assert_called_once_with("mongodb://env:27017")

    def test_raises_without_uri_or_env(self):
        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(ValueError, match="No MongoDB URI"):
                get_db()


# ------------------------------------------------------------------
# win_rates
# ------------------------------------------------------------------


class TestWinRates:
    def test_basic_pipeline(self):
        db = _mock_db()
        _set_aggregate(db, "matches", [
            {"_id": {"model": "gpt-4o", "event_type": "holdem"},
             "wins": 5, "losses": 2, "draws": 1, "total": 8, "win_rate": 0.625},
            {"_id": {"model": "sonnet", "event_type": "holdem"},
             "wins": 2, "losses": 5, "draws": 1, "total": 8, "win_rate": 0.25},
        ])

        result = win_rates(db)
        assert len(result) == 2
        assert result[0]["win_rate"] >= result[1]["win_rate"]
        db["matches"].aggregate.assert_called_once()

    def test_filters_by_model(self):
        db = _mock_db()
        _set_aggregate(db, "matches", [
            {"_id": {"model": "gpt-4o", "event_type": "holdem"},
             "wins": 5, "losses": 2, "draws": 1, "total": 8, "win_rate": 0.625},
        ])

        result = win_rates(db, model_id="gpt-4o")
        pipeline = db["matches"].aggregate.call_args[0][0]
        # Should have a $match stage that filters on models
        match_stages = [s for s in pipeline if "$match" in s]
        assert len(match_stages) > 0
        # At least one match stage should reference models
        found_model_filter = any(
            "models" in str(s) for s in match_stages
        )
        assert found_model_filter

    def test_filters_by_event_type(self):
        db = _mock_db()
        _set_aggregate(db, "matches", [])

        win_rates(db, event_type="holdem")
        pipeline = db["matches"].aggregate.call_args[0][0]
        match_stages = [s for s in pipeline if "$match" in s]
        found_event_filter = any(
            "event_type" in str(s) for s in match_stages
        )
        assert found_event_filter

    def test_filters_by_tier(self):
        db = _mock_db()
        _set_aggregate(db, "matches", [])

        win_rates(db, tier="midtier")
        pipeline = db["matches"].aggregate.call_args[0][0]
        match_stages = [s for s in pipeline if "$match" in s]
        found_tier_filter = any(
            "tier" in str(s) for s in match_stages
        )
        assert found_tier_filter


# ------------------------------------------------------------------
# avg_latency
# ------------------------------------------------------------------


class TestAvgLatency:
    def test_basic_pipeline(self):
        db = _mock_db()
        _set_aggregate(db, "turns", [
            {"_id": {"model_id": "gpt-4o", "event_type": "holdem"},
             "avg_ms": 120.5, "min_ms": 50.0, "max_ms": 300.0},
        ])

        result = avg_latency(db)
        assert len(result) == 1
        assert result[0]["avg_ms"] == 120.5
        db["turns"].aggregate.assert_called_once()

    def test_filters_by_model_and_event(self):
        db = _mock_db()
        _set_aggregate(db, "turns", [])

        avg_latency(db, model_id="gpt-4o", event_type="holdem")
        pipeline = db["turns"].aggregate.call_args[0][0]
        match_stages = [s for s in pipeline if "$match" in s]
        assert len(match_stages) > 0

    def test_filters_by_tournament_name(self):
        db = _mock_db()
        _set_aggregate(db, "turns", [])

        avg_latency(db, tournament_name="season-1")
        pipeline = db["turns"].aggregate.call_args[0][0]
        match_stages = [s for s in pipeline if "$match" in s]
        found_tourney = any(
            "tournament_name" in str(s) for s in match_stages
        )
        assert found_tourney

    def test_sorted_by_avg_ascending(self):
        db = _mock_db()
        _set_aggregate(db, "turns", [
            {"_id": {"model_id": "fast", "event_type": "holdem"}, "avg_ms": 50.0, "min_ms": 10.0, "max_ms": 100.0},
            {"_id": {"model_id": "slow", "event_type": "holdem"}, "avg_ms": 500.0, "min_ms": 200.0, "max_ms": 900.0},
        ])

        result = avg_latency(db)
        pipeline = db["turns"].aggregate.call_args[0][0]
        sort_stages = [s for s in pipeline if "$sort" in s]
        assert len(sort_stages) > 0
        assert sort_stages[-1]["$sort"]["avg_ms"] == 1  # ascending


# ------------------------------------------------------------------
# violation_frequency
# ------------------------------------------------------------------


class TestViolationFrequency:
    def test_basic_pipeline(self):
        db = _mock_db()
        _set_aggregate(db, "turns", [
            {"_id": {"model_id": "gpt-4o", "violation": "illegal_move"}, "count": 5},
        ])

        result = violation_frequency(db)
        assert len(result) == 1
        assert result[0]["count"] == 5

    def test_filters_non_null_violations(self):
        db = _mock_db()
        _set_aggregate(db, "turns", [])

        violation_frequency(db)
        pipeline = db["turns"].aggregate.call_args[0][0]
        match_stages = [s for s in pipeline if "$match" in s]
        # Should filter for violation != null
        found_violation_filter = any(
            "violation" in str(s) for s in match_stages
        )
        assert found_violation_filter

    def test_filters_by_model(self):
        db = _mock_db()
        _set_aggregate(db, "turns", [])

        violation_frequency(db, model_id="gpt-4o")
        pipeline = db["turns"].aggregate.call_args[0][0]
        match_stages = [s for s in pipeline if "$match" in s]
        found_model = any(
            "model_id" in str(s) for s in match_stages
        )
        assert found_model

    def test_sorted_by_count_desc(self):
        db = _mock_db()
        _set_aggregate(db, "turns", [])

        violation_frequency(db)
        pipeline = db["turns"].aggregate.call_args[0][0]
        sort_stages = [s for s in pipeline if "$sort" in s]
        assert len(sort_stages) > 0
        assert sort_stages[-1]["$sort"]["count"] == -1  # descending


# ------------------------------------------------------------------
# head_to_head
# ------------------------------------------------------------------


class TestHeadToHead:
    def test_counts_wins_losses_draws(self):
        db = _mock_db()
        _set_find(db, "matches", [
            {"match_id": "m1", "models": ["gpt-4o", "sonnet"], "winner": "gpt-4o"},
            {"match_id": "m2", "models": ["gpt-4o", "sonnet"], "winner": "sonnet"},
            {"match_id": "m3", "models": ["gpt-4o", "sonnet"], "winner": "gpt-4o"},
            {"match_id": "m4", "models": ["gpt-4o", "sonnet"], "winner": None},
        ])

        result = head_to_head(db, "gpt-4o", "sonnet")
        assert result["gpt-4o"] == 2
        assert result["sonnet"] == 1
        assert result["draws"] == 1
        assert sorted(result["matches"]) == ["m1", "m2", "m3", "m4"]

    def test_queries_both_models(self):
        db = _mock_db()
        _set_find(db, "matches", [])

        head_to_head(db, "gpt-4o", "sonnet")
        find_call = db["matches"].find.call_args[0][0]
        # Should query for matches containing both models
        assert "models" in find_call or "$and" in find_call

    def test_with_event_type_filter(self):
        db = _mock_db()
        _set_find(db, "matches", [])

        head_to_head(db, "gpt-4o", "sonnet", event_type="holdem")
        find_call = db["matches"].find.call_args[0][0]
        assert "event_type" in find_call

    def test_all_draws(self):
        db = _mock_db()
        _set_find(db, "matches", [
            {"match_id": "m1", "models": ["a", "b"], "winner": None},
            {"match_id": "m2", "models": ["a", "b"], "winner": None},
        ])

        result = head_to_head(db, "a", "b")
        assert result["a"] == 0
        assert result["b"] == 0
        assert result["draws"] == 2

    def test_no_matches(self):
        db = _mock_db()
        _set_find(db, "matches", [])

        result = head_to_head(db, "a", "b")
        assert result["a"] == 0
        assert result["b"] == 0
        assert result["draws"] == 0
        assert result["matches"] == []


# ------------------------------------------------------------------
# latency_by_phase
# ------------------------------------------------------------------


class TestLatencyByPhase:
    def test_basic_pipeline(self):
        db = _mock_db()
        _set_aggregate(db, "turns", [
            {"_id": "early", "avg_ms": 100.0},
            {"_id": "mid", "avg_ms": 150.0},
            {"_id": "late", "avg_ms": 200.0},
        ])

        result = latency_by_phase(db, "gpt-4o", "holdem")
        assert len(result) == 3
        db["turns"].aggregate.assert_called_once()

    def test_pipeline_uses_percentile_thirds(self):
        """Pipeline should assign phases based on percentile of max turn per match."""
        db = _mock_db()
        _set_aggregate(db, "turns", [])

        latency_by_phase(db, "gpt-4o", "holdem")
        pipeline = db["turns"].aggregate.call_args[0][0]
        pipeline_str = str(pipeline)
        # Should reference phase assignment logic
        assert "early" in pipeline_str
        assert "mid" in pipeline_str
        assert "late" in pipeline_str


# ------------------------------------------------------------------
# token_efficiency
# ------------------------------------------------------------------


class TestTokenEfficiency:
    def test_basic_pipeline(self):
        db = _mock_db()
        _set_aggregate(db, "matches", [
            {"_id": "gpt-4o", "avg_tokens": 5000, "avg_turns": 20,
             "tokens_per_turn": 250.0, "wins": 5, "total": 8, "win_rate": 0.625},
        ])

        result = token_efficiency(db)
        assert len(result) == 1
        assert result[0]["tokens_per_turn"] == 250.0
        db["matches"].aggregate.assert_called_once()

    def test_sorted_by_win_rate_desc(self):
        db = _mock_db()
        _set_aggregate(db, "matches", [])

        token_efficiency(db)
        pipeline = db["matches"].aggregate.call_args[0][0]
        sort_stages = [s for s in pipeline if "$sort" in s]
        assert len(sort_stages) > 0
        assert sort_stages[-1]["$sort"]["win_rate"] == -1

    def test_filters_by_model(self):
        db = _mock_db()
        _set_aggregate(db, "matches", [])

        token_efficiency(db, model_id="gpt-4o")
        pipeline = db["matches"].aggregate.call_args[0][0]
        match_stages = [s for s in pipeline if "$match" in s]
        found_model = any("models" in str(s) for s in match_stages)
        assert found_model

    def test_filters_by_event_type(self):
        db = _mock_db()
        _set_aggregate(db, "matches", [])

        token_efficiency(db, event_type="holdem")
        pipeline = db["matches"].aggregate.call_args[0][0]
        match_stages = [s for s in pipeline if "$match" in s]
        found_event = any("event_type" in str(s) for s in match_stages)
        assert found_event


# ------------------------------------------------------------------
# fidelity_scores
# ------------------------------------------------------------------


class TestFidelityScores:
    def test_basic_pipeline(self):
        db = _mock_db()
        _set_aggregate(db, "matches", [
            {"_id": "gpt-4o", "total_matches": 10, "total_violations": 2,
             "clean_matches": 8, "clean_pct": 80.0},
        ])

        result = fidelity_scores(db)
        assert len(result) == 1
        assert result[0]["clean_pct"] == 80.0
        db["matches"].aggregate.assert_called_once()

    def test_sorted_cleanest_first(self):
        db = _mock_db()
        _set_aggregate(db, "matches", [])

        fidelity_scores(db)
        pipeline = db["matches"].aggregate.call_args[0][0]
        sort_stages = [s for s in pipeline if "$sort" in s]
        assert len(sort_stages) > 0
        # Cleanest first = descending clean_pct
        assert sort_stages[-1]["$sort"]["clean_pct"] == -1

    def test_filters_by_event_type(self):
        db = _mock_db()
        _set_aggregate(db, "matches", [])

        fidelity_scores(db, event_type="holdem")
        pipeline = db["matches"].aggregate.call_args[0][0]
        match_stages = [s for s in pipeline if "$match" in s]
        found_event = any("event_type" in str(s) for s in match_stages)
        assert found_event

    def test_filters_by_tier(self):
        db = _mock_db()
        _set_aggregate(db, "matches", [])

        fidelity_scores(db, tier="midtier")
        pipeline = db["matches"].aggregate.call_args[0][0]
        match_stages = [s for s in pipeline if "$match" in s]
        found_tier = any("tier" in str(s) for s in match_stages)
        assert found_tier
