"""Tests for Gin Rummy meld detection algorithm — critical path."""

import pytest

from llmtourney.events.ginrummy.engine import (
    MeldResult,
    _can_lay_off,
    _card_rank_value,
    _deadwood_value,
    _enumerate_all_melds,
    _sort_hand,
    compute_layoffs,
    find_optimal_melds,
)


class TestSetDetection:
    """Sets: 3-4 cards of the same rank."""

    def test_three_of_a_kind(self):
        cards = ["5♣", "5♦", "5♥"]
        melds = _enumerate_all_melds(cards)
        assert len(melds) == 1
        assert set(melds[0]) == {"5♣", "5♦", "5♥"}

    def test_four_of_a_kind(self):
        cards = ["J♣", "J♦", "J♥", "J♠"]
        melds = _enumerate_all_melds(cards)
        # 4 three-of-a-kind combos + 1 four-of-a-kind
        three_card = [m for m in melds if len(m) == 3]
        four_card = [m for m in melds if len(m) == 4]
        assert len(three_card) == 4
        assert len(four_card) == 1
        assert set(four_card[0]) == {"J♣", "J♦", "J♥", "J♠"}

    def test_two_cards_not_a_set(self):
        cards = ["K♣", "K♦"]
        melds = _enumerate_all_melds(cards)
        assert len(melds) == 0


class TestRunDetection:
    """Runs: 3+ consecutive cards of the same suit, ace LOW only."""

    def test_three_card_run(self):
        cards = ["3♠", "4♠", "5♠"]
        melds = _enumerate_all_melds(cards)
        assert len(melds) == 1
        assert melds[0] == ("3♠", "4♠", "5♠")

    def test_five_card_run(self):
        cards = ["6♥", "7♥", "8♥", "9♥", "10♥"]
        melds = _enumerate_all_melds(cards)
        # 3-card: 6-7-8, 7-8-9, 8-9-10 = 3
        # 4-card: 6-7-8-9, 7-8-9-10 = 2
        # 5-card: 6-7-8-9-10 = 1
        assert len(melds) == 6

    def test_ace_low_run_valid(self):
        """A-2-3 is a valid run (ace is low)."""
        cards = ["A♦", "2♦", "3♦"]
        melds = _enumerate_all_melds(cards)
        assert len(melds) == 1
        assert melds[0] == ("A♦", "2♦", "3♦")

    def test_queen_king_ace_invalid(self):
        """Q-K-A is NOT valid — ace does not wrap high."""
        cards = ["Q♣", "K♣", "A♣"]
        melds = _enumerate_all_melds(cards)
        assert len(melds) == 0

    def test_run_must_be_same_suit(self):
        """3♠ 4♦ 5♠ should not form a run."""
        cards = ["3♠", "4♦", "5♠"]
        melds = _enumerate_all_melds(cards)
        assert len(melds) == 0


class TestOptimalMeldAssignment:
    """Backtracking finds minimum deadwood."""

    def test_single_set(self):
        cards = ["5♣", "5♦", "5♥", "K♠", "Q♣"]
        result = find_optimal_melds(cards)
        assert result.deadwood_value == 20  # K=10 + Q=10
        assert len(result.melds) == 1
        assert set(result.melds[0]) == {"5♣", "5♦", "5♥"}

    def test_single_run(self):
        cards = ["3♠", "4♠", "5♠", "J♥", "2♣"]
        result = find_optimal_melds(cards)
        assert result.deadwood_value == 12  # J=10 + 2=2
        assert len(result.melds) == 1

    def test_overlapping_set_and_run(self):
        """Card could be in a set or a run — algorithm picks best assignment."""
        # 5♣ could be in set {5♣,5♦,5♥} or run {3♣,4♣,5♣}
        cards = ["3♣", "4♣", "5♣", "5♦", "5♥", "K♠"]
        result = find_optimal_melds(cards)
        # Best: use both melds (set + run) since 5♣ only appears once
        # Can't have both: 5♣ in set AND run. Pick one.
        # Set uses 5♣,5♦,5♥ → deadwood 3♣(3)+4♣(4)+K♠(10) = 17
        # Run uses 3♣,4♣,5♣ → deadwood 5♦(5)+5♥(5)+K♠(10) = 20
        # Set is better: deadwood 17
        assert result.deadwood_value == 17

    def test_two_non_overlapping_melds(self):
        cards = ["5♣", "5♦", "5♥", "8♠", "9♠", "10♠", "K♣"]
        result = find_optimal_melds(cards)
        assert len(result.melds) == 2
        assert result.deadwood_value == 10  # K=10
        assert result.deadwood == ["K♣"]

    def test_gin_hand(self):
        """All 10 cards in melds = gin (deadwood 0)."""
        cards = [
            "A♣", "2♣", "3♣",      # run
            "5♦", "5♥", "5♠",      # set
            "9♠", "10♠", "J♠", "Q♠",  # run
        ]
        result = find_optimal_melds(cards)
        assert result.deadwood_value == 0
        assert len(result.deadwood) == 0

    def test_no_melds(self):
        """No sets or runs possible."""
        cards = ["A♣", "3♦", "5♥", "7♠", "9♣"]
        result = find_optimal_melds(cards)
        assert len(result.melds) == 0
        assert result.deadwood_value == 1 + 3 + 5 + 7 + 9  # 25

    def test_shorter_run_enables_better_total(self):
        """Sometimes using a shorter run allows a second meld for lower total deadwood."""
        # 5♥ 6♥ 7♥ 8♥ could be one 4-card run
        # But 5♥ 6♥ 7♥ as 3-card run + 8♥ 8♦ 8♣ as set might be better
        cards = ["5♥", "6♥", "7♥", "8♥", "8♦", "8♣", "K♠"]
        result = find_optimal_melds(cards)
        # Option A: 4-run (5-8♥) → deadwood 8♦(8)+8♣(8)+K♠(10)=26
        # Option B: 3-run (5-7♥) + set (8♥,8♦,8♣) → deadwood K♠(10)=10
        assert result.deadwood_value == 10
        assert len(result.melds) == 2

    def test_empty_hand(self):
        result = find_optimal_melds([])
        assert result.deadwood_value == 0
        assert result.melds == []
        assert result.deadwood == []

    def test_four_of_a_kind_optimal(self):
        """Using 4-of-a-kind as one meld vs two 3-of-a-kind."""
        cards = ["7♣", "7♦", "7♥", "7♠", "K♣", "K♦"]
        result = find_optimal_melds(cards)
        # 4-of-a-kind uses all four 7s, deadwood K♣(10)+K♦(10) = 20
        assert result.deadwood_value == 20
        # Should have exactly 1 meld (the 4-of-a-kind)
        assert any(len(m) == 4 for m in result.melds)


class TestLayoffs:
    """Defender laying off deadwood onto knocker's melds."""

    def test_extend_run_high_end(self):
        knocker_melds = [("3♠", "4♠", "5♠")]
        defender_dw = ["6♠"]
        remaining, melds = compute_layoffs(defender_dw, knocker_melds)
        assert remaining == []
        assert "6♠" in melds[0]

    def test_extend_run_low_end(self):
        knocker_melds = [("3♠", "4♠", "5♠")]
        defender_dw = ["2♠"]
        remaining, melds = compute_layoffs(defender_dw, knocker_melds)
        assert remaining == []
        assert "2♠" in melds[0]

    def test_add_to_set(self):
        knocker_melds = [("5♣", "5♦", "5♥")]
        defender_dw = ["5♠"]
        remaining, melds = compute_layoffs(defender_dw, knocker_melds)
        assert remaining == []
        assert len(melds[0]) == 4

    def test_four_card_set_rejection(self):
        """Cannot add to a 4-card set."""
        knocker_melds = [("5♣", "5♦", "5♥", "5♠")]
        # No more 5s exist, but test with a non-5 card
        defender_dw = ["K♣"]
        remaining, melds = compute_layoffs(defender_dw, knocker_melds)
        assert remaining == ["K♣"]

    def test_iterative_layoff_chain(self):
        """Laying off one card extends a run, enabling another layoff."""
        # Run is 3♠ 4♠ 5♠. Defender has 6♠ and 7♠.
        # 6♠ extends to 3-6♠, then 7♠ extends to 3-7♠.
        knocker_melds = [("3♠", "4♠", "5♠")]
        defender_dw = ["7♠", "6♠"]  # 7 comes first but needs 6 laid off first
        remaining, melds = compute_layoffs(defender_dw, knocker_melds)
        assert remaining == []
        assert len(melds[0]) == 5

    def test_no_layoff_possible(self):
        knocker_melds = [("5♣", "5♦", "5♥")]
        defender_dw = ["K♠", "Q♠"]
        remaining, melds = compute_layoffs(defender_dw, knocker_melds)
        assert remaining == ["K♠", "Q♠"]

    def test_wrong_suit_cant_extend_run(self):
        knocker_melds = [("3♠", "4♠", "5♠")]
        defender_dw = ["6♥"]
        remaining, melds = compute_layoffs(defender_dw, knocker_melds)
        assert remaining == ["6♥"]

    def test_multiple_melds_layoff(self):
        """Lay off onto different melds."""
        knocker_melds = [("3♠", "4♠", "5♠"), ("J♣", "J♦", "J♥")]
        defender_dw = ["6♠", "J♠"]
        remaining, melds = compute_layoffs(defender_dw, knocker_melds)
        assert remaining == []


class TestCanLayOff:
    """Unit tests for _can_lay_off helper."""

    def test_extend_set(self):
        assert _can_lay_off("5♠", ("5♣", "5♦", "5♥")) is True

    def test_full_set_reject(self):
        assert _can_lay_off("5♣", ("5♣", "5♦", "5♥", "5♠")) is False

    def test_wrong_rank_set(self):
        assert _can_lay_off("6♠", ("5♣", "5♦", "5♥")) is False

    def test_extend_run_high(self):
        assert _can_lay_off("6♠", ("3♠", "4♠", "5♠")) is True

    def test_extend_run_low(self):
        assert _can_lay_off("2♠", ("3♠", "4♠", "5♠")) is True

    def test_gap_in_run(self):
        assert _can_lay_off("7♠", ("3♠", "4♠", "5♠")) is False

    def test_wrong_suit_run(self):
        assert _can_lay_off("6♥", ("3♠", "4♠", "5♠")) is False

    def test_duplicate_suit_in_set(self):
        """Can't add 5♣ to a set that already has 5♣."""
        assert _can_lay_off("5♣", ("5♣", "5♦", "5♥")) is False
