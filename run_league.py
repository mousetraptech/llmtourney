#!/usr/bin/env python3
"""Run a league tournament from a config file.

Usage:
    python run_league.py <config.yaml>

Resumable — if interrupted, re-run the same command to pick up where you left off.
"""

import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path.home() / "projects" / ".env")

from llmtourney.config import load_config
from llmtourney.league import LeagueRunner

if len(sys.argv) < 2:
    print("Usage: python run_league.py <config.yaml>")
    sys.exit(1)

config = load_config(Path(sys.argv[1]))
runner = LeagueRunner(config)
runner.run()
