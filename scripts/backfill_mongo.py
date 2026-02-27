"""Backfill script — reads existing JSONL telemetry files and loads them into MongoDB.

Usage:
    python -m scripts.backfill_mongo [--uri URI] [--dir output/telemetry] [--dry-run]

Idempotent: safe to re-run. Duplicate turns are silently dropped via the
compound unique index. Matches are upserted on match_id.
"""

from __future__ import annotations

import argparse
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_URI = "mongodb://localhost:27017"
_DEFAULT_DIR = "output/telemetry"
_DB_NAME = "llmtourney"


# ------------------------------------------------------------------
# Parsing
# ------------------------------------------------------------------

def parse_jsonl_file(path: Path) -> tuple[list[dict], dict | None]:
    """Parse a JSONL file into (turns, summary_or_None).

    Lines with ``record_type == "match_summary"`` are treated as the
    match summary.  All other non-blank lines are treated as turn entries.
    """
    turns: list[dict] = []
    summary: dict | None = None

    with open(path) as f:
        for line in f:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                doc = json.loads(stripped)
            except json.JSONDecodeError:
                logger.warning("Skipping malformed JSON in %s: %s", path.name, stripped[:80])
                continue

            if doc.get("record_type") == "match_summary":
                summary = doc
            else:
                turns.append(doc)

    return turns, summary


# ------------------------------------------------------------------
# Document builders
# ------------------------------------------------------------------

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
        return None
    return player_models.get(top_players[0])


def _build_match_doc(summary: dict) -> dict[str, Any]:
    """Build a MongoDB match document from a JSONL match_summary record."""
    scores = summary.get("final_scores", {})
    player_models = summary.get("player_models", {})
    fidelity = summary.get("fidelity_report", {})
    event_type = summary.get("event", "unknown")

    return {
        "match_id": summary["match_id"],
        "schema_version": summary.get("schema_version", "1.1.0"),
        "scores": scores,
        "fidelity": fidelity,
        "player_models": player_models,
        "models": list(player_models.values()),
        "winner": _derive_winner(scores, player_models),
        "event_type": event_type,
        "tournament_name": summary.get("tournament_name", "unknown"),
        "tier": summary.get("tier", "unknown"),
        "round": summary.get("round", 0),
        "timestamp": summary.get("timestamp", datetime.now(timezone.utc).isoformat()),
        "_ingested_at": datetime.now(timezone.utc),
    }


def _enrich_turns(
    turns: list[dict],
    event_type: str,
    tournament_name: str,
    tier: str,
    round_num: int,
) -> list[dict]:
    """Add context fields and _ingested_at to each turn document."""
    now = datetime.now(timezone.utc)
    for t in turns:
        t["event_type"] = event_type
        t["tournament_name"] = tournament_name
        t["tier"] = tier
        t["round"] = round_num
        t["_ingested_at"] = now
    return turns


def _build_model_stat_updates(
    summary: dict,
    event_type: str,
) -> list[dict[str, Any]]:
    """Build model stat $inc updates from a match summary."""
    scores = summary.get("final_scores", {})
    player_models = summary.get("player_models", {})
    fidelity = summary.get("fidelity_report", {})
    winner = _derive_winner(scores, player_models)

    updates = []
    for player_id, model_id in player_models.items():
        is_winner = winner == model_id
        is_draw = winner is None
        player_fidelity = fidelity.get(player_id, {})
        violations = player_fidelity.get("total_violations", 0)

        updates.append({
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
        })
    return updates


# ------------------------------------------------------------------
# Backfill logic
# ------------------------------------------------------------------

def backfill_file(
    db: Any,
    path: Path,
    file_num: int,
    total: int,
) -> tuple[int, int]:
    """Backfill a single JSONL file into MongoDB.

    Returns (turns_inserted, matches_upserted).
    """
    from pymongo.errors import BulkWriteError, PyMongoError

    print(f"Processing file {file_num}/{total}: {path.name}...")

    turns, summary = parse_jsonl_file(path)
    turns_inserted = 0
    matches_upserted = 0

    if turns:
        # Derive context from summary if available
        if summary:
            event_type = summary.get("event", "unknown")
            tournament_name = summary.get("tournament_name", "unknown")
            tier = summary.get("tier", "unknown")
            round_num = summary.get("round", 0)
        else:
            event_type = "unknown"
            tournament_name = "unknown"
            tier = "unknown"
            round_num = 0

        enriched = _enrich_turns(turns, event_type, tournament_name, tier, round_num)

        try:
            result = db["turns"].insert_many(enriched, ordered=False)
            turns_inserted = len(result.inserted_ids)
        except BulkWriteError as exc:
            # Some dupes silently dropped — count what was actually inserted
            turns_inserted = exc.details.get("nInserted", 0)
        except PyMongoError as exc:
            logger.warning("Failed to insert turns from %s: %s", path.name, exc)

    if summary:
        match_doc = _build_match_doc(summary)
        try:
            db["matches"].update_one(
                {"match_id": match_doc["match_id"]},
                {"$set": match_doc},
                upsert=True,
            )
            matches_upserted = 1
        except PyMongoError as exc:
            logger.warning("Failed to upsert match from %s: %s", path.name, exc)

        # Model stats
        event_type = summary.get("event", "unknown")
        for stat in _build_model_stat_updates(summary, event_type):
            try:
                db["models"].update_one(
                    stat["filter"],
                    {"$inc": stat["inc"], "$set": stat["set"]},
                    upsert=True,
                )
            except PyMongoError as exc:
                logger.warning("Failed to update model stats from %s: %s", path.name, exc)

    return turns_inserted, matches_upserted


def run_backfill(
    telemetry_dir: Path | str,
    uri: str | None = None,
    dry_run: bool = False,
) -> None:
    """Main entry point for backfill.

    Args:
        telemetry_dir: Directory containing .jsonl files.
        uri: MongoDB connection URI. Ignored in dry-run mode.
        dry_run: If True, parse files and print stats without writing.
    """
    telemetry_dir = Path(telemetry_dir)
    files = sorted(telemetry_dir.glob("*.jsonl"))

    if not files:
        print(f"No .jsonl files found in {telemetry_dir}")
        return

    total = len(files)
    print(f"Found {total} JSONL file(s) in {telemetry_dir}")

    if dry_run:
        total_turns = 0
        total_summaries = 0
        for i, f in enumerate(files, 1):
            turns, summary = parse_jsonl_file(f)
            n_turns = len(turns)
            has_summary = 1 if summary else 0
            total_turns += n_turns
            total_summaries += has_summary
            print(f"  [{i}/{total}] {f.name}: {n_turns} turns, {has_summary} summary")
        print(f"\nDry-run totals: {total_turns} turns, {total_summaries} match summaries")
        return

    # Connect to MongoDB
    from pymongo import MongoClient

    uri = uri or _DEFAULT_URI
    client = MongoClient(uri, serverSelectionTimeoutMS=5000)
    client.admin.command("ping")
    db = client[_DB_NAME]
    print(f"Connected to MongoDB at {uri}")

    total_turns = 0
    total_matches = 0
    for i, f in enumerate(files, 1):
        t, m = backfill_file(db, f, i, total)
        total_turns += t
        total_matches += m

    print(f"\nBackfill complete: {total_turns} turns inserted, {total_matches} matches upserted")
    client.close()


# ------------------------------------------------------------------
# CLI
# ------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill JSONL telemetry files into MongoDB.",
    )
    parser.add_argument(
        "--uri",
        default=_DEFAULT_URI,
        help=f"MongoDB connection URI (default: {_DEFAULT_URI})",
    )
    parser.add_argument(
        "--dir",
        default=_DEFAULT_DIR,
        dest="telemetry_dir",
        help=f"Directory containing .jsonl files (default: {_DEFAULT_DIR})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse files and print stats without writing to MongoDB.",
    )
    args = parser.parse_args()
    run_backfill(args.telemetry_dir, uri=args.uri, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
