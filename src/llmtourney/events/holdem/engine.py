"""Pot-limit Texas Hold'em engine (2-9 players).

Implements the Event ABC for a full Hold'em match:
- Pot-limit betting with correct min/max raise calculation
- Seat rotation with proper blind posting (heads-up and multi-way)
- Street transitions: PREFLOP -> FLOP -> TURN -> RIVER -> SHOWDOWN
- Side pot calculation and distribution for multi-way all-ins
- Showdown using the hand evaluator
- Hand-over-hand play for configurable number of hands
- Bust-out detection and elimination
- Highlight detection for interesting hands
"""

from __future__ import annotations

import random
import string
from dataclasses import dataclass
from enum import Enum

from llmtourney.events.base import Event, ValidationResult
from llmtourney.events.holdem.evaluator import Card, best_five, evaluate_hand

__all__ = ["HoldemEvent", "SidePot", "build_side_pots", "distribute_pots"]

# Standard 52-card deck as string representations
RANKS = "23456789TJQKA"
SUITS = "hdcs"
FULL_DECK = [f"{r}{s}" for r in RANKS for s in SUITS]


# ------------------------------------------------------------------
# Side pot calculation
# ------------------------------------------------------------------

@dataclass
class SidePot:
    """A pot with an amount and the set of players eligible to win it."""
    amount: int
    eligible: set[str]


def build_side_pots(invested: dict[str, int], folded: set[str]) -> list[SidePot]:
    """Build layered side pots from player investments.

    Each layer corresponds to a unique investment level. Players who invested
    at least that level contribute to the layer. Only non-folded contributors
    are eligible to win.

    Returns pots ordered from main pot (smallest investment level) to largest side pot.
    """
    if not invested:
        return []

    # Get sorted unique non-zero investment levels
    levels = sorted(set(v for v in invested.values() if v > 0))
    if not levels:
        return []

    pots: list[SidePot] = []
    prev_level = 0

    for level in levels:
        increment = level - prev_level
        if increment <= 0:
            continue

        # Count players who invested at or above this level
        contributors = [pid for pid, inv in invested.items() if inv >= level]
        amount = increment * len(contributors)

        # Eligible = contributors who haven't folded
        eligible = {pid for pid in contributors if pid not in folded}

        if amount > 0:
            pots.append(SidePot(amount=amount, eligible=eligible))

        prev_level = level

    return pots


def distribute_pots(side_pots: list[SidePot], hand_scores: dict[str, int]) -> dict[str, int]:
    """Distribute side pots to winners based on hand scores.

    For each pot, the eligible player(s) with the best (highest) score win.
    Ties split evenly; remainder chips go to the first tied player (positional).

    Returns {player_id: total_chips_won}.
    """
    winnings: dict[str, int] = {}

    for pot in side_pots:
        if not pot.eligible:
            continue

        # Find best score among eligible players
        eligible_scores = {pid: hand_scores[pid] for pid in pot.eligible if pid in hand_scores}
        if not eligible_scores:
            continue

        best_score = max(eligible_scores.values())
        winners = [pid for pid, score in eligible_scores.items() if score == best_score]

        share = pot.amount // len(winners)
        remainder = pot.amount - share * len(winners)

        for i, pid in enumerate(winners):
            won = share + (1 if i == 0 else 0) * remainder
            winnings[pid] = winnings.get(pid, 0) + won

    return winnings


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
    """Pot-limit Texas Hold'em match engine (2-9 players).

    Parameters
    ----------
    hands_per_match : int
        Number of hands to play before the match ends (default 100).
    starting_stack : int
        Starting chip count for each player (default 200).
    blinds : tuple[int, int]
        Small blind and big blind amounts (default (1, 2)).
    num_players : int
        Number of players, 2-9 (default 2 for backward compat).
    """

    def __init__(
        self,
        hands_per_match: int = 100,
        starting_stack: int = 200,
        blinds: tuple[int, int] = (1, 2),
        blind_schedule: list[tuple[int, int, int]] | None = None,
        num_players: int = 2,
    ) -> None:
        self._hands_per_match = hands_per_match
        self._starting_stack = starting_stack
        self._base_blinds = blinds
        self._blinds = blinds
        self._blind_schedule = blind_schedule  # [(hand, small, big), ...]
        self._num_players = num_players

        # Dynamic player IDs and labels
        self._player_ids = [f"player_{string.ascii_lowercase[i]}" for i in range(num_players)]
        self._player_labels = {pid: string.ascii_uppercase[i] for i, pid in enumerate(self._player_ids)}

        # Load action schema
        self._action_schema = self._load_event_schema()

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

        # N-player hand state
        self._folded: set[str] = set()
        self._busted: set[str] = set()
        self._dead_seats: set[str] = set()  # forfeit-eliminated, post blinds until broke
        self._all_in: set[str] = set()

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
        self._stacks = {pid: self._starting_stack for pid in self._player_ids}
        self._hand_number = 0
        self._dealer = self._player_ids[0]  # first player is dealer for hand 1
        self._terminal = False
        self._busted = set()
        self._dead_seats = set()
        self._hand_history = []
        self._pot_totals = []
        self._highlight_hands = []

        self._start_new_hand()

    def current_player(self) -> str:
        """Return the player whose turn it is."""
        return self._active_player

    def get_prompt(self, player_id: str) -> str:
        """Generate the prompt for the given player."""
        label = self._player_labels[player_id]

        hole_str = " ".join(self._hole_cards.get(player_id, []))
        community_str = " ".join(self._community) if self._community else "none yet"

        actions_str = self._format_actions()
        call_cost = self._call_amount(player_id)
        min_raise, max_raise = self._raise_bounds(player_id)

        n = len(self._active_players())
        intro = f"You are playing Pot-Limit Texas Hold'em with {n} players. You are Player {label}."

        # Build player stacks display
        stack_lines = []
        for pid in self._player_ids:
            plabel = self._player_labels[pid]
            stack = self._stacks[pid] + self._invested.get(pid, 0)
            if pid == player_id:
                status = "(you)"
            elif pid in self._busted:
                status = "(busted)"
            elif pid in self._dead_seats:
                status = "(eliminated)"
            elif pid in self._folded:
                status = "(folded)"
            elif pid in self._all_in:
                status = "(all-in)"
            else:
                status = ""
            stack_lines.append(f"  Player {plabel}: {stack} chips {status}".rstrip())

        lines = [
            intro,
            "",
            "Match state:",
            f"- Hand {self._hand_number} of {self._hands_per_match}",
            f"- Pot: {self._pot} chips",
            f"- Blinds: {self._blinds[0]}/{self._blinds[1]}",
            "- Stacks:",
        ]
        lines.extend(stack_lines)
        lines.extend([
            "",
            f"Your hole cards: {hole_str}",
            f"Community cards: {community_str}",
            f"Betting this street: {actions_str}",
            "",
            "Legal actions:",
            "- fold",
        ])

        if call_cost > 0:
            lines.append(f"- call (cost: {call_cost} chips)")
        else:
            lines.append("- call (check, cost: 0 chips)")

        if min_raise is not None and max_raise is not None:
            lines.append(f"- raise (min: {min_raise}, max: {max_raise} chips)")

        lines.extend([
            "",
            'Respond with ONLY a JSON object: {"reasoning": "<your thinking>", "action": "fold|call|raise", "amount": <int if raise>}',
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

    def get_scores(self) -> dict[str, float]:
        """Return final chip counts as scores."""
        return {pid: float(self._stacks[pid]) for pid in self._player_ids}

    def get_state_snapshot(self) -> dict:
        """Return a serializable snapshot of current game state.

        The 'stacks' field reports each player's total chips (behind + invested
        in the current hand's pot) so that stacks always sum to the total chips
        in play.
        """
        reported_stacks = {
            pid: self._stacks[pid] + self._invested.get(pid, 0)
            for pid in self._player_ids
        }
        return {
            "hand_number": self._hand_number,
            "street": self._street.value,
            "pot": self._pot,
            "stacks": reported_stacks,
            "community_cards": list(self._community),
            "hole_cards": {pid: list(self._hole_cards.get(pid, [])) for pid in self._player_ids},
            "dealer": self._dealer,
            "active_player": self._active_player,
            "terminal": self._terminal,
            "blinds": list(self._blinds),
            "num_players": self._num_players,
            "folded": sorted(self._folded),
            "all_in": sorted(self._all_in),
            "busted": sorted(self._busted),
            "dead_seats": sorted(self._dead_seats),
        }

    def award_forfeit_wins(self, forfeiting_player_id: str) -> None:
        """Award all chips to remaining players on forfeit."""
        if self._num_players == 2:
            # Backward compat: give everything to opponent
            opponent = self._opponent(forfeiting_player_id)
            total = sum(self._stacks.values()) + self._pot
            for pid in self._player_ids:
                self._stacks[pid] = 0
            self._stacks[opponent] = total
        else:
            # N-player: distribute forfeiter's chips equally among remaining active
            forfeiter_chips = self._stacks[forfeiting_player_id] + self._pot
            self._stacks[forfeiting_player_id] = 0
            remaining = [pid for pid in self._player_ids
                         if pid != forfeiting_player_id
                         and pid not in self._busted
                         and pid not in self._dead_seats]
            if remaining:
                share = forfeiter_chips // len(remaining)
                remainder = forfeiter_chips - share * len(remaining)
                for i, pid in enumerate(remaining):
                    self._stacks[pid] += share + (1 if i == 0 else 0) * remainder
        self._pot = 0
        self._terminal = True

    def eliminate_player(self, player_id: str) -> None:
        """Mark player as dead seat (forfeit-eliminated).

        Dead seats continue to post forced blinds until broke, then
        transition to busted. They never get dealt cards or act.
        Also immediately folds them in the current hand.
        """
        self._dead_seats.add(player_id)
        # Immediately fold in current hand so they don't act again
        self._folded.add(player_id)

    def get_highlight_hands(self) -> list[int]:
        """Return list of hand numbers flagged as highlights."""
        return list(self._highlight_hands)

    # ------------------------------------------------------------------
    # Hand lifecycle
    # ------------------------------------------------------------------

    def _resolve_blinds(self, hand_number: int) -> tuple[int, int]:
        """Return (small, big) blinds for the given hand number."""
        if not self._blind_schedule:
            return self._base_blinds
        # Find the highest schedule entry <= hand_number
        result = self._base_blinds
        for threshold, sb, bb in self._blind_schedule:
            if hand_number >= threshold:
                result = (sb, bb)
            else:
                break
        return result

    def _start_new_hand(self) -> None:
        """Set up a new hand: shuffle deck, post blinds, deal hole cards."""
        self._hand_number += 1

        # Clear previous hand's invested so snapshot stacks are accurate even at terminal
        self._invested = {pid: 0 for pid in self._player_ids}

        # Check if match should be over
        if self._hand_number > self._hands_per_match:
            self._terminal = True
            return

        # Mark busted players
        for pid in self._player_ids:
            if self._stacks[pid] <= 0 and pid not in self._busted:
                self._busted.add(pid)

        # Transition broke dead seats to busted
        for pid in list(self._dead_seats):
            if self._stacks[pid] <= 0:
                self._busted.add(pid)
                self._dead_seats.discard(pid)

        # Check for terminal: 1 or fewer active players
        active = self._active_players()
        if len(active) <= 1:
            self._terminal = True
            return

        # Rotate dealer (after hand 1), skipping busted and dead players
        if self._hand_number > 1:
            self._dealer = self._next_active_seat(self._dealer, in_hand=False)

        # Shuffle deck
        self._deck = list(FULL_DECK)
        self._rng.shuffle(self._deck)
        self._deck_idx = 0

        # Resolve blinds for this hand (escalation)
        self._blinds = self._resolve_blinds(self._hand_number)

        # Reset per-hand state
        self._street = Street.PREFLOP
        self._pot = 0
        self._community = []
        self._hand_over = False
        self._actions_this_street = []
        self._acted_this_street = set()
        self._folded = set()
        self._all_in = set()
        self._bets = {pid: 0 for pid in self._player_ids}
        self._invested = {pid: 0 for pid in self._player_ids}
        self._last_raise_size = self._blinds[1]  # big blind is the initial "raise"

        # Determine SB and BB — use _next_seat_for_blinds so dead seats post blinds
        if len(active) == 2 and not self._dead_seats:
            # Heads-up (no dead seats): dealer is SB
            sb_player = self._dealer
            bb_player = self._next_active_seat(sb_player, in_hand=False)
        else:
            # Multi-way (or heads-up with dead seats still bleeding):
            # SB is left of dealer, BB is left of SB — dead seats participate
            sb_player = self._next_seat_for_blinds(self._dealer)
            bb_player = self._next_seat_for_blinds(sb_player)

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

        # Track all-in from blinds
        if self._stacks[sb_player] == 0:
            self._all_in.add(sb_player)
        if self._stacks[bb_player] == 0:
            self._all_in.add(bb_player)

        # Auto-fold dead seats (they never act)
        for pid in self._dead_seats:
            if pid not in self._busted:
                self._folded.add(pid)

        # Deal hole cards to active players only (skip dead seats)
        self._hole_cards = {}
        for pid in active:
            self._hole_cards[pid] = [self._deal_card(), self._deal_card()]

        # Set first player to act
        self._active_player = self._first_to_act(Street.PREFLOP)

        # If all can-act players <= 1, run out the board
        can_act = self._can_act_players()
        if len(can_act) <= 1:
            self._run_out_board()

    def _deal_card(self) -> str:
        """Deal the next card from the deck."""
        card = self._deck[self._deck_idx]
        self._deck_idx += 1
        return card

    def _finish_hand_with_pots(self, fold_winner: str | None = None) -> None:
        """Resolve pot distribution and clean up.

        If fold_winner is set, all remaining pot goes to that player.
        Otherwise, use side pot distribution via showdown scores.
        """
        if fold_winner is not None:
            # Everyone folded to one player — they win the entire pot
            self._stacks[fold_winner] += self._pot
            pot = self._pot
            self._finish_hand_cleanup(pot, fold_winner)
        else:
            # Showdown with side pots
            community_cards = [_card_str_to_card(c) for c in self._community]
            in_hand = self._players_in_hand()

            hand_scores: dict[str, int] = {}
            for pid in in_hand:
                hole = [_card_str_to_card(c) for c in self._hole_cards[pid]]
                all_cards = hole + community_cards
                best = best_five(all_cards)
                score = evaluate_hand(best)
                hand_scores[pid] = score

            # Build and distribute side pots
            side_pots = build_side_pots(self._invested, self._folded)
            winnings = distribute_pots(side_pots, hand_scores)

            # Award winnings
            total_pot = self._pot
            for pid, amount in winnings.items():
                self._stacks[pid] += amount

            # Any unaccounted chips (rounding) — verify conservation
            distributed = sum(winnings.values())
            if distributed < total_pot:
                # Give remainder to first winner (positional)
                if winnings:
                    first_winner = next(iter(winnings))
                    self._stacks[first_winner] += total_pot - distributed

            # Determine "winner" for highlight detection (biggest winner)
            winner = max(winnings, key=winnings.get) if winnings else None

            # Detect all-in highlight
            if any(pid in self._all_in for pid in in_hand):
                if self._hand_number not in self._highlight_hands:
                    self._highlight_hands.append(self._hand_number)

            self._finish_hand_cleanup(total_pot, winner)

    def _finish_hand_cleanup(self, pot: int, winner: str | None) -> None:
        """Common cleanup after pot distribution."""
        self._pot_totals.append(pot)
        self._detect_highlights(winner, pot)

        self._pot = 0
        self._hand_over = True

        # Start next hand
        self._start_new_hand()

    def _run_out_board(self) -> None:
        """Deal remaining community cards when players are all-in, then showdown."""
        while len(self._community) < 5:
            if len(self._community) == 0:
                self._deal_card()  # burn
                self._community.append(self._deal_card())
                self._community.append(self._deal_card())
                self._community.append(self._deal_card())
            else:
                self._deal_card()  # burn
                self._community.append(self._deal_card())

        self._street = Street.SHOWDOWN
        self._resolve_showdown()

    # ------------------------------------------------------------------
    # Betting actions
    # ------------------------------------------------------------------

    def _do_fold(self, player_id: str) -> None:
        """Player folds."""
        self._actions_this_street.append((player_id, "fold", None))
        self._folded.add(player_id)

        # Detect bluff success: fold after someone raised on the river
        if self._street == Street.RIVER:
            raisers = {p for p, a, _ in self._actions_this_street if a == "raise"}
            if raisers - {player_id}:
                self._highlight_hands.append(self._hand_number)

        # If only 1 player remains, they win
        remaining = self._players_in_hand()
        if len(remaining) == 1:
            self._finish_hand_with_pots(fold_winner=remaining[0])

    def _do_call(self, player_id: str) -> None:
        """Player calls (or checks if no bet to match)."""
        call_amt = self._call_amount(player_id)
        call_amt = min(call_amt, self._stacks[player_id])

        self._stacks[player_id] -= call_amt
        self._bets[player_id] += call_amt
        self._invested[player_id] += call_amt
        self._pot += call_amt

        self._actions_this_street.append((player_id, "call", call_amt))
        self._acted_this_street.add(player_id)

        # Track all-in
        if self._stacks[player_id] == 0:
            self._all_in.add(player_id)

    def _do_raise(self, player_id: str, raise_to: int) -> None:
        """Player raises to the specified total bet for this street."""
        current_bet = self._bets[player_id]
        additional = raise_to - current_bet
        additional = min(additional, self._stacks[player_id])
        actual_raise_to = current_bet + additional

        # Calculate raise increment against max bet from all players
        max_bet = max(self._bets[pid] for pid in self._players_in_hand())
        raise_increment = actual_raise_to - max_bet

        if raise_increment > 0:
            self._last_raise_size = raise_increment

        self._stacks[player_id] -= additional
        self._bets[player_id] = actual_raise_to
        self._invested[player_id] += additional
        self._pot += additional

        self._actions_this_street.append((player_id, "raise", actual_raise_to))
        self._acted_this_street.add(player_id)

        # Track all-in
        if self._stacks[player_id] == 0:
            self._all_in.add(player_id)

        # After a raise, everyone else must re-act (except all-in players)
        self._acted_this_street = {player_id} | self._all_in

    # ------------------------------------------------------------------
    # Street transitions
    # ------------------------------------------------------------------

    def _check_street_complete(self) -> None:
        """Check if the current betting round is complete and advance."""
        can_act = self._can_act_players()

        # All players who can act must have acted
        if not all(pid in self._acted_this_street for pid in can_act):
            # Advance to next player who needs to act
            current = self._active_player
            for _ in range(len(self._player_ids)):
                candidate = self._next_active_seat(current, in_hand=True)
                if candidate in can_act and candidate not in self._acted_this_street:
                    self._active_player = candidate
                    return
                current = candidate
            # Fallback: shouldn't get here, but advance anyway
            self._active_player = self._next_active_seat(self._active_player, in_hand=True)
            return

        # All can-act players have acted. Check if bets are equal.
        in_hand_bets = [self._bets[pid] for pid in can_act]
        bets_equal = len(set(in_hand_bets)) <= 1

        has_all_in = len(self._all_in & set(self._players_in_hand())) > 0

        if bets_equal or len(can_act) == 0:
            # Street is complete
            if has_all_in or len(can_act) <= 1:
                self._run_out_board()
            else:
                self._advance_street()
        else:
            # Bets not equal — find next player who needs to match
            current = self._active_player
            for _ in range(len(self._player_ids)):
                candidate = self._next_active_seat(current, in_hand=True)
                if candidate in can_act:
                    self._active_player = candidate
                    return
                current = candidate

    def _advance_street(self) -> None:
        """Move to the next street."""
        current_idx = _STREET_ORDER.index(self._street)
        next_street = _STREET_ORDER[current_idx + 1]

        # Reset street-level betting state
        self._bets = {pid: 0 for pid in self._player_ids}
        self._actions_this_street = []
        self._acted_this_street = set()
        self._last_raise_size = self._blinds[1]

        self._street = next_street

        if next_street == Street.FLOP:
            self._deal_card()  # burn
            self._community.append(self._deal_card())
            self._community.append(self._deal_card())
            self._community.append(self._deal_card())
        elif next_street in (Street.TURN, Street.RIVER):
            self._deal_card()  # burn
            self._community.append(self._deal_card())
        elif next_street == Street.SHOWDOWN:
            self._resolve_showdown()
            return

        # Set first to act for this street
        self._active_player = self._first_to_act(next_street)

        # If only 0-1 players can still act, run out the board
        if len(self._can_act_players()) <= 1:
            self._run_out_board()

    def _resolve_showdown(self) -> None:
        """Evaluate hands and distribute pots."""
        self._finish_hand_with_pots()

    # ------------------------------------------------------------------
    # Pot-limit math
    # ------------------------------------------------------------------

    def _call_amount(self, player_id: str) -> int:
        """How many chips the player needs to put in to call."""
        in_hand = self._players_in_hand()
        if not in_hand:
            return 0
        max_bet = max(self._bets[pid] for pid in in_hand)
        diff = max_bet - self._bets[player_id]
        return max(0, min(diff, self._stacks[player_id]))

    def _raise_bounds(self, player_id: str) -> tuple[int | None, int | None]:
        """Calculate min and max raise-to amounts.

        Returns (min_raise_to, max_raise_to) or (None, None) if raising is not possible.
        """
        in_hand = self._players_in_hand()
        if not in_hand:
            return None, None

        max_bet = max(self._bets[pid] for pid in in_hand)
        my_bet = self._bets[player_id]
        my_stack = self._stacks[player_id]

        call_amount = max(0, max_bet - my_bet)

        # Can't raise if we can't cover more than a call
        if my_stack <= call_amount:
            return None, None

        # Min raise-to: current max bet + last raise size (or BB)
        min_raise_increment = max(self._last_raise_size, self._blinds[1])
        min_raise_to = max_bet + min_raise_increment

        # Max raise (pot-limit):
        pot_after_call = self._pot + call_amount
        max_raise_to = max_bet + pot_after_call

        # Cap by player's stack
        max_total_bet = my_bet + my_stack
        min_raise_to = min(min_raise_to, max_total_bet)
        max_raise_to = min(max_raise_to, max_total_bet)

        if min_raise_to > max_raise_to:
            min_raise_to = max_raise_to

        if min_raise_to <= max_bet:
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

        # Comeback: trailing player wins pot > 20% of total chips (2p only)
        total_chips = self._starting_stack * self._num_players
        if winner is not None and self._num_players == 2:
            winner_stack_before = self._stacks[winner] - pot
            opponent = self._opponent(winner)
            opponent_stack_before = self._stacks[opponent]
            if winner_stack_before < opponent_stack_before and pot > 0.2 * total_chips:
                self._highlight_hands.append(hand_num)
                return

    # ------------------------------------------------------------------
    # Seat rotation helpers
    # ------------------------------------------------------------------

    def _active_players(self) -> list[str]:
        """Return players not busted and not dead-seated, in seat order."""
        return [pid for pid in self._player_ids
                if pid not in self._busted and pid not in self._dead_seats]

    def _players_in_hand(self) -> list[str]:
        """Return players still in the current hand (not folded, not busted)."""
        return [pid for pid in self._player_ids
                if pid not in self._folded and pid not in self._busted]

    def _can_act_players(self) -> list[str]:
        """Return players who can still make decisions (not folded, not busted, not all-in)."""
        return [pid for pid in self._player_ids
                if pid not in self._folded and pid not in self._busted and pid not in self._all_in]

    def _next_active_seat(self, from_pid: str, in_hand: bool = True) -> str:
        """Return the next player clockwise from from_pid.

        If in_hand=True, skip folded and busted players.
        If in_hand=False, skip only busted players (for dealer rotation).
        """
        pool = self._players_in_hand() if in_hand else self._active_players()
        if not pool:
            return from_pid

        try:
            idx = self._player_ids.index(from_pid)
        except ValueError:
            return pool[0]

        # Walk clockwise through all seats
        n = len(self._player_ids)
        for offset in range(1, n + 1):
            candidate = self._player_ids[(idx + offset) % n]
            if candidate in pool:
                return candidate

        return from_pid

    def _next_seat_for_blinds(self, from_pid: str) -> str:
        """Return the next non-busted player clockwise (includes dead seats).

        Used only for SB/BB assignment so dead seats still post blinds.
        """
        pool = [p for p in self._player_ids if p not in self._busted]
        if not pool:
            return from_pid

        try:
            idx = self._player_ids.index(from_pid)
        except ValueError:
            return pool[0]

        n = len(self._player_ids)
        for offset in range(1, n + 1):
            candidate = self._player_ids[(idx + offset) % n]
            if candidate in pool:
                return candidate

        return from_pid

    def _first_to_act(self, street: Street) -> str:
        """Return the first player to act on a given street.

        Preflop 2-player: SB/dealer acts first.
        Preflop 3+: UTG (first player left of BB).
        Postflop: first active player left of dealer.
        """
        active = self._can_act_players()
        if not active:
            return self._players_in_hand()[0] if self._players_in_hand() else self._active_players()[0]

        if street == Street.PREFLOP:
            if len(self._active_players()) == 2:
                # Heads-up: SB/dealer acts first preflop
                return self._dealer
            else:
                # Multi-way: UTG = left of BB
                bb = self._next_active_seat(self._dealer, in_hand=False)  # SB
                bb = self._next_active_seat(bb, in_hand=False)  # BB
                return self._next_active_seat(bb, in_hand=True)
        else:
            # Postflop: first active player left of dealer
            return self._next_active_seat(self._dealer, in_hand=True)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _opponent(player_id: str) -> str:
        """Return the opponent's player ID (backward compat for 2-player)."""
        return "player_b" if player_id == "player_a" else "player_a"

    def _format_actions(self) -> str:
        """Format the actions taken this street as a readable string."""
        if not self._actions_this_street:
            return "none"
        parts = []
        for pid, act, amt in self._actions_this_street:
            label = self._player_labels.get(pid, pid)
            if amt is not None and act == "raise":
                parts.append(f"Player {label} {act} to {amt}")
            elif amt is not None and act == "call" and amt > 0:
                parts.append(f"Player {label} {act} {amt}")
            else:
                parts.append(f"Player {label} {act}")
        return ", ".join(parts)
