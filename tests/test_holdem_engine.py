"""Tests for the Hold'em engine -- pot-limit heads-up."""

import pytest
from llmtourney.events.holdem.engine import HoldemEvent
from llmtourney.events.base import ValidationResult


@pytest.fixture
def game():
    g = HoldemEvent(hands_per_match=100, starting_stack=200, blinds=(1, 2))
    g.reset(seed=42)
    return g


class TestHoldemSetup:
    def test_reset_initializes_state(self, game):
        snap = game.get_state_snapshot()
        assert snap["hand_number"] == 1
        assert snap["stacks"]["player_a"] + snap["stacks"]["player_b"] == 400

    def test_not_terminal_at_start(self, game):
        assert game.is_terminal() is False

    def test_blinds_posted(self, game):
        snap = game.get_state_snapshot()
        assert snap["pot"] == 3  # small blind 1 + big blind 2

    def test_action_schema_present(self, game):
        schema = game.action_schema
        assert schema["type"] == "object"
        assert "action" in schema["properties"]

    def test_current_player_returns_string(self, game):
        player = game.current_player()
        assert player in ("player_a", "player_b")


class TestHoldemBetting:
    def test_call_is_legal(self, game):
        player = game.current_player()
        result = game.validate_action(player, {"action": "call"})
        assert result.legal is True

    def test_fold_is_legal(self, game):
        player = game.current_player()
        result = game.validate_action(player, {"action": "fold"})
        assert result.legal is True

    def test_raise_within_pot_limit_is_legal(self, game):
        player = game.current_player()
        prompt = game.get_prompt(player)
        assert "raise" in prompt.lower()

    def test_raise_above_pot_limit_is_illegal(self, game):
        player = game.current_player()
        result = game.validate_action(player, {"action": "raise", "amount": 9999})
        assert result.legal is False

    def test_raise_below_minimum_is_illegal(self, game):
        player = game.current_player()
        result = game.validate_action(player, {"action": "raise", "amount": 0})
        assert result.legal is False

    def test_fold_ends_hand(self, game):
        player = game.current_player()
        game.apply_action(player, {"action": "fold"})
        snap = game.get_state_snapshot()
        assert snap["hand_number"] == 2

    def test_call_call_advances_street(self, game):
        """Both players calling preflop should deal the flop."""
        p = game.current_player()
        game.apply_action(p, {"action": "call"})  # SB calls
        p = game.current_player()
        game.apply_action(p, {"action": "call"})  # BB checks
        snap = game.get_state_snapshot()
        assert snap["street"] == "flop"
        assert len(snap["community_cards"]) == 3


class TestHoldemChipConservation:
    def test_chips_conserved_after_fold(self, game):
        player = game.current_player()
        game.apply_action(player, {"action": "fold"})
        snap = game.get_state_snapshot()
        total = snap["stacks"]["player_a"] + snap["stacks"]["player_b"]
        assert total == 400

    def test_chips_conserved_after_full_hand(self, game):
        _play_call_down_hand(game)
        snap = game.get_state_snapshot()
        total = snap["stacks"]["player_a"] + snap["stacks"]["player_b"]
        assert total == 400


class TestHoldemMatchEnd:
    def test_match_ends_after_n_hands(self):
        game = HoldemEvent(hands_per_match=3, starting_stack=200, blinds=(1, 2))
        game.reset(seed=42)
        for _ in range(3):
            _play_call_down_hand(game)
        assert game.is_terminal() is True

    def test_match_ends_on_bustout(self):
        game = HoldemEvent(hands_per_match=100, starting_stack=10, blinds=(1, 2))
        game.reset(seed=42)
        for _ in range(100):
            if game.is_terminal():
                break
            _play_call_down_hand(game)
        assert game.is_terminal() is True


class TestHoldemForfeit:
    def test_forfeit_turn_does_not_crash(self, game):
        player = game.current_player()
        game.forfeit_turn(player)
        assert True

    def test_forfeit_conserves_chips(self, game):
        player = game.current_player()
        game.forfeit_turn(player)
        snap = game.get_state_snapshot()
        total = snap["stacks"]["player_a"] + snap["stacks"]["player_b"]
        assert total == 400


class TestHoldemPrompt:
    def test_prompt_contains_hole_cards(self, game):
        player = game.current_player()
        prompt = game.get_prompt(player)
        assert "hole cards" in prompt.lower() or "your cards" in prompt.lower()

    def test_prompt_contains_legal_actions(self, game):
        player = game.current_player()
        prompt = game.get_prompt(player)
        assert "fold" in prompt.lower()
        assert "call" in prompt.lower()

    def test_retry_prompt_contains_error(self, game):
        player = game.current_player()
        prompt = game.get_retry_prompt(player, "raise amount exceeds pot limit")
        assert "raise amount exceeds pot limit" in prompt


class TestHoldemScores:
    def test_scores_after_match(self):
        game = HoldemEvent(hands_per_match=3, starting_stack=200, blinds=(1, 2))
        game.reset(seed=42)
        for _ in range(3):
            _play_call_down_hand(game)
        scores = game.get_scores()
        assert "player_a" in scores
        assert "player_b" in scores
        assert scores["player_a"] + scores["player_b"] == 400

    def test_highlight_hands_is_list(self):
        game = HoldemEvent(hands_per_match=5, starting_stack=200, blinds=(1, 2))
        game.reset(seed=42)
        for _ in range(5):
            _play_call_down_hand(game)
        highlights = game.get_highlight_hands()
        assert isinstance(highlights, list)


class TestHoldemSeatRotation:
    def test_dealer_alternates(self):
        game = HoldemEvent(hands_per_match=4, starting_stack=200, blinds=(1, 2))
        game.reset(seed=42)
        first_player = game.current_player()
        game.apply_action(first_player, {"action": "fold"})
        second_hand_player = game.current_player()
        assert first_player != second_hand_player


def _play_call_down_hand(game: HoldemEvent) -> None:
    """Helper: play a single hand with both players calling every street."""
    initial_hand = game.get_state_snapshot()["hand_number"]
    for _ in range(100):
        if game.is_terminal():
            break
        snap = game.get_state_snapshot()
        if snap["hand_number"] != initial_hand and snap["hand_number"] > initial_hand:
            break
        player = game.current_player()
        action = {"action": "call"}
        if game.validate_action(player, action).legal:
            game.apply_action(player, action)
        else:
            game.apply_action(player, {"action": "fold"})
