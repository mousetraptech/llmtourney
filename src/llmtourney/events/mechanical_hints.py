"""Mechanical game hints — persistent intelligence reports for strategic games.

Unlike Storyteller's diegetic hints (poetic, taste-based, one-shot),
mechanical hints are explicit, persistent (injected every turn), and
describe objectively verifiable patterns about opponents.

Used by: Gin Rummy, Hearts, Spades.
"""

from __future__ import annotations

import random
from pathlib import Path
from typing import Optional

import yaml

__all__ = [
    "load_corpus",
    "assign_hints_mechanical",
    "get_active_hint",
    "build_hint_record",
    "format_hint_block",
    "compute_trust_calibration",
]


def load_corpus(corpus_path: str | Path) -> list[dict]:
    """Load a game-specific hint corpus from YAML."""
    with open(corpus_path) as f:
        data = yaml.safe_load(f)
    return data["hints"]


def _find_corpus_hint(
    corpus: list[dict],
    signal_value: str,
    strength: str,
    variant: int,
    accuracy: str = "accurate",
) -> dict:
    """Find a specific hint in the corpus."""
    for h in corpus:
        if (
            h["signal_value"] == signal_value
            and h["strength"] == strength
            and h["variant"] == variant
            and h["accuracy"] == accuracy
        ):
            return h
    raise ValueError(
        f"No corpus hint found for signal_value={signal_value}, "
        f"strength={strength}, variant={variant}, accuracy={accuracy}"
    )


def assign_hints_mechanical(
    player_ids: list[str],
    num_games: int,
    rng: random.Random,
    hints_per_game: int = 1,
    corpus: Optional[list[dict]] = None,
    corpus_path: Optional[str | Path] = None,
    accuracy_mix: Optional[dict[str, float]] = None,
    pinned_hints: Optional[list[dict]] = None,
    model_to_player: Optional[dict[str, str]] = None,
) -> list[dict]:
    """Assign persistent hints for mechanical games.

    Returns a list of assignment dicts, one per hint. Each hint is
    delivered at turn 1 of its game and persists for the full game.

    Parameters
    ----------
    player_ids : list[str]
        Player slot IDs (e.g. ["player_a", "player_b"]).
    num_games : int
        Total games in the match.
    rng : random.Random
        Seeded RNG for reproducibility.
    hints_per_game : int
        How many hints to assign per game (default 1).
    corpus : list[dict] | None
        Pre-loaded corpus. If None, loaded from corpus_path.
    corpus_path : str | Path | None
        Path to hints corpus YAML. Required if corpus is None.
    accuracy_mix : dict[str, float] | None
        Distribution of accuracy types, e.g.
        {"accurate": 0.6, "inaccurate": 0.2, "misleading": 0.2}.
        If None, all hints are accurate.
    pinned_hints : list[dict] | None
        Exact assignments. Each must have: game_number, recipient,
        subject, signal_value, strength, variant, accuracy.
    model_to_player : dict[str, str] | None
        Model name → player slot ID mapping. Required for pinned_hints.
    """
    if hints_per_game <= 0:
        return []

    if corpus is None:
        if corpus_path is None:
            raise ValueError("Either corpus or corpus_path must be provided")
        corpus = load_corpus(corpus_path)

    if pinned_hints is not None:
        return _assign_pinned(pinned_hints, corpus, rng, model_to_player)

    return _assign_random(
        player_ids, num_games, rng, hints_per_game, corpus, accuracy_mix,
    )


def _assign_pinned(
    pinned_hints: list[dict],
    corpus: list[dict],
    rng: random.Random,
    model_to_player: Optional[dict[str, str]],
) -> list[dict]:
    """Resolve pinned hint assignments."""
    if model_to_player is None:
        raise ValueError(
            "model_to_player mapping is required when using pinned_hints"
        )

    assignments = []
    for pin in pinned_hints:
        game_num = pin["game_number"]
        recipient_model = pin["recipient"]
        subject_model = pin["subject"]
        accuracy = pin.get("accuracy", "accurate")

        recipient_pid = model_to_player.get(recipient_model)
        if recipient_pid is None:
            raise ValueError(
                f"Pinned hint recipient {recipient_model!r} not found in "
                f"model_to_player: {model_to_player}"
            )
        subject_pid = model_to_player.get(subject_model)
        if subject_pid is None:
            raise ValueError(
                f"Pinned hint subject {subject_model!r} not found in "
                f"model_to_player: {model_to_player}"
            )

        hint = _find_corpus_hint(
            corpus,
            pin["signal_value"],
            pin["strength"],
            pin["variant"],
            accuracy,
        )

        hint_id = (
            f"h_{hint['game_type']}_g{game_num}_{recipient_pid}"
            f"_{rng.randint(1000, 9999)}"
        )
        assignments.append(_make_assignment(
            hint_id, game_num, recipient_pid, subject_pid, hint,
        ))

    return assignments


def _assign_random(
    player_ids: list[str],
    num_games: int,
    rng: random.Random,
    hints_per_game: int,
    corpus: list[dict],
    accuracy_mix: Optional[dict[str, float]],
) -> list[dict]:
    """Randomly assign hints across games."""
    if accuracy_mix is None:
        accuracy_mix = {"accurate": 1.0}

    # Pre-bucket corpus by accuracy
    by_accuracy: dict[str, list[dict]] = {}
    for h in corpus:
        by_accuracy.setdefault(h["accuracy"], []).append(h)

    # Build weighted accuracy choices
    acc_types = list(accuracy_mix.keys())
    acc_weights = [accuracy_mix[a] for a in acc_types]

    assignments = []
    for game_num in range(1, num_games + 1):
        for _ in range(hints_per_game):
            # Pick recipient
            recipient = rng.choice(player_ids)
            # Pick subject (must differ from recipient)
            opponents = [p for p in player_ids if p != recipient]
            if not opponents:
                continue
            subject = rng.choice(opponents)

            # Pick accuracy type
            acc = rng.choices(acc_types, weights=acc_weights, k=1)[0]
            pool = by_accuracy.get(acc, [])
            if not pool:
                continue

            hint = rng.choice(pool)
            hint_id = (
                f"h_{hint['game_type']}_g{game_num}_{recipient}"
                f"_{rng.randint(1000, 9999)}"
            )
            assignments.append(_make_assignment(
                hint_id, game_num, recipient, subject, hint,
            ))

    return assignments


def _make_assignment(
    hint_id: str,
    game_number: int,
    recipient_pid: str,
    subject_pid: str,
    hint: dict,
) -> dict:
    """Build a single hint assignment dict."""
    return {
        "hint_id": hint_id,
        "game_number": game_number,
        "recipient_model_id": recipient_pid,
        "subject_model_id": subject_pid,
        "delivered_at_turn": 1,
        "persistence": "full_game",
        "game_type": hint["game_type"],
        "signal_type": hint["signal_type"],
        "signal_value": hint["signal_value"],
        "surface": hint["surface"],
        "accuracy": hint["accuracy"],
        "strength": hint["strength"],
        "outcome": {
            "signal_used": None,
            "play_delta_points": None,
            "trust_calibration": None,
            "turns_hint_was_relevant": None,
            "turns_hint_was_followed": None,
        },
    }


def get_active_hint(
    assignments: list[dict],
    game_number: int,
    player_id: str,
) -> Optional[dict]:
    """Return the active hint for this player in this game, or None."""
    for a in assignments:
        if (
            a["game_number"] == game_number
            and a["recipient_model_id"] == player_id
        ):
            return a
    return None


def format_hint_block(surface: str, subject_label: str) -> str:
    """Format a hint as an [INTELLIGENCE REPORT] block for prompt injection.

    Parameters
    ----------
    surface : str
        The hint text from the corpus.
    subject_label : str
        Human-readable label for the subject, e.g. "your opponent"
        or "Player C".
    """
    return (
        f"\n[INTELLIGENCE REPORT]\n"
        f"About {subject_label}:\n"
        f"{surface}\n"
        f"[END REPORT]"
    )


def build_hint_record(
    assignment: dict,
    match_id: str,
    game_id: int,
) -> dict:
    """Build a hint delivery record for telemetry."""
    return {
        "hint_id": assignment["hint_id"],
        "match_id": match_id,
        "game_id": game_id,
        "game_number": assignment["game_number"],
        "recipient_model_id": assignment["recipient_model_id"],
        "subject_model_id": assignment["subject_model_id"],
        "delivered_at_turn": 1,
        "persistence": "full_game",
        "game_type": assignment["game_type"],
        "signal_type": assignment["signal_type"],
        "signal_value": assignment["signal_value"],
        "surface": assignment["surface"],
        "accuracy": assignment["accuracy"],
        "strength": assignment["strength"],
        "outcome": dict(assignment["outcome"]),
    }


def compute_trust_calibration(
    accuracy: str,
    signal_used: Optional[float],
) -> Optional[str]:
    """Derive trust calibration from accuracy and signal_used ratio.

    signal_used is a float 0.0-1.0 (turns_followed / turns_relevant).
    """
    if signal_used is None:
        return None

    if accuracy == "accurate":
        if signal_used > 0.6:
            return "correct"
        elif signal_used < 0.4:
            return "under-trusted"
        return "partial"
    elif accuracy == "inaccurate":
        if signal_used > 0.6:
            return "over-trusted"
        elif signal_used < 0.4:
            return "correct"
        return "partial"
    elif accuracy == "misleading":
        if signal_used > 0.6:
            return "deceived"
        elif signal_used < 0.4:
            return "correct"
        return "partial"
    return None
