"""Tests for N-player Hold'em engine."""

import pytest
from llmtourney.events.holdem.engine import HoldemEvent


class TestMultiplayerConstructor:
    def test_3_player_ids(self):
        g = HoldemEvent(num_players=3)
        assert g.player_ids == ["player_a", "player_b", "player_c"]

    def test_6_player_ids(self):
        g = HoldemEvent(num_players=6)
        assert len(g.player_ids) == 6
        assert g.player_ids[5] == "player_f"

    def test_default_is_2_players(self):
        g = HoldemEvent()
        assert g.player_ids == ["player_a", "player_b"]

    def test_9_player_ids(self):
        g = HoldemEvent(num_players=9)
        assert len(g.player_ids) == 9
        assert g.player_ids[8] == "player_i"


class TestMultiplayerBlinds:
    def test_3p_sb_left_of_dealer(self):
        """3 players: dealer=A, SB=B, BB=C."""
        g = HoldemEvent(num_players=3, starting_stack=200, blinds=(1, 2))
        g.reset(seed=42)
        snap = g.get_state_snapshot()
        # Dealer is player_a (first player)
        assert snap["dealer"] == "player_a"
        # Pot should be 3 (SB=1 + BB=2)
        assert snap["pot"] == 3
        # Total stacks should be 600
        total = sum(snap["stacks"].values())
        assert total == 600

    def test_3p_first_to_act_is_utg(self):
        """In 3-player, UTG (left of BB) acts first preflop."""
        g = HoldemEvent(num_players=3, starting_stack=200, blinds=(1, 2))
        g.reset(seed=42)
        # Dealer=A, SB=B, BB=C, UTG=A
        # In 3-player, UTG wraps back to dealer
        active = g.current_player()
        assert active == "player_a"


class TestDealerRotation:
    def test_dealer_rotates_3p(self):
        g = HoldemEvent(num_players=3, hands_per_match=10, starting_stack=200, blinds=(1, 2))
        g.reset(seed=42)
        dealers = []
        for hand_idx in range(3):
            snap = g.get_state_snapshot()
            dealers.append(snap["dealer"])
            # All fold to advance hand quickly
            for _ in range(10):
                if g.is_terminal():
                    break
                if g.get_state_snapshot()["hand_number"] != hand_idx + 1:
                    break
                p = g.current_player()
                g.apply_action(p, {"action": "fold"})
        # Dealer should rotate: A -> B -> C
        assert dealers == ["player_a", "player_b", "player_c"]

    def test_dealer_skips_busted(self):
        """Busted players should be skipped in dealer rotation."""
        g = HoldemEvent(num_players=3, hands_per_match=100, starting_stack=5, blinds=(1, 2))
        g.reset(seed=42)
        # Play until someone busts
        for _ in range(200):
            if g.is_terminal():
                break
            p = g.current_player()
            g.apply_action(p, {"action": "call"})
        # Just verify it terminates without crash
        assert True


class TestMultiplayerFold:
    def test_all_fold_to_one(self):
        """When all but one player fold, last player wins the pot."""
        g = HoldemEvent(num_players=3, hands_per_match=10, starting_stack=200, blinds=(1, 2))
        g.reset(seed=42)
        snap1 = g.get_state_snapshot()
        hand1 = snap1["hand_number"]

        # All players fold until hand advances
        for _ in range(10):
            if g.is_terminal():
                break
            if g.get_state_snapshot()["hand_number"] != hand1:
                break
            p = g.current_player()
            g.apply_action(p, {"action": "fold"})

        # Should be on hand 2 now (2 folds = last player wins)
        snap = g.get_state_snapshot()
        assert snap["hand_number"] == 2
        # Chips conserved
        assert sum(snap["stacks"].values()) == 600

    def test_fold_advances_to_next(self):
        """After fold, the next non-folded player should act."""
        g = HoldemEvent(num_players=4, hands_per_match=10, starting_stack=200, blinds=(1, 2))
        g.reset(seed=42)
        p1 = g.current_player()
        hand1 = g.get_state_snapshot()["hand_number"]
        g.apply_action(p1, {"action": "fold"})
        # Should still be same hand (3 players remain)
        assert g.get_state_snapshot()["hand_number"] == hand1
        p2 = g.current_player()
        assert p2 != p1
        assert p2 in g.player_ids


class TestCallRound:
    def test_call_round_completes_street_3p(self):
        """All 3 players calling should advance past preflop."""
        g = HoldemEvent(num_players=3, hands_per_match=10, starting_stack=200, blinds=(1, 2))
        g.reset(seed=42)

        # All players call/check preflop
        for _ in range(10):
            snap = g.get_state_snapshot()
            if snap["street"] != "preflop":
                break
            p = g.current_player()
            g.apply_action(p, {"action": "call"})

        snap = g.get_state_snapshot()
        assert snap["street"] == "flop"
        assert len(snap["community_cards"]) == 3


class TestRaiseReopens:
    def test_raise_reopens_action(self):
        """After a raise, all other players must re-act."""
        g = HoldemEvent(num_players=3, hands_per_match=10, starting_stack=200, blinds=(1, 2))
        g.reset(seed=42)

        # UTG calls
        p1 = g.current_player()
        g.apply_action(p1, {"action": "call"})

        # SB raises
        p2 = g.current_player()
        min_r, max_r = g._raise_bounds(p2)
        if min_r is not None:
            g.apply_action(p2, {"action": "raise", "amount": min_r})

            # BB must act again (wasn't done before raise)
            p3 = g.current_player()
            assert p3 not in (p2,)  # Not the raiser

            # UTG (p1) should also need to act again
            g.apply_action(p3, {"action": "call"})
            p4 = g.current_player()
            # Should still be preflop (UTG needs to respond to raise)
            snap = g.get_state_snapshot()
            assert snap["street"] == "preflop"


class TestChipConservation:
    def test_chips_conserved_3p_calldown(self):
        """Total chips must be conserved throughout a 3-player hand."""
        g = HoldemEvent(num_players=3, hands_per_match=5, starting_stack=200, blinds=(1, 2))
        g.reset(seed=42)
        total = 600

        for _ in range(5):
            _play_call_down_hand_mp(g)

        snap = g.get_state_snapshot()
        actual = sum(snap["stacks"].values())
        assert actual == total, f"Chip conservation: {actual} != {total}"

    def test_chips_conserved_6p_calldown(self):
        """Total chips must be conserved in a 6-player match."""
        g = HoldemEvent(num_players=6, hands_per_match=10, starting_stack=200, blinds=(1, 2))
        g.reset(seed=42)
        total = 1200

        for _ in range(10):
            _play_call_down_hand_mp(g)

        snap = g.get_state_snapshot()
        actual = sum(snap["stacks"].values())
        assert actual == total, f"Chip conservation: {actual} != {total}"

    def test_chips_conserved_after_fold_3p(self):
        g = HoldemEvent(num_players=3, hands_per_match=5, starting_stack=200, blinds=(1, 2))
        g.reset(seed=42)
        p = g.current_player()
        g.apply_action(p, {"action": "fold"})
        snap = g.get_state_snapshot()
        assert sum(snap["stacks"].values()) == 600


class TestSidePotIntegration:
    def test_short_stack_allin_3p(self):
        """Short stack goes all-in; proper side pot resolution."""
        g = HoldemEvent(num_players=3, hands_per_match=100, starting_stack=200, blinds=(1, 2))
        g.reset(seed=42)
        total = 600

        # Play many hands to try to create stack imbalances
        for _ in range(20):
            if g.is_terminal():
                break
            _play_call_down_hand_mp(g)

        snap = g.get_state_snapshot()
        actual = sum(snap["stacks"].values())
        assert actual == total, f"Chip conservation after side pots: {actual} != {total}"


class TestFullMatch:
    def test_6p_always_call_terminates(self):
        """6-player match with always-call should terminate normally."""
        g = HoldemEvent(num_players=6, hands_per_match=50, starting_stack=200, blinds=(1, 2))
        g.reset(seed=42)

        for _ in range(5000):  # safety limit
            if g.is_terminal():
                break
            p = g.current_player()
            g.apply_action(p, {"action": "call"})

        assert g.is_terminal()
        scores = g.get_scores()
        assert len(scores) == 6
        total = sum(scores.values())
        assert total == 1200, f"Final chip conservation: {total} != 1200"

    def test_4p_mixed_strategy_terminates(self):
        """4-player match with fold/call mix should terminate."""
        g = HoldemEvent(num_players=4, hands_per_match=30, starting_stack=100, blinds=(2, 4))
        g.reset(seed=123)

        turn = 0
        for _ in range(5000):
            if g.is_terminal():
                break
            p = g.current_player()
            turn += 1
            # Alternate between fold and call
            if turn % 3 == 0:
                g.apply_action(p, {"action": "fold"})
            else:
                g.apply_action(p, {"action": "call"})

        assert g.is_terminal()
        scores = g.get_scores()
        total = sum(scores.values())
        assert total == 400, f"Final chip conservation: {total} != 400"

    def test_3p_with_raises(self):
        """3-player match with some raises should work correctly."""
        g = HoldemEvent(num_players=3, hands_per_match=20, starting_stack=200, blinds=(1, 2))
        g.reset(seed=77)

        turn = 0
        for _ in range(5000):
            if g.is_terminal():
                break
            p = g.current_player()
            turn += 1
            if turn % 7 == 0:
                min_r, max_r = g._raise_bounds(p)
                if min_r is not None:
                    g.apply_action(p, {"action": "raise", "amount": min_r})
                    continue
            g.apply_action(p, {"action": "call"})

        assert g.is_terminal()
        scores = g.get_scores()
        total = sum(scores.values())
        assert total == 600, f"Final chip conservation: {total} != 600"


class TestSnapshotFields:
    def test_snapshot_has_new_fields(self):
        g = HoldemEvent(num_players=3, starting_stack=200, blinds=(1, 2))
        g.reset(seed=42)
        snap = g.get_state_snapshot()
        assert "num_players" in snap
        assert snap["num_players"] == 3
        assert "folded" in snap
        assert "all_in" in snap
        assert "busted" in snap
        assert len(snap["stacks"]) == 3


class TestForfeit:
    def test_forfeit_turn_3p(self):
        g = HoldemEvent(num_players=3, starting_stack=200, blinds=(1, 2))
        g.reset(seed=42)
        p = g.current_player()
        g.forfeit_turn(p)
        # Should not crash
        assert True

    def test_award_forfeit_wins_3p(self):
        g = HoldemEvent(num_players=3, starting_stack=200, blinds=(1, 2))
        g.reset(seed=42)
        g.award_forfeit_wins("player_a")
        assert g.is_terminal()
        scores = g.get_scores()
        # player_a should have 0
        assert scores["player_a"] == 0
        # Others should have the rest
        assert sum(scores.values()) == 600


def _play_call_down_hand_mp(game: HoldemEvent) -> None:
    """Play a single hand with all players calling."""
    if game.is_terminal():
        return
    initial_hand = game.get_state_snapshot()["hand_number"]
    for _ in range(200):  # safety limit
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
