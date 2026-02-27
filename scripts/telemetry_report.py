"""Console model performance summary from MongoDB.

Usage:
    python -m scripts.telemetry_report [--uri URI] [--event EVENT] [--model MODEL] [--json]
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import TextIO

from llmtourney.core import mongo_queries


def print_report(
    db,
    event_type: str | None = None,
    model_id: str | None = None,
    as_json: bool = False,
    file: TextIO | None = None,
) -> None:
    """Gather data from query helpers and print a formatted report."""
    if file is None:
        file = sys.stdout

    # Gather data
    leaderboard_raw = mongo_queries.win_rates(db, event_type=event_type)
    violations_raw = mongo_queries.violation_frequency(db, model_id=model_id)
    fidelity_raw = mongo_queries.fidelity_scores(db, event_type=event_type)
    latency_raw = mongo_queries.avg_latency(db, event_type=event_type)

    # Normalize into plain dicts for JSON / display
    leaderboard = []
    for r in leaderboard_raw:
        _id = r.get("_id", {})
        leaderboard.append({
            "model": _id.get("model", "unknown"),
            "event_type": _id.get("event_type", ""),
            "wins": r.get("wins", 0),
            "losses": r.get("losses", 0),
            "draws": r.get("draws", 0),
            "win_rate": r.get("win_rate", 0),
            "total": r.get("total", 0),
        })

    violations = []
    for r in violations_raw:
        _id = r.get("_id", {})
        violations.append({
            "model": _id.get("model_id", "unknown"),
            "violation": _id.get("violation", ""),
            "count": r.get("count", 0),
        })

    fidelity = []
    for r in fidelity_raw:
        fidelity.append({
            "model": r.get("_id", "unknown"),
            "total_violations": r.get("total_violations", 0),
            "clean_pct": r.get("clean_pct", 0),
            "total_matches": r.get("total_matches", 0),
        })

    latency = []
    for r in latency_raw:
        _id = r.get("_id", {})
        latency.append({
            "model": _id.get("model_id", "unknown"),
            "event_type": _id.get("event_type", ""),
            "avg_ms": r.get("avg_ms", 0),
        })

    data = {
        "leaderboard": leaderboard,
        "violations": violations,
        "fidelity": fidelity,
        "latency": latency,
    }

    if as_json:
        print(json.dumps(data, indent=2, default=str), file=file)
        return

    # Console report
    sep = "=" * 60
    dash = "-" * 60

    print(file=file)
    print(sep, file=file)
    print("  LLM Tourney \u2014 Model Performance Report", file=file)
    print(sep, file=file)

    # Leaderboard
    print(file=file)
    print(
        f"{'Model':<26} {'W':>5} {'L':>5} {'D':>5} {'Win%':>6} {'Games':>7}",
        file=file,
    )
    print(dash, file=file)
    for row in leaderboard:
        win_pct = f"{row['win_rate'] * 100:.1f}%"
        print(
            f"{row['model']:<26} {row['wins']:>5} {row['losses']:>5} "
            f"{row['draws']:>5} {win_pct:>6} {row['total']:>7}",
            file=file,
        )

    # Violations
    if violations:
        print(file=file)
        print(
            f"{'Model':<26} {'Violation':<23} {'Count':>5}",
            file=file,
        )
        print(dash, file=file)
        for row in violations:
            print(
                f"{row['model']:<26} {row['violation']:<23} {row['count']:>5}",
                file=file,
            )

    # Fidelity
    if fidelity:
        print(file=file)
        print(
            f"{'Model':<26} {'Violations':>10} {'Clean%':>8}",
            file=file,
        )
        print("-" * 46, file=file)
        for row in fidelity:
            clean = f"{row['clean_pct']:.1f}%"
            print(
                f"{row['model']:<26} {row['total_violations']:>10} {clean:>8}",
                file=file,
            )

    # Latency
    if latency:
        print(file=file)
        print(
            f"{'Model':<26} {'Game':<16} {'Avg ms':>8}",
            file=file,
        )
        print(dash, file=file)
        for row in latency:
            print(
                f"{row['model']:<26} {row['event_type']:<16} {row['avg_ms']:>8.0f}",
                file=file,
            )

    print(file=file)


def main():
    parser = argparse.ArgumentParser(
        description="LLM Tourney - Model Performance Report"
    )
    parser.add_argument("--uri", default=None, help="MongoDB URI")
    parser.add_argument("--event", default=None, help="Filter by event type")
    parser.add_argument("--model", default=None, help="Filter by model ID")
    parser.add_argument(
        "--json", dest="as_json", action="store_true",
        help="Output as JSON instead of formatted table",
    )
    args = parser.parse_args()

    db = mongo_queries.get_db(uri=args.uri)
    print_report(
        db,
        event_type=args.event,
        model_id=args.model,
        as_json=args.as_json,
    )


if __name__ == "__main__":
    main()
