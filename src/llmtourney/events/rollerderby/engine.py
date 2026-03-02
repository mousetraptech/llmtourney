"""Roller Derby — concurrent N-player Yahtzee racing engine.

All players fill out 13-round Yahtzee scorecards simultaneously, racing at
their own pace. Response latency IS the game mechanic: faster models get more
turns per wall-clock second in concurrent mode. Finish bonuses reward the
first players to complete all 13 categories.

Reuses all pure scoring logic from ``events.yahtzee.engine`` but with
per-player independent state behind threading locks for safe concurrent access.
"""

from __future__ import annotations

import random
import string
import threading

from llmtourney.events.base import Event, ValidationResult
from llmtourney.events.yahtzee.engine import (
    ALL_CATEGORIES,
    FACE_FOR_UPPER,
    LOWER_CATEGORIES,
    TOTAL_ROUNDS,
    UPPER_BONUS_THRESHOLD,
    UPPER_BONUS_VALUE,
    UPPER_CATEGORIES,
    YAHTZEE_BONUS_VALUE,
    score_category,
)

__all__ = ["ConcurrentYahtzeeEvent"]


class _PlayerState:
    """Per-player Yahtzee state — one per player, mutated under lock."""

    __slots__ = (
        "scorecard", "dice", "roll_number", "round_number",
        "yahtzee_bonuses", "rng", "finished", "finish_order_idx",
        "turns_taken", "game_scores",
    )

    def __init__(self, rng: random.Random) -> None:
        self.rng = rng
        self.scorecard: dict[str, int | None] = {cat: None for cat in ALL_CATEGORIES}
        self.dice: list[int] = []
        self.roll_number: int = 0
        self.round_number: int = 0
        self.yahtzee_bonuses: int = 0
        self.finished: bool = False
        self.finish_order_idx: int | None = None
        self.turns_taken: int = 0
        self.game_scores: list[int] = []  # total per completed game

    def start_round(self) -> None:
        self.round_number += 1
        self.roll_number = 1
        self.dice = [self.rng.randint(1, 6) for _ in range(5)]

    def available_categories(self) -> list[str]:
        return [cat for cat in ALL_CATEGORIES if self.scorecard[cat] is None]

    def calculate_total(self) -> int:
        sc = self.scorecard
        upper = sum(v for c in UPPER_CATEGORIES if (v := sc[c]) is not None)
        upper_bonus = UPPER_BONUS_VALUE if upper >= UPPER_BONUS_THRESHOLD else 0
        lower = sum(v for c in LOWER_CATEGORIES if (v := sc[c]) is not None)
        yb = self.yahtzee_bonuses * YAHTZEE_BONUS_VALUE
        return upper + upper_bonus + lower + yb


class ConcurrentYahtzeeEvent(Event):
    """N-player concurrent Yahtzee racing engine.

    Parameters
    ----------
    games_per_match : int
        Number of full 13-round scorecards in a match.
    num_players : int
        Number of players (2-9).
    finish_bonus : list[int]
        Bonus points for 1st/2nd/3rd finishers per game.
    race_timeout_s : float
        Max seconds per game before forced end.
    """

    def __init__(
        self,
        games_per_match: int = 1,
        num_players: int = 7,
        finish_bonus: list[int] | None = None,
        race_timeout_s: float = 300.0,
    ) -> None:
        self._games_per_match = games_per_match
        self._num_players = num_players
        self._finish_bonus = finish_bonus or [3, 2, 1]
        self._race_timeout_s = race_timeout_s

        self._player_ids = [
            f"player_{string.ascii_lowercase[i]}" for i in range(num_players)
        ]
        self._player_labels = {
            pid: string.ascii_uppercase[i]
            for i, pid in enumerate(self._player_ids)
        }
        self._action_schema = self._load_event_schema()

        # Match state
        self._terminal: bool = False
        self._game_number: int = 0
        self._match_scores: dict[str, float] = {p: 0.0 for p in self._player_ids}
        self._highlight_turns: list[int] = []
        self._turn_number: int = 0  # global turn counter for telemetry

        # Per-player state
        self._states: dict[str, _PlayerState] = {}
        self._finish_order: list[str] = []
        self._eliminated: set[str] = set()

        # Thread safety
        self._lock = threading.Lock()
        self._concurrent = True

    @property
    def display_name(self) -> str:
        return "Roller Derby"

    @property
    def race_timeout_s(self) -> float:
        return self._race_timeout_s

    @property
    def concurrent(self) -> bool:
        return self._concurrent

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def reset(self, seed: int) -> None:
        self._base_seed = seed
        self._game_number = 0
        self._terminal = False
        self._match_scores = {p: 0.0 for p in self._player_ids}
        self._highlight_turns = []
        self._turn_number = 0
        self._eliminated = set()
        self._start_new_game()

    def _start_new_game(self) -> None:
        self._game_number += 1
        if self._game_number > self._games_per_match:
            self._terminal = True
            return

        self._finish_order = []
        self._states = {}
        for pid in self._player_ids:
            rng = random.Random(hash((self._base_seed, pid, self._game_number)))
            ps = _PlayerState(rng)
            if pid not in self._eliminated:
                ps.start_round()
            else:
                # Zero-fill eliminated players
                ps.finished = True
                for cat in ALL_CATEGORIES:
                    ps.scorecard[cat] = 0
            self._states[pid] = ps

    def _finish_game(self) -> None:
        """Score the completed game and start the next."""
        # Calculate totals
        totals = {p: self._states[p].calculate_total() for p in self._player_ids}

        # Store game total
        for pid in self._player_ids:
            self._states[pid].game_scores.append(totals[pid])

        # Rank-based scoring with tie-sharing
        ranked = sorted(self._player_ids, key=lambda p: totals[p], reverse=True)
        i = 0
        while i < len(ranked):
            j = i + 1
            while j < len(ranked) and totals[ranked[j]] == totals[ranked[i]]:
                j += 1
            points_sum = sum(self._num_players - 1 - k for k in range(i, j))
            shared = points_sum / (j - i)
            for k in range(i, j):
                self._match_scores[ranked[k]] += shared
            i = j

        # Finish bonuses for first N completers
        for i, bonus in enumerate(self._finish_bonus):
            if i < len(self._finish_order):
                pid = self._finish_order[i]
                self._match_scores[pid] += float(bonus)

        self._start_new_game()

    # ------------------------------------------------------------------
    # Player state (thread-safe)
    # ------------------------------------------------------------------

    def player_finished(self, player_id: str) -> bool:
        with self._lock:
            return self._states[player_id].finished

    def race_over(self) -> bool:
        with self._lock:
            return all(self._states[p].finished for p in self._player_ids)

    # ------------------------------------------------------------------
    # Event ABC
    # ------------------------------------------------------------------

    def current_player(self) -> str:
        # In concurrent mode the tournament runner doesn't use this.
        # Round-robin by turns taken among active players.
        with self._lock:
            active = [
                p for p in self._player_ids
                if not self._states[p].finished and p not in self._eliminated
            ]
            if not active:
                return self._player_ids[0]
            return min(active, key=lambda p: self._states[p].turns_taken)

    def get_prompt(self, player_id: str) -> str:
        with self._lock:
            return self._build_prompt(player_id)

    def _build_prompt(self, player_id: str) -> str:
        """Build prompt for a player. Must hold self._lock."""
        ps = self._states[player_id]
        label = self._player_labels[player_id]

        lines = [
            f"You are playing Roller Derby (Yahtzee racing) with {self._num_players} players.",
            f"You are Player {label}.",
            "",
        ]

        if self._games_per_match > 1:
            lines.append(f"Game {self._game_number} of {self._games_per_match}.")
            score_parts = [f"{self._player_labels[p]}: {self._match_scores[p]:.0f}" for p in self._player_ids]
            lines.append(f"Match scores: {', '.join(score_parts)}")
            lines.append("")

        lines.append(f"Round {ps.round_number} of {TOTAL_ROUNDS}")
        lines.append(f"YOUR DICE (Roll {ps.roll_number} of 3): {self._format_dice(ps.dice)}")
        lines.append("")

        # Show available categories with potential scores
        available = ps.available_categories()
        lines.append("Available categories (what your current dice would score):")
        for cat in available:
            pts = score_category(ps.dice, cat)
            lines.append(f"  {cat}: {pts}")
        lines.append("")

        # Show filled categories
        filled = [(cat, v) for cat, v in ps.scorecard.items() if v is not None]
        if filled:
            lines.append("Your scorecard (filled categories):")
            upper_total = 0
            for cat in UPPER_CATEGORIES:
                v = ps.scorecard[cat]
                if v is not None:
                    lines.append(f"  {cat}: {v}")
                    upper_total += v
            if upper_total > 0:
                lines.append(f"  (upper subtotal: {upper_total}/63"
                             f"{' — bonus earned!' if upper_total >= UPPER_BONUS_THRESHOLD else ''})")
            for cat in LOWER_CATEGORIES:
                v = ps.scorecard[cat]
                if v is not None:
                    lines.append(f"  {cat}: {v}")
            if ps.yahtzee_bonuses > 0:
                lines.append(f"  yahtzee bonuses: {ps.yahtzee_bonuses} x {YAHTZEE_BONUS_VALUE}")
            lines.append(f"  RUNNING TOTAL: {ps.calculate_total()}")
            lines.append("")

        # Opponents — only totals + progress
        lines.append("Opponent progress:")
        for pid in self._player_ids:
            if pid != player_id:
                opp = self._states[pid]
                opp_label = self._player_labels[pid]
                opp_total = opp.calculate_total()
                filled_count = sum(1 for v in opp.scorecard.values() if v is not None)
                status = ""
                if opp.finished:
                    idx = opp.finish_order_idx
                    if idx is not None:
                        status = f" [FINISHED #{idx + 1}]"
                    else:
                        status = " [DONE]"
                lines.append(f"  Player {opp_label}: {opp_total} ({filled_count}/13 categories){status}")
        lines.append("")

        # Legal actions
        if ps.roll_number < 3:
            lines.append("You may REROLL or SCORE:")
            lines.append('  To reroll: {"action": "reroll", "keep": [0, 2, 4], "reasoning": "..."}')
            lines.append("    (keep = list of dice INDICES 0-4 to keep; unkept dice are re-rolled)")
            lines.append("    (keep all 5 to keep your current dice and use your roll)")
            lines.append('  To score: {"action": "score", "category": "full_house", "reasoning": "..."}')
        else:
            lines.append("Roll 3 of 3 — you MUST score now:")
            lines.append('  {"action": "score", "category": "full_house", "reasoning": "..."}')
        lines.append("")

        # Strategy tips
        lines.append("STRATEGY TIPS:")
        upper_so_far = sum(ps.scorecard[c] for c in UPPER_CATEGORIES if ps.scorecard[c] is not None)
        upper_remaining = [c for c in UPPER_CATEGORIES if ps.scorecard[c] is None]
        if upper_remaining:
            needed = max(0, UPPER_BONUS_THRESHOLD - upper_so_far)
            lines.append(f"- Upper section: {upper_so_far}/63 toward bonus (+35). Need {needed} more from {len(upper_remaining)} remaining categories.")
        lines.append("- Yahtzee (50 pts) is the highest single category. Additional yahtzees earn +100 bonus each.")
        lines.append("- Consider saving 'chance' as a fallback for bad rolls later.")
        lines.append("- Large straight (40) > full house (25) — worth pursuing if you have 4 in sequence.")
        lines.append("")
        lines.append("SPEED MATTERS. Faster responses = more turns = finish first = bonus points.")
        lines.append("Keep reasoning brief.")
        lines.append("")

        lines.append('Respond with ONLY a JSON object. Example: {"action": "score", "category": "threes", "reasoning": "..."}')

        return "\n".join(lines)

    def get_retry_prompt(self, player_id: str, error_reason: str) -> str:
        prompt = self.get_prompt(player_id)
        return (
            f"Your previous response was invalid: {error_reason}\n\n"
            f"{prompt}\n\n"
            "IMPORTANT: Respond with ONLY a JSON object. No markdown, no explanation."
        )

    def validate_action(self, player_id: str, action: dict) -> ValidationResult:
        with self._lock:
            return self._validate(player_id, action)

    def _validate(self, player_id: str, action: dict) -> ValidationResult:
        """Validate action. Must hold self._lock."""
        ps = self._states[player_id]

        if ps.finished:
            return ValidationResult(False, "Player has already finished all rounds")

        act = action.get("action")

        if act == "reroll":
            if ps.roll_number >= 3:
                return ValidationResult(False, "You have used all 3 rolls. You must score now.")
            keep = action.get("keep")
            if not isinstance(keep, list):
                return ValidationResult(False, "'keep' must be a list of dice indices (0-4).")
            for idx in keep:
                if not isinstance(idx, int) or idx < 0 or idx > 4:
                    return ValidationResult(False, f"Invalid dice index {idx}. Must be 0-4.")
            if len(keep) != len(set(keep)):
                return ValidationResult(False, "Duplicate indices in 'keep' list.")
            return ValidationResult(True)

        if act == "score":
            category = action.get("category")
            if category not in ALL_CATEGORIES:
                return ValidationResult(
                    False,
                    f"Unknown category '{category}'. Valid: {', '.join(ALL_CATEGORIES)}",
                )
            if ps.scorecard[category] is not None:
                return ValidationResult(
                    False,
                    f"Category '{category}' is already filled with {ps.scorecard[category]} points.",
                )
            return ValidationResult(True)

        return ValidationResult(
            False,
            f"Unknown action '{act}'. Expected 'reroll' or 'score'.",
        )

    def apply_action(self, player_id: str, action: dict) -> None:
        with self._lock:
            self._apply(player_id, action)

    def _apply(self, player_id: str, action: dict) -> None:
        """Apply action. Must hold self._lock."""
        ps = self._states[player_id]
        act = action["action"]
        self._turn_number += 1
        ps.turns_taken += 1

        if act == "reroll":
            keep_indices = action["keep"]
            new_dice = list(ps.dice)
            for i in range(5):
                if i not in keep_indices:
                    new_dice[i] = ps.rng.randint(1, 6)
            ps.dice = new_dice
            ps.roll_number += 1

        elif act == "score":
            category = action["category"]
            dice = ps.dice
            points = score_category(dice, category)

            # Yahtzee bonus
            is_yahtzee = all(d == dice[0] for d in dice)
            if is_yahtzee and category != "yahtzee":
                if ps.scorecard["yahtzee"] is not None and ps.scorecard["yahtzee"] > 0:
                    ps.yahtzee_bonuses += 1
                    self._highlight_turns.append(self._turn_number)
            elif is_yahtzee and category == "yahtzee":
                self._highlight_turns.append(self._turn_number)

            ps.scorecard[category] = points

            # Advance to next round or finish
            if ps.round_number >= TOTAL_ROUNDS:
                # All 13 categories scored
                ps.finished = True
                ps.finish_order_idx = len(self._finish_order)
                self._finish_order.append(player_id)
                self._highlight_turns.append(self._turn_number)
            else:
                ps.start_round()

            # Check if game is over (all finished)
            if all(self._states[p].finished for p in self._player_ids):
                self._finish_game()

    def forfeit_turn(self, player_id: str) -> None:
        """On violation/timeout, auto-score best available category."""
        with self._lock:
            ps = self._states[player_id]
            if ps.finished:
                return
            self._turn_number += 1
            ps.turns_taken += 1

            available = ps.available_categories()
            if not available:
                return
            best_cat = max(available, key=lambda c: score_category(ps.dice, c))
            # Inline the scoring (can't call _apply since we already hold lock)
            points = score_category(ps.dice, best_cat)
            ps.scorecard[best_cat] = points

            if ps.round_number >= TOTAL_ROUNDS:
                ps.finished = True
                ps.finish_order_idx = len(self._finish_order)
                self._finish_order.append(player_id)
            else:
                ps.start_round()

            if all(self._states[p].finished for p in self._player_ids):
                self._finish_game()

    def eliminate_player(self, player_id: str) -> None:
        """Remove player — zero-fill remaining categories, mark finished."""
        with self._lock:
            self._eliminated.add(player_id)
            ps = self._states[player_id]
            if not ps.finished:
                for cat in ALL_CATEGORIES:
                    if ps.scorecard[cat] is None:
                        ps.scorecard[cat] = 0
                ps.finished = True
                # Don't add to finish_order — eliminated, not finished

            if all(self._states[p].finished for p in self._player_ids):
                self._finish_game()

    def force_forfeit_match(self, player_id: str) -> None:
        with self._lock:
            self._terminal = True

    def award_forfeit_wins(self, forfeiting_player_id: str) -> None:
        with self._lock:
            remaining = self._games_per_match - self._game_number + 1
            pts = float(self._num_players - 1)
            for pid in self._player_ids:
                if pid != forfeiting_player_id:
                    self._match_scores[pid] += pts * remaining
            self._terminal = True

    def get_scores(self) -> dict[str, float]:
        with self._lock:
            return dict(self._match_scores)

    def get_state_snapshot(self) -> dict:
        with self._lock:
            scorecards_out = {}
            for pid in self._player_ids:
                ps = self._states[pid]
                sc = dict(ps.scorecard)
                sc["_upper_subtotal"] = sum(
                    v for c in UPPER_CATEGORIES if (v := ps.scorecard[c]) is not None
                )
                sc["_upper_bonus"] = UPPER_BONUS_VALUE if sc["_upper_subtotal"] >= UPPER_BONUS_THRESHOLD else 0
                sc["_yahtzee_bonuses"] = ps.yahtzee_bonuses
                sc["_total"] = ps.calculate_total()
                scorecards_out[pid] = sc

            return {
                "game_number": self._game_number,
                "games_per_match": self._games_per_match,
                "total_rounds": TOTAL_ROUNDS,
                "turn_number": self._turn_number,
                "terminal": self._terminal,
                "match_scores": dict(self._match_scores),
                "finish_order": list(self._finish_order),
                "eliminated": sorted(self._eliminated),
                "player_labels": dict(self._player_labels),
                "players": {
                    pid: {
                        "round": self._states[pid].round_number,
                        "roll_number": self._states[pid].roll_number,
                        "dice": list(self._states[pid].dice),
                        "finished": self._states[pid].finished,
                        "finish_order_idx": self._states[pid].finish_order_idx,
                        "turns_taken": self._states[pid].turns_taken,
                    }
                    for pid in self._player_ids
                },
                "scorecards": scorecards_out,
                "potential_scores": {
                    p: {
                        cat: score_category(self._states[p].dice, cat)
                        for cat in self._states[p].available_categories()
                    }
                    for p in self._player_ids
                    if not self._states[p].finished
                },
            }

    def get_highlight_hands(self) -> list[int]:
        with self._lock:
            return list(self._highlight_turns)

    @staticmethod
    def _format_dice(dice: list[int]) -> str:
        return " ".join(f"[{d}]" for d in dice)
