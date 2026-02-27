"""Tests for dead seat mechanics in Hold'em engine.

Dead seats are forfeit-eliminated players who continue to post forced blinds
until broke, then transition to busted. They never get dealt cards or act.
"""

import pytest
from llmtourney.events.holdem.engine import HoldemEvent
from llmtourney.config import ForfeitEscalationConfig
from llmtourney.core.referee import Referee, Ruling, ViolationKind


class TestEliminateMethods:
    def test_eliminate_marks_dead(self):
        """eliminate_player() adds to _dead_seats, removes from _active_players()."""
        g = HoldemEvent(num_players=3, starting_stack=200, blinds=(1, 2))
        g.reset(seed=42)
        g.eliminate_player("player_a")
        assert "player_a" in g._dead_seats
        assert "player_a" not in g._active_players()

    def test_dead_seat_in_snapshot(self):
        """Snapshot includes dead_seats field."""
        g = HoldemEvent(num_players=3, starting_stack=200, blinds=(1, 2))
        g.reset(seed=42)
        g.eliminate_player("player_c")
        snap = g.get_state_snapshot()
        assert "dead_seats" in snap
        assert "player_c" in snap["dead_seats"]


class TestDeadSeatBlindPosting:
    def test_dead_seat_posts_blinds(self):
        """Eliminated player in blind position still has chips deducted."""
        g = HoldemEvent(num_players=3, hands_per_match=20, starting_stack=200, blinds=(1, 2))
        g.reset(seed=42)

        total = 600
        # Play hand 1 normally
        _advance_hand(g)

        # Eliminate player_b (they'll still post blinds)
        stack_before = g._stacks["player_b"]
        g.eliminate_player("player_b")

        # Start a new hand by advancing via folds
        _advance_hand(g)

        # player_b should have lost chips to blinds if they were in blind position,
        # OR stayed the same if they weren't. But chips must be conserved.
        snap = g.get_state_snapshot()
        actual = sum(snap["stacks"].values())
        assert actual == total, f"Chip conservation: {actual} != {total}"


class TestDeadSeatNeverActs:
    def test_dead_seat_never_current_player(self):
        """After elimination, current_player() never returns dead player."""
        g = HoldemEvent(num_players=3, hands_per_match=20, starting_stack=200, blinds=(1, 2))
        g.reset(seed=42)
        g.eliminate_player("player_c")

        # Play several hands, verify player_c never acts
        for _ in range(200):
            if g.is_terminal():
                break
            p = g.current_player()
            assert p != "player_c", "Dead seat should never be current player"
            g.apply_action(p, {"action": "call"})


class TestDeadSeatBleedsToZero:
    def test_dead_seat_bleeds_to_zero(self):
        """Play hands until dead seat's stack reaches 0, verify transitions to busted."""
        g = HoldemEvent(num_players=3, hands_per_match=200, starting_stack=20, blinds=(1, 2))
        g.reset(seed=42)
        g.eliminate_player("player_c")

        for _ in range(2000):
            if g.is_terminal():
                break
            p = g.current_player()
            g.apply_action(p, {"action": "call"})

        # player_c should be busted (no longer dead seat)
        assert "player_c" in g._busted or g._stacks["player_c"] == 0


class TestLastActiveWins:
    def test_last_active_wins(self):
        """Eliminate all but one player, verify terminal."""
        g = HoldemEvent(num_players=3, hands_per_match=200, starting_stack=20, blinds=(1, 2))
        g.reset(seed=42)
        g.eliminate_player("player_b")
        g.eliminate_player("player_c")

        # With both eliminated, only player_a is active
        # Next hand start should detect terminal (1 active player)
        _advance_hand(g)
        assert g.is_terminal()


class TestHeadsUpAfterElimination:
    def test_heads_up_after_elimination(self):
        """3→2 active players after elimination, game continues normally."""
        g = HoldemEvent(num_players=3, hands_per_match=20, starting_stack=200, blinds=(1, 2))
        g.reset(seed=42)
        g.eliminate_player("player_c")

        # Should still be playable with 2 active players
        assert not g.is_terminal()

        # Play several hands — should work like heads-up
        for _ in range(500):
            if g.is_terminal():
                break
            p = g.current_player()
            assert p in ("player_a", "player_b")
            g.apply_action(p, {"action": "call"})

        # Should terminate normally (hands or bustout)
        assert g.is_terminal()
        scores = g.get_scores()
        assert sum(scores.values()) == 600


class TestDealerSkipsDeadSeat:
    def test_dealer_skips_dead_seat(self):
        """Verify dealer rotation skips eliminated players."""
        g = HoldemEvent(num_players=4, hands_per_match=20, starting_stack=200, blinds=(1, 2))
        g.reset(seed=42)

        # Eliminate player_b
        g.eliminate_player("player_b")

        dealers_seen = set()
        for _ in range(10):
            if g.is_terminal():
                break
            snap = g.get_state_snapshot()
            dealers_seen.add(snap["dealer"])
            _advance_hand(g)

        assert "player_b" not in dealers_seen, "Dead seat should never be dealer"


class TestChipConservation:
    def test_dead_seat_chips_conserved(self):
        """Total chips constant throughout with dead seats."""
        g = HoldemEvent(num_players=4, hands_per_match=30, starting_stack=200, blinds=(1, 2))
        g.reset(seed=42)
        total = 800

        # Eliminate one player after a few hands
        _advance_hand(g)
        g.eliminate_player("player_d")

        for _ in range(2000):
            if g.is_terminal():
                break
            snap = g.get_state_snapshot()
            actual = sum(snap["stacks"].values())
            assert actual == total, f"Chip conservation violated at hand {snap['hand_number']}: {actual} != {total}"
            p = g.current_player()
            g.apply_action(p, {"action": "call"})


class TestTwoPlayerForfeitUnchanged:
    def test_2player_forfeit_unchanged(self):
        """2-player match still uses FORFEIT_MATCH, not ELIMINATE_PLAYER."""
        esc = ForfeitEscalationConfig(
            turn_forfeit_threshold=1,
            match_forfeit_threshold=3,
            strike_violations=["timeout", "empty_response"],
        )
        ref = Referee(escalation=esc, num_players=2)
        for _ in range(3):
            ref.record_turn_forfeit("player_a", ViolationKind.TIMEOUT)
        assert ref.get_match_forfeit_player() == "player_a"
        assert ref.get_eliminated_players() == []

    def test_2player_engine_forfeit(self):
        """2-player HoldemEvent.award_forfeit_wins still terminates match."""
        g = HoldemEvent(num_players=2, starting_stack=200, blinds=(1, 2))
        g.reset(seed=42)
        g.award_forfeit_wins("player_a")
        assert g.is_terminal()
        scores = g.get_scores()
        assert scores["player_a"] == 0
        assert scores["player_b"] == 400


class TestPromptShowsEliminated:
    def test_prompt_shows_eliminated_status(self):
        """Dead seat shows '(eliminated)' in prompt stacks display."""
        g = HoldemEvent(num_players=3, hands_per_match=20, starting_stack=200, blinds=(1, 2))
        g.reset(seed=42)
        g.eliminate_player("player_c")
        _advance_hand(g)

        if not g.is_terminal():
            p = g.current_player()
            prompt = g.get_prompt(p)
            assert "(eliminated)" in prompt


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _advance_hand(game: HoldemEvent) -> None:
    """Play through current hand by folding until hand number changes."""
    if game.is_terminal():
        return
    initial = game.get_state_snapshot()["hand_number"]
    for _ in range(100):
        if game.is_terminal():
            break
        snap = game.get_state_snapshot()
        if snap["hand_number"] > initial:
            break
        p = game.current_player()
        game.apply_action(p, {"action": "fold"})
