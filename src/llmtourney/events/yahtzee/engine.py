"""Yahtzee — concurrent multiplayer dice game engine.

Each of 13 rounds, all players roll 5 dice simultaneously. Players get up
to 3 rolls per round: after each roll they choose to reroll unkept dice or
score in an available category. "Concurrent" means information hiding —
players cannot see each other's scoring decisions until the round completes.

Supports 2-9 players. No joker rules (simpler, avoids confusing LLMs).

Scoring:
  Upper section: ones-sixes (sum of matching face), +35 bonus if >= 63
  Lower section: three/four-of-a-kind (sum all), full house (25),
    small straight (30), large straight (40), yahtzee (50), chance (sum all)
  Yahtzee bonus: +100 per additional yahtzee (only if first yahtzee > 0)

Match scoring: rank-based (N-1 for 1st, N-2 for 2nd, ..., 0 for last).
Ties share the average of their positions.
"""

from __future__ import annotations

from collections import Counter

from llmtourney.events.base import MultiplayerSeriesEvent, ValidationResult

__all__ = ["YahtzeeEvent"]

UPPER_CATEGORIES = ["ones", "twos", "threes", "fours", "fives", "sixes"]
LOWER_CATEGORIES = [
    "three_of_a_kind", "four_of_a_kind", "full_house",
    "small_straight", "large_straight", "yahtzee", "chance",
]
ALL_CATEGORIES = UPPER_CATEGORIES + LOWER_CATEGORIES

FACE_FOR_UPPER = {"ones": 1, "twos": 2, "threes": 3, "fours": 4, "fives": 5, "sixes": 6}
UPPER_BONUS_THRESHOLD = 63
UPPER_BONUS_VALUE = 35
YAHTZEE_BONUS_VALUE = 100
TOTAL_ROUNDS = 13


def score_category(dice: list[int], category: str) -> int:
    """Calculate what a set of dice would score in a category."""
    counts = Counter(dice)
    total = sum(dice)

    if category in FACE_FOR_UPPER:
        face = FACE_FOR_UPPER[category]
        return counts.get(face, 0) * face

    if category == "three_of_a_kind":
        return total if any(c >= 3 for c in counts.values()) else 0
    if category == "four_of_a_kind":
        return total if any(c >= 4 for c in counts.values()) else 0
    if category == "full_house":
        vals = sorted(counts.values())
        return 25 if vals == [2, 3] else 0
    if category == "small_straight":
        faces = set(dice)
        for start in (1, 2, 3):
            if {start, start + 1, start + 2, start + 3} <= faces:
                return 30
        return 0
    if category == "large_straight":
        faces = set(dice)
        if faces == {1, 2, 3, 4, 5} or faces == {2, 3, 4, 5, 6}:
            return 40
        return 0
    if category == "yahtzee":
        return 50 if any(c >= 5 for c in counts.values()) else 0
    if category == "chance":
        return total

    return 0


class YahtzeeEvent(MultiplayerSeriesEvent):
    """N-player concurrent Yahtzee engine (display name: Roller Derby).

    Parameters
    ----------
    games_per_match : int
        Number of full 13-round games in a match.
    num_players : int
        Number of players (2-9).
    """

    @property
    def display_name(self) -> str:
        return "Roller Derby"

    def __init__(
        self,
        games_per_match: int = 1,
        num_players: int = 3,
    ) -> None:
        super().__init__(games_per_match, num_players)

        # Per-game state
        self._round_number: int = 0
        self._turn_number: int = 0  # global turn counter for telemetry
        self._current_player_idx: int = 0  # which player within the round
        self._roll_number: int = 0  # 1-3 within a player's turn

        self._dice: dict[str, list[int]] = {}  # current dice for each player
        self._scorecards: dict[str, dict[str, int | None]] = {}  # category -> score or None
        self._yahtzee_bonuses: dict[str, int] = {}  # count of bonus yahtzees
        self._round_decisions: dict[str, dict] = {}  # what each player scored this round (revealed at round end)

        # Yahtzee-specific tracking
        self._commentary: list[dict] = []  # recent events for spectator
        self._eliminated_players: set[str] = set()  # stuck-loop eliminated

    # ------------------------------------------------------------------
    # Event ABC
    # ------------------------------------------------------------------

    def current_player(self) -> str:
        return self._player_ids[self._current_player_idx]

    def get_prompt(self, player_id: str) -> str:
        label = self._player_labels[player_id]
        dice = self._dice[player_id]
        scorecard = self._scorecards[player_id]

        lines = [
            f"You are playing Yahtzee with {self._num_players} players.",
            f"You are Player {label}.",
            "",
        ]

        if self._games_per_match > 1:
            lines.append(f"Game {self._game_number} of {self._games_per_match}.")
            score_parts = [f"{self._player_labels[p]}: {self._match_scores[p]:.0f}" for p in self._player_ids]
            lines.append(f"Match scores: {', '.join(score_parts)}")
            lines.append("")

        lines.append(f"Round {self._round_number} of {TOTAL_ROUNDS}")
        lines.append(f"YOUR DICE (Roll {self._roll_number} of 3): {self._format_dice(dice)}")
        lines.append("")

        # Show available categories with potential scores
        available = self._available_categories(player_id)
        lines.append("Available categories (what your current dice would score):")
        for cat in available:
            pts = score_category(dice, cat)
            lines.append(f"  {cat}: {pts}")
        lines.append("")

        # Show filled categories
        filled = [(cat, v) for cat, v in scorecard.items() if v is not None]
        if filled:
            lines.append("Your scorecard (filled categories):")
            upper_total = 0
            for cat in UPPER_CATEGORIES:
                v = scorecard[cat]
                if v is not None:
                    lines.append(f"  {cat}: {v}")
                    upper_total += v
            if upper_total > 0:
                lines.append(f"  (upper subtotal: {upper_total}/63"
                             f"{' — bonus earned!' if upper_total >= UPPER_BONUS_THRESHOLD else ''})")
            for cat in LOWER_CATEGORIES:
                v = scorecard[cat]
                if v is not None:
                    lines.append(f"  {cat}: {v}")
            if self._yahtzee_bonuses[player_id] > 0:
                lines.append(f"  yahtzee bonuses: {self._yahtzee_bonuses[player_id]} x {YAHTZEE_BONUS_VALUE}")
            lines.append(f"  RUNNING TOTAL: {self._calculate_total(player_id)}")
            lines.append("")

        # Opponents' visible state — only show totals, not current round decisions
        lines.append("Opponent scores (running totals):")
        for pid in self._player_ids:
            if pid != player_id:
                opp_label = self._player_labels[pid]
                opp_total = self._calculate_total(pid)
                # Count how many categories they've filled
                filled_count = sum(1 for v in self._scorecards[pid].values() if v is not None)
                lines.append(f"  Player {opp_label}: {opp_total} ({filled_count}/13 categories filled)")
        lines.append("")

        # Legal actions
        if self._roll_number < 3:
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
        upper_so_far = sum(scorecard[c] for c in UPPER_CATEGORIES if scorecard[c] is not None)
        upper_remaining = [c for c in UPPER_CATEGORIES if scorecard[c] is None]
        if upper_remaining:
            needed = max(0, UPPER_BONUS_THRESHOLD - upper_so_far)
            lines.append(f"- Upper section: {upper_so_far}/63 toward bonus (+35). Need {needed} more from {len(upper_remaining)} remaining categories.")
        lines.append("- Yahtzee (50 pts) is the highest single category. Additional yahtzees earn +100 bonus each.")
        lines.append("- Consider saving 'chance' as a fallback for bad rolls later.")
        lines.append("- Large straight (40) > full house (25) — worth pursuing if you have 4 in sequence.")
        lines.append("")

        lines.append('Respond with ONLY a JSON object. Example: {"action": "score", "category": "threes", "reasoning": "..."}')

        return "\n".join(lines)

    def get_retry_prompt(self, player_id: str, error_reason: str) -> str:
        return (
            f"Your last action was invalid: {error_reason}\n\n"
            f"{self.get_prompt(player_id)}"
        )

    def validate_action(self, player_id: str, action: dict) -> ValidationResult:
        act = action.get("action")

        if act == "reroll":
            if self._roll_number >= 3:
                return ValidationResult(legal=False, reason="You have used all 3 rolls. You must score now.")
            keep = action.get("keep")
            if not isinstance(keep, list):
                return ValidationResult(legal=False, reason="'keep' must be a list of dice indices (0-4).")
            for idx in keep:
                if not isinstance(idx, int) or idx < 0 or idx > 4:
                    return ValidationResult(legal=False, reason=f"Invalid dice index {idx}. Must be 0-4.")
            if len(keep) != len(set(keep)):
                return ValidationResult(legal=False, reason="Duplicate indices in 'keep' list.")
            return ValidationResult(legal=True)

        if act == "score":
            category = action.get("category")
            if category not in ALL_CATEGORIES:
                return ValidationResult(
                    legal=False,
                    reason=f"Unknown category '{category}'. Valid: {', '.join(ALL_CATEGORIES)}",
                )
            if self._scorecards[player_id][category] is not None:
                return ValidationResult(
                    legal=False,
                    reason=f"Category '{category}' is already filled with {self._scorecards[player_id][category]} points.",
                )
            return ValidationResult(legal=True)

        return ValidationResult(
            legal=False,
            reason=f"Unknown action '{act}'. Expected 'reroll' or 'score'.",
        )

    def apply_action(self, player_id: str, action: dict) -> None:
        act = action["action"]
        if act == "reroll":
            self._do_reroll(player_id, action["keep"])
        else:
            self._do_score(player_id, action["category"])

    def forfeit_turn(self, player_id: str) -> None:
        """Auto-score the highest-value available category with current dice."""
        available = self._available_categories(player_id)
        if not available:
            return

        dice = self._dice[player_id]
        best_cat = max(available, key=lambda c: score_category(dice, c))
        self._do_score(player_id, best_cat)

    def get_state_snapshot(self) -> dict:
        scorecards_out = {}
        for pid in self._player_ids:
            sc = dict(self._scorecards[pid])
            sc["_upper_subtotal"] = sum(
                v for c in UPPER_CATEGORIES if (v := self._scorecards[pid][c]) is not None
            )
            sc["_upper_bonus"] = UPPER_BONUS_VALUE if sc["_upper_subtotal"] >= UPPER_BONUS_THRESHOLD else 0
            sc["_yahtzee_bonuses"] = self._yahtzee_bonuses[pid]
            sc["_total"] = self._calculate_total(pid)
            scorecards_out[pid] = sc

        return {
            "game_number": self._game_number,
            "games_per_match": self._games_per_match,
            "round": self._round_number,
            "total_rounds": TOTAL_ROUNDS,
            "turn_number": self._turn_number,
            "active_player": self.current_player() if not self._terminal else None,
            "roll_number": self._roll_number,
            "dice": {p: list(self._dice.get(p, [])) for p in self._player_ids},
            "scorecards": scorecards_out,
            "round_decisions": dict(self._round_decisions),
            "terminal": self._terminal,
            "match_scores": dict(self._match_scores),
            "eliminated_players": sorted(self._eliminated_players),
            "commentary": self._commentary[-20:],
            "potential_scores": {
                p: {
                    cat: score_category(self._dice.get(p, []), cat)
                    for cat in self._available_categories(p)
                }
                for p in self._player_ids
            },
        }

    # ------------------------------------------------------------------
    # Resume support
    # ------------------------------------------------------------------

    def load_state(self, snapshot: dict, seed: int) -> None:
        """Restore full game state from a telemetry snapshot."""
        super().load_state(snapshot, seed)

        self._round_number = snapshot["round"]
        self._turn_number = snapshot["turn_number"]
        self._roll_number = snapshot["roll_number"]

        # Restore current player index from active_player
        active = snapshot.get("active_player")
        if active and active in self._player_ids:
            self._current_player_idx = self._player_ids.index(active)
        else:
            self._current_player_idx = 0

        # Restore dice
        self._dice = {p: list(d) for p, d in snapshot["dice"].items()}

        # Restore scorecards — strip computed keys
        computed_keys = {"_upper_subtotal", "_upper_bonus", "_yahtzee_bonuses", "_total"}
        self._scorecards = {}
        for pid, sc in snapshot["scorecards"].items():
            self._scorecards[pid] = {
                k: v for k, v in sc.items() if k not in computed_keys
            }

        # Restore yahtzee bonuses from scorecard computed field
        self._yahtzee_bonuses = {
            pid: snapshot["scorecards"][pid].get("_yahtzee_bonuses", 0)
            for pid in self._player_ids
        }

        self._round_decisions = dict(snapshot.get("round_decisions", {}))
        self._commentary = list(snapshot.get("commentary", []))
        self._eliminated_players = set(snapshot.get("eliminated_players", []))

    def eliminate_player(self, player_id: str) -> None:
        """Mark player as eliminated — zero-fill scorecard, skip in future rounds."""
        self._eliminated_players.add(player_id)
        for cat in ALL_CATEGORIES:
            if self._scorecards[player_id][cat] is None:
                self._scorecards[player_id][cat] = 0
        # If this was the current player, advance
        if self._player_ids[self._current_player_idx] == player_id:
            self._advance_to_next_player()

    # ------------------------------------------------------------------
    # Game lifecycle
    # ------------------------------------------------------------------

    def _start_new_game(self) -> None:
        self._game_number += 1
        if self._game_number > self._games_per_match:
            self._terminal = True
            return

        self._round_number = 0
        self._turn_number = 0
        self._commentary = []

        # Initialize scorecards (eliminated players get zero-filled)
        self._scorecards = {
            p: {cat: (0 if p in self._eliminated_players else None) for cat in ALL_CATEGORIES}
            for p in self._player_ids
        }
        self._yahtzee_bonuses = {p: 0 for p in self._player_ids}
        self._dice = {p: [] for p in self._player_ids}
        self._round_decisions = {}

        self._start_new_round()

    def _start_new_round(self) -> None:
        self._round_number += 1
        if self._round_number > TOTAL_ROUNDS:
            self._finish_game()
            return

        # Find first non-eliminated player
        self._current_player_idx = 0
        while (self._current_player_idx < self._num_players
               and self._player_ids[self._current_player_idx] in self._eliminated_players):
            self._current_player_idx += 1
        if self._current_player_idx >= self._num_players:
            # All players eliminated — end game
            self._finish_game()
            return
        self._round_decisions = {}
        self._start_player_turn(self._player_ids[self._current_player_idx])

    def _start_player_turn(self, player_id: str) -> None:
        """Roll initial 5 dice for a player's turn."""
        self._roll_number = 1
        self._dice[player_id] = [self._rng.randint(1, 6) for _ in range(5)]

    def _advance_to_next_player(self) -> None:
        """Move to next non-eliminated player in the round, or start new round."""
        self._current_player_idx += 1
        # Skip eliminated players
        while (self._current_player_idx < self._num_players
               and self._player_ids[self._current_player_idx] in self._eliminated_players):
            self._current_player_idx += 1
        if self._current_player_idx >= self._num_players:
            # All active players have scored this round — reveal decisions
            self._reveal_round_decisions()
            self._start_new_round()
        else:
            self._start_player_turn(self._player_ids[self._current_player_idx])

    def _reveal_round_decisions(self) -> None:
        """Add commentary about what everyone scored this round."""
        if not self._round_decisions:
            return
        for pid, decision in self._round_decisions.items():
            label = self._player_labels[pid]
            cat = decision["category"]
            pts = decision["points"]
            self._commentary.append({
                "round": self._round_number,
                "player": pid,
                "label": label,
                "event": "scored",
                "category": cat,
                "points": pts,
                "total": self._calculate_total(pid),
            })

    def _finish_game(self) -> None:
        """Score the game by rank, award match points, start next game."""
        # Calculate final totals
        totals = {p: self._calculate_total(p) for p in self._player_ids}

        # Sort by total descending
        ranked = sorted(self._player_ids, key=lambda p: totals[p], reverse=True)

        # Award rank-based points with tie-sharing
        i = 0
        while i < len(ranked):
            # Find tie group
            j = i + 1
            while j < len(ranked) and totals[ranked[j]] == totals[ranked[i]]:
                j += 1
            # Positions i..j-1 are tied — share average
            # 1st place gets N-1 points, 2nd gets N-2, etc.
            points_sum = sum(self._num_players - 1 - k for k in range(i, j))
            shared = points_sum / (j - i)
            for k in range(i, j):
                self._match_scores[ranked[k]] += shared
            i = j

        # Commentary for game end
        for pid in ranked:
            label = self._player_labels[pid]
            self._commentary.append({
                "round": self._round_number,
                "player": pid,
                "label": label,
                "event": "game_end",
                "game_total": totals[pid],
                "match_score": self._match_scores[pid],
            })

        self._start_new_game()

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _do_reroll(self, player_id: str, keep_indices: list[int]) -> None:
        """Re-roll unkept dice."""
        self._turn_number += 1
        dice = self._dice[player_id]
        new_dice = list(dice)
        for i in range(5):
            if i not in keep_indices:
                new_dice[i] = self._rng.randint(1, 6)
        self._dice[player_id] = new_dice
        self._roll_number += 1

    def _do_score(self, player_id: str, category: str) -> None:
        """Score current dice in a category and advance."""
        self._turn_number += 1
        dice = self._dice[player_id]
        points = score_category(dice, category)

        # Check for yahtzee bonus
        is_yahtzee = all(d == dice[0] for d in dice)
        if is_yahtzee and category != "yahtzee":
            # Yahtzee bonus only if first yahtzee was scored > 0
            if self._scorecards[player_id]["yahtzee"] is not None and self._scorecards[player_id]["yahtzee"] > 0:
                self._yahtzee_bonuses[player_id] += 1
                self._commentary.append({
                    "round": self._round_number,
                    "player": player_id,
                    "label": self._player_labels[player_id],
                    "event": "yahtzee_bonus",
                    "dice": list(dice),
                })
                self._highlight_turns.append(self._turn_number)
        elif is_yahtzee and category == "yahtzee":
            self._highlight_turns.append(self._turn_number)

        self._scorecards[player_id][category] = points

        # Record decision (hidden until round ends)
        self._round_decisions[player_id] = {
            "category": category,
            "points": points,
            "dice": list(dice),
            "roll_number": self._roll_number,
        }

        self._advance_to_next_player()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _available_categories(self, player_id: str) -> list[str]:
        """Return unfilled categories for a player."""
        return [cat for cat in ALL_CATEGORIES if self._scorecards[player_id][cat] is None]

    def _calculate_total(self, player_id: str) -> int:
        """Calculate total score including bonuses."""
        sc = self._scorecards[player_id]

        # Upper section
        upper = sum(v for c in UPPER_CATEGORIES if (v := sc[c]) is not None)
        upper_bonus = UPPER_BONUS_VALUE if upper >= UPPER_BONUS_THRESHOLD else 0

        # Lower section
        lower = sum(v for c in LOWER_CATEGORIES if (v := sc[c]) is not None)

        # Yahtzee bonuses
        yb = self._yahtzee_bonuses[player_id] * YAHTZEE_BONUS_VALUE

        return upper + upper_bonus + lower + yb

    @staticmethod
    def _format_dice(dice: list[int]) -> str:
        """Format dice as [3] [3] [5] [3] [6] style."""
        return " ".join(f"[{d}]" for d in dice)
