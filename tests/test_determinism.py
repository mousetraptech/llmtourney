"""Determinism test: same seed + same mocks = identical outcomes."""

import json
from pathlib import Path
from llmtourney.tournament import TournamentEngine
from llmtourney.config import load_config


EXAMPLE_CONFIG = Path(__file__).resolve().parent.parent / "tournament.yaml.example"


class TestDeterminism:
    def test_same_seed_same_result(self, tmp_path):
        """Two runs with the same config produce identical match summaries."""
        results = []
        for i in range(2):
            config = load_config(EXAMPLE_CONFIG)
            config.output_dir = tmp_path / f"run-{i}"
            engine = TournamentEngine(config)
            result = engine.run()
            results.append(result)

        # Compare match scores
        for m1, m2 in zip(results[0].matches, results[1].matches):
            assert m1.scores == m2.scores, (
                f"Scores differ: {m1.scores} vs {m2.scores}"
            )

    def test_different_seed_different_telemetry(self, tmp_path):
        """Two runs with different seeds produce different turn-level data.

        Final scores may coincidentally match (e.g., heuristic always busts caller),
        but the dealt cards and per-turn actions must differ.
        """
        telemetry = []
        for seed in [42, 99]:
            config = load_config(EXAMPLE_CONFIG)
            config.seed = seed
            config.output_dir = tmp_path / f"run-{seed}"
            result = TournamentEngine(config).run()
            # Collect all turn-level state_snapshots
            for jsonl_file in sorted(result.telemetry_dir.glob("*.jsonl")):
                lines = jsonl_file.read_text().strip().split("\n")
                snapshots = []
                for line in lines:
                    d = json.loads(line)
                    if "state_snapshot" in d:
                        snapshots.append(d["state_snapshot"])
                telemetry.append(snapshots)

        # The state snapshots must differ (different cards dealt)
        assert telemetry[0] != telemetry[1], (
            "Different seeds produced identical state snapshots"
        )

    def test_telemetry_turn_by_turn_identical(self, tmp_path):
        """Same seed produces identical turn actions (ignoring timestamps)."""
        runs = []
        for i in range(2):
            config = load_config(EXAMPLE_CONFIG)
            config.output_dir = tmp_path / f"run-{i}"
            result = TournamentEngine(config).run()
            runs.append(result)

        files_0 = sorted(runs[0].telemetry_dir.glob("*.jsonl"))
        files_1 = sorted(runs[1].telemetry_dir.glob("*.jsonl"))
        assert len(files_0) == len(files_1), "Different number of telemetry files"

        for jsonl_0, jsonl_1 in zip(files_0, files_1):
            lines_0 = jsonl_0.read_text().strip().split("\n")
            lines_1 = jsonl_1.read_text().strip().split("\n")
            assert len(lines_0) == len(lines_1), "Different number of telemetry lines"

            for line_0, line_1 in zip(lines_0, lines_1):
                d0 = json.loads(line_0)
                d1 = json.loads(line_1)
                # Timestamps, latency, and match_id (contains UUID) will differ
                for key in ("timestamp", "latency_ms", "match_id"):
                    d0.pop(key, None)
                    d1.pop(key, None)
                assert d0 == d1
