"""Tests for poker hand evaluator — stdlib only, no dependencies."""

import pytest
from llmtourney.events.holdem.evaluator import (
    evaluate_hand,
    best_five,
    Card,
    HandRank,
)


def c(s: str) -> Card:
    """Shorthand: c('Ah') -> Card('A', 'h')"""
    return Card(rank=s[:-1], suit=s[-1])


def cards(s: str) -> list[Card]:
    """Shorthand: cards('Ah Kh Qh Jh Th') -> [Card(...), ...]"""
    return [c(x) for x in s.split()]


class TestHandRankings:
    """Verify all 10 hand categories rank correctly against each other."""

    def test_royal_flush_beats_straight_flush(self):
        royal = cards("Ah Kh Qh Jh Th")
        sf = cards("9h 8h 7h 6h 5h")
        assert evaluate_hand(royal) > evaluate_hand(sf)

    def test_straight_flush_beats_quads(self):
        sf = cards("9h 8h 7h 6h 5h")
        quads = cards("As Ah Ad Ac Kh")
        assert evaluate_hand(sf) > evaluate_hand(quads)

    def test_quads_beats_full_house(self):
        quads = cards("As Ah Ad Ac Kh")
        fh = cards("As Ah Ad Ks Kh")
        assert evaluate_hand(quads) > evaluate_hand(fh)

    def test_full_house_beats_flush(self):
        fh = cards("As Ah Ad Ks Kh")
        flush = cards("Ah 9h 7h 5h 3h")
        assert evaluate_hand(fh) > evaluate_hand(flush)

    def test_flush_beats_straight(self):
        flush = cards("Ah 9h 7h 5h 3h")
        straight = cards("9h 8d 7c 6s 5h")
        assert evaluate_hand(flush) > evaluate_hand(straight)

    def test_straight_beats_trips(self):
        straight = cards("9h 8d 7c 6s 5h")
        trips = cards("As Ah Ad Kh Qc")
        assert evaluate_hand(straight) > evaluate_hand(trips)

    def test_trips_beats_two_pair(self):
        trips = cards("As Ah Ad Kh Qc")
        two_pair = cards("As Ah Ks Kh Qc")
        assert evaluate_hand(trips) > evaluate_hand(two_pair)

    def test_two_pair_beats_pair(self):
        two_pair = cards("As Ah Ks Kh Qc")
        pair = cards("As Ah Kh Qc Jd")
        assert evaluate_hand(two_pair) > evaluate_hand(pair)

    def test_pair_beats_high_card(self):
        pair = cards("As Ah Kh Qc Jd")
        high = cards("Ah Kd Qc Js 9h")
        assert evaluate_hand(pair) > evaluate_hand(high)


class TestEdgeCases:
    def test_wheel_straight(self):
        """A-2-3-4-5 is a valid straight (lowest)."""
        wheel = cards("Ah 2d 3c 4s 5h")
        score = evaluate_hand(wheel)
        regular = cards("6h 5d 4c 3s 2h")
        assert evaluate_hand(regular) > score  # 6-high straight > wheel

    def test_ace_high_straight(self):
        ace_high = cards("Ah Kd Qc Js Th")
        king_high = cards("Kh Qd Jc Ts 9h")
        assert evaluate_hand(ace_high) > evaluate_hand(king_high)

    def test_kicker_matters_in_pair(self):
        pair_king_kicker = cards("As Ah Kh Qc Jd")
        pair_queen_kicker = cards("As Ah Qh Jc Td")
        assert evaluate_hand(pair_king_kicker) > evaluate_hand(pair_queen_kicker)

    def test_same_hand_equal(self):
        h1 = cards("As Ah Kh Qc Jd")
        h2 = cards("Ad Ac Kd Qs Jh")
        assert evaluate_hand(h1) == evaluate_hand(h2)

    def test_flush_kicker(self):
        high_flush = cards("Ah Kh Qh Jh 9h")
        low_flush = cards("Ah Kh Qh Jh 8h")
        assert evaluate_hand(high_flush) > evaluate_hand(low_flush)


class TestBestFive:
    def test_picks_best_from_seven(self):
        seven = cards("Ah Kh Qh Jh Th 2c 3d")
        five = best_five(seven)
        assert len(five) == 5
        score = evaluate_hand(five)
        royal = cards("Ah Kh Qh Jh Th")
        assert score == evaluate_hand(royal)

    def test_seven_card_pair(self):
        seven = cards("As Ah 7d 5c 3h 2d 9s")
        five = best_five(seven)
        assert len(five) == 5
        score = evaluate_hand(five)
        assert score > evaluate_hand(cards("Ah 9s 7d 5c 3h"))  # high card
