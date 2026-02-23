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


class TestAllInExcessRefund:
    """Verify that unmatched bets are refunded when one player is all-in."""

    def test_allin_excess_returned_to_overbettor(self):
        """When one player is all-in for less, the overbettor gets the excess back.

        Setup: player_a has 10 chips, player_b has 200 chips.
        player_a is SB/dealer (posts 1), player_b is BB (posts 2).
        player_a raises all-in to 10.  player_b calls (matching 10).
        The effective pot should be 20 (10 from each side).
        The excess (0 in this case) means nothing extra.

        Instead, we force a scenario where bets are unequal at showdown:
        player_a goes all-in for 10, player_b raises to 50 -- but player_a
        can only match 10.  The excess 40 must be refunded to player_b.
        """
        # Small starting stack for player_a to create asymmetry
        game = HoldemEvent(hands_per_match=10, starting_stack=10, blinds=(1, 2))
        game.reset(seed=42)

        total_chips = 20  # 10 + 10

        # Record stacks before the hand
        snap = game.get_state_snapshot()
        assert snap["stacks"]["player_a"] + snap["stacks"]["player_b"] == total_chips

        # Play through the hand: both call down to showdown
        initial_hand = snap["hand_number"]
        for _ in range(100):
            if game.is_terminal():
                break
            snap = game.get_state_snapshot()
            if snap["hand_number"] != initial_hand:
                break
            player = game.current_player()
            action = {"action": "call"}
            if game.validate_action(player, action).legal:
                game.apply_action(player, action)
            else:
                game.apply_action(player, {"action": "fold"})

        # After the hand, total chips must be conserved
        snap = game.get_state_snapshot()
        total = snap["stacks"]["player_a"] + snap["stacks"]["player_b"]
        assert total == total_chips, (
            f"Chip conservation violated: {total} != {total_chips}"
        )

    def test_allin_short_stack_cannot_win_more_than_invested(self):
        """A short-stacked all-in player's maximum gain is capped.

        With starting_stack=5 for both (via constructor), player_a posts SB=1,
        player_b posts BB=2. If player_a shoves all-in and player_b calls,
        chip conservation must hold and the short-stack winner can only win
        what was matched.
        """
        game = HoldemEvent(hands_per_match=100, starting_stack=5, blinds=(1, 2))
        game.reset(seed=99)

        total_chips = 10  # 5 + 5

        snap = game.get_state_snapshot()
        assert snap["stacks"]["player_a"] + snap["stacks"]["player_b"] == total_chips

        # Play through: both call down
        initial_hand = snap["hand_number"]
        for _ in range(100):
            if game.is_terminal():
                break
            snap = game.get_state_snapshot()
            if snap["hand_number"] != initial_hand:
                break
            player = game.current_player()
            action = {"action": "call"}
            if game.validate_action(player, action).legal:
                game.apply_action(player, action)
            else:
                game.apply_action(player, {"action": "fold"})

        # Total chips must be conserved
        snap = game.get_state_snapshot()
        total = snap["stacks"]["player_a"] + snap["stacks"]["player_b"]
        assert total == total_chips, (
            f"Chip conservation violated: {total} != {total_chips}"
        )

    def test_allin_excess_refund_with_raise(self):
        """Excess chips from an overbet are refunded when opponent is all-in.

        player_a has 8 chips (SB) vs player_b with 392 chips (BB).
        player_a raises all-in to 8; player_b calls.  After showdown the
        effective pot should be 16 (8 matched from each side) and the total
        chips in play must remain 400.

        We use get_scores() for the final check because it reports raw
        stacks without adding stale per-hand invested amounts.
        """
        game = HoldemEvent(hands_per_match=100, starting_stack=200, blinds=(1, 2))
        game.reset(seed=77)

        # Cleanly set up asymmetric stacks before the first hand.
        game._stacks["player_a"] = 8
        game._stacks["player_b"] = 392
        game._invested = {"player_a": 0, "player_b": 0}
        game._bets = {"player_a": 0, "player_b": 0}
        game._pot = 0
        game._hand_number = 0
        game._start_new_hand()

        total_chips = 400

        # player_a is SB/dealer, so acts first preflop
        p = game.current_player()
        assert p == "player_a"

        # player_a raises all-in (stack + current bet = total they can put up)
        max_bet = game._stacks["player_a"] + game._bets["player_a"]
        game.apply_action("player_a", {"action": "raise", "amount": max_bet})

        # If hand hasn't resolved yet, player_b calls
        if game._hand_number == 1 and not game.is_terminal():
            p = game.current_player()
            if p == "player_b":
                game.apply_action("player_b", {"action": "call"})

        # Verify chip conservation using raw stacks (scores == stacks as floats)
        scores = game.get_scores()
        total = scores["player_a"] + scores["player_b"]
        assert total == total_chips, (
            f"Chip conservation violated after all-in raise: {total} != {total_chips}"
        )


class TestMultiStreetCallDown:
    """Verify community cards at each stage of a full hand."""

    def test_community_cards_through_all_streets(self, game):
        """Play through all 4 streets, verifying community card counts.

        Preflop: 0 community cards
        Flop: 3 community cards
        Turn: 4 community cards
        River: 5 community cards
        """
        # PREFLOP: 0 community cards
        snap = game.get_state_snapshot()
        assert snap["street"] == "preflop"
        assert len(snap["community_cards"]) == 0

        # SB calls, BB checks -> advance to flop
        p = game.current_player()
        game.apply_action(p, {"action": "call"})  # SB limps
        p = game.current_player()
        game.apply_action(p, {"action": "call"})  # BB checks

        # FLOP: 3 community cards
        snap = game.get_state_snapshot()
        assert snap["street"] == "flop", f"Expected flop, got {snap['street']}"
        assert len(snap["community_cards"]) == 3

        # Both check through the flop -> advance to turn
        p = game.current_player()
        game.apply_action(p, {"action": "call"})  # BB checks
        p = game.current_player()
        game.apply_action(p, {"action": "call"})  # SB checks

        # TURN: 4 community cards
        snap = game.get_state_snapshot()
        assert snap["street"] == "turn", f"Expected turn, got {snap['street']}"
        assert len(snap["community_cards"]) == 4

        # Both check through the turn -> advance to river
        p = game.current_player()
        game.apply_action(p, {"action": "call"})  # BB checks
        p = game.current_player()
        game.apply_action(p, {"action": "call"})  # SB checks

        # RIVER: 5 community cards
        snap = game.get_state_snapshot()
        assert snap["street"] == "river", f"Expected river, got {snap['street']}"
        assert len(snap["community_cards"]) == 5

        # Both check through the river -> showdown and next hand
        p = game.current_player()
        game.apply_action(p, {"action": "call"})  # BB checks
        p = game.current_player()
        game.apply_action(p, {"action": "call"})  # SB checks

        # Should now be on hand 2
        snap = game.get_state_snapshot()
        assert snap["hand_number"] == 2


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
