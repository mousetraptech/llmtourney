"""Backfill script — reads existing JSONL telemetry files and loads them into MongoDB.

Usage:
    python -m scripts.backfill_mongo [--uri URI] [--dir output/telemetry] [--dry-run]
        [--tournament-name NAME] [--tier TIER]

Idempotent: safe to re-run. Duplicate turns are silently dropped via the
compound unique index. Matches are upserted on match_id.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from llmtourney.core.model_names import normalize

logger = logging.getLogger(__name__)

_DEFAULT_URI = "mongodb://localhost:27017"
_DEFAULT_DIR = "output/telemetry"
_DB_NAME = "llmtourney"

# Known event type prefixes (all single words, no hyphens)
_KNOWN_EVENTS = {
    "bullshit", "holdem", "liarsdice", "rollerderby",
    "connectfour", "checkers", "reversi", "scrabble",
    "tictactoe", "yahtzee",
}


# ------------------------------------------------------------------
# Metadata inference
# ------------------------------------------------------------------

def _parse_event_from_match_id(match_id: str) -> str:
    """Extract event type from match_id prefix (e.g. 'holdem-...' → 'holdem')."""
    prefix = match_id.split("-")[0]
    if prefix in _KNOWN_EVENTS:
        return prefix
    return "unknown"


def _infer_tier_from_name(tournament_name: str) -> str:
    """Infer tier from tournament name (e.g. 's2-league-bantam' → 'bantam')."""
    if not tournament_name or tournament_name == "unknown":
        return "unknown"
    parts = tournament_name.rsplit("-", 1)
    return parts[-1] if len(parts) > 1 else "unknown"


def _resolve_metadata(
    summary: dict | None,
    match_id: str,
    cli_tournament_name: str | None,
    cli_tier: str | None,
) -> tuple[str, str, str, int]:
    """Resolve event_type, tournament_name, tier, round from all sources.

    Priority: summary fields > CLI overrides > match_id inference > "unknown".
    """
    # Event type: summary > match_id parse
    event_type = (summary or {}).get("event") or _parse_event_from_match_id(match_id)

    # Tournament name: summary > CLI override
    tournament_name = (summary or {}).get("tournament_name") or cli_tournament_name or "unknown"

    # Tier: summary > CLI override > infer from tournament_name
    tier = (summary or {}).get("tier") or cli_tier or _infer_tier_from_name(tournament_name)

    # Round: summary only
    round_num = (summary or {}).get("round", 0) or 0

    return event_type, tournament_name, tier, round_num


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


def _build_match_doc(
    summary: dict,
    event_type: str,
    tournament_name: str,
    tier: str,
    round_num: int,
) -> dict[str, Any]:
    """Build a MongoDB match document from a JSONL match_summary record."""
    scores = summary.get("final_scores", {})
    raw_player_models = summary.get("player_models", {})
    fidelity = summary.get("fidelity_report", {})

    # Normalize model identifiers
    player_models = {k: normalize(v) for k, v in raw_player_models.items()}

    return {
        "match_id": summary["match_id"],
        "schema_version": summary.get("schema_version", "1.1.0"),
        "scores": scores,
        "fidelity": fidelity,
        "player_models": player_models,
        "models": list(player_models.values()),
        "winner": _derive_winner(scores, player_models),
        "event_type": event_type,
        "tournament_name": tournament_name,
        "tier": tier,
        "round": round_num,
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
        # Normalize model identifiers
        if "model_id" in t:
            t["model_id"] = normalize(t["model_id"])
        if "model_version" in t:
            t["model_version"] = normalize(t["model_version"])
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
    for player_id, raw_model_id in player_models.items():
        model_id = normalize(raw_model_id)
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
    cli_tournament_name: str | None = None,
    cli_tier: str | None = None,
) -> tuple[int, int]:
    """Backfill a single JSONL file into MongoDB.

    Returns (turns_inserted, matches_upserted).
    """
    from pymongo.errors import BulkWriteError, PyMongoError

    print(f"Processing file {file_num}/{total}: {path.name}...")

    turns, summary = parse_jsonl_file(path)
    turns_inserted = 0
    matches_upserted = 0

    # Derive match_id from summary or filename
    match_id = ""
    if summary:
        match_id = summary.get("match_id", "")
    elif turns:
        match_id = turns[0].get("match_id", "")
    if not match_id:
        match_id = path.stem  # filename without extension

    event_type, tournament_name, tier, round_num = _resolve_metadata(
        summary, match_id, cli_tournament_name, cli_tier,
    )

    if turns:
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
        match_doc = _build_match_doc(summary, event_type, tournament_name, tier, round_num)
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
    tournament_name: str | None = None,
    tier: str | None = None,
) -> None:
    """Main entry point for backfill.

    Args:
        telemetry_dir: Directory containing .jsonl files.
        uri: MongoDB connection URI. Ignored in dry-run mode.
        dry_run: If True, parse files and print stats without writing.
        tournament_name: Override tournament_name for all files.
        tier: Override tier for all files.
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
            match_id = ""
            if summary:
                match_id = summary.get("match_id", "")
            elif turns:
                match_id = turns[0].get("match_id", "")
            if not match_id:
                match_id = f.stem

            evt, tname, t, rnd = _resolve_metadata(summary, match_id, tournament_name, tier)
            total_turns += n_turns
            total_summaries += has_summary
            print(f"  [{i}/{total}] {f.name}: {n_turns} turns, {has_summary} summary "
                  f"[event={evt}, tier={t}, tournament={tname}]")
        print(f"\nDry-run totals: {total_turns} turns, {total_summaries} match summaries")
        return

    # Connect to MongoDB
    from pymongo import MongoClient

    uri = uri or os.environ.get("TOURNEY_MONGO_URI", _DEFAULT_URI)
    client = MongoClient(uri, serverSelectionTimeoutMS=5000)
    client.admin.command("ping")
    db = client[_DB_NAME]
    print(f"Connected to MongoDB at {uri}")

    total_turns = 0
    total_matches = 0
    for i, f in enumerate(files, 1):
        t, m = backfill_file(db, f, i, total, tournament_name, tier)
        total_turns += t
        total_matches += m

    print(f"\nBackfill complete: {total_turns} turns inserted, {total_matches} matches upserted")
    client.close()


# ------------------------------------------------------------------
# Corrective update — fix metadata on existing records
# ------------------------------------------------------------------

def fix_existing_metadata(
    uri: str | None = None,
    dry_run: bool = False,
    tournament_name: str | None = None,
    tier: str | None = None,
) -> None:
    """Update event_type/tier/tournament_name on existing MongoDB records.

    Parses event_type from match_id prefix for all records where it's
    'unknown' or null. Applies CLI overrides for tier/tournament_name.
    """
    from pymongo import MongoClient

    uri = uri or os.environ.get("TOURNEY_MONGO_URI", _DEFAULT_URI)
    client = MongoClient(uri, serverSelectionTimeoutMS=5000)
    client.admin.command("ping")
    db = client[_DB_NAME]
    print(f"Connected to MongoDB at {uri}")

    # Fix matches collection
    matches_fixed = 0
    for doc in db["matches"].find():
        updates: dict[str, Any] = {}
        mid = doc.get("match_id", "")

        # Fix event_type
        if not doc.get("event_type") or doc["event_type"] == "unknown":
            parsed = _parse_event_from_match_id(mid)
            if parsed != "unknown":
                updates["event_type"] = parsed

        # Fix tournament_name
        if tournament_name and (not doc.get("tournament_name") or doc["tournament_name"] == "unknown"):
            updates["tournament_name"] = tournament_name

        # Fix tier
        resolved_tier = tier
        if not resolved_tier:
            tname = updates.get("tournament_name") or doc.get("tournament_name", "")
            resolved_tier = _infer_tier_from_name(tname)
        if resolved_tier != "unknown" and (not doc.get("tier") or doc["tier"] == "unknown"):
            updates["tier"] = resolved_tier

        if updates:
            if dry_run:
                print(f"  [dry-run] matches {mid}: {updates}")
            else:
                db["matches"].update_one({"_id": doc["_id"]}, {"$set": updates})
            matches_fixed += 1

    # Fix turns collection
    turns_fixed = 0
    # Use bulk update by match_id groups for efficiency
    match_ids = db["turns"].distinct("match_id")
    for mid in match_ids:
        sample = db["turns"].find_one({"match_id": mid})
        if not sample:
            continue

        updates: dict[str, Any] = {}

        if not sample.get("event_type") or sample["event_type"] == "unknown":
            parsed = _parse_event_from_match_id(mid)
            if parsed != "unknown":
                updates["event_type"] = parsed

        if tournament_name and (not sample.get("tournament_name") or sample["tournament_name"] == "unknown"):
            updates["tournament_name"] = tournament_name

        resolved_tier = tier
        if not resolved_tier:
            tname = updates.get("tournament_name") or sample.get("tournament_name", "")
            resolved_tier = _infer_tier_from_name(tname)
        if resolved_tier != "unknown" and (not sample.get("tier") or sample["tier"] == "unknown"):
            updates["tier"] = resolved_tier

        if updates:
            if dry_run:
                count = db["turns"].count_documents({"match_id": mid})
                print(f"  [dry-run] turns {mid}: {updates} ({count} docs)")
            else:
                db["turns"].update_many({"match_id": mid}, {"$set": updates})
            turns_fixed += 1

    action = "Would fix" if dry_run else "Fixed"
    print(f"\n{action} {matches_fixed} match records, {turns_fixed} turn groups")
    client.close()


# ------------------------------------------------------------------
# CLI
# ------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill JSONL telemetry files into MongoDB.",
    )
    sub = parser.add_subparsers(dest="command")

    # Default backfill command
    backfill_parser = sub.add_parser("backfill", help="Load JSONL files into MongoDB")
    backfill_parser.add_argument(
        "--uri", default=None,
        help="MongoDB connection URI (default: $TOURNEY_MONGO_URI or localhost:27017)",
    )
    backfill_parser.add_argument(
        "--dir", default=_DEFAULT_DIR, dest="telemetry_dir",
        help=f"Directory containing .jsonl files (default: {_DEFAULT_DIR})",
    )
    backfill_parser.add_argument(
        "--dry-run", action="store_true",
        help="Parse files and print stats without writing to MongoDB.",
    )
    backfill_parser.add_argument(
        "--tournament-name", default=None,
        help="Override tournament_name for all files (e.g. 's2-league-bantam').",
    )
    backfill_parser.add_argument(
        "--tier", default=None,
        help="Override tier for all files (e.g. 'bantam').",
    )

    # Fix existing records
    fix_parser = sub.add_parser("fix", help="Fix metadata on existing MongoDB records")
    fix_parser.add_argument(
        "--uri", default=None,
        help="MongoDB connection URI",
    )
    fix_parser.add_argument(
        "--dry-run", action="store_true",
        help="Show what would be updated without writing.",
    )
    fix_parser.add_argument(
        "--tournament-name", default=None,
        help="Set tournament_name on records where it's unknown.",
    )
    fix_parser.add_argument(
        "--tier", default=None,
        help="Set tier on records where it's unknown.",
    )

    args = parser.parse_args()

    if args.command == "fix":
        fix_existing_metadata(
            uri=args.uri, dry_run=args.dry_run,
            tournament_name=args.tournament_name, tier=args.tier,
        )
    elif args.command == "backfill":
        run_backfill(
            args.telemetry_dir, uri=args.uri, dry_run=args.dry_run,
            tournament_name=args.tournament_name, tier=args.tier,
        )
    else:
        # No subcommand — run backfill for backwards compat
        parser.add_argument("--uri", default=None)
        parser.add_argument("--dir", default=_DEFAULT_DIR, dest="telemetry_dir")
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--tournament-name", default=None)
        parser.add_argument("--tier", default=None)
        args = parser.parse_args()
        run_backfill(
            args.telemetry_dir, uri=args.uri, dry_run=args.dry_run,
            tournament_name=args.tournament_name, tier=args.tier,
        )


if __name__ == "__main__":
    main()
