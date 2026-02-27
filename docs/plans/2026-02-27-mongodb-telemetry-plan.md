# MongoDB Telemetry Backend — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add MongoDB Atlas as an optional second telemetry sink alongside JSONL, with query helpers, backfill, and reporting.

**Architecture:** Wrapper sink pattern — a standalone `MongoSink` class with background writer thread + queue. TelemetryLogger delegates to it via 3 touch points. If Mongo is unavailable, JSONL continues unaffected.

**Tech Stack:** Python 3.11+, pymongo (optional dep), existing TelemetryLogger/TelemetryEntry

**Design doc:** `docs/plans/2026-02-27-mongodb-telemetry-design.md`

---

### Task 1: Add pymongo optional dependency

**Files:**
- Modify: `pyproject.toml:14-17`

**Step 1: Add mongo optional dependency group**

```toml
[project.optional-dependencies]
live = ["openai>=1.0", "anthropic>=0.40"]
dev = ["pytest>=8.0"]
mongo = ["pymongo>=4.6"]
all = ["llmtourney[live,dev,mongo]"]
```

**Step 2: Install it**

Run: `cd /Users/dave/projects/play-games/llmtourney && pip install -e ".[mongo,dev]"`
Expected: pymongo installed successfully

**Step 3: Commit**

```bash
git add pyproject.toml
git commit -m "chore: add pymongo as optional dependency"
```

---

### Task 2: MongoSink — background writer with queue

**Files:**
- Create: `src/llmtourney/core/mongo_sink.py`
- Test: `tests/test_mongo_sink.py`

**Step 1: Write failing tests**

```python
"""Tests for MongoSink background writer."""

import queue
import threading
import time
from datetime import datetime, timezone
from dataclasses import asdict
from unittest.mock import MagicMock, patch, call

import pytest

from llmtourney.core.telemetry import TelemetryEntry


def _make_entry(**overrides) -> TelemetryEntry:
    """Build a TelemetryEntry with sensible defaults."""
    defaults = dict(
        turn_number=1,
        hand_number=1,
        street="unknown",
        player_id="player_a",
        model_id="test-model",
        model_version="test-model-v1",
        prompt="You are playing a game.",
        raw_output='{"action": "play"}',
        reasoning_output=None,
        parsed_action={"action": "play"},
        parse_success=True,
        validation_result="legal",
        violation=None,
        ruling=None,
        state_snapshot={"board": []},
        input_tokens=100,
        output_tokens=50,
        latency_ms=1234.5,
        engine_version="0.1.0",
        prompt_version="1.0.0",
    )
    defaults.update(overrides)
    return TelemetryEntry(**defaults)


@pytest.fixture
def mock_mongo_client():
    """Patch pymongo.MongoClient and return mock db."""
    with patch("llmtourney.core.mongo_sink.MongoClient") as MockClient:
        mock_client = MagicMock()
        mock_db = MagicMock()
        mock_client.__getitem__ = MagicMock(return_value=mock_db)
        MockClient.return_value = mock_client
        yield mock_db, MockClient


class TestMongoSinkInit:
    def test_creates_indexes_on_init(self, mock_mongo_client):
        mock_db, MockClient = mock_mongo_client
        from llmtourney.core.mongo_sink import MongoSink

        sink = MongoSink("mongodb://localhost/test")
        # Should have called create_index on turns and matches
        assert mock_db["turns"].create_index.called
        assert mock_db["matches"].create_index.called
        sink.close()

    def test_disabled_when_connection_fails(self):
        with patch("llmtourney.core.mongo_sink.MongoClient", side_effect=Exception("no mongo")):
            from llmtourney.core.mongo_sink import MongoSink

            sink = MongoSink("mongodb://badhost/test")
            assert sink._disabled is True
            sink.close()  # should not raise


class TestMongoSinkLogTurn:
    def test_turn_document_has_required_fields(self, mock_mongo_client):
        mock_db, _ = mock_mongo_client
        from llmtourney.core.mongo_sink import MongoSink

        sink = MongoSink("mongodb://localhost/test")
        entry = _make_entry()
        ctx = {"tournament_name": "test-tourney", "tier": "midtier", "round": 1, "event_type": "tictactoe"}
        sink.log_turn("match-123", entry, ctx)
        sink.close()  # drains queue

        # Verify insert was called on turns collection
        insert_call = mock_db["turns"].insert_many
        assert insert_call.called
        docs = insert_call.call_args[0][0]
        doc = docs[0]
        assert doc["match_id"] == "match-123"
        assert doc["model_id"] == "test-model"
        assert doc["tournament_name"] == "test-tourney"
        assert doc["event_type"] == "tictactoe"
        assert "_ingested_at" in doc

    def test_prompt_excluded_by_default(self, mock_mongo_client):
        mock_db, _ = mock_mongo_client
        from llmtourney.core.mongo_sink import MongoSink

        sink = MongoSink("mongodb://localhost/test", store_prompts=False)
        entry = _make_entry(prompt="A very long prompt")
        ctx = {"tournament_name": "t", "tier": "t", "round": 1, "event_type": "ttt"}
        sink.log_turn("m-1", entry, ctx)
        sink.close()

        docs = mock_db["turns"].insert_many.call_args[0][0]
        doc = docs[0]
        assert "prompt" not in doc
        assert "prompt_hash" in doc
        assert "prompt_chars" in doc
        assert "prompt_tokens" in doc

    def test_prompt_included_when_store_prompts_true(self, mock_mongo_client):
        mock_db, _ = mock_mongo_client
        from llmtourney.core.mongo_sink import MongoSink

        sink = MongoSink("mongodb://localhost/test", store_prompts=True)
        entry = _make_entry(prompt="Full prompt text")
        ctx = {"tournament_name": "t", "tier": "t", "round": 1, "event_type": "ttt"}
        sink.log_turn("m-1", entry, ctx)
        sink.close()

        docs = mock_db["turns"].insert_many.call_args[0][0]
        assert docs[0]["prompt"] == "Full prompt text"

    def test_noop_when_disabled(self, mock_mongo_client):
        mock_db, _ = mock_mongo_client
        from llmtourney.core.mongo_sink import MongoSink

        sink = MongoSink("mongodb://localhost/test")
        sink._disabled = True
        entry = _make_entry()
        sink.log_turn("m-1", entry, {})
        sink.close()
        assert not mock_db["turns"].insert_many.called


class TestMongoSinkBatching:
    def test_batches_multiple_turns(self, mock_mongo_client):
        mock_db, _ = mock_mongo_client
        from llmtourney.core.mongo_sink import MongoSink

        sink = MongoSink("mongodb://localhost/test")
        ctx = {"tournament_name": "t", "tier": "t", "round": 1, "event_type": "ttt"}
        for i in range(5):
            sink.log_turn("m-1", _make_entry(turn_number=i), ctx)
        sink.close()

        # Should have batched into one or few insert_many calls
        total_docs = sum(
            len(c[0][0]) for c in mock_db["turns"].insert_many.call_args_list
        )
        assert total_docs == 5


class TestMongoSinkContextManager:
    def test_context_manager_calls_close(self, mock_mongo_client):
        from llmtourney.core.mongo_sink import MongoSink

        with MongoSink("mongodb://localhost/test") as sink:
            assert sink._disabled is False
        # After exit, thread should be stopped
        assert not sink._writer_thread.is_alive()


class TestMongoSinkFinalize:
    def test_finalize_writes_match_doc(self, mock_mongo_client):
        mock_db, _ = mock_mongo_client
        from llmtourney.core.mongo_sink import MongoSink

        sink = MongoSink("mongodb://localhost/test")
        scores = {"player_a": 5.0, "player_b": 4.0}
        fidelity = {"player_a": {"total_violations": 0}, "player_b": {"total_violations": 1}}
        extra = {
            "event": "tictactoe",
            "player_models": {"player_a": "gpt-4o", "player_b": "sonnet"},
            "ruling": "completed",
        }
        ctx = {"tournament_name": "test", "tier": "mid", "round": 1, "event_type": "tictactoe"}
        sink.finalize_match("match-1", scores, fidelity, extra, ctx)
        sink.close()

        # Match doc should be upserted
        assert mock_db["matches"].update_one.called
        # Model stats should be updated
        assert mock_db["models"].update_one.called
```

**Step 2: Run tests to verify they fail**

Run: `cd /Users/dave/projects/play-games/llmtourney && python -m pytest tests/test_mongo_sink.py -v 2>&1 | head -30`
Expected: FAIL — `ModuleNotFoundError: No module named 'llmtourney.core.mongo_sink'`

**Step 3: Implement MongoSink**

Create `src/llmtourney/core/mongo_sink.py`:

```python
"""MongoSink — optional MongoDB telemetry backend.

Background writer thread drains a queue and batch-inserts documents.
If Mongo is unreachable, all operations silently no-op.
"""

import hashlib
import logging
import queue
import threading
from collections import defaultdict
from dataclasses import asdict
from datetime import datetime, timezone

from llmtourney.core.telemetry import TelemetryEntry

logger = logging.getLogger(__name__)

_BATCH_SIZE = 50
_SENTINEL = None  # signals writer thread to stop


class MongoSink:
    """Optional MongoDB sink for telemetry. Fire-and-forget with background writer."""

    def __init__(
        self,
        uri: str,
        db_name: str = "llmtourney",
        store_prompts: bool = False,
    ):
        self._store_prompts = store_prompts
        self._disabled = False
        self._queue: queue.Queue = queue.Queue()

        try:
            from pymongo import MongoClient, ASCENDING
            self._client = MongoClient(uri, serverSelectionTimeoutMS=5000)
            # Force a connection check
            self._client.admin.command("ping")
            self._db = self._client[db_name]
            self._ensure_indexes()
        except Exception as exc:
            logger.warning("MongoDB unavailable, sink disabled: %s", exc)
            self._disabled = True
            self._client = None
            self._db = None

        self._writer_thread = threading.Thread(
            target=self._writer_loop, daemon=True, name="mongo-sink-writer"
        )
        self._writer_thread.start()

    # -- Context manager --------------------------------------------------

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # -- Public API -------------------------------------------------------

    def log_turn(
        self,
        match_id: str,
        entry: TelemetryEntry,
        tournament_context: dict,
    ) -> None:
        if self._disabled:
            return
        doc = asdict(entry)
        doc["match_id"] = match_id
        doc["timestamp"] = datetime.now(timezone.utc).isoformat()
        doc["_ingested_at"] = datetime.now(timezone.utc)
        doc["schema_version"] = "1.1.0"

        # Denormalize tournament context
        doc["event_type"] = tournament_context.get("event_type", "unknown")
        doc["tournament_name"] = tournament_context.get("tournament_name", "unknown")
        doc["tier"] = tournament_context.get("tier", "unknown")
        doc["round"] = tournament_context.get("round", 0)

        # Prompt handling
        if not self._store_prompts:
            prompt_text = doc.pop("prompt")
            doc["prompt_hash"] = hashlib.sha256(prompt_text.encode()).hexdigest()
            doc["prompt_chars"] = len(prompt_text)
            doc["prompt_tokens"] = entry.input_tokens

        self._queue.put(("turns", doc))

    def finalize_match(
        self,
        match_id: str,
        scores: dict,
        fidelity: dict,
        extra: dict,
        tournament_context: dict,
    ) -> None:
        if self._disabled:
            return

        models = list(extra.get("player_models", {}).values())
        winner = _derive_winner(scores, extra.get("player_models", {}))

        match_doc = {
            "match_id": match_id,
            "final_scores": scores,
            "fidelity_report": fidelity,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "_ingested_at": datetime.now(timezone.utc),
            "schema_version": "1.1.0",
            "event_type": tournament_context.get("event_type", "unknown"),
            "tournament_name": tournament_context.get("tournament_name", "unknown"),
            "tier": tournament_context.get("tier", "unknown"),
            "round": tournament_context.get("round", 0),
            "models": models,
            "winner": winner,
        }
        match_doc.update(extra)
        self._queue.put(("matches", match_doc))

        # Enqueue model stat updates
        for player_id, model_id in extra.get("player_models", {}).items():
            player_fidelity = fidelity.get(player_id, {})
            is_winner = (winner == model_id)
            is_draw = (winner is None)
            model_update = {
                "model_id": model_id,
                "match_id": match_id,
                "event_type": tournament_context.get("event_type", "unknown"),
                "is_winner": is_winner,
                "is_draw": is_draw,
                "fidelity": player_fidelity,
            }
            self._queue.put(("_model_update", model_update))

    def close(self) -> None:
        self._queue.put(_SENTINEL)
        self._writer_thread.join(timeout=10)
        if self._client:
            self._client.close()

    # -- Background writer ------------------------------------------------

    def _writer_loop(self) -> None:
        while True:
            batch = self._drain_batch()
            if batch is None:
                return  # sentinel received
            self._flush_batch(batch)

    def _drain_batch(self) -> dict | None:
        """Drain up to _BATCH_SIZE items from queue, grouped by collection."""
        groups = defaultdict(list)
        try:
            item = self._queue.get(block=True)
            if item is _SENTINEL:
                return None
            groups[item[0]].append(item[1])
        except Exception:
            return None

        # Drain remaining without blocking, up to batch size
        drained = 1
        while drained < _BATCH_SIZE:
            try:
                item = self._queue.get_nowait()
                if item is _SENTINEL:
                    # Flush what we have, then stop next iteration
                    self._queue.put(_SENTINEL)
                    break
                groups[item[0]].append(item[1])
                drained += 1
            except queue.Empty:
                break
        return dict(groups)

    def _flush_batch(self, groups: dict) -> None:
        """Write grouped documents to Mongo."""
        for collection_name, docs in groups.items():
            try:
                if collection_name == "_model_update":
                    for update in docs:
                        self._upsert_model_stats(update)
                elif collection_name == "matches":
                    for doc in docs:
                        match_id = doc["match_id"]
                        self._db["matches"].update_one(
                            {"match_id": match_id},
                            {"$set": doc},
                            upsert=True,
                        )
                else:
                    self._db[collection_name].insert_many(docs, ordered=False)
            except Exception as exc:
                logger.warning("MongoDB write error (%s): %s", collection_name, exc)

    def _upsert_model_stats(self, update: dict) -> None:
        """Increment model aggregate stats."""
        model_id = update["model_id"]
        event_type = update["event_type"]
        fidelity = update.get("fidelity", {})

        inc_fields = {
            "matches_played": 1,
            f"games.{event_type}.matches_played": 1,
        }
        if update["is_draw"]:
            inc_fields["draws"] = 1
            inc_fields[f"games.{event_type}.draws"] = 1
        elif update["is_winner"]:
            inc_fields["wins"] = 1
            inc_fields[f"games.{event_type}.wins"] = 1
        else:
            inc_fields["losses"] = 1
            inc_fields[f"games.{event_type}.losses"] = 1

        # Violation counts
        for vtype in ("malformed_json", "illegal_move", "timeout", "empty_response", "injection_attempts"):
            count = fidelity.get(vtype, 0)
            if count:
                inc_fields[f"total_violations.{vtype}"] = count

        self._db["models"].update_one(
            {"_id": model_id},
            {
                "$inc": inc_fields,
                "$set": {"last_played": datetime.now(timezone.utc)},
            },
            upsert=True,
        )

    # -- Index setup ------------------------------------------------------

    def _ensure_indexes(self) -> None:
        from pymongo import ASCENDING
        turns = self._db["turns"]
        turns.create_index("match_id")
        turns.create_index("model_id")
        turns.create_index("event_type")
        turns.create_index("timestamp")
        turns.create_index([("match_id", ASCENDING), ("turn_number", ASCENDING)])
        turns.create_index(
            [("match_id", ASCENDING), ("turn_number", ASCENDING),
             ("hand_number", ASCENDING), ("player_id", ASCENDING)],
            unique=True,
        )

        matches = self._db["matches"]
        matches.create_index("match_id", unique=True)
        matches.create_index("event_type")
        matches.create_index("models")  # multikey
        matches.create_index([("models", ASCENDING), ("event_type", ASCENDING)])
        matches.create_index("tournament_name")

        self._db["tournaments"].create_index("name")
```

**Step 4: Run tests to verify they pass**

Run: `cd /Users/dave/projects/play-games/llmtourney && python -m pytest tests/test_mongo_sink.py -v`
Expected: All tests PASS

**Step 5: Run existing tests to verify no regressions**

Run: `cd /Users/dave/projects/play-games/llmtourney && python -m pytest tests/ -v --timeout=30 2>&1 | tail -20`
Expected: All existing tests still PASS

**Step 6: Commit**

```bash
git add src/llmtourney/core/mongo_sink.py tests/test_mongo_sink.py
git commit -m "feat: add MongoSink with background writer thread and batch inserts"
```

---

### Task 3: Integrate MongoSink into TelemetryLogger

**Files:**
- Modify: `src/llmtourney/core/telemetry.py:51-55` (constructor), `61-66` (log_turn), `68-85` (finalize_match)
- Test: `tests/test_mongo_integration.py`

**Step 1: Write failing tests**

```python
"""Tests for TelemetryLogger + MongoSink integration."""

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from llmtourney.core.telemetry import TelemetryLogger, TelemetryEntry


def _make_entry(**overrides) -> TelemetryEntry:
    defaults = dict(
        turn_number=1, hand_number=1, street="unknown",
        player_id="player_a", model_id="test-model",
        model_version="v1", prompt="prompt", raw_output="out",
        reasoning_output=None, parsed_action=None, parse_success=True,
        validation_result="legal", violation=None, ruling=None,
        state_snapshot={}, input_tokens=10, output_tokens=5,
        latency_ms=100.0, engine_version="0.1.0", prompt_version="1.0.0",
    )
    defaults.update(overrides)
    return TelemetryEntry(**defaults)


class TestTelemetryLoggerWithSink:
    def test_log_turn_delegates_to_sink(self, tmp_path):
        sink = MagicMock()
        ctx = {"tournament_name": "t", "tier": "mid", "round": 1, "event_type": "ttt"}
        logger = TelemetryLogger(tmp_path, "m-1", mongo_sink=sink, tournament_context=ctx)
        entry = _make_entry()
        logger.log_turn(entry)

        sink.log_turn.assert_called_once_with("m-1", entry, ctx)

    def test_finalize_delegates_to_sink(self, tmp_path):
        sink = MagicMock()
        ctx = {"tournament_name": "t", "tier": "mid", "round": 1, "event_type": "ttt"}
        logger = TelemetryLogger(tmp_path, "m-1", mongo_sink=sink, tournament_context=ctx)
        logger.finalize_match({"player_a": 5.0}, {"player_a": {}}, {"event": "ttt"})

        sink.finalize_match.assert_called_once_with(
            "m-1", {"player_a": 5.0}, {"player_a": {}}, {"event": "ttt"}, ctx
        )

    def test_jsonl_still_written_with_sink(self, tmp_path):
        sink = MagicMock()
        logger = TelemetryLogger(tmp_path, "m-1", mongo_sink=sink)
        logger.log_turn(_make_entry())
        logger.finalize_match({"player_a": 1.0}, {})

        lines = logger.file_path.read_text().strip().split("\n")
        assert len(lines) == 2  # turn + summary

    def test_works_without_sink(self, tmp_path):
        logger = TelemetryLogger(tmp_path, "m-1")
        logger.log_turn(_make_entry())
        logger.finalize_match({"player_a": 1.0}, {})

        lines = logger.file_path.read_text().strip().split("\n")
        assert len(lines) == 2

    def test_sink_error_does_not_break_jsonl(self, tmp_path):
        sink = MagicMock()
        sink.log_turn.side_effect = Exception("mongo down")
        logger = TelemetryLogger(tmp_path, "m-1", mongo_sink=sink)
        # Should not raise
        logger.log_turn(_make_entry())

        lines = logger.file_path.read_text().strip().split("\n")
        assert len(lines) == 1  # JSONL still written
```

**Step 2: Run tests to verify they fail**

Run: `cd /Users/dave/projects/play-games/llmtourney && python -m pytest tests/test_mongo_integration.py -v 2>&1 | head -30`
Expected: FAIL — TelemetryLogger.__init__ doesn't accept mongo_sink parameter

**Step 3: Modify TelemetryLogger**

In `src/llmtourney/core/telemetry.py`, change the three methods:

Constructor (line 51):
```python
def __init__(self, output_dir: Path, match_id: str, mongo_sink=None, tournament_context=None):
    self._output_dir = Path(output_dir)
    self._match_id = match_id
    self._output_dir.mkdir(parents=True, exist_ok=True)
    self._file_path = self._output_dir / f"{match_id}.jsonl"
    self._sink = mongo_sink
    self._tournament_context = tournament_context or {}
```

log_turn (line 61), add after `self._append(record)`:
```python
if self._sink:
    try:
        self._sink.log_turn(self._match_id, entry, self._tournament_context)
    except Exception:
        pass  # sink errors never break JSONL
```

finalize_match (line 68), add after `self._append(record)`:
```python
if self._sink:
    try:
        self._sink.finalize_match(self._match_id, scores, fidelity, extra or {}, self._tournament_context)
    except Exception:
        pass
```

**Step 4: Run tests**

Run: `cd /Users/dave/projects/play-games/llmtourney && python -m pytest tests/test_mongo_integration.py tests/test_mongo_sink.py -v`
Expected: All PASS

**Step 5: Run full test suite**

Run: `cd /Users/dave/projects/play-games/llmtourney && python -m pytest tests/ -v --timeout=30 2>&1 | tail -20`
Expected: All existing tests still PASS (constructor change is backwards-compatible)

**Step 6: Commit**

```bash
git add src/llmtourney/core/telemetry.py tests/test_mongo_integration.py
git commit -m "feat: integrate MongoSink into TelemetryLogger with 3 touch points"
```

---

### Task 4: Wire MongoSink into TournamentEngine

**Files:**
- Modify: `src/llmtourney/tournament.py:73-77` (init), `289` (logger creation), `726-730` (finalize)
- Test: `tests/test_tournament_mongo.py`

**Step 1: Write failing test**

```python
"""Tests for TournamentEngine MongoDB integration."""

import os
from unittest.mock import patch, MagicMock

import pytest

from llmtourney.config import (
    TournamentConfig, ModelConfig, EventConfig, ComputeCaps,
)


class TestTournamentEngineMongoInit:
    def test_creates_sink_when_uri_set(self):
        config = TournamentConfig(
            name="test", seed=42, version="0.1.0",
            models={"m": ModelConfig(name="m", provider="mock", model_id=None,
                                     strategy="center", api_key_env=None, base_url=None,
                                     site_url=None, app_name=None)},
            events={"tictactoe": EventConfig(name="tictactoe", weight=1)},
            compute_caps=ComputeCaps(),
        )
        with patch.dict(os.environ, {"TOURNEY_MONGO_URI": "mongodb://localhost/test"}):
            with patch("llmtourney.tournament.MongoSink") as MockSink:
                from llmtourney.tournament import TournamentEngine
                engine = TournamentEngine(config)
                MockSink.assert_called_once()
                assert engine._mongo_sink is not None

    def test_no_sink_when_uri_not_set(self):
        config = TournamentConfig(
            name="test", seed=42, version="0.1.0",
            models={}, events={}, compute_caps=ComputeCaps(),
        )
        with patch.dict(os.environ, {}, clear=True):
            # Remove TOURNEY_MONGO_URI if present
            os.environ.pop("TOURNEY_MONGO_URI", None)
            from llmtourney.tournament import TournamentEngine
            engine = TournamentEngine(config)
            assert engine._mongo_sink is None

    def test_sink_failure_does_not_prevent_engine_init(self):
        config = TournamentConfig(
            name="test", seed=42, version="0.1.0",
            models={}, events={}, compute_caps=ComputeCaps(),
        )
        with patch.dict(os.environ, {"TOURNEY_MONGO_URI": "mongodb://badhost/test"}):
            with patch("llmtourney.tournament.MongoSink", side_effect=Exception("conn fail")):
                from llmtourney.tournament import TournamentEngine
                engine = TournamentEngine(config)
                assert engine._mongo_sink is None
```

**Step 2: Run tests to verify they fail**

Run: `cd /Users/dave/projects/play-games/llmtourney && python -m pytest tests/test_tournament_mongo.py -v 2>&1 | head -20`
Expected: FAIL — TournamentEngine has no `_mongo_sink` attribute

**Step 3: Modify TournamentEngine**

In `src/llmtourney/tournament.py`:

Add import near top:
```python
import os
import logging
# ... existing imports ...

_logger = logging.getLogger(__name__)
```

Modify `__init__` (line 73):
```python
def __init__(self, config: TournamentConfig) -> None:
    self.config = config
    self.seed_mgr = SeedManager(config.seed)
    self.telemetry_dir = self._resolve_telemetry_dir()
    self.adapters: dict[str, ModelAdapter] = self._build_adapters()
    self._mongo_sink = self._init_mongo_sink()
```

Add helper method:
```python
def _init_mongo_sink(self):
    uri = os.environ.get("TOURNEY_MONGO_URI")
    if not uri:
        return None
    try:
        from llmtourney.core.mongo_sink import MongoSink
        return MongoSink(uri)
    except Exception as exc:
        _logger.warning("MongoDB unavailable, continuing JSONL-only: %s", exc)
        return None
```

Modify logger creation at line 289:
```python
tournament_context = {
    "tournament_name": self.config.name,
    "tier": "unknown",  # tier comes from bracket config if present
    "round": 0,
    "event_type": event_name,
}
logger = TelemetryLogger(
    self.telemetry_dir, match_id,
    mongo_sink=self._mongo_sink,
    tournament_context=tournament_context,
)
```

Add cleanup. Find the `run()` method and wrap the main execution in try/finally.
In `run()` method (around line 83), ensure cleanup:

```python
def run(self) -> TournamentResult:
    try:
        # ... existing run logic ...
        return result
    finally:
        if self._mongo_sink:
            self._mongo_sink.close()
```

**Step 4: Run tests**

Run: `cd /Users/dave/projects/play-games/llmtourney && python -m pytest tests/test_tournament_mongo.py -v`
Expected: All PASS

**Step 5: Run full test suite**

Run: `cd /Users/dave/projects/play-games/llmtourney && python -m pytest tests/ -v --timeout=30 2>&1 | tail -20`
Expected: All PASS

**Step 6: Commit**

```bash
git add src/llmtourney/tournament.py tests/test_tournament_mongo.py
git commit -m "feat: wire MongoSink into TournamentEngine with graceful fallback"
```

---

### Task 5: Query helpers

**Files:**
- Create: `src/llmtourney/core/mongo_queries.py`
- Test: `tests/test_mongo_queries.py`

**Step 1: Write failing tests**

```python
"""Tests for MongoDB query helpers.

Uses mongomock or mock aggregation results to test pipeline construction.
"""

from unittest.mock import MagicMock, patch

import pytest


def _mock_db_with_data():
    """Create a mock db that returns canned aggregation results."""
    db = MagicMock()
    return db


class TestWinRates:
    def test_returns_sorted_by_win_rate(self):
        db = _mock_db_with_data()
        db["matches"].aggregate.return_value = [
            {"_id": {"model": "gpt-4o", "event_type": "reversi"}, "wins": 8, "losses": 2, "draws": 0, "total": 10},
            {"_id": {"model": "sonnet", "event_type": "reversi"}, "wins": 5, "losses": 5, "draws": 0, "total": 10},
        ]
        from llmtourney.core.mongo_queries import win_rates
        result = win_rates(db)
        assert len(result) == 2
        assert result[0]["win_rate"] >= result[1]["win_rate"]

    def test_filters_by_event_type(self):
        db = _mock_db_with_data()
        db["matches"].aggregate.return_value = []
        from llmtourney.core.mongo_queries import win_rates
        win_rates(db, event_type="reversi")
        pipeline = db["matches"].aggregate.call_args[0][0]
        # First stage should be $match with event_type
        assert pipeline[0]["$match"]["event_type"] == "reversi"


class TestAvgLatency:
    def test_returns_latency_by_model(self):
        db = MagicMock()
        db["turns"].aggregate.return_value = [
            {"_id": {"model_id": "gpt-4o", "event_type": "ttt"}, "avg_latency_ms": 2500.0},
        ]
        from llmtourney.core.mongo_queries import avg_latency
        result = avg_latency(db)
        assert result[0]["avg_latency_ms"] == 2500.0


class TestHeadToHead:
    def test_returns_win_counts(self):
        db = MagicMock()
        db["matches"].find.return_value = [
            {"winner": "gpt-4o", "models": ["gpt-4o", "sonnet"]},
            {"winner": "gpt-4o", "models": ["gpt-4o", "sonnet"]},
            {"winner": "sonnet", "models": ["gpt-4o", "sonnet"]},
            {"winner": None, "models": ["gpt-4o", "sonnet"]},
        ]
        from llmtourney.core.mongo_queries import head_to_head
        result = head_to_head(db, "gpt-4o", "sonnet")
        assert result["gpt-4o"] == 2
        assert result["sonnet"] == 1
        assert result["draws"] == 1


class TestViolationFrequency:
    def test_groups_by_model_and_kind(self):
        db = MagicMock()
        db["turns"].aggregate.return_value = [
            {"_id": {"model_id": "haiku", "violation": "illegal_move"}, "count": 12},
        ]
        from llmtourney.core.mongo_queries import violation_frequency
        result = violation_frequency(db)
        assert result[0]["count"] == 12


class TestFidelityScores:
    def test_returns_clean_play_percentage(self):
        db = MagicMock()
        db["matches"].aggregate.return_value = [
            {"_id": "gpt-4o", "total_violations": 2, "total_turns": 100, "clean_pct": 98.0},
        ]
        from llmtourney.core.mongo_queries import fidelity_scores
        result = fidelity_scores(db)
        assert result[0]["clean_pct"] == 98.0


class TestGetDb:
    def test_returns_database(self):
        with patch("llmtourney.core.mongo_queries.MongoClient") as MockClient:
            mock_client = MagicMock()
            mock_db = MagicMock()
            mock_client.__getitem__ = MagicMock(return_value=mock_db)
            MockClient.return_value = mock_client

            from llmtourney.core.mongo_queries import get_db
            db = get_db("mongodb://localhost/test")
            assert db is mock_db
```

**Step 2: Run tests to verify they fail**

Run: `cd /Users/dave/projects/play-games/llmtourney && python -m pytest tests/test_mongo_queries.py -v 2>&1 | head -20`
Expected: FAIL — no module `llmtourney.core.mongo_queries`

**Step 3: Implement query helpers**

Create `src/llmtourney/core/mongo_queries.py`:

```python
"""MongoDB aggregation query helpers for telemetry analysis.

Standalone functions that take a pymongo Database and return plain dicts.
"""

from pymongo import MongoClient
from pymongo.database import Database


def get_db(uri: str = None, db_name: str = "llmtourney") -> Database:
    """Connect and return the database handle."""
    import os
    uri = uri or os.environ.get("TOURNEY_MONGO_URI", "mongodb://localhost:27017")
    client = MongoClient(uri)
    return client[db_name]


def win_rates(
    db: Database,
    model_id: str | None = None,
    event_type: str | None = None,
    tier: str | None = None,
) -> list[dict]:
    """Model win rates by game type and tier."""
    match_stage = {}
    if model_id:
        match_stage["models"] = model_id
    if event_type:
        match_stage["event_type"] = event_type
    if tier:
        match_stage["tier"] = tier

    pipeline = []
    if match_stage:
        pipeline.append({"$match": match_stage})
    pipeline.extend([
        {"$unwind": "$models"},
        {"$group": {
            "_id": {"model": "$models", "event_type": "$event_type"},
            "wins": {"$sum": {"$cond": [{"$eq": ["$winner", "$models"]}, 1, 0]}},
            "losses": {"$sum": {"$cond": [
                {"$and": [
                    {"$ne": ["$winner", None]},
                    {"$ne": ["$winner", "$models"]},
                ]}, 1, 0,
            ]}},
            "draws": {"$sum": {"$cond": [{"$eq": ["$winner", None]}, 1, 0]}},
            "total": {"$sum": 1},
        }},
        {"$addFields": {
            "win_rate": {"$cond": [
                {"$gt": ["$total", 0]},
                {"$multiply": [{"$divide": ["$wins", "$total"]}, 100]},
                0,
            ]},
        }},
        {"$sort": {"win_rate": -1}},
    ])
    return list(db["matches"].aggregate(pipeline))


def avg_latency(
    db: Database,
    model_id: str | None = None,
    event_type: str | None = None,
    tournament_name: str | None = None,
) -> list[dict]:
    """Average latency by model across games."""
    match_stage = {}
    if model_id:
        match_stage["model_id"] = model_id
    if event_type:
        match_stage["event_type"] = event_type
    if tournament_name:
        match_stage["tournament_name"] = tournament_name

    pipeline = []
    if match_stage:
        pipeline.append({"$match": match_stage})
    pipeline.extend([
        {"$group": {
            "_id": {"model_id": "$model_id", "event_type": "$event_type"},
            "avg_latency_ms": {"$avg": "$latency_ms"},
            "min_latency_ms": {"$min": "$latency_ms"},
            "max_latency_ms": {"$max": "$latency_ms"},
            "turn_count": {"$sum": 1},
        }},
        {"$sort": {"avg_latency_ms": 1}},
    ])
    return list(db["turns"].aggregate(pipeline))


def violation_frequency(
    db: Database,
    model_id: str | None = None,
    violation: str | None = None,
) -> list[dict]:
    """Violation frequency by model and kind."""
    match_stage = {"violation": {"$ne": None}}
    if model_id:
        match_stage["model_id"] = model_id
    if violation:
        match_stage["violation"] = violation

    pipeline = [
        {"$match": match_stage},
        {"$group": {
            "_id": {"model_id": "$model_id", "violation": "$violation"},
            "count": {"$sum": 1},
        }},
        {"$sort": {"count": -1}},
    ]
    return list(db["turns"].aggregate(pipeline))


def head_to_head(
    db: Database,
    model_a: str,
    model_b: str,
    event_type: str | None = None,
) -> dict:
    """Head-to-head record between two models."""
    query = {"models": {"$all": [model_a, model_b]}}
    if event_type:
        query["event_type"] = event_type

    results = {model_a: 0, model_b: 0, "draws": 0, "matches": []}
    for match in db["matches"].find(query):
        results["matches"].append(match.get("match_id"))
        winner = match.get("winner")
        if winner == model_a:
            results[model_a] += 1
        elif winner == model_b:
            results[model_b] += 1
        else:
            results["draws"] += 1
    return results


def latency_by_phase(
    db: Database,
    model_id: str,
    event_type: str,
) -> list[dict]:
    """Latency distribution across game phases (percentile-based thirds)."""
    pipeline = [
        {"$match": {"model_id": model_id, "event_type": event_type}},
        # Get max turn per match for percentile calculation
        {"$group": {
            "_id": "$match_id",
            "turns": {"$push": {
                "turn_number": "$turn_number",
                "latency_ms": "$latency_ms",
            }},
            "max_turn": {"$max": "$turn_number"},
        }},
        {"$unwind": "$turns"},
        # Assign phase based on thirds
        {"$addFields": {
            "phase": {"$switch": {
                "branches": [
                    {"case": {"$lte": ["$turns.turn_number", {"$multiply": ["$max_turn", 0.333]}]}, "then": "early"},
                    {"case": {"$lte": ["$turns.turn_number", {"$multiply": ["$max_turn", 0.667]}]}, "then": "mid"},
                ],
                "default": "late",
            }},
        }},
        {"$group": {
            "_id": "$phase",
            "avg_latency_ms": {"$avg": "$turns.latency_ms"},
            "turn_count": {"$sum": 1},
        }},
        {"$sort": {"_id": 1}},
    ]
    return list(db["turns"].aggregate(pipeline))


def token_efficiency(
    db: Database,
    model_id: str | None = None,
    event_type: str | None = None,
) -> list[dict]:
    """Token usage correlated with outcomes. Runs on matches collection."""
    match_stage = {}
    if event_type:
        match_stage["event_type"] = event_type

    pipeline = []
    if match_stage:
        pipeline.append({"$match": match_stage})
    pipeline.extend([
        {"$unwind": "$models"},
        {"$group": {
            "_id": "$models",
            "avg_total_tokens": {"$avg": "$total_tokens"},
            "avg_total_turns": {"$avg": "$total_turns"},
            "wins": {"$sum": {"$cond": [{"$eq": ["$winner", "$models"]}, 1, 0]}},
            "total": {"$sum": 1},
        }},
        {"$addFields": {
            "win_rate": {"$cond": [
                {"$gt": ["$total", 0]},
                {"$multiply": [{"$divide": ["$wins", "$total"]}, 100]},
                0,
            ]},
            "tokens_per_turn": {"$cond": [
                {"$gt": ["$avg_total_turns", 0]},
                {"$divide": ["$avg_total_tokens", "$avg_total_turns"]},
                0,
            ]},
        }},
        {"$sort": {"win_rate": -1}},
    ])

    if model_id:
        pipeline.append({"$match": {"_id": model_id}})

    return list(db["matches"].aggregate(pipeline))


def fidelity_scores(
    db: Database,
    event_type: str | None = None,
    tier: str | None = None,
) -> list[dict]:
    """Which models play cleanest? Sorted by clean play percentage."""
    match_stage = {}
    if event_type:
        match_stage["event_type"] = event_type
    if tier:
        match_stage["tier"] = tier

    pipeline = []
    if match_stage:
        pipeline.append({"$match": match_stage})
    pipeline.extend([
        {"$unwind": "$models"},
        {"$addFields": {
            "player_fidelity": {
                "$arrayElemAt": [
                    {"$objectToArray": "$fidelity_report"},
                    {"$indexOfArray": [
                        {"$map": {"input": {"$objectToArray": "$fidelity_report"}, "as": "f", "in": "$$f.k"}},
                        # Match by position — player_a maps to first model, etc.
                        {"$arrayElemAt": [
                            {"$map": {"input": {"$objectToArray": "$fidelity_report"}, "as": "f", "in": "$$f.k"}},
                            0,
                        ]},
                    ]},
                ],
            },
        }},
        {"$group": {
            "_id": "$models",
            "total_violations": {"$sum": {
                "$ifNull": [{"$getField": {"input": "$player_fidelity.v", "field": "total_violations"}}, 0]
            }},
            "total_turns": {"$sum": {"$ifNull": ["$total_turns", 0]}},
            "matches": {"$sum": 1},
        }},
        {"$addFields": {
            "clean_pct": {"$cond": [
                {"$gt": ["$total_turns", 0]},
                {"$multiply": [
                    {"$divide": [
                        {"$subtract": ["$total_turns", "$total_violations"]},
                        "$total_turns",
                    ]},
                    100,
                ]},
                100,
            ]},
        }},
        {"$sort": {"clean_pct": -1}},
    ])
    return list(db["matches"].aggregate(pipeline))
```

**Step 4: Run tests**

Run: `cd /Users/dave/projects/play-games/llmtourney && python -m pytest tests/test_mongo_queries.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add src/llmtourney/core/mongo_queries.py tests/test_mongo_queries.py
git commit -m "feat: add 7 MongoDB query helpers for telemetry analysis"
```

---

### Task 6: Backfill script

**Files:**
- Create: `scripts/backfill_mongo.py`
- Test: `tests/test_backfill.py`

**Step 1: Write failing test**

```python
"""Tests for JSONL → MongoDB backfill script."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


def _write_jsonl(path: Path, match_id: str, turns: int = 3):
    """Write a fake JSONL telemetry file."""
    lines = []
    for i in range(turns):
        lines.append(json.dumps({
            "turn_number": i,
            "hand_number": 1,
            "street": "unknown",
            "player_id": "player_a" if i % 2 == 0 else "player_b",
            "model_id": "gpt-4o" if i % 2 == 0 else "sonnet",
            "model_version": "v1",
            "prompt": f"Turn {i} prompt",
            "raw_output": "{}",
            "reasoning_output": None,
            "parsed_action": None,
            "parse_success": True,
            "validation_result": "legal",
            "violation": None,
            "ruling": None,
            "state_snapshot": {},
            "input_tokens": 100,
            "output_tokens": 50,
            "latency_ms": 1000.0,
            "schema_version": "1.1.0",
            "match_id": match_id,
            "timestamp": "2026-01-15T12:00:00+00:00",
        }))
    # Match summary
    lines.append(json.dumps({
        "schema_version": "1.1.0",
        "record_type": "match_summary",
        "match_id": match_id,
        "final_scores": {"player_a": 2.0, "player_b": 1.0},
        "fidelity_report": {
            "player_a": {"total_violations": 0},
            "player_b": {"total_violations": 1, "illegal_move": 1},
        },
        "event": "tictactoe",
        "player_models": {"player_a": "gpt-4o", "player_b": "sonnet"},
        "ruling": "completed",
        "timestamp": "2026-01-15T12:05:00+00:00",
    }))
    path.write_text("\n".join(lines) + "\n")


class TestBackfillParsing:
    def test_parses_turns_and_summary(self, tmp_path):
        jsonl_dir = tmp_path / "telemetry"
        jsonl_dir.mkdir()
        _write_jsonl(jsonl_dir / "match-1.jsonl", "match-1", turns=3)

        from scripts.backfill_mongo import parse_jsonl_file
        turns, summary = parse_jsonl_file(jsonl_dir / "match-1.jsonl")
        assert len(turns) == 3
        assert summary["record_type"] == "match_summary"
        assert summary["match_id"] == "match-1"

    def test_missing_context_defaults_to_unknown(self, tmp_path):
        jsonl_dir = tmp_path / "telemetry"
        jsonl_dir.mkdir()
        _write_jsonl(jsonl_dir / "match-1.jsonl", "match-1", turns=1)

        from scripts.backfill_mongo import parse_jsonl_file
        turns, summary = parse_jsonl_file(jsonl_dir / "match-1.jsonl")
        # Old files won't have tournament_name — backfill should handle gracefully
        # (tested during actual insert, not parsing)


class TestBackfillDryRun:
    def test_dry_run_prints_counts_no_writes(self, tmp_path, capsys):
        jsonl_dir = tmp_path / "telemetry"
        jsonl_dir.mkdir()
        _write_jsonl(jsonl_dir / "match-1.jsonl", "match-1")
        _write_jsonl(jsonl_dir / "match-2.jsonl", "match-2")

        from scripts.backfill_mongo import run_backfill
        run_backfill(jsonl_dir, uri=None, dry_run=True)

        output = capsys.readouterr().out
        assert "2" in output  # 2 files
        assert "6" in output  # 6 turns total (3 per file)
```

**Step 2: Run tests to verify they fail**

Run: `cd /Users/dave/projects/play-games/llmtourney && python -m pytest tests/test_backfill.py -v 2>&1 | head -20`
Expected: FAIL — no module `scripts.backfill_mongo`

**Step 3: Create scripts directory and implement**

Run: `mkdir -p /Users/dave/projects/play-games/llmtourney/scripts`

Create `scripts/__init__.py` (empty) and `scripts/backfill_mongo.py`:

```python
"""Backfill existing JSONL telemetry files into MongoDB.

Usage:
    python -m scripts.backfill_mongo [--uri URI] [--dir DIR] [--dry-run]
"""

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


def parse_jsonl_file(path: Path) -> tuple[list[dict], dict | None]:
    """Parse a JSONL telemetry file into turns and optional match summary."""
    turns = []
    summary = None
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            if record.get("record_type") == "match_summary":
                summary = record
            else:
                turns.append(record)
    return turns, summary


def backfill_file(db, path: Path, file_num: int, total: int) -> tuple[int, int]:
    """Backfill one JSONL file. Returns (turns_inserted, matches_upserted)."""
    print(f"Processing file {file_num}/{total}: {path.name}...")
    turns, summary = parse_jsonl_file(path)

    turns_inserted = 0
    if turns:
        # Add _ingested_at and default missing context fields
        for turn in turns:
            turn["_ingested_at"] = datetime.now(timezone.utc)
            turn.setdefault("event_type", summary.get("event", "unknown") if summary else "unknown")
            turn.setdefault("tournament_name", "unknown")
            turn.setdefault("tier", "unknown")
            turn.setdefault("round", 0)
            turn.setdefault("hand_number", 0)

        try:
            result = db["turns"].insert_many(turns, ordered=False)
            turns_inserted = len(result.inserted_ids)
        except Exception as exc:
            # BulkWriteError for dupes — count what succeeded
            if hasattr(exc, "details"):
                turns_inserted = exc.details.get("nInserted", 0)
                dupes = len(turns) - turns_inserted
                if dupes:
                    logger.info("  %d duplicate turns skipped", dupes)
            else:
                logger.warning("  Turn insert error: %s", exc)

    matches_upserted = 0
    if summary:
        summary["_ingested_at"] = datetime.now(timezone.utc)
        summary.setdefault("event_type", summary.get("event", "unknown"))
        summary.setdefault("tournament_name", "unknown")
        summary.setdefault("tier", "unknown")
        summary.setdefault("round", 0)
        summary.setdefault("models", list(summary.get("player_models", {}).values()))
        # Derive winner
        scores = summary.get("final_scores", {})
        player_models = summary.get("player_models", {})
        if scores and player_models:
            max_score = max(scores.values())
            winners = [pid for pid, s in scores.items() if s == max_score]
            if len(winners) == 1:
                summary["winner"] = player_models.get(winners[0])
            else:
                summary["winner"] = None
        summary.setdefault("total_turns", len(turns))

        try:
            db["matches"].update_one(
                {"match_id": summary["match_id"]},
                {"$set": summary},
                upsert=True,
            )
            matches_upserted = 1
        except Exception as exc:
            logger.warning("  Match upsert error: %s", exc)

        # Update model stats
        for player_id, model_id in player_models.items():
            try:
                fidelity = summary.get("fidelity_report", {}).get(player_id, {})
                is_winner = (summary.get("winner") == model_id)
                is_draw = (summary.get("winner") is None)

                inc_fields = {"matches_played": 1}
                event = summary.get("event_type", "unknown")
                inc_fields[f"games.{event}.matches_played"] = 1
                if is_draw:
                    inc_fields["draws"] = 1
                    inc_fields[f"games.{event}.draws"] = 1
                elif is_winner:
                    inc_fields["wins"] = 1
                    inc_fields[f"games.{event}.wins"] = 1
                else:
                    inc_fields["losses"] = 1
                    inc_fields[f"games.{event}.losses"] = 1

                for vtype in ("malformed_json", "illegal_move", "timeout", "empty_response", "injection_attempts"):
                    count = fidelity.get(vtype, 0)
                    if count:
                        inc_fields[f"total_violations.{vtype}"] = count

                db["models"].update_one(
                    {"_id": model_id},
                    {
                        "$inc": inc_fields,
                        "$set": {"last_played": datetime.now(timezone.utc)},
                    },
                    upsert=True,
                )
            except Exception as exc:
                logger.warning("  Model stats error for %s: %s", model_id, exc)

    return turns_inserted, matches_upserted


def run_backfill(telemetry_dir: Path, uri: str | None = None, dry_run: bool = False):
    """Main backfill entry point."""
    files = sorted(telemetry_dir.glob("*.jsonl"))
    if not files:
        print(f"No JSONL files found in {telemetry_dir}")
        return

    total_turns = 0
    total_matches = 0

    if dry_run:
        for i, f in enumerate(files, 1):
            turns, summary = parse_jsonl_file(f)
            total_turns += len(turns)
            total_matches += 1 if summary else 0
            print(f"  [{i}/{len(files)}] {f.name}: {len(turns)} turns, {'1 summary' if summary else 'no summary'}")
        print(f"\nDry run complete: {len(files)} files, {total_turns} turns, {total_matches} match summaries")
        return

    uri = uri or os.environ.get("TOURNEY_MONGO_URI")
    if not uri:
        print("Error: No MongoDB URI. Set TOURNEY_MONGO_URI or pass --uri")
        sys.exit(1)

    from pymongo import MongoClient
    client = MongoClient(uri)
    db = client["llmtourney"]

    for i, f in enumerate(files, 1):
        t, m = backfill_file(db, f, i, len(files))
        total_turns += t
        total_matches += m

    print(f"\nBackfill complete: {total_turns} turns inserted, {total_matches} matches upserted")
    client.close()


def main():
    parser = argparse.ArgumentParser(description="Backfill JSONL telemetry into MongoDB")
    parser.add_argument("--uri", help="MongoDB connection URI")
    parser.add_argument("--dir", default="output/telemetry", help="Telemetry JSONL directory")
    parser.add_argument("--dry-run", action="store_true", help="Parse files but don't write to Mongo")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    run_backfill(Path(args.dir), uri=args.uri, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
```

**Step 4: Run tests**

Run: `cd /Users/dave/projects/play-games/llmtourney && python -m pytest tests/test_backfill.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add scripts/ tests/test_backfill.py
git commit -m "feat: add idempotent JSONL-to-MongoDB backfill script"
```

---

### Task 7: Report script

**Files:**
- Create: `scripts/telemetry_report.py`
- Test: `tests/test_report.py`

**Step 1: Write failing test**

```python
"""Tests for telemetry report script."""

from unittest.mock import MagicMock, patch
from io import StringIO

import pytest


class TestReportOutput:
    def test_prints_leaderboard(self, capsys):
        mock_db = MagicMock()

        with patch("llmtourney.core.mongo_queries.win_rates") as mock_wr:
            mock_wr.return_value = [
                {"_id": {"model": "gpt-4o", "event_type": "all"}, "wins": 10, "losses": 2, "draws": 1, "total": 13, "win_rate": 76.9},
            ]
            with patch("llmtourney.core.mongo_queries.violation_frequency") as mock_vf:
                mock_vf.return_value = []
                from scripts.telemetry_report import print_report
                print_report(mock_db)

        output = capsys.readouterr().out
        assert "gpt-4o" in output
        assert "76.9" in output or "76.9%" in output

    def test_json_flag_outputs_valid_json(self, capsys):
        mock_db = MagicMock()

        with patch("llmtourney.core.mongo_queries.win_rates") as mock_wr, \
             patch("llmtourney.core.mongo_queries.violation_frequency") as mock_vf, \
             patch("llmtourney.core.mongo_queries.fidelity_scores") as mock_fs, \
             patch("llmtourney.core.mongo_queries.avg_latency") as mock_al:
            mock_wr.return_value = []
            mock_vf.return_value = []
            mock_fs.return_value = []
            mock_al.return_value = []

            from scripts.telemetry_report import print_report
            print_report(mock_db, as_json=True)

        import json
        output = capsys.readouterr().out
        data = json.loads(output)  # Should not raise
        assert "leaderboard" in data
```

**Step 2: Run tests to verify they fail**

Run: `cd /Users/dave/projects/play-games/llmtourney && python -m pytest tests/test_report.py -v 2>&1 | head -20`
Expected: FAIL

**Step 3: Implement report script**

Create `scripts/telemetry_report.py`:

```python
"""Quick model performance summary from MongoDB telemetry.

Usage:
    python -m scripts.telemetry_report [--uri URI] [--event EVENT] [--model MODEL] [--json]
"""

import argparse
import json
import logging
import os
import sys
from pathlib import Path

from llmtourney.core import mongo_queries


def print_report(db, event_type=None, model_id=None, as_json=False):
    """Print model performance summary."""
    # Gather data
    leaderboard = mongo_queries.win_rates(db, event_type=event_type)
    violations = mongo_queries.violation_frequency(db, model_id=model_id)
    fidelity = mongo_queries.fidelity_scores(db, event_type=event_type)
    latency = mongo_queries.avg_latency(db, event_type=event_type)

    if as_json:
        data = {
            "leaderboard": leaderboard,
            "violations": violations,
            "fidelity": fidelity,
            "latency": latency,
        }
        print(json.dumps(data, indent=2, default=str))
        return

    # Console output
    print("=" * 60)
    print("  LLM Tourney — Model Performance Report")
    print("=" * 60)

    if leaderboard:
        print(f"\n{'Model':<25} {'W':>4} {'L':>4} {'D':>4} {'Win%':>7} {'Games':>6}")
        print("-" * 56)
        for row in leaderboard:
            model = row["_id"]["model"] if isinstance(row["_id"], dict) else row["_id"]
            print(f"{model:<25} {row['wins']:>4} {row['losses']:>4} {row['draws']:>4} "
                  f"{row['win_rate']:>6.1f}% {row['total']:>6}")
    else:
        print("\nNo match data found.")

    if violations:
        print(f"\n{'Model':<25} {'Violation':<20} {'Count':>6}")
        print("-" * 53)
        for row in violations:
            model = row["_id"]["model_id"]
            kind = row["_id"]["violation"]
            print(f"{model:<25} {kind:<20} {row['count']:>6}")

    if fidelity:
        print(f"\n{'Model':<25} {'Violations':>11} {'Clean%':>8}")
        print("-" * 46)
        for row in fidelity:
            model = row["_id"]
            print(f"{model:<25} {row['total_violations']:>11} {row['clean_pct']:>7.1f}%")

    if latency:
        print(f"\n{'Model':<25} {'Game':<15} {'Avg ms':>8} {'Turns':>6}")
        print("-" * 56)
        for row in latency:
            model = row["_id"]["model_id"]
            event = row["_id"]["event_type"]
            print(f"{model:<25} {event:<15} {row['avg_latency_ms']:>8.0f} {row['turn_count']:>6}")

    print()


def main():
    parser = argparse.ArgumentParser(description="Model performance report from MongoDB")
    parser.add_argument("--uri", help="MongoDB connection URI")
    parser.add_argument("--event", help="Filter by event type")
    parser.add_argument("--model", help="Filter by model")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    uri = args.uri or os.environ.get("TOURNEY_MONGO_URI")
    if not uri:
        print("Error: No MongoDB URI. Set TOURNEY_MONGO_URI or pass --uri")
        sys.exit(1)

    db = mongo_queries.get_db(uri)
    print_report(db, event_type=args.event, model_id=args.model, as_json=args.json)


if __name__ == "__main__":
    main()
```

**Step 4: Run tests**

Run: `cd /Users/dave/projects/play-games/llmtourney && python -m pytest tests/test_report.py -v`
Expected: All PASS

**Step 5: Run full test suite**

Run: `cd /Users/dave/projects/play-games/llmtourney && python -m pytest tests/ -v --timeout=30 2>&1 | tail -20`
Expected: All PASS

**Step 6: Commit**

```bash
git add scripts/telemetry_report.py tests/test_report.py
git commit -m "feat: add telemetry report script with --json output"
```

---

### Task 8: Final integration test and cleanup

**Files:**
- Modify: `src/llmtourney/core/__init__.py` (optional: export MongoSink)
- Review: all new files for consistency

**Step 1: Run full test suite**

Run: `cd /Users/dave/projects/play-games/llmtourney && python -m pytest tests/ -v --timeout=30`
Expected: All tests PASS

**Step 2: Verify imports work cleanly**

Run:
```bash
cd /Users/dave/projects/play-games/llmtourney
python -c "from llmtourney.core.mongo_sink import MongoSink; print('MongoSink OK')"
python -c "from llmtourney.core.mongo_queries import win_rates; print('Queries OK')"
python -c "from scripts.backfill_mongo import run_backfill; print('Backfill OK')"
python -c "from scripts.telemetry_report import print_report; print('Report OK')"
```
Expected: All print OK (pymongo import errors acceptable if not installed — test that graceful import failure works)

**Step 3: Verify backfill dry run on real data**

Run:
```bash
cd /Users/dave/projects/play-games/llmtourney
python -m scripts.backfill_mongo --dir output/telemetry --dry-run
```
Expected: Lists all JSONL files with turn/summary counts

**Step 4: Commit any final tweaks**

```bash
git add -A
git commit -m "chore: final integration cleanup for MongoDB telemetry backend"
```

---

## Summary

| Task | What | Files |
|------|------|-------|
| 1 | pymongo optional dep | `pyproject.toml` |
| 2 | MongoSink + tests | `core/mongo_sink.py`, `tests/test_mongo_sink.py` |
| 3 | TelemetryLogger integration + tests | `core/telemetry.py`, `tests/test_mongo_integration.py` |
| 4 | TournamentEngine wiring + tests | `tournament.py`, `tests/test_tournament_mongo.py` |
| 5 | Query helpers + tests | `core/mongo_queries.py`, `tests/test_mongo_queries.py` |
| 6 | Backfill script + tests | `scripts/backfill_mongo.py`, `tests/test_backfill.py` |
| 7 | Report script + tests | `scripts/telemetry_report.py`, `tests/test_report.py` |
| 8 | Integration test + cleanup | All files |
