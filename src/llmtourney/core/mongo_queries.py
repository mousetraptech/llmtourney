"""MongoDB aggregation pipeline helpers for llmtourney analytics.

All functions take a pymongo.database.Database and return plain dicts.
pymongo is imported inside functions (optional dependency pattern).
"""

from __future__ import annotations

import os


def get_db(uri: str | None = None, db_name: str = "llmtourney"):
    """Connect and return a pymongo Database handle.

    Falls back to TOURNEY_MONGO_URI env var if no uri provided.
    """
    from pymongo import MongoClient

    if uri is None:
        uri = os.environ.get("TOURNEY_MONGO_URI")
    if not uri:
        raise ValueError("No MongoDB URI provided and TOURNEY_MONGO_URI not set")
    client = MongoClient(uri)
    return client[db_name]


def win_rates(
    db,
    model_id: str | None = None,
    event_type: str | None = None,
    tier: str | None = None,
) -> list[dict]:
    """Win/loss/draw rates per model from the matches collection.

    Groups by (model, event_type), sorted by win_rate descending.
    """
    pipeline: list[dict] = []

    # Optional filters
    match_filter: dict = {}
    if model_id:
        match_filter["models"] = model_id
    if event_type:
        match_filter["event_type"] = event_type
    if tier:
        match_filter["tier"] = tier
    if match_filter:
        pipeline.append({"$match": match_filter})

    # Unwind models array so each model gets its own row
    pipeline.append({"$unwind": "$models"})

    # If model_id specified, filter again after unwind to get only that model's rows
    if model_id:
        pipeline.append({"$match": {"models": model_id}})

    # Group by (model, event_type) and count wins/losses/draws
    pipeline.append({
        "$group": {
            "_id": {"model": "$models", "event_type": "$event_type"},
            "wins": {
                "$sum": {"$cond": [{"$eq": ["$winner", "$models"]}, 1, 0]}
            },
            "losses": {
                "$sum": {
                    "$cond": [
                        {"$and": [
                            {"$ne": ["$winner", None]},
                            {"$ne": ["$winner", "$models"]},
                        ]},
                        1,
                        0,
                    ]
                }
            },
            "draws": {
                "$sum": {"$cond": [{"$eq": ["$winner", None]}, 1, 0]}
            },
            "total": {"$sum": 1},
        }
    })

    # Compute win_rate
    pipeline.append({
        "$addFields": {
            "win_rate": {
                "$cond": [
                    {"$gt": ["$total", 0]},
                    {"$divide": ["$wins", "$total"]},
                    0,
                ]
            }
        }
    })

    # Sort by win_rate descending
    pipeline.append({"$sort": {"win_rate": -1}})

    return list(db["matches"].aggregate(pipeline))


def avg_latency(
    db,
    model_id: str | None = None,
    event_type: str | None = None,
    tournament_name: str | None = None,
) -> list[dict]:
    """Average, min, max latency per model from the turns collection.

    Groups by (model_id, event_type), sorted by avg ascending.
    """
    pipeline: list[dict] = []

    match_filter: dict = {}
    if model_id:
        match_filter["model_id"] = model_id
    if event_type:
        match_filter["event_type"] = event_type
    if tournament_name:
        match_filter["tournament_name"] = tournament_name
    if match_filter:
        pipeline.append({"$match": match_filter})

    pipeline.append({
        "$group": {
            "_id": {"model_id": "$model_id", "event_type": "$event_type"},
            "avg_ms": {"$avg": "$latency_ms"},
            "min_ms": {"$min": "$latency_ms"},
            "max_ms": {"$max": "$latency_ms"},
        }
    })

    pipeline.append({"$sort": {"avg_ms": 1}})

    return list(db["turns"].aggregate(pipeline))


def violation_frequency(
    db,
    model_id: str | None = None,
    violation: str | None = None,
) -> list[dict]:
    """Violation counts per model from the turns collection.

    Only considers turns where violation is not null.
    Groups by (model_id, violation), sorted by count descending.
    """
    pipeline: list[dict] = []

    match_filter: dict = {"violation": {"$ne": None}}
    if model_id:
        match_filter["model_id"] = model_id
    if violation:
        match_filter["violation"] = violation
    pipeline.append({"$match": match_filter})

    pipeline.append({
        "$group": {
            "_id": {"model_id": "$model_id", "violation": "$violation"},
            "count": {"$sum": 1},
        }
    })

    pipeline.append({"$sort": {"count": -1}})

    return list(db["turns"].aggregate(pipeline))


def head_to_head(
    db,
    model_a: str,
    model_b: str,
    event_type: str | None = None,
) -> dict:
    """Head-to-head record between two models.

    Returns {model_a: wins, model_b: wins, draws: count, matches: [match_ids]}.
    """
    query: dict = {"models": {"$all": [model_a, model_b]}}
    if event_type:
        query["event_type"] = event_type

    matches = list(db["matches"].find(query))

    a_wins = 0
    b_wins = 0
    draws = 0
    match_ids = []

    for m in matches:
        match_ids.append(m["match_id"])
        winner = m.get("winner")
        if winner == model_a:
            a_wins += 1
        elif winner == model_b:
            b_wins += 1
        else:
            draws += 1

    return {
        model_a: a_wins,
        model_b: b_wins,
        "draws": draws,
        "matches": match_ids,
    }


def latency_by_phase(
    db,
    model_id: str,
    event_type: str,
) -> list[dict]:
    """Average latency by game phase (early/mid/late) for a model.

    Assigns phases using percentile thirds of max turn per match:
    turn_number <= max_turn * 0.333 = early, <= 0.667 = mid, else late.
    """
    pipeline: list[dict] = []

    # Filter to this model and event type
    pipeline.append({"$match": {"model_id": model_id, "event_type": event_type}})

    # First pass: group by match to get max_turn per match, keeping all turns
    # Use $lookup on self is too complex; instead use two-stage approach:
    # Stage 1: compute max turn per match
    # Stage 2: join back and assign phase

    # Group by match_id to get max turn_number, preserving turn data
    pipeline.append({
        "$group": {
            "_id": "$match_id",
            "max_turn": {"$max": "$turn_number"},
            "turns": {
                "$push": {
                    "turn_number": "$turn_number",
                    "latency_ms": "$latency_ms",
                }
            },
        }
    })

    # Unwind turns back out
    pipeline.append({"$unwind": "$turns"})

    # Assign phase based on percentile thirds
    pipeline.append({
        "$addFields": {
            "phase": {
                "$cond": [
                    {"$lte": [
                        "$turns.turn_number",
                        {"$multiply": ["$max_turn", 0.333]},
                    ]},
                    "early",
                    {
                        "$cond": [
                            {"$lte": [
                                "$turns.turn_number",
                                {"$multiply": ["$max_turn", 0.667]},
                            ]},
                            "mid",
                            "late",
                        ]
                    },
                ]
            }
        }
    })

    # Group by phase with avg latency
    pipeline.append({
        "$group": {
            "_id": "$phase",
            "avg_ms": {"$avg": "$turns.latency_ms"},
        }
    })

    # Sort early -> mid -> late (alphabetical happens to work)
    pipeline.append({"$sort": {"_id": 1}})

    return list(db["turns"].aggregate(pipeline))


def token_efficiency(
    db,
    model_id: str | None = None,
    event_type: str | None = None,
) -> list[dict]:
    """Token efficiency per model from the matches collection.

    Uses denormalized total_tokens and total_turns on match docs.
    Computes avg total_tokens, avg total_turns, tokens_per_turn, win_rate.
    Sorted by win_rate descending.
    """
    pipeline: list[dict] = []

    match_filter: dict = {}
    if model_id:
        match_filter["models"] = model_id
    if event_type:
        match_filter["event_type"] = event_type
    if match_filter:
        pipeline.append({"$match": match_filter})

    # Unwind models
    pipeline.append({"$unwind": "$models"})

    # Filter after unwind if model_id specified
    if model_id:
        pipeline.append({"$match": {"models": model_id}})

    # Group by model
    pipeline.append({
        "$group": {
            "_id": "$models",
            "avg_tokens": {"$avg": "$total_tokens"},
            "avg_turns": {"$avg": "$total_turns"},
            "wins": {
                "$sum": {"$cond": [{"$eq": ["$winner", "$models"]}, 1, 0]}
            },
            "total": {"$sum": 1},
        }
    })

    # Compute tokens_per_turn and win_rate
    pipeline.append({
        "$addFields": {
            "tokens_per_turn": {
                "$cond": [
                    {"$gt": ["$avg_turns", 0]},
                    {"$divide": ["$avg_tokens", "$avg_turns"]},
                    0,
                ]
            },
            "win_rate": {
                "$cond": [
                    {"$gt": ["$total", 0]},
                    {"$divide": ["$wins", "$total"]},
                    0,
                ]
            },
        }
    })

    pipeline.append({"$sort": {"win_rate": -1}})

    return list(db["matches"].aggregate(pipeline))


def fidelity_scores(
    db,
    event_type: str | None = None,
    tier: str | None = None,
) -> list[dict]:
    """Fidelity (clean play) scores per model from the matches collection.

    Groups by model, sums violation counts from fidelity_report,
    computes clean play percentage. Sorted cleanest first.
    """
    pipeline: list[dict] = []

    match_filter: dict = {}
    if event_type:
        match_filter["event_type"] = event_type
    if tier:
        match_filter["tier"] = tier
    if match_filter:
        pipeline.append({"$match": match_filter})

    # Unwind models to get one row per model per match
    pipeline.append({"$unwind": "$models"})

    # Group by model, summing violations from the fidelity field
    # The fidelity doc is keyed by player_id (player_a, player_b, etc.)
    # with total_violations per player. Since we unwound models, we need
    # to sum all violations across the fidelity sub-doc.
    # We use $objectToArray to handle dynamic player keys.
    pipeline.append({
        "$addFields": {
            "fidelity_entries": {"$objectToArray": {"$ifNull": ["$fidelity", {}]}},
        }
    })

    pipeline.append({
        "$addFields": {
            "match_violations": {
                "$sum": "$fidelity_entries.v.total_violations"
            }
        }
    })

    pipeline.append({
        "$group": {
            "_id": "$models",
            "total_matches": {"$sum": 1},
            "total_violations": {"$sum": "$match_violations"},
            "clean_matches": {
                "$sum": {"$cond": [{"$eq": ["$match_violations", 0]}, 1, 0]}
            },
        }
    })

    # Compute clean_pct
    pipeline.append({
        "$addFields": {
            "clean_pct": {
                "$cond": [
                    {"$gt": ["$total_matches", 0]},
                    {"$multiply": [
                        {"$divide": ["$clean_matches", "$total_matches"]},
                        100,
                    ]},
                    0,
                ]
            }
        }
    })

    # Sorted cleanest first (highest clean_pct)
    pipeline.append({"$sort": {"clean_pct": -1}})

    return list(db["matches"].aggregate(pipeline))
