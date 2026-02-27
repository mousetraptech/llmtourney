"""Tests for side pot calculation and distribution."""

import pytest
from llmtourney.events.holdem.engine import SidePot, build_side_pots, distribute_pots


class TestBuildSidePots:
    def test_two_players_equal_investment(self):
        """2 players each invest 100 → 1 pot of 200."""
        invested = {"a": 100, "b": 100}
        pots = build_side_pots(invested, folded=set())
        assert len(pots) == 1
        assert pots[0].amount == 200
        assert pots[0].eligible == {"a", "b"}

    def test_three_players_one_short(self):
        """3 players: A=50, B=100, C=100 → main pot 150, side pot 100."""
        invested = {"a": 50, "b": 100, "c": 100}
        pots = build_side_pots(invested, folded=set())
        assert len(pots) == 2
        # Main pot: 50 * 3 = 150 (all three eligible)
        assert pots[0].amount == 150
        assert pots[0].eligible == {"a", "b", "c"}
        # Side pot: (100-50) * 2 = 100 (only B and C)
        assert pots[1].amount == 100
        assert pots[1].eligible == {"b", "c"}

    def test_three_players_all_different(self):
        """3 players: A=30, B=70, C=100 → 3 layered pots."""
        invested = {"a": 30, "b": 70, "c": 100}
        pots = build_side_pots(invested, folded=set())
        assert len(pots) == 3
        # Layer 1: 30 * 3 = 90
        assert pots[0].amount == 90
        assert pots[0].eligible == {"a", "b", "c"}
        # Layer 2: (70-30) * 2 = 80
        assert pots[1].amount == 80
        assert pots[1].eligible == {"b", "c"}
        # Layer 3: (100-70) * 1 = 30
        assert pots[2].amount == 30
        assert pots[2].eligible == {"c"}

    def test_folder_chips_in_pot_but_ineligible(self):
        """Folded player's chips contribute to pot but they can't win."""
        invested = {"a": 50, "b": 100, "c": 100}
        pots = build_side_pots(invested, folded={"a"})
        assert len(pots) == 2
        # Main pot still 150 (A contributed) but A not eligible
        assert pots[0].amount == 150
        assert pots[0].eligible == {"b", "c"}
        # Side pot: B and C only
        assert pots[1].amount == 100
        assert pots[1].eligible == {"b", "c"}

    def test_empty_invested(self):
        pots = build_side_pots({}, folded=set())
        assert pots == []

    def test_all_zero_invested(self):
        pots = build_side_pots({"a": 0, "b": 0}, folded=set())
        assert pots == []

    def test_total_pot_equals_total_invested(self):
        """Total across all pots must equal total invested."""
        invested = {"a": 30, "b": 70, "c": 100, "d": 50}
        pots = build_side_pots(invested, folded=set())
        total_pot = sum(p.amount for p in pots)
        assert total_pot == sum(invested.values())

    def test_four_players_two_short_stacks(self):
        """A=20, B=20, C=80, D=80 → 2 pots."""
        invested = {"a": 20, "b": 20, "c": 80, "d": 80}
        pots = build_side_pots(invested, folded=set())
        assert len(pots) == 2
        assert pots[0].amount == 80   # 20 * 4
        assert pots[0].eligible == {"a", "b", "c", "d"}
        assert pots[1].amount == 120  # 60 * 2
        assert pots[1].eligible == {"c", "d"}


class TestDistributePots:
    def test_single_winner(self):
        pots = [SidePot(amount=200, eligible={"a", "b"})]
        scores = {"a": 100, "b": 50}
        winnings = distribute_pots(pots, scores)
        assert winnings == {"a": 200}

    def test_side_pot_winner_differs_from_main(self):
        """Short stack wins main pot, big stack wins side pot."""
        pots = [
            SidePot(amount=150, eligible={"a", "b", "c"}),
            SidePot(amount=100, eligible={"b", "c"}),
        ]
        # A has best hand but only eligible for main pot
        scores = {"a": 300, "b": 200, "c": 100}
        winnings = distribute_pots(pots, scores)
        assert winnings["a"] == 150  # main pot
        assert winnings["b"] == 100  # side pot
        assert winnings.get("c", 0) == 0

    def test_tie_split(self):
        """Two players tie → split evenly."""
        pots = [SidePot(amount=200, eligible={"a", "b"})]
        scores = {"a": 100, "b": 100}
        winnings = distribute_pots(pots, scores)
        assert winnings["a"] + winnings["b"] == 200
        assert winnings["a"] == 100
        assert winnings["b"] == 100

    def test_tie_split_odd_amount(self):
        """Odd pot split → total distributed, one player gets remainder."""
        pots = [SidePot(amount=101, eligible={"a", "b"})]
        scores = {"a": 100, "b": 100}
        winnings = distribute_pots(pots, scores)
        assert winnings["a"] + winnings["b"] == 101
        # One player gets 51, other gets 50
        assert sorted(winnings.values()) == [50, 51]

    def test_three_way_tie(self):
        pots = [SidePot(amount=300, eligible={"a", "b", "c"})]
        scores = {"a": 100, "b": 100, "c": 100}
        winnings = distribute_pots(pots, scores)
        assert sum(winnings.values()) == 300

    def test_total_distributed_equals_total_pots(self):
        """All chips must be accounted for."""
        pots = [
            SidePot(amount=90, eligible={"a", "b", "c"}),
            SidePot(amount=80, eligible={"b", "c"}),
            SidePot(amount=30, eligible={"c"}),
        ]
        scores = {"a": 50, "b": 200, "c": 100}
        winnings = distribute_pots(pots, scores)
        assert sum(winnings.values()) == 200  # 90 + 80 + 30

    def test_empty_pots(self):
        winnings = distribute_pots([], {"a": 100})
        assert winnings == {}
