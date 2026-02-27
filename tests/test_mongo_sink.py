"""Tests for MongoSink — background MongoDB writer with queue."""

import hashlib
import time
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch, call

import pytest

from llmtourney.core.telemetry import TelemetryEntry


def _make_entry(
    turn_number: int = 1,
    hand_number: int = 1,
    player_id: str = "player_a",
    model_id: str = "mock-v1",
    prompt: str = "Your turn",
    input_tokens: int = 50,
    output_tokens: int = 5,
    violation: str | None = None,
) -> TelemetryEntry:
    return TelemetryEntry(
        turn_number=turn_number,
        hand_number=hand_number,
        street="preflop",
        player_id=player_id,
        model_id=model_id,
        model_version=model_id,
        prompt=prompt,
        raw_output='{"action": "call"}',
        reasoning_output=None,
        parsed_action={"action": "call"},
        parse_success=True,
        validation_result="ok",
        violation=violation,
        ruling=None,
        state_snapshot={"pot": 4},
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        latency_ms=12.3,
        engine_version="0.1.0",
        prompt_version="holdem-v1",
    )


def _make_context(
    event_type: str = "holdem",
    tournament_name: str = "test-tourney",
    tier: str = "midtier",
    round: int = 1,
) -> dict:
    return {
        "event_type": event_type,
        "tournament_name": tournament_name,
        "tier": tier,
        "round": round,
    }


@pytest.fixture
def mock_client_class():
    """Patch pymongo.MongoClient and return (MongoSink class, mock_client_instance)."""
    with patch("llmtourney.core.mongo_sink.MongoClient") as MockClientClass:
        mock_client = MagicMock()
        MockClientClass.return_value = mock_client
        # Successful ping
        mock_client.admin.command.return_value = {"ok": 1}
        # Mock database and collections
        mock_db = MagicMock()
        mock_client.__getitem__ = MagicMock(return_value=mock_db)
        mock_collection = MagicMock()
        mock_db.__getitem__ = MagicMock(return_value=mock_collection)

        from llmtourney.core.mongo_sink import MongoSink
        yield MongoSink, mock_client, mock_db, mock_collection


class TestMongoSinkInit:
    def test_creates_indexes_on_init(self, mock_client_class):
        MongoSink, mock_client, mock_db, mock_col = mock_client_class
        sink = MongoSink("mongodb://localhost:27017", "testdb")
        # Should have called create_index multiple times for turns, matches, tournaments
        assert mock_col.create_index.call_count > 0
        sink.close()

    def test_disabled_when_connection_fails(self):
        with patch("llmtourney.core.mongo_sink.MongoClient") as MockClientClass:
            mock_client = MagicMock()
            MockClientClass.return_value = mock_client
            # Simulate connection failure
            from pymongo.errors import ConnectionFailure
            mock_client.admin.command.side_effect = ConnectionFailure("cannot connect")

            from llmtourney.core.mongo_sink import MongoSink
            sink = MongoSink("mongodb://localhost:27017", "testdb")
            assert sink._disabled is True
            sink.close()

    def test_disabled_when_server_selection_timeout(self):
        with patch("llmtourney.core.mongo_sink.MongoClient") as MockClientClass:
            mock_client = MagicMock()
            MockClientClass.return_value = mock_client
            from pymongo.errors import ServerSelectionTimeoutError
            mock_client.admin.command.side_effect = ServerSelectionTimeoutError("timeout")

            from llmtourney.core.mongo_sink import MongoSink
            sink = MongoSink("mongodb://localhost:27017", "testdb")
            assert sink._disabled is True
            sink.close()


class TestLogTurn:
    def test_turn_has_required_fields(self, mock_client_class):
        MongoSink, mock_client, mock_db, mock_col = mock_client_class
        sink = MongoSink("mongodb://localhost:27017", "testdb")
        entry = _make_entry()
        ctx = _make_context()

        sink.log_turn("match-001", entry, ctx)
        # Wait for background thread to process
        sink.close()

        # Find the insert_many call for turns
        insert_calls = mock_col.insert_many.call_args_list
        assert len(insert_calls) > 0
        docs = insert_calls[0][0][0]  # first positional arg of first call
        assert len(docs) == 1
        doc = docs[0]

        assert doc["match_id"] == "match-001"
        assert doc["model_id"] == "mock-v1"
        assert doc["player_id"] == "player_a"
        assert doc["turn_number"] == 1
        assert doc["event_type"] == "holdem"
        assert doc["tournament_name"] == "test-tourney"
        assert doc["tier"] == "midtier"
        assert doc["round"] == 1
        assert "_ingested_at" in doc
        assert isinstance(doc["_ingested_at"], datetime)
        assert doc["schema_version"] == "1.1.0"

    def test_prompt_excluded_by_default(self, mock_client_class):
        MongoSink, mock_client, mock_db, mock_col = mock_client_class
        sink = MongoSink("mongodb://localhost:27017", "testdb")
        entry = _make_entry(prompt="This is a long prompt")
        ctx = _make_context()

        sink.log_turn("match-001", entry, ctx)
        sink.close()

        insert_calls = mock_col.insert_many.call_args_list
        docs = insert_calls[0][0][0]
        doc = docs[0]

        # Prompt should be replaced with hash/chars/tokens
        assert "prompt" not in doc or not isinstance(doc["prompt"], str)
        assert doc["prompt"]["prompt_hash"] == hashlib.sha256(
            "This is a long prompt".encode()
        ).hexdigest()
        assert doc["prompt"]["prompt_chars"] == len("This is a long prompt")
        assert doc["prompt"]["prompt_tokens"] == 50  # input_tokens

    def test_prompt_included_when_store_prompts_true(self, mock_client_class):
        MongoSink, mock_client, mock_db, mock_col = mock_client_class
        sink = MongoSink(
            "mongodb://localhost:27017", "testdb", store_prompts=True
        )
        entry = _make_entry(prompt="Full prompt text here")
        ctx = _make_context()

        sink.log_turn("match-001", entry, ctx)
        sink.close()

        insert_calls = mock_col.insert_many.call_args_list
        docs = insert_calls[0][0][0]
        doc = docs[0]

        assert doc["prompt"] == "Full prompt text here"

    def test_noop_when_disabled(self):
        with patch("llmtourney.core.mongo_sink.MongoClient") as MockClientClass:
            mock_client = MagicMock()
            MockClientClass.return_value = mock_client
            from pymongo.errors import ConnectionFailure
            mock_client.admin.command.side_effect = ConnectionFailure("nope")

            from llmtourney.core.mongo_sink import MongoSink
            sink = MongoSink("mongodb://localhost:27017", "testdb")
            assert sink._disabled is True

            # These should all no-op without error
            entry = _make_entry()
            ctx = _make_context()
            sink.log_turn("match-001", entry, ctx)
            sink.finalize_match(
                "match-001",
                scores={"player_a": 10, "player_b": 5},
                fidelity={},
                player_models={"player_a": "model-a", "player_b": "model-b"},
                tournament_context=ctx,
            )
            sink.close()

            # No insert_many or update_one should have been called
            mock_client.__getitem__.assert_not_called()

    def test_batching_multiple_turns(self, mock_client_class):
        MongoSink, mock_client, mock_db, mock_col = mock_client_class
        sink = MongoSink("mongodb://localhost:27017", "testdb")
        ctx = _make_context()

        # Log multiple turns quickly
        for i in range(5):
            sink.log_turn(f"match-001", _make_entry(turn_number=i + 1), ctx)

        sink.close()

        # All 5 turns should have been written (possibly in one or more batches)
        total_docs = 0
        for c in mock_col.insert_many.call_args_list:
            total_docs += len(c[0][0])
        assert total_docs == 5


class TestFinalizeMatch:
    def test_writes_match_doc_and_model_stats(self, mock_client_class):
        MongoSink, mock_client, mock_db, mock_col = mock_client_class
        sink = MongoSink("mongodb://localhost:27017", "testdb")
        ctx = _make_context()

        sink.finalize_match(
            match_id="match-001",
            scores={"player_a": 10, "player_b": 5},
            fidelity={"player_a": {"total_violations": 0}, "player_b": {"total_violations": 2}},
            player_models={"player_a": "gpt-4o", "player_b": "claude-sonnet-4.5"},
            tournament_context=ctx,
        )
        sink.close()

        # Should have update_one calls for match doc and model stats
        update_calls = mock_col.update_one.call_args_list
        assert len(update_calls) >= 1  # at least match doc

    def test_winner_derivation_clear_winner(self, mock_client_class):
        MongoSink, mock_client, mock_db, mock_col = mock_client_class
        sink = MongoSink("mongodb://localhost:27017", "testdb")
        ctx = _make_context()

        sink.finalize_match(
            match_id="match-001",
            scores={"player_a": 10, "player_b": 5},
            fidelity={},
            player_models={"player_a": "gpt-4o", "player_b": "claude-sonnet-4.5"},
            tournament_context=ctx,
        )
        sink.close()

        # Find the match upsert call — look for one with match_id filter
        match_upsert = None
        for c in mock_col.update_one.call_args_list:
            filter_arg = c[0][0]  # first positional arg (filter)
            if "match_id" in filter_arg:
                match_upsert = c
                break

        assert match_upsert is not None
        update_doc = match_upsert[0][1]  # second positional arg (update)
        set_doc = update_doc.get("$set", update_doc)
        assert set_doc["winner"] == "gpt-4o"

    def test_winner_derivation_tie(self, mock_client_class):
        MongoSink, mock_client, mock_db, mock_col = mock_client_class
        sink = MongoSink("mongodb://localhost:27017", "testdb")
        ctx = _make_context()

        sink.finalize_match(
            match_id="match-002",
            scores={"player_a": 10, "player_b": 10},
            fidelity={},
            player_models={"player_a": "gpt-4o", "player_b": "claude-sonnet-4.5"},
            tournament_context=ctx,
        )
        sink.close()

        match_upsert = None
        for c in mock_col.update_one.call_args_list:
            filter_arg = c[0][0]
            if "match_id" in filter_arg:
                match_upsert = c
                break

        assert match_upsert is not None
        update_doc = match_upsert[0][1]
        set_doc = update_doc.get("$set", update_doc)
        assert set_doc["winner"] is None

    def test_model_stats_inc_pattern(self, mock_client_class):
        MongoSink, mock_client, mock_db, mock_col = mock_client_class
        sink = MongoSink("mongodb://localhost:27017", "testdb")
        ctx = _make_context()

        sink.finalize_match(
            match_id="match-001",
            scores={"player_a": 10, "player_b": 5},
            fidelity={
                "player_a": {"total_violations": 0},
                "player_b": {"total_violations": 2},
            },
            player_models={"player_a": "gpt-4o", "player_b": "claude-sonnet-4.5"},
            tournament_context=ctx,
        )
        sink.close()

        # Find model stat update calls — look for $inc pattern
        inc_calls = [
            c for c in mock_col.update_one.call_args_list
            if "$inc" in c[0][1]  # second positional arg has $inc
        ]
        assert len(inc_calls) == 2  # one per model


class TestContextManager:
    def test_context_manager_calls_close(self, mock_client_class):
        MongoSink, mock_client, mock_db, mock_col = mock_client_class

        with MongoSink("mongodb://localhost:27017", "testdb") as sink:
            assert sink._disabled is False
        # After exiting, the thread should have been joined
        # (close was called implicitly)
        assert not sink._thread.is_alive()


class TestClose:
    def test_close_drains_queue(self, mock_client_class):
        MongoSink, mock_client, mock_db, mock_col = mock_client_class
        sink = MongoSink("mongodb://localhost:27017", "testdb")
        ctx = _make_context()

        # Enqueue items then close
        for i in range(3):
            sink.log_turn(f"match-001", _make_entry(turn_number=i + 1), ctx)
        sink.close()

        total_docs = 0
        for c in mock_col.insert_many.call_args_list:
            total_docs += len(c[0][0])
        assert total_docs == 3

    def test_close_idempotent(self, mock_client_class):
        MongoSink, mock_client, mock_db, mock_col = mock_client_class
        sink = MongoSink("mongodb://localhost:27017", "testdb")
        sink.close()
        sink.close()  # should not raise


class TestErrorHandling:
    def test_insert_many_error_does_not_raise(self, mock_client_class):
        MongoSink, mock_client, mock_db, mock_col = mock_client_class
        from pymongo.errors import PyMongoError
        mock_col.insert_many.side_effect = PyMongoError("write failed")

        sink = MongoSink("mongodb://localhost:27017", "testdb")
        ctx = _make_context()

        # Should not raise
        sink.log_turn("match-001", _make_entry(), ctx)
        sink.close()

    def test_update_one_error_does_not_raise(self, mock_client_class):
        MongoSink, mock_client, mock_db, mock_col = mock_client_class
        from pymongo.errors import PyMongoError
        mock_col.update_one.side_effect = PyMongoError("update failed")

        sink = MongoSink("mongodb://localhost:27017", "testdb")
        ctx = _make_context()

        # Should not raise
        sink.finalize_match(
            match_id="match-001",
            scores={"player_a": 10, "player_b": 5},
            fidelity={},
            player_models={"player_a": "gpt-4o", "player_b": "claude-sonnet-4.5"},
            tournament_context=ctx,
        )
        sink.close()
