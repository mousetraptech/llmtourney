"""MongoSink — background MongoDB writer with queue.

Accepts telemetry entries and match summaries via a thread-safe queue,
batches writes, and sends them to MongoDB in a background daemon thread.
All pymongo errors are caught and logged as warnings — never raises to caller.
"""

from __future__ import annotations

import hashlib
import logging
import queue
import threading
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any

from llmtourney.core.model_names import normalize
from llmtourney.core.telemetry import TelemetryEntry

logger = logging.getLogger(__name__)

_SCHEMA_VERSION = "1.1.0"
_BATCH_SIZE = 50
_SENTINEL = object()


class MongoSink:
    """Background MongoDB writer.

    Connects to MongoDB, verifies connectivity with a ping, then runs a
    daemon thread that drains a queue and writes documents in batches.
    If the initial connection fails, the sink disables itself and all
    methods become no-ops.
    """

    def __init__(
        self,
        uri: str,
        db_name: str,
        *,
        store_prompts: bool = False,
    ) -> None:
        self._uri = uri
        self._db_name = db_name
        self._store_prompts = store_prompts
        self._disabled = False
        self._closed = False
        self._client = None
        self._queue: queue.Queue = queue.Queue()

        # Attempt connection
        try:
            from pymongo import MongoClient
            from pymongo.errors import ConnectionFailure, PyMongoError, ServerSelectionTimeoutError

            self._client = MongoClient(uri, serverSelectionTimeoutMS=5000)
            self._client.admin.command("ping")
        except (ConnectionFailure, ServerSelectionTimeoutError, PyMongoError) as exc:
            logger.warning("MongoDB connection failed, telemetry disabled: %s", exc)
            self._disabled = True
            self._thread = threading.Thread(target=lambda: None, daemon=True)
            self._thread.start()
            return
        except Exception as exc:
            logger.warning("Unexpected error connecting to MongoDB: %s", exc)
            self._disabled = True
            self._thread = threading.Thread(target=lambda: None, daemon=True)
            self._thread.start()
            return

        self._db = self._client[db_name]
        self._ensure_indexes()

        # Start background writer thread
        self._thread = threading.Thread(
            target=self._writer_loop, daemon=True, name="mongo-sink-writer",
        )
        self._thread.start()

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def __enter__(self) -> MongoSink:
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @staticmethod
    def _infer_event_from_match_id(match_id: str) -> str:
        """Extract event type from match_id prefix (e.g. 'holdem-...' → 'holdem')."""
        _known = {
            "bullshit", "holdem", "liarsdice", "rollerderby",
            "connectfour", "checkers", "reversi", "scrabble",
            "tictactoe", "yahtzee",
        }
        prefix = match_id.split("-")[0]
        return prefix if prefix in _known else "unknown"

    @staticmethod
    def _infer_tier(tournament_name: str) -> str:
        """Infer tier from tournament name (e.g. 's2-league-bantam' → 'bantam')."""
        if not tournament_name or tournament_name == "unknown":
            return "unknown"
        parts = tournament_name.rsplit("-", 1)
        return parts[-1] if len(parts) > 1 else "unknown"

    def _resolve_context(self, match_id: str, tournament_context: dict) -> dict:
        """Fill in missing tournament_context fields from match_id inference."""
        event_type = tournament_context.get("event_type") or self._infer_event_from_match_id(match_id)
        tournament_name = tournament_context.get("tournament_name") or "unknown"
        tier = tournament_context.get("tier") or self._infer_tier(tournament_name)
        round_num = tournament_context.get("round", 0)
        return {
            "event_type": event_type,
            "tournament_name": tournament_name,
            "tier": tier,
            "round": round_num,
        }

    def log_turn(
        self,
        match_id: str,
        entry: TelemetryEntry,
        tournament_context: dict,
    ) -> None:
        """Enqueue a turn document for background insertion."""
        if self._disabled:
            return

        doc = asdict(entry)
        doc["match_id"] = match_id
        doc["schema_version"] = _SCHEMA_VERSION
        doc["timestamp"] = datetime.now(timezone.utc).isoformat()
        doc["_ingested_at"] = datetime.now(timezone.utc)

        # Normalize model identifiers
        doc["model_id"] = normalize(doc.get("model_id", ""))
        doc["model_version"] = normalize(doc.get("model_version", ""))

        # Denormalize tournament context with fallback inference
        ctx = self._resolve_context(match_id, tournament_context)
        doc["event_type"] = ctx["event_type"]
        doc["tournament_name"] = ctx["tournament_name"]
        doc["tier"] = ctx["tier"]
        doc["round"] = ctx["round"]

        # Handle prompt based on store_prompts flag
        if not self._store_prompts:
            prompt_text = doc.pop("prompt")
            doc["prompt_hash"] = hashlib.sha256(prompt_text.encode()).hexdigest()
            doc["prompt_chars"] = len(prompt_text)
            doc["prompt_tokens"] = entry.input_tokens

        self._queue.put(("turn", "turns", doc))

    def finalize_match(
        self,
        match_id: str,
        scores: dict[str, float],
        fidelity: dict,
        player_models: dict[str, str],
        tournament_context: dict,
        extra: dict | None = None,
    ) -> None:
        """Enqueue match summary upsert and model stat updates."""
        if self._disabled:
            return

        # Normalize model identifiers
        player_models = {k: normalize(v) for k, v in player_models.items()}

        # Derive winner
        winner = self._derive_winner(scores, player_models)

        ctx = self._resolve_context(match_id, tournament_context)

        match_doc: dict[str, Any] = {
            "match_id": match_id,
            "schema_version": _SCHEMA_VERSION,
            "scores": scores,
            "fidelity": fidelity,
            "player_models": player_models,
            "models": list(player_models.values()),
            "winner": winner,
            "event_type": ctx["event_type"],
            "tournament_name": ctx["tournament_name"],
            "tier": ctx["tier"],
            "round": ctx["round"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "_ingested_at": datetime.now(timezone.utc),
        }
        if extra:
            match_doc.update(extra)

        self._queue.put(("match", "matches", match_doc))

        # Enqueue model stat updates
        for player_id, model_id in player_models.items():
            is_winner = winner == model_id
            is_draw = winner is None
            player_fidelity = fidelity.get(player_id, {})
            violations = player_fidelity.get("total_violations", 0)
            event_type = ctx["event_type"]

            stat_update: dict[str, Any] = {
                "filter": {"_id": model_id},
                "inc": {
                    "total_matches": 1,
                    "wins": 1 if is_winner else 0,
                    "losses": 0 if (is_winner or is_draw) else 1,
                    "draws": 1 if is_draw else 0,
                    f"games.{event_type}.matches": 1,
                    f"games.{event_type}.wins": 1 if is_winner else 0,
                    f"games.{event_type}.losses": 0 if (is_winner or is_draw) else 1,
                    f"games.{event_type}.draws": 1 if is_draw else 0,
                    "total_violations": violations,
                },
                "set": {
                    "last_played": datetime.now(timezone.utc),
                },
            }
            self._queue.put(("model_stat", "models", stat_update))

    def close(self) -> None:
        """Send sentinel, drain remaining items, join background thread."""
        if self._closed:
            return
        self._closed = True

        if not self._disabled:
            self._queue.put(_SENTINEL)
        self._thread.join(timeout=10)

        if self._client:
            self._client.close()

    # ------------------------------------------------------------------
    # Internal: background writer
    # ------------------------------------------------------------------

    def _writer_loop(self) -> None:
        """Background thread: drain queue and batch-write to MongoDB."""
        while True:
            batch: list[tuple[str, str, dict]] = []

            # Block for first item
            try:
                item = self._queue.get(timeout=1.0)
            except queue.Empty:
                continue

            if item is _SENTINEL:
                # Drain remaining items before exiting
                self._drain_remaining(batch)
                return

            batch.append(item)

            # Drain up to BATCH_SIZE
            while len(batch) < _BATCH_SIZE:
                try:
                    item = self._queue.get_nowait()
                except queue.Empty:
                    break
                if item is _SENTINEL:
                    self._flush_batch(batch)
                    self._drain_remaining([])
                    return
                batch.append(item)

            self._flush_batch(batch)

    def _drain_remaining(self, batch: list) -> None:
        """Drain any remaining items from the queue and flush."""
        while True:
            try:
                item = self._queue.get_nowait()
            except queue.Empty:
                break
            if item is _SENTINEL:
                continue
            batch.append(item)
        if batch:
            self._flush_batch(batch)

    def _flush_batch(self, batch: list[tuple[str, str, dict]]) -> None:
        """Group items by type and write to MongoDB."""
        from pymongo.errors import PyMongoError

        # Group turns by collection for insert_many
        turns_by_collection: dict[str, list[dict]] = {}
        matches: list[dict] = []
        model_stats: list[dict] = []

        for item_type, collection_name, doc in batch:
            if item_type == "turn":
                turns_by_collection.setdefault(collection_name, []).append(doc)
            elif item_type == "match":
                matches.append(doc)
            elif item_type == "model_stat":
                model_stats.append(doc)

        # Write turns with insert_many
        for collection_name, docs in turns_by_collection.items():
            try:
                self._db[collection_name].insert_many(docs)
            except PyMongoError as exc:
                logger.warning("Failed to insert turns: %s", exc)

        # Write matches with update_one upsert
        for doc in matches:
            try:
                match_id = doc["match_id"]
                self._db["matches"].update_one(
                    {"match_id": match_id},
                    {"$set": doc},
                    upsert=True,
                )
            except PyMongoError as exc:
                logger.warning("Failed to upsert match %s: %s", doc.get("match_id"), exc)

        # Write model stats with $inc upsert
        for stat in model_stats:
            try:
                self._db["models"].update_one(
                    stat["filter"],
                    {
                        "$inc": stat["inc"],
                        "$set": stat["set"],
                    },
                    upsert=True,
                )
            except PyMongoError as exc:
                logger.warning("Failed to update model stats: %s", exc)

    # ------------------------------------------------------------------
    # Internal: indexes
    # ------------------------------------------------------------------

    def _ensure_indexes(self) -> None:
        """Create indexes for efficient querying."""
        from pymongo import ASCENDING
        from pymongo.errors import PyMongoError

        try:
            turns = self._db["turns"]
            turns.create_index("match_id")
            turns.create_index("model_id")
            turns.create_index("event_type")
            turns.create_index("timestamp")
            turns.create_index([("match_id", ASCENDING), ("turn_number", ASCENDING)])
            turns.create_index(
                [
                    ("match_id", ASCENDING),
                    ("turn_number", ASCENDING),
                    ("hand_number", ASCENDING),
                    ("player_id", ASCENDING),
                ],
                unique=True,
            )

            matches = self._db["matches"]
            matches.create_index("match_id", unique=True)
            matches.create_index("event_type")
            matches.create_index("models")
            matches.create_index([("models", ASCENDING), ("event_type", ASCENDING)])
            matches.create_index("tournament_name")

            tournaments = self._db["tournaments"]
            tournaments.create_index("name")
        except PyMongoError as exc:
            logger.warning("Failed to create indexes: %s", exc)

    # ------------------------------------------------------------------
    # Internal: helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _derive_winner(
        scores: dict[str, float],
        player_models: dict[str, str],
    ) -> str | None:
        """Find the winner from scores. Returns model_id or None on tie."""
        if not scores:
            return None

        max_score = max(scores.values())
        top_players = [pid for pid, s in scores.items() if s == max_score]

        if len(top_players) != 1:
            return None  # tie

        return player_models.get(top_players[0])
