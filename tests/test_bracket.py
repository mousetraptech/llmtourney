"""Tests for bracket tournament mode."""

import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from llmtourney.bracket import (
    BracketRunner,
    _bracket_pairings,
    _round_label,
    determine_winner,
    BracketMatch,
)
from llmtourney.config import (
    TournamentConfig,
    ModelConfig,
    EventConfig,
    ComputeCaps,
)
from llmtourney.tournament import MatchResult


# ── Seeding tests ────────────────────────────────────────────────


class TestBracketPairings:
    def test_2_models(self):
        assert _bracket_pairings(2) == [(1, 2)]

    def test_4_models(self):
        pairings = _bracket_pairings(4)
        assert len(pairings) == 2
        # Seeds 1 and 2 should be in opposite halves
        seeds_match_1 = set(pairings[0])
        seeds_match_2 = set(pairings[1])
        assert 1 in seeds_match_1 and 4 in seeds_match_1
        assert 2 in seeds_match_2 or 3 in seeds_match_2

    def test_8_models(self):
        pairings = _bracket_pairings(8)
        assert len(pairings) == 4
        # 1v8 should be first match
        assert pairings[0] == (1, 8)
        # 2v7 should be in the opposite half (last two matches)
        all_seeds = set()
        for a, b in pairings:
            all_seeds.add(a)
            all_seeds.add(b)
        assert all_seeds == {1, 2, 3, 4, 5, 6, 7, 8}

    def test_16_models(self):
        pairings = _bracket_pairings(16)
        assert len(pairings) == 8
        # All seeds 1-16 present
        all_seeds = set()
        for a, b in pairings:
            all_seeds.add(a)
            all_seeds.add(b)
        assert all_seeds == set(range(1, 17))
        # 1v16 first
        assert pairings[0] == (1, 16)

    def test_favorites_meet_in_final(self):
        """If favorites always win, seeds 1 and 2 should meet in the final."""
        pairings = _bracket_pairings(8)
        # Simulate: higher seed (lower number) always wins
        # Round 1: 4 matches → 4 winners
        round1_winners = [min(a, b) for a, b in pairings]
        # Round 2: pair adjacent winners
        round2_winners = []
        for i in range(0, len(round1_winners), 2):
            round2_winners.append(min(round1_winners[i], round1_winners[i + 1]))
        # Final: should be seeds 1 vs 2
        assert set(round2_winners) == {1, 2}


# ── Round label tests ────────────────────────────────────────────


class TestRoundLabels:
    def test_final(self):
        assert _round_label(1, 3, 3) == "FINAL"

    def test_semifinals(self):
        assert _round_label(2, 2, 3) == "SEMIFINALS"

    def test_quarterfinals(self):
        assert _round_label(3, 1, 3) == "QUARTERFINALS"

    def test_early_round(self):
        # 16-model bracket, round 1 of 4
        label = _round_label(4, 1, 4)
        assert label == "ROUND 1"


# ── Winner determination ─────────────────────────────────────────


class TestDetermineWinner:
    def _make_result(self, score_a, score_b, viol_a=0, viol_b=0) -> MatchResult:
        return MatchResult(
            match_id="test-match",
            event="checkers",
            scores={"player_a": score_a, "player_b": score_b},
            fidelity={
                "player_a": {"total_violations": viol_a},
                "player_b": {"total_violations": viol_b},
            },
            player_models={"player_a": "model-a", "player_b": "model-b"},
        )

    def test_higher_score_wins(self):
        result = self._make_result(3, 1)
        winner, seed = determine_winner(result, 1, 4)
        assert winner == "model-a"
        assert seed == 1

    def test_lower_score_loses(self):
        result = self._make_result(1, 3)
        winner, seed = determine_winner(result, 1, 4)
        assert winner == "model-b"
        assert seed == 4

    def test_tiebreak_violations(self):
        result = self._make_result(2, 2, viol_a=3, viol_b=1)
        winner, seed = determine_winner(result, 1, 4)
        assert winner == "model-b"  # fewer violations

    def test_tiebreak_seed(self):
        result = self._make_result(2, 2, viol_a=0, viol_b=0)
        winner, seed = determine_winner(result, 1, 4)
        assert winner == "model-a"  # higher seed (lower number)
        assert seed == 1


# ── Validation tests ─────────────────────────────────────────────


def _make_config(num_models: int, num_events: int = 1, fmt: str = "bracket"):
    models = {}
    for i in range(num_models):
        name = f"mock-{i}"
        models[name] = ModelConfig(
            name=name, provider="mock", strategy="always_call"
        )
    events = {}
    for i in range(num_events):
        events[f"event-{i}"] = EventConfig(name=f"event-{i}", weight=1)
    return TournamentConfig(
        name="test-bracket",
        seed=42,
        version="0.1.0",
        format=fmt,
        models=models,
        events=events,
    )


class TestBracketValidation:
    def test_rejects_non_power_of_2(self):
        config = _make_config(3)
        with pytest.raises(ValueError, match="power-of-2"):
            BracketRunner(config)

    def test_rejects_single_model(self):
        config = _make_config(1)
        with pytest.raises(ValueError, match="power-of-2"):
            BracketRunner(config)

    def test_accepts_multiple_events(self):
        config = _make_config(4, num_events=2)
        runner = BracketRunner(config)
        assert runner.multi_event is True
        assert len(runner.event_names) == 2

    def test_accepts_power_of_2(self):
        for n in (2, 4, 8, 16):
            config = _make_config(n)
            runner = BracketRunner(config)
            assert runner.num_models == n
            assert runner.num_rounds == n.bit_length() - 1


# ── Config format field ──────────────────────────────────────────


class TestConfigFormat:
    def test_default_format(self):
        config = TournamentConfig(name="test", seed=1, version="0.1.0")
        assert config.format == "round_robin"

    def test_bracket_format(self):
        config = TournamentConfig(
            name="test", seed=1, version="0.1.0", format="bracket"
        )
        assert config.format == "bracket"


# ── Mock bracket run ─────────────────────────────────────────────


class TestBracketRun:
    @patch.object(BracketRunner, "_write_manifest")
    def test_4_model_bracket(self, mock_write):
        """Run a 4-model bracket with mocked _run_match."""
        config = _make_config(4)

        # Mock _run_match to return predictable results
        # Higher seed (lower number) always wins
        def fake_run_match(event_name, event_cfg, model_a, model_b, match_id=None):
            # Extract seed number from model name
            seed_a = int(model_a.split("-")[1])
            seed_b = int(model_b.split("-")[1])
            winner_is_a = seed_a < seed_b
            return MatchResult(
                match_id=match_id or f"test-{model_a}-vs-{model_b}",
                event=event_name,
                scores={
                    "player_a": 3.0 if winner_is_a else 1.0,
                    "player_b": 1.0 if winner_is_a else 3.0,
                },
                fidelity={
                    "player_a": {"total_violations": 0},
                    "player_b": {"total_violations": 0},
                },
                player_models={"player_a": model_a, "player_b": model_b},
            )

        runner = BracketRunner(config)
        runner.engine._run_match = fake_run_match

        manifest = runner.run()

        assert manifest["num_models"] == 4
        assert manifest["num_rounds"] == 2
        assert len(manifest["rounds"]) == 2
        assert manifest["champion"] == "mock-0"  # seed 1 always wins
        assert manifest["status"] == "complete"

        # Round 1 should have 2 matches
        assert len(manifest["rounds"][0]["matches"]) == 2
        # Final should have 1 match
        assert len(manifest["rounds"][1]["matches"]) == 1
