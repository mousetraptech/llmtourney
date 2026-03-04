"""Hybrid scoring: 50pts placement floor + 50pts score proportion."""

from collections import defaultdict


def hybrid_holdem_scores(
    elimination_order: list[tuple[str, int]],
    final_chips: dict[str, float],
    n_players: int,
) -> dict[str, float]:
    """Compute hybrid scores for elimination-format Hold'em.

    Args:
        elimination_order: List of (player_id, hand_number) in order of
            elimination. Players eliminated on the same hand share averaged
            placements.
        final_chips: Final chip counts for all players (busted players have 0).
        n_players: Total number of players in the match.

    Returns:
        dict mapping player_id to a score in [0, 100].
        Placement floor contributes up to 50 points, chip bonus up to 50.
    """
    # Group busted players by hand number for same-hand averaging
    hand_groups: dict[int, list[str]] = defaultdict(list)
    for pid, hand in elimination_order:
        hand_groups[hand].append(pid)

    # Assign placements: 1 = first out (worst), ascending
    placement: dict[str, float] = {}
    next_placement = 1
    for hand in sorted(hand_groups):
        group = hand_groups[hand]
        # Average the placements for same-hand busts
        avg = sum(range(next_placement, next_placement + len(group))) / len(group)
        for pid in group:
            placement[pid] = avg
        next_placement += len(group)

    # Players busted but not in elimination_order (e.g., forfeited mid-game)
    # Group them at the current placement level with averaged placements
    untracked_busted = [
        pid for pid in final_chips
        if pid not in placement and final_chips[pid] <= 0
    ]
    if untracked_busted:
        avg = sum(range(next_placement, next_placement + len(untracked_busted))) / len(untracked_busted)
        for pid in untracked_busted:
            placement[pid] = avg
        next_placement += len(untracked_busted)

    # Survivors: ranked by chip count ascending, assigned remaining placements
    survivors = [
        pid for pid in final_chips
        if pid not in placement and final_chips[pid] > 0
    ]
    survivors.sort(key=lambda pid: final_chips[pid])

    for pid in survivors:
        placement[pid] = next_placement
        next_placement += 1

    # Compute scores
    scores: dict[str, float] = {}
    total_surviving_chips = sum(
        final_chips[pid] for pid in survivors
    ) if survivors else 0

    for pid in final_chips:
        # Floor: ((placement - 1) / (N - 1)) * 50
        floor = ((placement[pid] - 1) / (n_players - 1)) * 50 if n_players > 1 else 50

        # Chip bonus: survivors only
        if pid in placement and final_chips.get(pid, 0) > 0 and total_surviving_chips > 0:
            chip_bonus = (final_chips[pid] / total_surviving_chips) * 50
        else:
            chip_bonus = 0.0

        scores[pid] = round(floor + chip_bonus, 1)

    return scores


def hybrid_normalize(raw_scores: dict[str, float]) -> dict[str, float]:
    """Normalize any event's raw scores to 0-100 using the hybrid formula.

    50pts from placement ranking + 50pts from score proportion.
    Tied raw scores share averaged placements.

    Args:
        raw_scores: dict mapping player_id to raw event score.

    Returns:
        dict mapping player_id to a score in [0, 100].
    """
    n = len(raw_scores)
    if n <= 1:
        return {pid: 100.0 for pid in raw_scores}

    # Group players by raw score for tie handling
    score_groups: dict[float, list[str]] = defaultdict(list)
    for pid, sc in raw_scores.items():
        score_groups[sc].append(pid)

    # Assign placements: 1 = worst (lowest score), ascending
    placement: dict[str, float] = {}
    next_placement = 1
    for sc in sorted(score_groups):
        group = score_groups[sc]
        avg = sum(range(next_placement, next_placement + len(group))) / len(group)
        for pid in group:
            placement[pid] = avg
        next_placement += len(group)

    # Score proportion
    total = sum(raw_scores.values())

    scores: dict[str, float] = {}
    for pid in raw_scores:
        floor = ((placement[pid] - 1) / (n - 1)) * 50
        proportion = (raw_scores[pid] / total * 50) if total > 0 else 0.0
        scores[pid] = round(floor + proportion, 1)

    return scores
