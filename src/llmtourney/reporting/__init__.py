"""LLM Tourney reporting module.

Usage:
    from llmtourney.reporting import MatchData, analyze_bullshit, generate_dashboard

    match = MatchData.from_file("path/to/telemetry.jsonl")
    report = analyze_bullshit(match)
    generate_dashboard(report, "output/report.html")
"""

from .reader import MatchData, Turn
from .bullshit_analyzer import analyze as analyze_bullshit, BullshitReport
from .dashboard import generate_dashboard

__all__ = [
    "MatchData",
    "Turn",
    "analyze_bullshit",
    "BullshitReport",
    "generate_dashboard",
]
