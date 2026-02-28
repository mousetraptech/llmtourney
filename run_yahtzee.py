#!/usr/bin/env python3
"""Run a single multiplayer yahtzee match."""

import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path.home() / "projects" / ".env")

from llmtourney.config import load_config
from llmtourney.tournament import TournamentEngine

cfg_path = sys.argv[1] if len(sys.argv) > 1 else "configs/yahtzee-midtier-match.yaml"
config = load_config(Path(cfg_path))
engine = TournamentEngine(config)

models = list(config.models.keys())
print(f"Running yahtzee match: {' vs '.join(models)}")

event_cfg = config.events["yahtzee"]
result = engine._run_multiplayer_match("yahtzee", event_cfg, models)

print(f"\nMatch complete: {result.match_id}")
print(f"Scores: {result.scores}")
print(f"Player models: {result.player_models}")
print(f"Telemetry: {engine.telemetry_dir / result.match_id}.jsonl")
