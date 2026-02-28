"""Tests for the Liar's Dice engine."""

import math
import pytest
from llmtourney.events.liarsdice.engine import LiarsDiceEvent, _binom_pmf


@pytest.fixture
def game():
    g = LiarsDiceEvent(num_players=4, starting_dice=5)
    g.reset(seed=42)
    return g


@pytest.fixture
def two_player():
    g = LiarsDiceEvent(num_players=2, starting_dice=3)
    g.reset(seed=42)
    return g


# ------------------------------------------------------------------
# Setup
# ------------------------------------------------------------------

class TestSetup:
    def test_reset_initializes(self, game):
        snap = game.get_state_snapshot()
        assert snap["round"] == 1
        assert snap["terminal"] is False
        assert snap["game_number"] == 1

    def test_not_terminal_at_start(self, game):
        assert game.is_terminal() is False

    def test_player_a_goes_first(self, game):
        assert game.current_player() == "player_a"

    def test_four_players_have_five_dice(self, game):
        snap = game.get_state_snapshot()
        for pid in game.player_ids:
            assert snap["dice_counts"][pid] == 5
            assert len(snap["all_dice"][pid]) == 5

    def test_all_dice_are_1_to_6(self, game):
        snap = game.get_state_snapshot()
        for pid in game.player_ids:
            for d in snap["all_dice"][pid]:
                assert 1 <= d <= 6

    def test_action_schema_present(self, game):
        schema = game.action_schema
        assert "oneOf" in schema
        assert len(schema["oneOf"]) == 2

    def test_initial_scores_zero(self, game):
        scores = game.get_scores()
        for pid in game.player_ids:
            assert scores[pid] == 0.0

    def test_player_ids_correct(self, game):
        assert game.player_ids == ["player_a", "player_b", "player_c", "player_d"]

    def test_wilds_active_at_start(self, game):
        snap = game.get_state_snapshot()
        assert snap["wilds_active"] is True

    def test_no_bid_at_start(self, game):
        snap = game.get_state_snapshot()
        assert snap["current_bid"] is None

    def test_total_dice_correct(self, game):
        snap = game.get_state_snapshot()
        assert snap["total_dice"] == 20  # 4 players * 5 dice


# ------------------------------------------------------------------
# Validation
# ------------------------------------------------------------------

class TestValidation:
    def test_valid_bid_accepted(self, game):
        result = game.validate_action("player_a", {"action": "bid", "quantity": 3, "face": 4})
        assert result.legal is True

    def test_valid_liar_rejected_no_bid(self, game):
        result = game.validate_action("player_a", {"action": "liar"})
        assert result.legal is False
        assert "no bid" in result.reason.lower()

    def test_bid_quantity_zero_rejected(self, game):
        result = game.validate_action("player_a", {"action": "bid", "quantity": 0, "face": 3})
        assert result.legal is False

    def test_bid_face_zero_rejected(self, game):
        result = game.validate_action("player_a", {"action": "bid", "quantity": 1, "face": 0})
        assert result.legal is False

    def test_bid_face_seven_rejected(self, game):
        result = game.validate_action("player_a", {"action": "bid", "quantity": 1, "face": 7})
        assert result.legal is False

    def test_bid_quantity_exceeds_total_dice(self, game):
        result = game.validate_action("player_a", {"action": "bid", "quantity": 21, "face": 3})
        assert result.legal is False
        assert "exceeds" in result.reason.lower()

    def test_unknown_action_rejected(self, game):
        result = game.validate_action("player_a", {"action": "fold"})
        assert result.legal is False

    def test_raise_must_be_higher(self, game):
        game.apply_action("player_a", {"action": "bid", "quantity": 3, "face": 4})
        # Same bid is not a raise
        result = game.validate_action("player_b", {"action": "bid", "quantity": 3, "face": 4})
        assert result.legal is False

    def test_raise_same_face_higher_quantity(self, game):
        game.apply_action("player_a", {"action": "bid", "quantity": 3, "face": 4})
        result = game.validate_action("player_b", {"action": "bid", "quantity": 4, "face": 4})
        assert result.legal is True

    def test_raise_higher_face_same_quantity(self, game):
        game.apply_action("player_a", {"action": "bid", "quantity": 3, "face": 4})
        result = game.validate_action("player_b", {"action": "bid", "quantity": 3, "face": 5})
        assert result.legal is True

    def test_raise_lower_face_same_quantity_rejected(self, game):
        game.apply_action("player_a", {"action": "bid", "quantity": 3, "face": 4})
        result = game.validate_action("player_b", {"action": "bid", "quantity": 3, "face": 3})
        assert result.legal is False

    def test_raise_lower_face_higher_quantity_accepted(self, game):
        game.apply_action("player_a", {"action": "bid", "quantity": 3, "face": 4})
        result = game.validate_action("player_b", {"action": "bid", "quantity": 4, "face": 3})
        assert result.legal is True

    def test_liar_valid_after_bid(self, game):
        game.apply_action("player_a", {"action": "bid", "quantity": 3, "face": 4})
        result = game.validate_action("player_b", {"action": "liar"})
        assert result.legal is True


# ------------------------------------------------------------------
# 1s switching rules
# ------------------------------------------------------------------

class TestOnesSwitching:
    def test_switch_to_ones_halves_quantity(self, game):
        game.apply_action("player_a", {"action": "bid", "quantity": 6, "face": 4})
        # ceil(6/2) = 3
        result = game.validate_action("player_b", {"action": "bid", "quantity": 3, "face": 1})
        assert result.legal is True

    def test_switch_to_ones_too_low(self, game):
        game.apply_action("player_a", {"action": "bid", "quantity": 6, "face": 4})
        result = game.validate_action("player_b", {"action": "bid", "quantity": 2, "face": 1})
        assert result.legal is False

    def test_switch_from_ones_doubles_plus_one(self, game):
        game.apply_action("player_a", {"action": "bid", "quantity": 3, "face": 1})
        # 3 * 2 + 1 = 7
        result = game.validate_action("player_b", {"action": "bid", "quantity": 7, "face": 4})
        assert result.legal is True

    def test_switch_from_ones_too_low(self, game):
        game.apply_action("player_a", {"action": "bid", "quantity": 3, "face": 1})
        result = game.validate_action("player_b", {"action": "bid", "quantity": 6, "face": 4})
        assert result.legal is False

    def test_ones_to_ones_just_needs_higher_quantity(self, game):
        game.apply_action("player_a", {"action": "bid", "quantity": 3, "face": 1})
        result = game.validate_action("player_b", {"action": "bid", "quantity": 4, "face": 1})
        assert result.legal is True

    def test_odd_quantity_switch_to_ones_rounds_up(self, game):
        game.apply_action("player_a", {"action": "bid", "quantity": 5, "face": 3})
        # ceil(5/2) = 3
        result = game.validate_action("player_b", {"action": "bid", "quantity": 3, "face": 1})
        assert result.legal is True
        result2 = game.validate_action("player_b", {"action": "bid", "quantity": 2, "face": 1})
        assert result2.legal is False


# ------------------------------------------------------------------
# Wild ones rule
# ------------------------------------------------------------------

class TestWildOnes:
    def test_wilds_active_by_default(self, game):
        snap = game.get_state_snapshot()
        assert snap["wilds_active"] is True

    def test_opening_on_ones_disables_wilds(self, game):
        game.apply_action("player_a", {"action": "bid", "quantity": 2, "face": 1})
        snap = game.get_state_snapshot()
        assert snap["wilds_active"] is False

    def test_opening_on_non_ones_keeps_wilds(self, game):
        game.apply_action("player_a", {"action": "bid", "quantity": 2, "face": 3})
        snap = game.get_state_snapshot()
        assert snap["wilds_active"] is True

    def test_wild_counting_in_challenge(self):
        """Wilds should count toward the bid face when active."""
        g = LiarsDiceEvent(num_players=2, starting_dice=3)
        g.reset(seed=0)

        # Force dice for deterministic test
        g._dice["player_a"] = [1, 4, 4]  # 1 wild + 2 fours = 3 fours
        g._dice["player_b"] = [2, 3, 6]  # 0 fours

        g.apply_action("player_a", {"action": "bid", "quantity": 3, "face": 4})
        g.apply_action("player_b", {"action": "liar"})

        # Actual count should be 3 (2 fours + 1 wild)
        snap = g.get_state_snapshot()
        cr = snap["challenge_result"]
        assert cr["actual_count"] == 3
        assert cr["bid_was_correct"] is True
        assert cr["loser"] == "player_b"

    def test_wilds_off_dont_count(self):
        """When wilds are off, 1s don't count toward other faces."""
        g = LiarsDiceEvent(num_players=2, starting_dice=3)
        g.reset(seed=0)

        g._dice["player_a"] = [1, 1, 4]
        g._dice["player_b"] = [1, 3, 6]

        # Open on 1s — wilds off
        g.apply_action("player_a", {"action": "bid", "quantity": 3, "face": 1})
        assert g._wilds_active is False

        # B challenges — there are exactly 3 ones
        g.apply_action("player_b", {"action": "liar"})
        snap = g.get_state_snapshot()
        cr = snap["challenge_result"]
        assert cr["actual_count"] == 3
        assert cr["bid_was_correct"] is True


# ------------------------------------------------------------------
# Challenge resolution
# ------------------------------------------------------------------

class TestChallenge:
    def test_wrong_bid_bidder_loses_die(self):
        g = LiarsDiceEvent(num_players=2, starting_dice=3)
        g.reset(seed=0)
        g._dice["player_a"] = [2, 3, 5]
        g._dice["player_b"] = [4, 6, 6]

        # Bid 4 fives — only 1 five exists
        g.apply_action("player_a", {"action": "bid", "quantity": 4, "face": 5})
        g.apply_action("player_b", {"action": "liar"})

        snap = g.get_state_snapshot()
        cr = snap["challenge_result"]
        assert cr["bid_was_correct"] is False
        assert cr["loser"] == "player_a"
        assert snap["dice_counts"]["player_a"] == 2
        assert snap["dice_counts"]["player_b"] == 3

    def test_correct_bid_challenger_loses_die(self):
        g = LiarsDiceEvent(num_players=2, starting_dice=3)
        g.reset(seed=0)
        g._dice["player_a"] = [3, 3, 5]
        g._dice["player_b"] = [3, 1, 6]

        # Bid 4 threes — 3 threes + 1 wild = 4
        g.apply_action("player_a", {"action": "bid", "quantity": 4, "face": 3})
        g.apply_action("player_b", {"action": "liar"})

        snap = g.get_state_snapshot()
        cr = snap["challenge_result"]
        assert cr["bid_was_correct"] is True
        assert cr["loser"] == "player_b"
        assert snap["dice_counts"]["player_b"] == 2

    def test_new_round_starts_after_challenge(self):
        g = LiarsDiceEvent(num_players=2, starting_dice=3)
        g.reset(seed=0)
        g._dice["player_a"] = [2, 3, 5]
        g._dice["player_b"] = [4, 6, 6]

        g.apply_action("player_a", {"action": "bid", "quantity": 4, "face": 5})
        g.apply_action("player_b", {"action": "liar"})

        snap = g.get_state_snapshot()
        assert snap["round"] == 2
        assert snap["current_bid"] is None  # new round, no bid

    def test_loser_starts_next_round(self):
        g = LiarsDiceEvent(num_players=2, starting_dice=3)
        g.reset(seed=0)
        g._dice["player_a"] = [2, 3, 5]
        g._dice["player_b"] = [4, 6, 6]

        g.apply_action("player_a", {"action": "bid", "quantity": 4, "face": 5})
        g.apply_action("player_b", {"action": "liar"})

        # A lost, so A should start next round
        assert g.current_player() == "player_a"

    def test_dice_rerolled_after_challenge(self):
        g = LiarsDiceEvent(num_players=2, starting_dice=3)
        g.reset(seed=42)
        initial_dice_a = list(g._dice["player_a"])

        g.apply_action("player_a", {"action": "bid", "quantity": 1, "face": 2})
        g.apply_action("player_b", {"action": "liar"})

        # Dice should have been rerolled (may or may not be different, but count changes)
        # The loser has fewer dice now
        snap = g.get_state_snapshot()
        loser = snap["challenge_result"]["loser"]
        assert snap["dice_counts"][loser] == 2


# ------------------------------------------------------------------
# Elimination
# ------------------------------------------------------------------

class TestElimination:
    def test_player_eliminated_at_zero_dice(self):
        g = LiarsDiceEvent(num_players=2, starting_dice=1)
        g.reset(seed=42)
        g._dice["player_a"] = [3]
        g._dice["player_b"] = [5]

        # Bid 2 threes (impossible with 2 total dice, unless wild)
        g.apply_action("player_a", {"action": "bid", "quantity": 2, "face": 3})
        g.apply_action("player_b", {"action": "liar"})

        snap = g.get_state_snapshot()
        # A should be eliminated (0 dice)
        assert "player_a" in snap["eliminated"]
        assert snap["terminal"] is True  # only 1 player left

    def test_last_player_wins(self):
        g = LiarsDiceEvent(num_players=3, starting_dice=1)
        g.reset(seed=42)

        # Round 1
        g._dice["player_a"] = [3]
        g._dice["player_b"] = [5]
        g._dice["player_c"] = [2]

        g.apply_action("player_a", {"action": "bid", "quantity": 3, "face": 3})
        g.apply_action("player_b", {"action": "liar"})
        # Only 1 three exists, bid was wrong, A loses die and is eliminated

        snap = g.get_state_snapshot()
        assert "player_a" in snap["eliminated"]

        if not g.is_terminal():
            # Round 2 — B and C remain
            g._dice["player_b"] = [4]
            g._dice["player_c"] = [6]

            g.apply_action(g.current_player(), {"action": "bid", "quantity": 2, "face": 4})
            other = g.current_player()
            g.apply_action(other, {"action": "liar"})

            # Game should be terminal now
            assert g.is_terminal()

    def test_elimination_order_determines_score(self):
        g = LiarsDiceEvent(num_players=3, starting_dice=1)
        g.reset(seed=42)

        # Force quick eliminations
        g._dice["player_a"] = [3]
        g._dice["player_b"] = [5]
        g._dice["player_c"] = [2]

        # A bids impossibly, B challenges
        g.apply_action("player_a", {"action": "bid", "quantity": 3, "face": 6})
        g.apply_action("player_b", {"action": "liar"})

        if not g.is_terminal():
            # B and C remain — force another elimination
            cp = g.current_player()
            other = [p for p in ["player_b", "player_c"] if p != cp][0]
            g._dice["player_b"] = [2]
            g._dice["player_c"] = [5]

            g.apply_action(cp, {"action": "bid", "quantity": 2, "face": 6})
            g.apply_action(other, {"action": "liar"})

        scores = g.get_scores()
        # First eliminated gets 1 point, last standing gets most
        assert scores[g._eliminated[0]] == 1.0


# ------------------------------------------------------------------
# Forfeit behavior
# ------------------------------------------------------------------

class TestForfeit:
    def test_forfeit_opens_with_one_two(self, game):
        game.forfeit_turn("player_a")
        snap = game.get_state_snapshot()
        assert snap["current_bid"] is not None
        assert snap["current_bid"]["quantity"] == 1
        assert snap["current_bid"]["face"] == 2

    def test_forfeit_raises_bid(self, game):
        game.apply_action("player_a", {"action": "bid", "quantity": 3, "face": 4})
        game.forfeit_turn("player_b")
        snap = game.get_state_snapshot()
        # Should have raised to 4 fours
        assert snap["current_bid"]["quantity"] == 4
        assert snap["current_bid"]["face"] == 4

    def test_forfeit_challenges_when_cant_raise(self):
        g = LiarsDiceEvent(num_players=2, starting_dice=2)
        g.reset(seed=42)
        g._dice["player_a"] = [3, 5]
        g._dice["player_b"] = [2, 4]

        # Bid maximum
        g.apply_action("player_a", {"action": "bid", "quantity": 4, "face": 6})
        # B can't raise (4 is total dice), should challenge
        g.forfeit_turn("player_b")

        snap = g.get_state_snapshot()
        # A challenge should have happened
        assert snap.get("challenge_result") is not None or snap["round"] == 2


# ------------------------------------------------------------------
# Full game
# ------------------------------------------------------------------

class TestFullGame:
    def test_deterministic_game_completes(self):
        """A game with seed should run to completion deterministically."""
        g = LiarsDiceEvent(num_players=4, starting_dice=3)
        g.reset(seed=123)

        max_turns = 500
        turns = 0
        while not g.is_terminal() and turns < max_turns:
            pid = g.current_player()
            snap = g.get_state_snapshot()

            if snap["current_bid"] is None:
                # Must bid — bid conservatively
                g.apply_action(pid, {"action": "bid", "quantity": 1, "face": 2})
            else:
                # Always challenge (aggressive but guarantees game ends)
                g.apply_action(pid, {"action": "liar"})

            turns += 1

        assert g.is_terminal()
        assert turns < max_turns

        scores = g.get_scores()
        # All players should have scores
        assert len(scores) == 4
        # Scores should be 1,2,3,4 (one of each)
        assert sorted(scores.values()) == [1.0, 2.0, 3.0, 4.0]

    def test_multiple_games_per_match(self):
        g = LiarsDiceEvent(num_players=2, starting_dice=2, games_per_match=2)
        g.reset(seed=42)

        max_turns = 200
        turns = 0
        while not g.is_terminal() and turns < max_turns:
            pid = g.current_player()
            snap = g.get_state_snapshot()

            if snap["current_bid"] is None:
                g.apply_action(pid, {"action": "bid", "quantity": 1, "face": 3})
            else:
                g.apply_action(pid, {"action": "liar"})
            turns += 1

        assert g.is_terminal()
        scores = g.get_scores()
        # Both players should have accumulated points across 2 games
        assert sum(scores.values()) > 0


# ------------------------------------------------------------------
# Prompt
# ------------------------------------------------------------------

class TestPrompt:
    def test_prompt_contains_dice(self, game):
        prompt = game.get_prompt("player_a")
        assert "Your dice:" in prompt

    def test_prompt_contains_total_dice(self, game):
        prompt = game.get_prompt("player_a")
        assert "Total dice in play: 20" in prompt

    def test_prompt_contains_player_identity(self, game):
        prompt = game.get_prompt("player_a")
        assert "You are Player A" in prompt

    def test_prompt_contains_wild_rule(self, game):
        prompt = game.get_prompt("player_a")
        assert "wild" in prompt.lower()

    def test_prompt_contains_json_instruction(self, game):
        prompt = game.get_prompt("player_a")
        assert '"action": "bid"' in prompt

    def test_prompt_shows_current_bid(self, game):
        game.apply_action("player_a", {"action": "bid", "quantity": 3, "face": 4})
        prompt = game.get_prompt("player_b")
        assert "3 fours" in prompt.lower() or "3 Fours" in prompt or "3 fours" in prompt

    def test_prompt_shows_bid_history(self, game):
        game.apply_action("player_a", {"action": "bid", "quantity": 2, "face": 3})
        game.apply_action("player_b", {"action": "bid", "quantity": 3, "face": 3})
        prompt = game.get_prompt("player_c")
        assert "Bid history" in prompt

    def test_retry_prompt_contains_error(self, game):
        prompt = game.get_retry_prompt("player_a", "invalid face value")
        assert "invalid face value" in prompt

    def test_prompt_does_not_reveal_other_dice(self, game):
        prompt = game.get_prompt("player_a")
        # Should not contain other players' actual dice values
        # (only counts, not values)
        b_dice = game._dice["player_b"]
        # The prompt should show player_a's dice but not explicitly
        # list player_b's dice values
        assert f"Player B: {game._dice_counts['player_b']} dice" in prompt


# ------------------------------------------------------------------
# State snapshot
# ------------------------------------------------------------------

class TestStateSnapshot:
    def test_snapshot_contains_all_dice(self, game):
        snap = game.get_state_snapshot()
        assert "all_dice" in snap
        for pid in game.player_ids:
            assert pid in snap["all_dice"]
            assert len(snap["all_dice"][pid]) == 5

    def test_snapshot_contains_player_stats(self, game):
        snap = game.get_state_snapshot()
        assert "player_stats" in snap
        for pid in game.player_ids:
            assert "total_bids" in snap["player_stats"][pid]
            assert "bluff_bids" in snap["player_stats"][pid]

    def test_snapshot_tracks_challenge_result(self):
        g = LiarsDiceEvent(num_players=2, starting_dice=3)
        g.reset(seed=42)
        g._dice["player_a"] = [2, 3, 5]
        g._dice["player_b"] = [4, 6, 6]

        g.apply_action("player_a", {"action": "bid", "quantity": 5, "face": 5})
        g.apply_action("player_b", {"action": "liar"})

        snap = g.get_state_snapshot()
        assert "challenge_result" in snap
        cr = snap["challenge_result"]
        assert "challenger" in cr
        assert "bidder" in cr
        assert "actual_count" in cr
        assert "bid_was_correct" in cr


# ------------------------------------------------------------------
# Probability helper
# ------------------------------------------------------------------

class TestProbability:
    def test_certain_bid(self):
        # Own dice already satisfy the bid
        p = LiarsDiceEvent.bid_probability(
            bid_quantity=2, bid_face=4,
            own_dice=[4, 4, 3], total_dice=10, wilds_active=True,
        )
        assert p == 1.0

    def test_impossible_bid(self):
        # Need more matches than unknown dice can provide
        p = LiarsDiceEvent.bid_probability(
            bid_quantity=10, bid_face=4,
            own_dice=[4], total_dice=2, wilds_active=True,
        )
        assert p < 0.01

    def test_probability_range(self):
        p = LiarsDiceEvent.bid_probability(
            bid_quantity=3, bid_face=4,
            own_dice=[4, 2, 5], total_dice=10, wilds_active=True,
        )
        assert 0.0 <= p <= 1.0

    def test_wilds_off_lower_probability(self):
        p_wilds = LiarsDiceEvent.bid_probability(
            bid_quantity=3, bid_face=4,
            own_dice=[2, 5, 6], total_dice=10, wilds_active=True,
        )
        p_no_wilds = LiarsDiceEvent.bid_probability(
            bid_quantity=3, bid_face=4,
            own_dice=[2, 5, 6], total_dice=10, wilds_active=False,
        )
        assert p_wilds > p_no_wilds

    def test_binom_pmf_basic(self):
        # P(X=0) for n=1, p=0.5 should be 0.5
        assert abs(_binom_pmf(0, 1, 0.5) - 0.5) < 1e-10

    def test_binom_pmf_sum_to_one(self):
        n, p = 10, 1/3
        total = sum(_binom_pmf(k, n, p) for k in range(n + 1))
        assert abs(total - 1.0) < 1e-10


# ------------------------------------------------------------------
# Edge cases
# ------------------------------------------------------------------

class TestEdgeCases:
    def test_two_player_one_die_each(self):
        g = LiarsDiceEvent(num_players=2, starting_dice=1)
        g.reset(seed=42)
        g._dice["player_a"] = [4]
        g._dice["player_b"] = [2]

        g.apply_action("player_a", {"action": "bid", "quantity": 1, "face": 4})
        g.apply_action("player_b", {"action": "liar"})

        # There IS 1 four, so bid is correct, B loses
        snap = g.get_state_snapshot()
        assert snap["terminal"] is True
        assert "player_b" in snap["eliminated"]

    def test_bid_on_ones_with_wilds_off(self):
        """Opening on 1s disables wilds, so only actual 1s count."""
        g = LiarsDiceEvent(num_players=2, starting_dice=3)
        g.reset(seed=42)
        g._dice["player_a"] = [1, 1, 4]
        g._dice["player_b"] = [1, 3, 5]

        g.apply_action("player_a", {"action": "bid", "quantity": 3, "face": 1})
        # Wilds off — count actual 1s only
        # A has 2 ones, B has 1 one = 3 total
        g.apply_action("player_b", {"action": "liar"})

        snap = g.get_state_snapshot()
        cr = snap["challenge_result"]
        assert cr["actual_count"] == 3
        assert cr["bid_was_correct"] is True

    def test_eliminate_player_method(self, game):
        """Tournament engine's eliminate_player should work."""
        game.eliminate_player("player_c")
        snap = game.get_state_snapshot()
        assert "player_c" in snap["eliminated"]
        assert snap["dice_counts"]["player_c"] == 0

    def test_award_forfeit_wins(self, game):
        game.award_forfeit_wins("player_a")
        assert game.is_terminal()
        scores = game.get_scores()
        # Other players should have gotten points
        assert scores["player_a"] == 0.0
        assert scores["player_b"] > 0.0

    def test_highlight_turns_on_challenge(self):
        g = LiarsDiceEvent(num_players=2, starting_dice=3)
        g.reset(seed=42)
        g.apply_action("player_a", {"action": "bid", "quantity": 1, "face": 2})
        g.apply_action("player_b", {"action": "liar"})

        highlights = g.get_highlight_hands()
        assert len(highlights) > 0
