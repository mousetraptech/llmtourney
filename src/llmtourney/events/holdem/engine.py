"""Pot-limit heads-up Texas Hold'em engine.

Implements the Event ABC for a full heads-up Hold'em match:
- Pot-limit betting with correct min/max raise calculation
- Seat rotation (SB/dealer alternates each hand)
- Street transitions: PREFLOP -> FLOP -> TURN -> RIVER -> SHOWDOWN
- Showdown using the hand evaluator
- Hand-over-hand play for configurable number of hands
- Bust-out detection
- Highlight detection for interesting hands
"""

from __future__ import annotations

import random
from enum import Enum
from pathlib import Path

from llmtourney.events.base import Event, ValidationResult
from llmtourney.events.holdem.evaluator import Card, best_five, evaluate_hand
from llmtourney.core.schemas import load_schema

__all__ = ["HoldemEvent"]

# Standard 52-card deck as string representations
RANKS = "23456789TJQKA"
SUITS = "hdcs"
FULL_DECK = [f"{r}{s}" for r in RANKS for s in SUITS]


class Street(Enum):
    """Betting streets in Hold'em."""

    PREFLOP = "preflop"
    FLOP = "flop"
    TURN = "turn"
    RIVER = "river"
    SHOWDOWN = "showdown"


# Ordered street progression
_STREET_ORDER = [Street.PREFLOP, Street.FLOP, Street.TURN, Street.RIVER, Street.SHOWDOWN]


def _card_str_to_card(s: str) -> Card:
    """Convert a string like 'Ah' to a Card object."""
    return Card(rank=s[0], suit=s[1])


class HoldemEvent(Event):
    """Pot-limit heads-up Texas Hold'em match engine.

    Parameters
    ----------
    hands_per_match : int
        Number of hands to play before the match ends (default 100).
    starting_stack : int
        Starting chip count for each player (default 200).
    blinds : tuple[int, int]
        Small blind and big blind amounts (default (1, 2)).
    """

    def __init__(
        self,
        hands_per_match: int = 100,
        starting_stack: int = 200,
        blinds: tuple[int, int] = (1, 2),
    ) -> None:
        self._hands_per_match = hands_per_match
        self._starting_stack = starting_stack
        self._blinds = blinds

        # Load action schema
        schema_path = Path(__file__).parent / "schema.json"
        self._action_schema = load_schema(schema_path)

        # State initialized by reset()
        self._rng: random.Random | None = None
        self._stacks: dict[str, int] = {}
        self._hand_number: int = 0
        self._dealer: str = ""  # who is SB/dealer this hand
        self._terminal: bool = False

        # Per-hand state
        self._street: Street = Street.PREFLOP
        self._pot: int = 0
        self._hole_cards: dict[str, list[str]] = {}
        self._community: list[str] = []
        self._deck: list[str] = []
        self._deck_idx: int = 0

        # Betting state for current street
        self._bets: dict[str, int] = {}  # total chips bet this street per player
        self._invested: dict[str, int] = {}  # total chips invested this entire hand
        self._actions_this_street: list[tuple[str, str, int | None]] = []
        self._acted_this_street: set[str] = set()
        self._active_player: str = ""
        self._last_raise_size: int = 0
        self._hand_over: bool = False

        # Match tracking
        self._hand_history: list[dict] = []  # summary per hand
        self._pot_totals: list[int] = []  # pot sizes for highlight detection
        self._highlight_hands: list[int] = []

    # ------------------------------------------------------------------
    # Event ABC implementation
    # ------------------------------------------------------------------

    def reset(self, seed: int) -> None:
        """Initialize/reset the match state with the given seed."""
        self._rng = random.Random(seed)
        self._stacks = {
            "player_a": self._starting_stack,
            "player_b": self._starting_stack,
        }
        self._hand_number = 0
        self._dealer = "player_a"  # player_a is dealer/SB for hand 1
        self._terminal = False
        self._hand_history = []
        self._pot_totals = []
        self._highlight_hands = []

        self._start_new_hand()

    def current_player(self) -> str:
        """Return the player whose turn it is."""
        return self._active_player

    def get_prompt(self, player_id: str) -> str:
        """Generate the prompt for the given player."""
        opponent = self._opponent(player_id)
        label = "A" if player_id == "player_a" else "B"

        hole_str = " ".join(self._hole_cards.get(player_id, []))
        community_str = " ".join(self._community) if self._community else "none yet"

        # Build betting history for this street
        actions_str = self._format_actions()

        # Calculate legal action details
        call_cost = self._call_amount(player_id)
        min_raise, max_raise = self._raise_bounds(player_id)

        lines = [
            f"You are playing Pot-Limit Texas Hold'em. You are Player {label}.",
            "",
            "Match state:",
            f"- Hand {self._hand_number} of {self._hands_per_match}",
            f"- Your stack: {self._stacks[player_id]} chips | Opponent stack: {self._stacks[opponent]} chips",
            f"- Pot: {self._pot} chips",
            f"- Blinds: {self._blinds[0]}/{self._blinds[1]}",
            "",
            f"Your hole cards: {hole_str}",
            f"Community cards: {community_str}",
            f"Betting this street: {actions_str}",
            "",
            "Legal actions:",
            "- fold",
        ]

        if call_cost > 0:
            lines.append(f"- call (cost: {call_cost} chips)")
        else:
            lines.append("- call (check, cost: 0 chips)")

        if min_raise is not None and max_raise is not None:
            lines.append(f"- raise (min: {min_raise}, max: {max_raise} chips)")

        lines.extend([
            "",
            'Respond with a JSON object: {"action": "fold|call|raise", "amount": <int if raise>}',
        ])

        return "\n".join(lines)

    def get_retry_prompt(self, player_id: str, error_reason: str) -> str:
        """Generate a retry prompt explaining what went wrong."""
        return (
            f"Your last action was invalid: {error_reason}\n\n"
            f"{self.get_prompt(player_id)}"
        )

    def validate_action(self, player_id: str, action: dict) -> ValidationResult:
        """Check if an action is legal without modifying state."""
        act = action.get("action")
        if act not in ("fold", "call", "raise"):
            return ValidationResult(legal=False, reason=f"Unknown action: {act}")

        if player_id != self._active_player:
            return ValidationResult(legal=False, reason="Not your turn.")

        if act == "fold":
            return ValidationResult(legal=True)

        if act == "call":
            return ValidationResult(legal=True)

        # Raise validation
        amount = action.get("amount")
        if amount is None:
            return ValidationResult(legal=False, reason="Raise requires an amount.")

        if not isinstance(amount, int):
            return ValidationResult(legal=False, reason="Amount must be an integer.")

        min_raise, max_raise = self._raise_bounds(player_id)
        if min_raise is None:
            return ValidationResult(
                legal=False, reason="Cannot raise (insufficient stack or already all-in)."
            )

        if amount < min_raise:
            return ValidationResult(
                legal=False,
                reason=f"Raise amount {amount} is below minimum {min_raise}.",
            )

        if amount > max_raise:
            return ValidationResult(
                legal=False,
                reason=f"Raise amount {amount} exceeds pot limit maximum {max_raise}.",
            )

        return ValidationResult(legal=True)

    def apply_action(self, player_id: str, action: dict) -> None:
        """Apply a validated action to the game state."""
        act = action["action"]
        hand_before = self._hand_number

        if act == "fold":
            self._do_fold(player_id)
            return  # Fold resolves the hand immediately
        elif act == "call":
            self._do_call(player_id)
        elif act == "raise":
            self._do_raise(player_id, action["amount"])

        # Only check street completion if we're still in the same hand
        if self._hand_number == hand_before and not self._terminal:
            self._check_street_complete()

    def forfeit_turn(self, player_id: str) -> None:
        """Forfeit: check if free, otherwise fold."""
        call_cost = self._call_amount(player_id)
        if call_cost == 0:
            self.apply_action(player_id, {"action": "call"})
        else:
            self.apply_action(player_id, {"action": "fold"})

    def is_terminal(self) -> bool:
        """Return True if the match is over."""
        return self._terminal

    def get_scores(self) -> dict[str, float]:
        """Return final chip counts as scores."""
        return {
            "player_a": float(self._stacks["player_a"]),
            "player_b": float(self._stacks["player_b"]),
        }

    def get_state_snapshot(self) -> dict:
        """Return a serializable snapshot of current game state.

        The 'stacks' field reports each player's total chips (behind + invested
        in the current hand's pot) so that stacks always sum to the total chips
        in play.
        """
        reported_stacks = {
            pid: self._stacks[pid] + self._invested.get(pid, 0)
            for pid in ("player_a", "player_b")
        }
        return {
            "hand_number": self._hand_number,
            "street": self._street.value,
            "pot": self._pot,
            "stacks": reported_stacks,
            "community_cards": list(self._community),
            "dealer": self._dealer,
            "active_player": self._active_player,
            "terminal": self._terminal,
        }

    @property
    def action_schema(self) -> dict:
        """Return the JSON Schema for valid actions."""
        return self._action_schema

    def get_highlight_hands(self) -> list[int]:
        """Return list of hand numbers flagged as highlights."""
        return list(self._highlight_hands)

    # ------------------------------------------------------------------
    # Hand lifecycle
    # ------------------------------------------------------------------

    def _start_new_hand(self) -> None:
        """Set up a new hand: shuffle deck, post blinds, deal hole cards."""
        self._hand_number += 1

        # Check if match should be over
        if self._hand_number > self._hands_per_match:
            self._terminal = True
            return

        # Check for bust-out
        if self._stacks["player_a"] <= 0 or self._stacks["player_b"] <= 0:
            self._terminal = True
            return

        # Alternate dealer each hand (after hand 1)
        if self._hand_number > 1:
            self._dealer = self._opponent(self._dealer)

        # Shuffle deck
        self._deck = list(FULL_DECK)
        self._rng.shuffle(self._deck)
        self._deck_idx = 0

        # Reset per-hand state
        self._street = Street.PREFLOP
        self._pot = 0
        self._community = []
        self._hand_over = False
        self._actions_this_street = []
        self._acted_this_street = set()
        self._bets = {"player_a": 0, "player_b": 0}
        self._invested = {"player_a": 0, "player_b": 0}
        self._last_raise_size = self._blinds[1]  # big blind is the initial "raise"

        # Determine SB and BB
        sb_player = self._dealer  # In heads-up, dealer is SB
        bb_player = self._opponent(sb_player)

        # Post blinds (capped by stack)
        sb_amount = min(self._blinds[0], self._stacks[sb_player])
        bb_amount = min(self._blinds[1], self._stacks[bb_player])

        self._stacks[sb_player] -= sb_amount
        self._stacks[bb_player] -= bb_amount
        self._bets[sb_player] = sb_amount
        self._bets[bb_player] = bb_amount
        self._invested[sb_player] = sb_amount
        self._invested[bb_player] = bb_amount
        self._pot = sb_amount + bb_amount

        # Deal hole cards (2 each)
        self._hole_cards = {}
        self._hole_cards[sb_player] = [self._deal_card(), self._deal_card()]
        self._hole_cards[bb_player] = [self._deal_card(), self._deal_card()]

        # In heads-up, SB acts first preflop
        self._active_player = sb_player

        # If either player is all-in from blinds, run out the board
        if self._stacks[sb_player] == 0 or self._stacks[bb_player] == 0:
            self._run_out_board()

    def _deal_card(self) -> str:
        """Deal the next card from the deck."""
        card = self._deck[self._deck_idx]
        self._deck_idx += 1
        return card

    def _finish_hand(self, winner: str | None, pot: int) -> None:
        """Award pot to winner and start next hand.

        If winner is None, it's a split pot.
        """
        if winner is None:
            # Split pot
            half = pot // 2
            remainder = pot - 2 * half
            self._stacks["player_a"] += half
            self._stacks["player_b"] += half
            # Give remainder to the player who was BB (positional disadvantage)
            bb_player = self._opponent(self._dealer)
            self._stacks[bb_player] += remainder
        else:
            self._stacks[winner] += pot

        # Detect highlights
        self._pot_totals.append(pot)
        self._detect_highlights(winner, pot)

        self._pot = 0
        self._hand_over = True

        # Start next hand
        self._start_new_hand()

    def _run_out_board(self) -> None:
        """Deal remaining community cards when a player is all-in, then showdown."""
        # Deal remaining community cards
        while len(self._community) < 5:
            if len(self._community) == 0:
                # Burn and deal flop (3 cards)
                self._deal_card()  # burn
                self._community.append(self._deal_card())
                self._community.append(self._deal_card())
                self._community.append(self._deal_card())
            else:
                # Burn and deal one card (turn or river)
                self._deal_card()  # burn
                self._community.append(self._deal_card())

        self._street = Street.SHOWDOWN
        self._resolve_showdown()

    # ------------------------------------------------------------------
    # Betting actions
    # ------------------------------------------------------------------

    def _do_fold(self, player_id: str) -> None:
        """Player folds: opponent wins the pot."""
        self._actions_this_street.append((player_id, "fold", None))
        opponent = self._opponent(player_id)

        # Detect bluff success: fold after opponent raised on the river
        is_river_bluff = (
            self._street == Street.RIVER
            and any(
                p == opponent and a == "raise"
                for p, a, _ in self._actions_this_street
            )
        )
        if is_river_bluff:
            self._highlight_hands.append(self._hand_number)

        self._finish_hand(opponent, self._pot)

    def _do_call(self, player_id: str) -> None:
        """Player calls (or checks if no bet to match)."""
        call_amt = self._call_amount(player_id)

        # Cap by stack
        call_amt = min(call_amt, self._stacks[player_id])

        self._stacks[player_id] -= call_amt
        self._bets[player_id] += call_amt
        self._invested[player_id] += call_amt
        self._pot += call_amt

        self._actions_this_street.append((player_id, "call", call_amt))
        self._acted_this_street.add(player_id)

    def _do_raise(self, player_id: str, raise_to: int) -> None:
        """Player raises to the specified total bet for this street.

        raise_to is the total amount the player's bet is raised to for the street.
        """
        current_bet = self._bets[player_id]
        additional = raise_to - current_bet

        # Cap by stack
        additional = min(additional, self._stacks[player_id])
        actual_raise_to = current_bet + additional

        # Calculate raise increment (how much above the current bet to match)
        opponent = self._opponent(player_id)
        opponent_bet = self._bets[opponent]
        raise_increment = actual_raise_to - opponent_bet

        if raise_increment > 0:
            self._last_raise_size = raise_increment

        self._stacks[player_id] -= additional
        self._bets[player_id] = actual_raise_to
        self._invested[player_id] += additional
        self._pot += additional

        self._actions_this_street.append((player_id, "raise", actual_raise_to))
        self._acted_this_street.add(player_id)

        # After a raise, the opponent needs to act again
        # Reset acted set so opponent must respond
        self._acted_this_street = {player_id}

    # ------------------------------------------------------------------
    # Street transitions
    # ------------------------------------------------------------------

    def _check_street_complete(self) -> None:
        """Check if the current betting round is complete and advance."""
        # Both players must have acted at least once
        if len(self._acted_this_street) < 2:
            # Switch to other player
            self._active_player = self._opponent(self._active_player)
            return

        # Bets must be equal (or a player is all-in)
        bets_equal = self._bets["player_a"] == self._bets["player_b"]
        a_allin = self._stacks["player_a"] == 0
        b_allin = self._stacks["player_b"] == 0

        if bets_equal or a_allin or b_allin:
            # Street is complete
            if a_allin or b_allin:
                # Someone is all-in: run out the board
                self._run_out_board()
            else:
                self._advance_street()
        else:
            # Continue betting
            self._active_player = self._opponent(self._active_player)

    def _advance_street(self) -> None:
        """Move to the next street."""
        current_idx = _STREET_ORDER.index(self._street)
        next_street = _STREET_ORDER[current_idx + 1]

        # Reset street-level betting state
        self._bets = {"player_a": 0, "player_b": 0}
        self._actions_this_street = []
        self._acted_this_street = set()
        self._last_raise_size = self._blinds[1]  # reset min raise to BB

        self._street = next_street

        if next_street == Street.FLOP:
            # Burn and deal 3
            self._deal_card()  # burn
            self._community.append(self._deal_card())
            self._community.append(self._deal_card())
            self._community.append(self._deal_card())
        elif next_street in (Street.TURN, Street.RIVER):
            # Burn and deal 1
            self._deal_card()  # burn
            self._community.append(self._deal_card())
        elif next_street == Street.SHOWDOWN:
            self._resolve_showdown()
            return

        # Post-flop: BB acts first (BB is the non-dealer in heads-up)
        bb_player = self._opponent(self._dealer)
        self._active_player = bb_player

    def _resolve_showdown(self) -> None:
        """Evaluate both hands and award the pot."""
        community_cards = [_card_str_to_card(c) for c in self._community]

        hands = {}
        scores = {}
        for pid in ("player_a", "player_b"):
            hole = [_card_str_to_card(c) for c in self._hole_cards[pid]]
            all_cards = hole + community_cards
            best = best_five(all_cards)
            score = evaluate_hand(best)
            hands[pid] = best
            scores[pid] = score

        if scores["player_a"] > scores["player_b"]:
            winner = "player_a"
        elif scores["player_b"] > scores["player_a"]:
            winner = "player_b"
        else:
            winner = None  # split pot

        pot = self._pot

        # Detect all-in highlight
        if self._stacks["player_a"] == 0 or self._stacks["player_b"] == 0:
            if self._hand_number not in self._highlight_hands:
                self._highlight_hands.append(self._hand_number)

        self._finish_hand(winner, pot)

    # ------------------------------------------------------------------
    # Pot-limit math
    # ------------------------------------------------------------------

    def _call_amount(self, player_id: str) -> int:
        """How many chips the player needs to put in to call."""
        opponent = self._opponent(player_id)
        diff = self._bets[opponent] - self._bets[player_id]
        return max(0, min(diff, self._stacks[player_id]))

    def _raise_bounds(self, player_id: str) -> tuple[int | None, int | None]:
        """Calculate min and max raise-to amounts.

        Returns (min_raise_to, max_raise_to) or (None, None) if raising is not possible.

        The raise-to amount is the total bet for this street after the raise.
        """
        opponent = self._opponent(player_id)
        opponent_bet = self._bets[opponent]
        my_bet = self._bets[player_id]
        my_stack = self._stacks[player_id]

        call_amount = max(0, opponent_bet - my_bet)

        # Can't raise if we can't cover more than a call
        if my_stack <= call_amount:
            return None, None

        # Min raise-to: opponent's bet + last raise size (or BB)
        min_raise_increment = max(self._last_raise_size, self._blinds[1])
        min_raise_to = opponent_bet + min_raise_increment

        # Max raise (pot-limit):
        # pot_after_call = current pot + call_amount
        # max_raise_increment = pot_after_call
        # max_raise_to = opponent_bet + max_raise_increment
        #   (equivalently: call to match, then raise by the size of the pot)
        pot_after_call = self._pot + call_amount
        max_raise_to = opponent_bet + pot_after_call

        # Cap by player's stack (total they can put in this street)
        max_total_bet = my_bet + my_stack
        min_raise_to = min(min_raise_to, max_total_bet)
        max_raise_to = min(max_raise_to, max_total_bet)

        # If min raise is more than we can afford, it's an all-in shove
        if min_raise_to > max_raise_to:
            min_raise_to = max_raise_to

        # Must be able to at least beat a call
        if min_raise_to <= opponent_bet:
            return None, None

        return min_raise_to, max_raise_to

    # ------------------------------------------------------------------
    # Highlight detection
    # ------------------------------------------------------------------

    def _detect_highlights(self, winner: str | None, pot: int) -> None:
        """Flag hands as highlights based on criteria."""
        hand_num = self._hand_number

        # Already flagged (e.g. bluff or all-in)?
        if hand_num in self._highlight_hands:
            return

        # Big pot: pot > 3x average
        if len(self._pot_totals) >= 2:
            avg_pot = sum(self._pot_totals[:-1]) / len(self._pot_totals[:-1])
            if pot > 3 * avg_pot:
                self._highlight_hands.append(hand_num)
                return

        # Comeback: trailing player wins pot > 20% of total chips
        total_chips = self._starting_stack * 2
        if winner is not None:
            # Check if winner was trailing before winning
            winner_stack_before = self._stacks[winner] - pot
            opponent_stack_before = self._stacks[self._opponent(winner)] + pot
            if winner_stack_before < opponent_stack_before and pot > 0.2 * total_chips:
                self._highlight_hands.append(hand_num)
                return

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _opponent(player_id: str) -> str:
        """Return the opponent's player ID."""
        return "player_b" if player_id == "player_a" else "player_a"

    def _format_actions(self) -> str:
        """Format the actions taken this street as a readable string."""
        if not self._actions_this_street:
            return "none"
        parts = []
        for pid, act, amt in self._actions_this_street:
            label = "A" if pid == "player_a" else "B"
            if amt is not None and act == "raise":
                parts.append(f"Player {label} {act} to {amt}")
            elif amt is not None and act == "call" and amt > 0:
                parts.append(f"Player {label} {act} {amt}")
            else:
                parts.append(f"Player {label} {act}")
        return ", ".join(parts)
