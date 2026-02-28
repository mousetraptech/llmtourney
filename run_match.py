#!/usr/bin/env python3
"""Run a single match from a config file, or resume an interrupted one.

Usage:
    python run_match.py <config>
    python run_match.py <config> --resume <telemetry.jsonl>

The event name and player count are inferred from the config.
Replaces the per-game run_bullshit.py, run_holdem.py, etc. scripts.
"""

import json
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path.home() / "projects" / ".env")

from llmtourney.config import load_config
from llmtourney.tournament import TournamentEngine

DISPLAY_NAMES = {
    "holdem": "Hold'em",
    "bullshit": "Bullshit",
    "liarsdice": "Liar's Dice",
    "rollerderby": "Roller Derby",
    "yahtzee": "Roller Derby",
    "tictactoe": "Tic-Tac-Toe",
    "connectfour": "Connect Four",
    "checkers": "Checkers",
    "reversi": "Reversi",
    "scrabble": "Scrabble",
}


def _parse_resume_file(jsonl_path: Path) -> dict:
    """Read telemetry JSONL and extract resume state from last turn."""
    last_turn = None
    with open(jsonl_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            # Skip match_summary records
            if record.get("record_type") == "match_summary":
                continue
            last_turn = record

    if last_turn is None:
        print("Error: no turn records found in telemetry file")
        sys.exit(1)

    snapshot = last_turn["state_snapshot"]
    match_id = last_turn["match_id"]
    turn_number = last_turn["turn_number"]

    # Extract per-player cumulative strikes from the last turn for each player
    # We need to scan all turns for the latest strike count per player
    strikes: dict[str, int] = {}
    with open(jsonl_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            if record.get("record_type") == "match_summary":
                continue
            pid = record.get("player_id")
            cs = record.get("cumulative_strikes")
            if pid and cs is not None:
                strikes[pid] = cs

    # Extract player_models from snapshot (injected by engine)
    player_models = snapshot.get("player_models", {})

    return {
        "match_id": match_id,
        "snapshot": snapshot,
        "turn_number": turn_number,
        "strikes": strikes,
        "player_models": player_models,
    }


# --- Argument parsing ---
args = sys.argv[1:]
resume_path = None

if "--resume" in args:
    idx = args.index("--resume")
    if idx + 1 >= len(args):
        print("Error: --resume requires a telemetry JSONL path")
        sys.exit(1)
    resume_path = Path(args[idx + 1])
    args = args[:idx] + args[idx + 2:]

if len(args) < 1:
    print("Usage: python run_match.py <config.yaml> [--resume <telemetry.jsonl>]")
    sys.exit(1)

cfg_path = args[0]
config = load_config(Path(cfg_path))
engine = TournamentEngine(config)

event_name = next(iter(config.events))
event_cfg = config.events[event_name]
models = list(config.models.keys())
label = DISPLAY_NAMES.get(event_name, event_name)

if resume_path:
    resume_state = _parse_resume_file(resume_path)

    # Use model ordering from original match's player_models mapping
    if resume_state["player_models"]:
        player_ids = sorted(resume_state["player_models"].keys())
        models = [resume_state["player_models"][pid] for pid in player_ids]

    print(f"Resuming {label} match: {resume_state['match_id']}")
    print(f"  From turn {resume_state['turn_number']}, {', '.join(models)}")

    result = engine._run_multiplayer_match(
        event_name, event_cfg, models, resume_state=resume_state,
    )
else:
    print(f"Running {label} match: {', '.join(models)}")
    result = engine._run_multiplayer_match(event_name, event_cfg, models)

print(f"\nMatch complete: {result.match_id}")
print(f"Scores: {result.scores}")
print(f"Player models: {result.player_models}")
print(f"Telemetry: {engine.telemetry_dir / result.match_id}.jsonl")
