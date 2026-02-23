"""Poker hand evaluator — stdlib only, no external dependencies.

Evaluates 5-card poker hands and selects the best 5 from 7 cards.
Used by the Hold'em engine at showdown to determine the winner.
"""

from __future__ import annotations

import itertools
from collections import Counter
from dataclasses import dataclass
from enum import IntEnum

__all__ = ["Card", "HandRank", "evaluate_hand", "best_five"]

RANKS = "23456789TJQKA"
RANK_VALUE: dict[str, int] = {r: i for i, r in enumerate(RANKS)}


@dataclass(frozen=True)
class Card:
    """A playing card with rank and suit."""

    rank: str
    suit: str

    def __repr__(self) -> str:
        return f"{self.rank}{self.suit}"


class HandRank(IntEnum):
    """Hand categories ordered from weakest to strongest."""

    HIGH_CARD = 0
    PAIR = 1
    TWO_PAIR = 2
    THREE_OF_A_KIND = 3
    STRAIGHT = 4
    FLUSH = 5
    FULL_HOUSE = 6
    FOUR_OF_A_KIND = 7
    STRAIGHT_FLUSH = 8


def _rank_values(hand: list[Card]) -> list[int]:
    """Return sorted rank values (descending) for a hand."""
    return sorted((RANK_VALUE[c.rank] for c in hand), reverse=True)


def _is_flush(hand: list[Card]) -> bool:
    """Check if all five cards share the same suit."""
    return len({c.suit for c in hand}) == 1


def _is_straight(values: list[int]) -> tuple[bool, int]:
    """Check if values form a straight.

    Returns (is_straight, high_card_value).
    Handles the wheel (A-2-3-4-5) where ace plays low.
    """
    # values are sorted descending
    unique = sorted(set(values), reverse=True)
    if len(unique) != 5:
        return False, 0

    # Normal straight check: highest - lowest == 4
    if unique[0] - unique[4] == 4:
        return True, unique[0]

    # Wheel: A-5-4-3-2 (values: 12, 3, 2, 1, 0)
    if unique == [12, 3, 2, 1, 0]:
        return True, 3  # 5 is the high card (value 3)

    return False, 0


def _encode_kickers(*kicker_groups: int | list[int]) -> int:
    """Encode kicker values into the lower 20 bits.

    Each kicker gets 4 bits (values 0-12 fit in 4 bits).
    Up to 5 kickers packed from most significant to least significant.
    """
    flat: list[int] = []
    for item in kicker_groups:
        if isinstance(item, list):
            flat.extend(item)
        else:
            flat.append(item)

    result = 0
    for i, v in enumerate(flat[:5]):
        result |= v << (4 * (4 - i))
    return result


def evaluate_hand(hand: list[Card]) -> int:
    """Score a 5-card poker hand as an integer.

    Higher scores beat lower scores. Hands of the same category
    are distinguished by kickers.

    Score format: hand_category << 20 | kicker_bits
    """
    if len(hand) != 5:
        raise ValueError(f"Expected 5 cards, got {len(hand)}")

    values = _rank_values(hand)
    flush = _is_flush(hand)
    straight, straight_high = _is_straight(values)

    # Count rank occurrences
    rank_counts = Counter(RANK_VALUE[c.rank] for c in hand)
    # Sort by (count desc, value desc) for grouping
    groups = sorted(rank_counts.items(), key=lambda x: (x[1], x[0]), reverse=True)

    counts = [g[1] for g in groups]
    group_values = [g[0] for g in groups]

    # Straight flush (includes royal flush)
    if flush and straight:
        return (HandRank.STRAIGHT_FLUSH << 20) | _encode_kickers(straight_high)

    # Four of a kind
    if counts[0] == 4:
        quad_val = group_values[0]
        kicker = group_values[1]
        return (HandRank.FOUR_OF_A_KIND << 20) | _encode_kickers(quad_val, kicker)

    # Full house
    if counts[0] == 3 and counts[1] == 2:
        trip_val = group_values[0]
        pair_val = group_values[1]
        return (HandRank.FULL_HOUSE << 20) | _encode_kickers(trip_val, pair_val)

    # Flush
    if flush:
        return (HandRank.FLUSH << 20) | _encode_kickers(values)

    # Straight
    if straight:
        return (HandRank.STRAIGHT << 20) | _encode_kickers(straight_high)

    # Three of a kind
    if counts[0] == 3:
        trip_val = group_values[0]
        kickers = sorted([g[0] for g in groups[1:]], reverse=True)
        return (HandRank.THREE_OF_A_KIND << 20) | _encode_kickers(trip_val, kickers)

    # Two pair
    if counts[0] == 2 and counts[1] == 2:
        high_pair = max(group_values[0], group_values[1])
        low_pair = min(group_values[0], group_values[1])
        kicker = group_values[2]
        return (HandRank.TWO_PAIR << 20) | _encode_kickers(high_pair, low_pair, kicker)

    # One pair
    if counts[0] == 2:
        pair_val = group_values[0]
        kickers = sorted([g[0] for g in groups[1:]], reverse=True)
        return (HandRank.PAIR << 20) | _encode_kickers(pair_val, kickers)

    # High card
    return (HandRank.HIGH_CARD << 20) | _encode_kickers(values)


def best_five(cards: list[Card]) -> list[Card]:
    """Select the best 5-card hand from a list of cards (typically 7).

    Tries all C(n, 5) combinations and returns the one with the
    highest evaluate_hand score.
    """
    if len(cards) < 5:
        raise ValueError(f"Need at least 5 cards, got {len(cards)}")

    best_score = -1
    best_combo: tuple[Card, ...] = ()

    for combo in itertools.combinations(cards, 5):
        combo_list = list(combo)
        score = evaluate_hand(combo_list)
        if score > best_score:
            best_score = score
            best_combo = combo

    return list(best_combo)
