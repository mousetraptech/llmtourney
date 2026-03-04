"""CLI entry point: python -m llmtourney <config.yaml>"""

import argparse
import sys
from pathlib import Path

from llmtourney.config import load_config
from llmtourney.tournament import TournamentEngine


def _run_round_robin(config, resume_file: Path | None = None) -> None:
    """Run a round-robin tournament."""
    resume_state = None
    if resume_file:
        from llmtourney.core.telemetry import load_resume_state
        resume_state = load_resume_state(resume_file)
        print(f"Resuming match {resume_state['match_id']} from turn {resume_state['turn_number']}")
        print()

    engine = TournamentEngine(config)
    result = engine.run(resume_state=resume_state)

    print("=" * 60)
    print("RESULTS")
    print("=" * 60)
    print()

    for match in result.matches:
        models = match.player_models
        scores = match.scores
        winner = max(scores, key=scores.get)
        winner_model = models[winner]
        margin = scores[winner] - scores[min(scores, key=scores.get)]
        violations = sum(
            v.get("total_violations", 0)
            for v in match.fidelity.values()
        )
        print(f"  {match.match_id}")
        # Sort players by score descending
        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        for pid, sc in ranked:
            print(f"    {models[pid]:20s} {sc:>6.0f} pts")
        print(f"    Winner: {winner_model} (+{margin:.0f})  Violations: {violations}")
        print()

    print("-" * 60)
    print("STANDINGS")
    print("-" * 60)
    for rank, (model, score) in enumerate(
        sorted(result.standings.items(), key=lambda x: x[1], reverse=True), 1
    ):
        print(f"  {rank}. {model:20s} {score:>8.0f}")
    print()
    print(f"Telemetry: {result.telemetry_dir}")


def _run_league(config) -> None:
    """Run a round-robin league tournament."""
    from llmtourney.league import LeagueRunner

    runner = LeagueRunner(config)
    manifest = runner.run()

    print(f"Telemetry: {runner.engine.telemetry_dir}")
    print(f"Manifest:  {runner.manifest_path}")


def _run_bracket(config, pause_before_final: bool = False) -> None:
    """Run a single-elimination bracket tournament."""
    from llmtourney.bracket import BracketRunner

    runner = BracketRunner(config, pause_before_final=pause_before_final)
    manifest = runner.run()

    runner.print_bracket()

    print()
    print(f"Telemetry: {runner.engine.telemetry_dir}")
    print(f"Manifest:  {runner.manifest_path}")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="llmtourney",
        description="LLM Tournament of Champions",
    )
    parser.add_argument(
        "config",
        type=Path,
        help="Path to tournament YAML config file",
    )
    parser.add_argument(
        "-o", "--output",
        type=Path,
        default=None,
        help="Output directory (default: output/runs/)",
    )
    parser.add_argument(
        "--pause-before-final",
        action="store_true",
        default=False,
        help="Pause for confirmation before starting the final match",
    )
    parser.add_argument(
        "--resume",
        type=Path,
        default=None,
        help="Resume a crashed match from a telemetry JSONL file",
    )
    args = parser.parse_args()

    if not args.config.exists():
        print(f"Error: config file not found: {args.config}", file=sys.stderr)
        sys.exit(1)

    config = load_config(args.config)
    if args.output:
        config.output_dir = args.output

    print(f"Tournament: {config.name} (seed={config.seed}, format={config.format})")
    print(f"Models: {', '.join(config.models)}")
    print(f"Events: {', '.join(config.events)}")
    print()

    if config.format == "bracket":
        _run_bracket(config, pause_before_final=args.pause_before_final)
    elif config.format == "league":
        _run_league(config)
    else:
        _run_round_robin(config, resume_file=args.resume)


if __name__ == "__main__":
    main()
