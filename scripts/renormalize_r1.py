#!/usr/bin/env python3
"""Renormalize S2 Champions R1 scores using hybrid Hold'em scoring.

Hardcoded verified data from R1 — no telemetry parsing needed.
"""

from llmtourney.scoring.hybrid import hybrid_holdem_scores

# Verified R1 elimination order (player, hand_number)
elimination_order = [
    ("deepseek-chat", 29),
    ("haiku-4.5", 40),
    ("gpt-4o-mini", 45),
    ("opus-4.6", 52),
    ("grok-3-mini", 68),
]

# Final chip counts (survivors only have chips)
final_chips = {
    "deepseek-chat": 0,
    "haiku-4.5": 0,
    "gpt-4o-mini": 0,
    "opus-4.6": 0,
    "grok-3-mini": 0,
    "gpt-4o": 328,
    "grok-3": 734,
    "sonnet-4.5": 1338,
}

scores = hybrid_holdem_scores(elimination_order, final_chips, n_players=8)

# Display results sorted by score descending
print("S2 Champions R1 — Hybrid Scores")
print("=" * 60)
print(f"{'Model':<16} {'Placement':>9} {'Floor':>7} {'Chip Bonus':>11} {'Total':>7}")
print("-" * 60)

# Reconstruct floor and chip bonus for display
busted_set = {pid for pid, _ in elimination_order}
survivors = [pid for pid in final_chips if pid not in busted_set and final_chips[pid] > 0]
total_surviving_chips = sum(final_chips[pid] for pid in survivors)

for pid in sorted(final_chips, key=lambda p: scores[p], reverse=True):
    total = scores[pid]
    chip_bonus = (final_chips[pid] / total_surviving_chips * 50) if final_chips[pid] > 0 else 0.0
    floor = total - chip_bonus
    # Determine placement rank
    placement = round(floor * 7 / 50 + 1, 1)
    print(f"{pid:<16} {placement:>9} {floor:>7.1f} {chip_bonus:>11.1f} {total:>7.1f}")
