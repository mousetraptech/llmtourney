#!/usr/bin/env python3
"""Run a single match from a config file.

Usage:
    python run_match.py <config>

The event name and player count are inferred from the config.
Replaces the per-game run_bullshit.py, run_holdem.py, etc. scripts.
"""

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

if len(sys.argv) < 2:
    print("Usage: python run_match.py <config.yaml>")
    sys.exit(1)

cfg_path = sys.argv[1]
config = load_config(Path(cfg_path))
engine = TournamentEngine(config)

event_name = next(iter(config.events))
event_cfg = config.events[event_name]
models = list(config.models.keys())
label = DISPLAY_NAMES.get(event_name, event_name)

print(f"Running {label} match: {', '.join(models)}")

result = engine._run_multiplayer_match(event_name, event_cfg, models)

print(f"\nMatch complete: {result.match_id}")
print(f"Scores: {result.scores}")
print(f"Player models: {result.player_models}")
print(f"Telemetry: {engine.telemetry_dir / result.match_id}.jsonl")
