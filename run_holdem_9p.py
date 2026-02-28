#!/usr/bin/env python3
"""Run a single 9-player holdem match."""

import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path.home() / "projects" / ".env")

from llmtourney.config import load_config
from llmtourney.tournament import TournamentEngine

cfg_path = sys.argv[1] if len(sys.argv) > 1 else "configs/holdem-9player-alltier.yaml"
config = load_config(Path(cfg_path))
engine = TournamentEngine(config)

models = list(config.models.keys())
print(f"Running 9-player holdem: {', '.join(models)}")

event_cfg = config.events["holdem"]
result = engine._run_multiplayer_match("holdem", event_cfg, models)

print(f"\nMatch complete: {result.match_id}")
print(f"Scores: {result.scores}")
print(f"Player models: {result.player_models}")
print(f"Telemetry: {engine.telemetry_dir / result.match_id}.jsonl")
