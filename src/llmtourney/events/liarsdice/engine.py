"""Liar's Dice — N-player bluffing/probability dice game engine.

Each player has hidden dice under a cup. Players take turns bidding on the
total count of a face value across ALL cups combined. Bids must be raised
each turn. Any player can challenge the current bid by calling "liar."
If the bid was wrong the bidder loses a die; if correct the challenger
loses one. Last player standing wins.

Wild ones rule: dice showing 1 count toward any face value, unless the
opening bid of a round is on 1s — then wilds are off for that round.

Supports 2-10 players (default 4). Starting dice per player is configurable
(default 5).

Modes:
- attrition (default): loser loses a die, that's it.
- redistribution: loser loses a die AND winner gains one.
"""

from __future__ import annotations

import math

from llmtourney.events.base import MultiplayerSeriesEvent, ValidationResult

__all__ = ["LiarsDiceEvent"]

FACE_NAMES = {1: "ones", 2: "twos", 3: "threes", 4: "fours", 5: "fives", 6: "sixes"}


class LiarsDiceEvent(MultiplayerSeriesEvent):
    """N-player Liar's Dice engine.

    Parameters
    ----------
    games_per_match : int
        Number of games to play in a match (default 1).
    num_players : int
        Number of players (2-10, default 4).
    starting_dice : int
        Dice per player at game start (default 5).
    """

    def __init__(
        self,
        games_per_match: int = 1,
        num_players: int = 4,
        starting_dice: int = 5,
        mode: str = "attrition",
    ) -> None:
        if mode not in ("attrition", "redistribution"):
            raise ValueError(f"Invalid mode '{mode}'. Must be 'attrition' or 'redistribution'.")
        super().__init__(games_per_match, num_players)
        self._starting_dice = starting_dice
        self._mode = mode

        # Per-game state
        self._dice: dict[str, list[int]] = {}
        self._dice_counts: dict[str, int] = {}
        self._round_number: int = 0
        self._turn_number: int = 0
        self._current_bid: dict | None = None
        self._bid_history: list[dict] = []
        self._turn_player_idx: int = 0
        self._wilds_active: bool = True
        self._eliminated: list[str] = []
        self._eliminated_set: set[str] = set()

        # Tracking
        self._round_history: list[dict] = []

        # Per-player bluff stats
        self._player_stats: dict[str, dict] = {
            p: {
                "total_bids": 0,
                "bluff_bids": 0,
                "challenges_made": 0,
                "challenges_won": 0,
                "dice_lost": 0,
            }
            for p in self._player_ids
        }

    def _forfeit_points_per_game(self) -> float:
        return float(self._num_players)

    def current_player(self) -> str:
        idx = self._turn_player_idx % len(self._player_ids)
        pid = self._player_ids[idx]
        # Safety: if pointing at an eliminated player, advance
        if pid in self._eliminated_set:
            self._turn_player_idx = idx
            self._advance_to_active_player()
            pid = self._player_ids[self._turn_player_idx]
        return pid

    def get_prompt(self, player_id: str) -> str:
        label = self._player_labels[player_id]
        my_dice = self._dice[player_id]
        active_players = self._active_players()
        total_dice = sum(self._dice_counts[p] for p in active_players)

        lines = [
            f"You are playing Liar's Dice with {self._num_players} players.",
            f"You are Player {label}.",
            "",
        ]

        if self._games_per_match > 1:
            lines.append(f"Game {self._game_number} of {self._games_per_match}.")
            score_parts = [f"{self._player_labels[p]}: {self._match_scores[p]:.0f}" for p in self._player_ids]
            lines.append(f"Match scores: {', '.join(score_parts)}")
            lines.append("")

        # Dice info
        lines.append(f"Round {self._round_number}")
        lines.append(f"Your dice: {my_dice}")
        lines.append(f"Total dice in play: {total_dice}")
        lines.append("")

        # Other players' dice counts
        lines.append("Dice counts:")
        for pid in self._player_ids:
            pl = self._player_labels[pid]
            if pid in self._eliminated_set:
                lines.append(f"  Player {pl}: ELIMINATED")
            elif pid == player_id:
                lines.append(f"  Player {pl}: {self._dice_counts[pid]} dice (you)")
            else:
                lines.append(f"  Player {pl}: {self._dice_counts[pid]} dice")
        lines.append("")

        # Wild ones rule
        if self._wilds_active:
            lines.append("WILD ONES: Dice showing 1 are wild and count toward any face value.")
        else:
            lines.append("WILDS OFF: The opening bid was on 1s, so wilds are disabled this round.")
        lines.append("")

        # Current bid
        if self._current_bid is None:
            lines.append("No bid yet this round — you must open with a bid.")
            lines.append("")
            lines.append("Your bid must specify a quantity and a face value (1-6).")
            lines.append(f"Quantity cannot exceed {total_dice} (total dice in play).")
            lines.append("")
            lines.append("Example: {\"action\": \"bid\", \"quantity\": 3, \"face\": 4, \"reasoning\": \"...\"}")
            lines.append("This means: \"I believe there are at least three 4s across all cups.\"")
        else:
            bid_q = self._current_bid["quantity"]
            bid_f = self._current_bid["face"]
            bidder_label = self._player_labels[self._current_bid["bidder"]]
            lines.append(f"Current bid: {bid_q} {FACE_NAMES[bid_f]} (by Player {bidder_label})")
            bid_prob = self.bid_probability(bid_q, bid_f, my_dice, total_dice, self._wilds_active)
            lines.append(f"Probability the current bid is true (from your perspective): {bid_prob:.0%}")
            lines.append("")

            # Bid history this round
            if self._bid_history:
                lines.append("Bid history this round:")
                for entry in self._bid_history:
                    bl = self._player_labels[entry["player"]]
                    lines.append(f"  Player {bl}: {entry['quantity']} {FACE_NAMES[entry['face']]}")
                lines.append("")

            # Legal actions
            lines.append("You may either RAISE the bid or CHALLENGE by calling \"liar\".")
            lines.append("")
            lines.append("To RAISE: your new bid must be strictly higher than the current bid.")
            if bid_f == 1:
                # Current bid is on 1s, raising to 2-6 requires quantity * 2 + 1
                min_same = bid_q + 1
                min_switch = bid_q * 2 + 1
                lines.append(f"  - Stay on 1s: quantity must be at least {min_same}")
                lines.append(f"  - Switch to 2-6: quantity must be at least {min_switch}")
            else:
                min_q_same_face = bid_q + 1
                min_q_higher_face = bid_q
                min_q_ones = math.ceil(bid_q / 2)
                lines.append(f"  - Same face ({bid_f}): quantity must be at least {min_q_same_face}")
                if bid_f < 6:
                    lines.append(f"  - Higher face ({bid_f+1}-6): quantity must be at least {min_q_higher_face}")
                lines.append(f"  - Switch to 1s: quantity must be at least {min_q_ones}")
            lines.append(f"  - Maximum quantity: {total_dice}")
            lines.append("")
            lines.append("To CHALLENGE: {\"action\": \"liar\", \"reasoning\": \"...\"}")
            if self._mode == "redistribution":
                lines.append("If the bid is wrong (actual count < bid), the bidder loses a die and YOU gain one.")
                lines.append("If the bid is correct (actual count >= bid), YOU lose a die and the bidder gains one.")
            else:
                lines.append("If the bid is wrong (actual count < bid), the bidder loses a die.")
                lines.append("If the bid is correct (actual count >= bid), YOU lose a die.")

        lines.append("")

        # Reasoning guidance
        lines.append("STRATEGY TIPS:")
        lines.append(f"- You have {len(my_dice)} dice. Consider what you know vs what's hidden.")
        if self._wilds_active:
            matching = sum(1 for d in my_dice if d == (self._current_bid["face"] if self._current_bid else 0))
            wilds = sum(1 for d in my_dice if d == 1)
            if self._current_bid:
                lines.append(f"- You have {matching} {FACE_NAMES[self._current_bid['face']]} and {wilds} wilds in your hand.")
            lines.append("- Each unknown die has ~1/3 chance of matching (1/6 for the face + 1/6 for wild).")
        else:
            lines.append("- Each unknown die has ~1/6 chance of matching (no wilds).")
        lines.append("- Think about whether the current bid is plausible given the total dice count.")
        lines.append("- Consider what your raise signals to other players.")
        if len(active_players) >= 6:
            lines.append("- In a large game, conservative play allows others to accumulate advantages. Consider when aggression is warranted.")
        if self._mode == "redistribution":
            lines.append("- REDISTRIBUTION MODE: Winning a challenge gains you a die. Challenges are high-reward, not just defensive.")
            lines.append("- A successful challenge grows your cup AND shrinks theirs — double swing.")
        lines.append("")

        # Eliminated players
        if self._eliminated:
            lines.append("Eliminated players:")
            for i, pid in enumerate(self._eliminated):
                lines.append(f"  {i+1}. Player {self._player_labels[pid]}")
            lines.append("")

        lines.append('Respond with ONLY a JSON object. Example: {"action": "bid", "quantity": 3, "face": 4, "reasoning": "..."} or {"action": "liar", "reasoning": "..."}')

        return "\n".join(lines)

    def get_retry_prompt(self, player_id: str, error_reason: str) -> str:
        return (
            f"Your last action was invalid: {error_reason}\n\n"
            f"{self.get_prompt(player_id)}"
        )

    def validate_action(self, player_id: str, action: dict) -> ValidationResult:
        act = action.get("action")
        active_players = self._active_players()
        total_dice = sum(self._dice_counts[p] for p in active_players)

        if act == "bid":
            quantity = action.get("quantity")
            face = action.get("face")

            if not isinstance(quantity, int) or quantity < 1:
                return ValidationResult(legal=False, reason="Quantity must be a positive integer.")
            if not isinstance(face, int) or face < 1 or face > 6:
                return ValidationResult(legal=False, reason="Face must be an integer from 1 to 6.")
            if quantity > total_dice:
                return ValidationResult(
                    legal=False,
                    reason=f"Quantity {quantity} exceeds total dice in play ({total_dice}).",
                )

            if self._current_bid is not None:
                if not self._is_valid_raise(self._current_bid, quantity, face):
                    cur = self._current_bid
                    return ValidationResult(
                        legal=False,
                        reason=(
                            f"Bid of {quantity} {FACE_NAMES[face]} does not raise the "
                            f"current bid of {cur['quantity']} {FACE_NAMES[cur['face']]}."
                        ),
                    )

            return ValidationResult(legal=True)

        elif act == "liar":
            if self._current_bid is None:
                return ValidationResult(
                    legal=False,
                    reason="Cannot challenge when no bid exists. You must open with a bid.",
                )
            return ValidationResult(legal=True)

        return ValidationResult(
            legal=False,
            reason=f"Unknown action '{act}'. Expected 'bid' or 'liar'.",
        )

    def apply_action(self, player_id: str, action: dict) -> None:
        act = action["action"]
        if act == "bid":
            self._do_bid(player_id, action["quantity"], action["face"])
        else:
            self._do_challenge(player_id)

    def forfeit_turn(self, player_id: str) -> None:
        if self._current_bid is None:
            # Must open — bid "one 2" (most conservative)
            self.apply_action(player_id, {"action": "bid", "quantity": 1, "face": 2})
        else:
            # Auto-raise by minimum: quantity + 1, same face
            cur = self._current_bid
            new_q = cur["quantity"] + 1
            new_f = cur["face"]

            # If that exceeds total dice, try switching faces
            active_players = self._active_players()
            total_dice = sum(self._dice_counts[p] for p in active_players)

            if new_q > total_dice:
                # Can't raise further — must challenge
                self.apply_action(player_id, {"action": "liar"})
                return

            # For 1s switching rules
            if new_f != 1 and self._is_valid_raise(cur, new_q, new_f):
                self.apply_action(player_id, {"action": "bid", "quantity": new_q, "face": new_f})
            elif self._is_valid_raise(cur, new_q, new_f):
                self.apply_action(player_id, {"action": "bid", "quantity": new_q, "face": new_f})
            else:
                # Fallback: just challenge
                self.apply_action(player_id, {"action": "liar"})

    def get_state_snapshot(self) -> dict:
        active_players = self._active_players()
        total_dice = sum(self._dice_counts[p] for p in active_players)

        snap: dict = {
            "mode": self._mode,
            "game_number": self._game_number,
            "games_per_match": self._games_per_match,
            "starting_dice": self._starting_dice,
            "round": self._round_number,
            "turn_number": self._turn_number,
            "total_dice": total_dice,
            "dice_counts": {p: self._dice_counts[p] for p in self._player_ids},
            "current_bid": dict(self._current_bid) if self._current_bid else None,
            "bid_history": [dict(b) for b in self._bid_history],
            "wilds_active": self._wilds_active,
            "eliminated": list(self._eliminated),
            "active_player": self.current_player() if not self._terminal else None,
            "all_dice": {p: list(self._dice[p]) for p in self._player_ids},
            "terminal": self._terminal,
            "match_scores": dict(self._match_scores),
            "player_stats": {p: dict(self._player_stats[p]) for p in self._player_ids},
            "round_history": [dict(r) for r in self._round_history[-10:]],
        }

        # Include challenge result if last action was a challenge
        if self._last_challenge_result is not None:
            snap["challenge_result"] = dict(self._last_challenge_result)

        return snap

    def eliminate_player(self, player_id: str) -> None:
        """Called by tournament engine for stuck-loop elimination."""
        if player_id not in self._eliminated_set:
            self._eliminated_set.add(player_id)
            self._eliminated.append(player_id)
            self._dice_counts[player_id] = 0
            self._dice[player_id] = []
            self._check_game_over()

    # ------------------------------------------------------------------
    # Game lifecycle
    # ------------------------------------------------------------------

    def _start_new_game(self) -> None:
        self._game_number += 1
        if self._game_number > self._games_per_match:
            self._terminal = True
            return

        self._dice_counts = {p: self._starting_dice for p in self._player_ids}
        self._dice = {p: [] for p in self._player_ids}
        self._eliminated = []
        self._eliminated_set = set()
        self._round_number = 0
        self._turn_number = 0
        self._round_history = []
        self._last_challenge_result: dict | None = None

        # Reset per-game stats
        for p in self._player_ids:
            self._player_stats[p] = {
                "total_bids": 0,
                "bluff_bids": 0,
                "challenges_made": 0,
                "challenges_won": 0,
                "dice_lost": 0,
            }

        self._start_new_round(starting_player_idx=0)

    def _start_new_round(self, starting_player_idx: int | None = None) -> None:
        """Roll dice for all active players and reset round state."""
        self._round_number += 1
        self._current_bid = None
        self._bid_history = []
        self._wilds_active = True
        # Note: _last_challenge_result is preserved across round transitions
        # so the spectator/telemetry can see it. It's cleared on next bid.

        # Roll dice for active players
        for pid in self._player_ids:
            if pid not in self._eliminated_set:
                self._dice[pid] = [self._rng.randint(1, 6) for _ in range(self._dice_counts[pid])]
            else:
                self._dice[pid] = []

        # Set starting player
        if starting_player_idx is not None:
            self._turn_player_idx = starting_player_idx
            # Make sure it's an active player
            self._advance_to_active_player()
        # else keep current

    def _advance_to_active_player(self) -> None:
        """Ensure turn_player_idx points to an active player."""
        for _ in range(self._num_players):
            pid = self._player_ids[self._turn_player_idx]
            if pid not in self._eliminated_set:
                return
            self._turn_player_idx = (self._turn_player_idx + 1) % self._num_players

    def _advance_turn(self) -> None:
        """Move to next active player clockwise."""
        for _ in range(self._num_players):
            self._turn_player_idx = (self._turn_player_idx + 1) % self._num_players
            pid = self._player_ids[self._turn_player_idx]
            if pid not in self._eliminated_set:
                return

    def _active_players(self) -> list[str]:
        return [p for p in self._player_ids if p not in self._eliminated_set]

    def _finish_game(self) -> None:
        """Score the game based on elimination order and start next."""
        # Players eliminated first get fewest points
        # Last standing gets most points
        active = self._active_players()

        # Build final order: eliminated first (in order), then remaining
        final_order = list(self._eliminated) + active

        # Award points: 1 for first eliminated, 2 for second, ..., N for last standing
        for i, pid in enumerate(final_order):
            self._match_scores[pid] += float(i + 1)

        self._start_new_game()

    def _check_game_over(self) -> None:
        """Check if only one player remains."""
        active = self._active_players()
        if len(active) <= 1:
            self._finish_game()

    # ------------------------------------------------------------------
    # Bid mechanics
    # ------------------------------------------------------------------

    def _is_valid_raise(self, current: dict, new_quantity: int, new_face: int) -> bool:
        """Check if a new bid is a valid raise over the current bid."""
        cur_q = current["quantity"]
        cur_f = current["face"]

        # Special rules for 1s (since wilds don't apply to 1s bids)
        if cur_f == 1 and new_face == 1:
            # Staying on 1s: must increase quantity
            return new_quantity > cur_q
        elif cur_f == 1 and new_face != 1:
            # Switching FROM 1s TO 2-6: need quantity * 2 + 1
            return new_quantity >= cur_q * 2 + 1
        elif cur_f != 1 and new_face == 1:
            # Switching FROM 2-6 TO 1s: need ceil(current_quantity / 2)
            min_q = math.ceil(cur_q / 2)
            return new_quantity >= min_q
        else:
            # Both are 2-6
            if new_face > cur_f:
                return new_quantity >= cur_q
            elif new_face == cur_f:
                return new_quantity > cur_q
            else:
                # Lower face: must increase quantity
                return new_quantity > cur_q

    def _count_face(self, face: int) -> int:
        """Count how many dice show the given face across all active players, including wilds."""
        count = 0
        for pid in self._active_players():
            for d in self._dice[pid]:
                if d == face:
                    count += 1
                elif d == 1 and self._wilds_active and face != 1:
                    count += 1
        return count

    def _do_bid(self, player_id: str, quantity: int, face: int) -> None:
        """Process a bid action."""
        self._last_challenge_result = None
        self._turn_number += 1

        # If this is the opening bid and it's on 1s, wilds are off
        if self._current_bid is None and face == 1:
            self._wilds_active = False

        # Track bluff stats
        actual_count = self._count_face(face)
        is_bluff = actual_count < quantity

        self._player_stats[player_id]["total_bids"] += 1
        if is_bluff:
            self._player_stats[player_id]["bluff_bids"] += 1

        self._current_bid = {"quantity": quantity, "face": face, "bidder": player_id}
        self._bid_history.append({
            "player": player_id,
            "quantity": quantity,
            "face": face,
            "actual_count": actual_count,
            "is_bluff": is_bluff,
        })

        self._advance_turn()

    def _do_challenge(self, challenger: str) -> None:
        """Process a 'liar' challenge."""
        self._turn_number += 1
        bid = self._current_bid
        if bid is None:
            raise RuntimeError("_do_challenge called with no current bid")
        bidder = bid["bidder"]
        bid_face = bid["face"]
        bid_quantity = bid["quantity"]

        actual_count = self._count_face(bid_face)

        # Count wilds separately for display
        wilds_counted = 0
        face_count = 0
        if self._wilds_active and bid_face != 1:
            for pid in self._active_players():
                for d in self._dice[pid]:
                    if d == bid_face:
                        face_count += 1
                    elif d == 1:
                        wilds_counted += 1
        else:
            face_count = actual_count

        bid_was_correct = actual_count >= bid_quantity

        # Determine loser and winner
        if bid_was_correct:
            loser = challenger
            winner = bidder
        else:
            loser = bidder
            winner = challenger

        # Loser loses a die
        self._dice_counts[loser] -= 1
        self._player_stats[loser]["dice_lost"] += 1

        # Redistribution: winner gains a die
        die_gained_by = None
        if self._mode == "redistribution":
            self._dice_counts[winner] += 1
            die_gained_by = winner

        # Track challenge stats
        self._player_stats[challenger]["challenges_made"] += 1
        if not bid_was_correct:
            self._player_stats[challenger]["challenges_won"] += 1

        # Check elimination
        eliminated = False
        if self._dice_counts[loser] <= 0:
            self._dice_counts[loser] = 0
            self._eliminated_set.add(loser)
            self._eliminated.append(loser)
            eliminated = True

        self._last_challenge_result = {
            "challenger": challenger,
            "bidder": bidder,
            "bid": {"quantity": bid_quantity, "face": bid_face},
            "actual_count": actual_count,
            "face_count": face_count,
            "wilds_counted": wilds_counted,
            "bid_was_correct": bid_was_correct,
            "loser": loser,
            "winner": winner,
            "die_lost_by": loser,
            "die_gained_by": die_gained_by,
            "eliminated": eliminated,
        }

        # Record round in history
        self._round_history.append({
            "round": self._round_number,
            "bids": [dict(b) for b in self._bid_history],
            "challenge": dict(self._last_challenge_result),
        })

        # Highlight dramatic moments
        self._highlight_turns.append(self._turn_number)

        # Check if game is over
        active = self._active_players()
        if len(active) <= 1:
            self._finish_game()
            return

        # Start new round — loser starts (if still in), else next clockwise
        if loser in self._eliminated_set:
            # Find next active player clockwise from loser's position
            loser_idx = self._player_ids.index(loser)
            self._turn_player_idx = loser_idx
            self._advance_turn()
        else:
            self._turn_player_idx = self._player_ids.index(loser)

        self._start_new_round(starting_player_idx=self._turn_player_idx)

    # ------------------------------------------------------------------
    # Probability helpers (for spectator/telemetry)
    # ------------------------------------------------------------------

    @staticmethod
    def bid_probability(
        bid_quantity: int,
        bid_face: int,
        own_dice: list[int],
        total_dice: int,
        wilds_active: bool,
    ) -> float:
        """Calculate P(bid is true) using binomial distribution.

        Each unknown die has:
        - 1/3 chance of matching if wilds active (1/6 for face + 1/6 for wild)
        - 1/6 chance if wilds off or bidding on 1s
        """
        # Count how many of bid_face (+ wilds) we already have
        known_count = 0
        for d in own_dice:
            if d == bid_face:
                known_count += 1
            elif d == 1 and wilds_active and bid_face != 1:
                known_count += 1

        needed = bid_quantity - known_count
        if needed <= 0:
            return 1.0

        unknown_dice = total_dice - len(own_dice)
        if unknown_dice <= 0:
            return 0.0

        # Probability each unknown die matches
        if wilds_active and bid_face != 1:
            p = 1 / 3  # face + wild
        else:
            p = 1 / 6  # just the face (no wilds, or bidding on 1s)

        # P(X >= needed) where X ~ Binomial(unknown_dice, p)
        # = 1 - P(X < needed) = 1 - sum(P(X = k) for k in 0..needed-1)
        prob_less = 0.0
        for k in range(needed):
            prob_less += _binom_pmf(k, unknown_dice, p)

        return 1.0 - prob_less


def _binom_pmf(k: int, n: int, p: float) -> float:
    """Binomial probability mass function."""
    if k < 0 or k > n:
        return 0.0
    coeff = math.comb(n, k)
    return coeff * (p ** k) * ((1 - p) ** (n - k))
