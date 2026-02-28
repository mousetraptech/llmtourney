#!/usr/bin/env python3
"""Backfill "unknown" event_type in MongoDB.

Many turns and matches have event_type="unknown" because they came from
crashed matches (no match_summary line) or the backfill script defaulted
to "unknown". This script infers event_type from the match_id prefix
(e.g., "holdem-xxx" → "holdem") and updates MongoDB in place.

Usage:
    python scripts/backfill_event_types.py [--dry-run]
"""

import argparse
import re
import sys

from pymongo import MongoClient, UpdateMany

# Ordered longest-prefix-first to avoid false matches
EVENT_PREFIXES = [
    ("connectfour-", "connectfour"),
    ("tictactoe-", "tictactoe"),
    ("rollerderby-", "rollerderby"),
    ("liarsdice-", "liarsdice"),
    ("bullshit-", "bullshit"),
    ("checkers-", "checkers"),
    ("scrabble-", "scrabble"),
    ("reversi-", "reversi"),
    ("yahtzee-", "rollerderby"),  # legacy prefix → new canonical name
    ("holdem-", "holdem"),
]


def infer_event_type(match_id: str) -> str | None:
    """Infer event_type from match_id prefix."""
    for prefix, event_type in EVENT_PREFIXES:
        if match_id.startswith(prefix):
            return event_type
    return None


def main():
    parser = argparse.ArgumentParser(description="Backfill unknown event_type in MongoDB")
    parser.add_argument("--dry-run", action="store_true", help="Print what would be done without writing")
    parser.add_argument("--uri", default="mongodb://localhost:27017", help="MongoDB URI")
    parser.add_argument("--db", default="llmtourney", help="Database name")
    args = parser.parse_args()

    client = MongoClient(args.uri)
    db = client[args.db]

    for collection_name in ("turns", "matches"):
        coll = db[collection_name]
        unknown_count = coll.count_documents({"event_type": "unknown"})
        print(f"\n{collection_name}: {unknown_count} documents with event_type='unknown'")

        if unknown_count == 0:
            continue

        # Get distinct match_ids with unknown event_type
        match_ids = coll.distinct("match_id", {"event_type": "unknown"})
        print(f"  {len(match_ids)} distinct match_ids")

        fixed = 0
        unfixable = 0
        updates_by_type: dict[str, list[str]] = {}

        for mid in match_ids:
            inferred = infer_event_type(mid)
            if inferred:
                updates_by_type.setdefault(inferred, []).append(mid)
            else:
                unfixable += 1
                print(f"  [SKIP] Cannot infer event_type for: {mid}")

        for event_type, mids in updates_by_type.items():
            if args.dry_run:
                print(f"  [DRY RUN] Would set {len(mids)} match_ids → event_type='{event_type}'")
                fixed += len(mids)
            else:
                result = coll.update_many(
                    {"match_id": {"$in": mids}, "event_type": "unknown"},
                    {"$set": {"event_type": event_type}},
                )
                print(f"  Updated {result.modified_count} docs → event_type='{event_type}'")
                fixed += result.modified_count

        print(f"  Summary: {fixed} fixed, {unfixable} unfixable")

    # Also fix any "yahtzee" → "rollerderby" in non-unknown docs
    for collection_name in ("turns", "matches"):
        coll = db[collection_name]
        yahtzee_count = coll.count_documents({"event_type": "yahtzee"})
        if yahtzee_count > 0:
            if args.dry_run:
                print(f"\n{collection_name}: [DRY RUN] Would rename {yahtzee_count} 'yahtzee' → 'rollerderby'")
            else:
                result = coll.update_many(
                    {"event_type": "yahtzee"},
                    {"$set": {"event_type": "rollerderby"}},
                )
                print(f"\n{collection_name}: Renamed {result.modified_count} 'yahtzee' → 'rollerderby'")

    # Fix model stats: rename games.yahtzee → games.rollerderby
    models_coll = db["models"]
    yahtzee_models = list(models_coll.find({"games.yahtzee": {"$exists": True}}))
    if yahtzee_models:
        if args.dry_run:
            print(f"\nmodels: [DRY RUN] Would rename games.yahtzee → games.rollerderby for {len(yahtzee_models)} models")
        else:
            result = models_coll.update_many(
                {"games.yahtzee": {"$exists": True}},
                {"$rename": {"games.yahtzee": "games.rollerderby"}},
            )
            print(f"\nmodels: Renamed games.yahtzee → games.rollerderby for {result.modified_count} models")

    client.close()
    print("\nDone.")


if __name__ == "__main__":
    main()
