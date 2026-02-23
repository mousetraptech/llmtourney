"""Integration test: full Hold'em match via TournamentEngine."""

import json
from pathlib import Path

import pytest

from llmtourney.config import load_config
from llmtourney.tournament import TournamentEngine


EXAMPLE_CONFIG = Path(__file__).resolve().parent.parent / "tournament.yaml.example"


class TestTournamentHoldem:
    def test_full_match_completes(self, tmp_path):
        config = load_config(EXAMPLE_CONFIG)
        config.output_dir = tmp_path / "output"
        engine = TournamentEngine(config)
        result = engine.run()
        assert result is not None

    def test_telemetry_files_created(self, tmp_path):
        config = load_config(EXAMPLE_CONFIG)
        config.output_dir = tmp_path / "output"
        engine = TournamentEngine(config)
        result = engine.run()
        jsonl_files = list(result.telemetry_dir.glob("*.jsonl"))
        assert len(jsonl_files) >= 1

    def test_telemetry_valid_jsonl(self, tmp_path):
        config = load_config(EXAMPLE_CONFIG)
        config.output_dir = tmp_path / "output"
        engine = TournamentEngine(config)
        result = engine.run()
        for jsonl_file in result.telemetry_dir.glob("*.jsonl"):
            for line in jsonl_file.read_text().strip().split("\n"):
                parsed = json.loads(line)
                assert "schema_version" in parsed

    def test_match_summary_has_scores(self, tmp_path):
        config = load_config(EXAMPLE_CONFIG)
        config.output_dir = tmp_path / "output"
        engine = TournamentEngine(config)
        result = engine.run()
        for jsonl_file in result.telemetry_dir.glob("*.jsonl"):
            lines = jsonl_file.read_text().strip().split("\n")
            summary = json.loads(lines[-1])
            if summary.get("record_type") == "match_summary":
                assert "final_scores" in summary
                scores = summary["final_scores"]
                total = sum(scores.values())
                assert total == 400  # chip conservation

    def test_no_violations_from_clean_mocks(self, tmp_path):
        config = load_config(EXAMPLE_CONFIG)
        config.output_dir = tmp_path / "output"
        engine = TournamentEngine(config)
        result = engine.run()
        for jsonl_file in result.telemetry_dir.glob("*.jsonl"):
            lines = jsonl_file.read_text().strip().split("\n")
            summary = json.loads(lines[-1])
            if summary.get("record_type") == "match_summary":
                fidelity = summary["fidelity_report"]
                for player_report in fidelity.values():
                    assert player_report["total_violations"] == 0

    def test_result_has_standings(self, tmp_path):
        config = load_config(EXAMPLE_CONFIG)
        config.output_dir = tmp_path / "output"
        engine = TournamentEngine(config)
        result = engine.run()
        assert "mock-caller" in result.standings or "mock-heuristic" in result.standings
