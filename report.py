#!/usr/bin/env python3
"""Generate match reports from telemetry files.

Usage:
    python report.py <telemetry.jsonl>              # auto-detect game, output HTML
    python report.py <telemetry.jsonl> -o report.html
    python report.py output/telemetry/*.jsonl       # batch mode
    python report.py <telemetry.jsonl> --json       # dump report as JSON
"""

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from llmtourney.reporting.reader import MatchData
from llmtourney.reporting.bullshit_analyzer import analyze as analyze_bullshit
from llmtourney.reporting.dashboard import generate_dashboard


def main():
    parser = argparse.ArgumentParser(description="Generate match telemetry reports")
    parser.add_argument("files", nargs="+", help="JSONL telemetry file(s)")
    parser.add_argument("-o", "--output", help="Output file path (default: auto-named)")
    parser.add_argument(
        "--output-dir",
        default="output/reports",
        help="Output directory for batch mode (default: output/reports)",
    )
    parser.add_argument("--json", action="store_true", help="Output JSON instead of HTML")
    parser.add_argument("--quiet", action="store_true", help="Suppress progress output")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    for filepath in args.files:
        path = Path(filepath)
        if not path.exists():
            print(f"  SKIP {path} (not found)", file=sys.stderr)
            continue

        if not args.quiet:
            print(f"  Loading {path.name}...", end=" ")

        try:
            match = MatchData.from_file(path)
        except Exception as e:
            print(f"ERROR: {e}", file=sys.stderr)
            continue

        if not args.quiet:
            print(f"{match.game_type} | {match.num_players}p | {len(match.turns)} turns")

        if match.game_type == "bullshit":
            report = analyze_bullshit(match)

            if args.json:
                out_path = Path(args.output) if args.output else output_dir / f"{path.stem}-report.json"
                out_path.write_text(json.dumps(asdict(report), indent=2, default=str))
            else:
                out_path = Path(args.output) if args.output else output_dir / f"{path.stem}-report.html"
                generate_dashboard(report, out_path)

            if not args.quiet:
                print(f"    → {out_path}")
                print(f"    Finish: {' → '.join(report.finish_order)}")
                print(f"    Suboptimal plays: {len(report.suboptimal_plays)}")
        else:
            if not args.quiet:
                print(f"    → No analyzer for '{match.game_type}' yet (reader OK, analyzer needed)")


if __name__ == "__main__":
    main()
