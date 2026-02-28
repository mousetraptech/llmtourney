"""Bullshit (Cheat / I Doubt It) — N-player card game engine.

A bluffing card game where players take turns placing cards face-down,
claiming they match the current target rank. Other players may challenge
("call bullshit"). If the challenge is correct the liar picks up the
discard pile; if wrong the challenger does. First to empty their hand wins.

Supports 3-10 players (default 4). Uses 1 deck for <=6 players, 2 for 7+.
"""

from __future__ import annotations

from enum import Enum

from llmtourney.events.base import MultiplayerSeriesEvent, ValidationResult

__all__ = ["BullshitEvent"]

RANKS = ["A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K"]
SUITS = ["♠", "♥", "♦", "♣"]
FULL_DECK = [f"{r}{s}" for r in RANKS for s in SUITS]
PLAYER_IDS = ["player_a", "player_b", "player_c", "player_d"]
PLAYER_LABELS = {"player_a": "A", "player_b": "B", "player_c": "C", "player_d": "D"}

RANK_NAMES = {
    "A": "Aces", "2": "Twos", "3": "Threes", "4": "Fours",
    "5": "Fives", "6": "Sixes", "7": "Sevens", "8": "Eights",
    "9": "Nines", "10": "Tens", "J": "Jacks", "Q": "Queens", "K": "Kings",
}


def _card_rank(card: str) -> str:
    """Extract rank from a card string like 'A♠' or '10♥'."""
    return card[:-1]


class Phase(Enum):
    PLAY = "play"
    CHALLENGE = "challenge"


class BullshitEvent(MultiplayerSeriesEvent):
    """N-player Bullshit card game engine.

    Parameters
    ----------
    games_per_match : int
        Number of games to play in a match (default 1 for standalone).
    num_players : int
        Number of players (3-10, default 4).
    """

    def __init__(self, games_per_match: int = 1, num_players: int = 4) -> None:
        super().__init__(games_per_match, num_players)

        # Per-game state
        self._hands: dict[str, list[str]] = {}
        self._discard_pile: list[str] = []
        self._target_rank_idx: int = 0
        self._turn_player_idx: int = 0
        self._phase: Phase = Phase.PLAY
        self._challenge_idx: int = 0
        self._challengers: list[str] = []

        # Last play info (for challenge resolution)
        self._last_play_player: str = ""
        self._last_play_cards: list[str] = []
        self._last_play_count: int = 0
        self._last_play_rank: str = ""

        # Tracking
        self._turn_number: int = 0
        self._history: list[dict] = []
        self._finish_order: list[str] = []
        self._eliminated: set[str] = set()

        # Per-player deception stats
        self._player_stats: dict[str, dict] = {
            p: {
                "lie_count": 0,
                "truth_count": 0,
                "times_caught": 0,
                "times_called_bs": 0,
                "correct_calls": 0,
            }
            for p in self._player_ids
        }

    def current_player(self) -> str:
        if self._phase == Phase.PLAY:
            return self._player_ids[self._turn_player_idx]
        else:
            return self._challengers[self._challenge_idx]

    def get_prompt(self, player_id: str) -> str:
        label = self._player_labels[player_id]
        hand = self._hands[player_id]
        target_rank = RANKS[self._target_rank_idx]

        lines = [
            f"You are playing Bullshit (a.k.a. Cheat / I Doubt It) with {self._num_players} players.",
            f"You are Player {label}.",
            "",
        ]

        if self._games_per_match > 1:
            lines.append(f"Game {self._game_number} of {self._games_per_match}.")
            score_parts = []
            for pid in self._player_ids:
                pl = self._player_labels[pid]
                score_parts.append(f"{pl}: {self._match_scores[pid]:.0f}")
            lines.append(f"Match scores: {', '.join(score_parts)}")
            lines.append("")

        # Card counts
        lines.append("Card counts:")
        for pid in self._player_ids:
            pl = self._player_labels[pid]
            n = len(self._hands[pid])
            marker = " (you)" if pid == player_id else ""
            if pid in self._eliminated:
                lines.append(f"  Player {pl}: OUT (0 cards)")
            else:
                lines.append(f"  Player {pl}: {n} cards{marker}")

        lines.append(f"Discard pile: {len(self._discard_pile)} cards")
        lines.append("")

        # Your hand
        sorted_hand = sorted(hand, key=lambda c: (RANKS.index(_card_rank(c)), c[-1]))
        hand_display = ", ".join(f"[{i}] {c}" for i, c in enumerate(sorted_hand))
        # Store sorted order so card indices match what the player sees
        lines.append(f"Your hand ({len(hand)} cards): {hand_display}")
        lines.append("")

        if self._phase == Phase.PLAY:
            lines.append(f"TARGET RANK THIS TURN: {target_rank} ({RANK_NAMES[target_rank]})")
            lines.append("")
            lines.append("It is your turn to play. Place 1-4 cards face-down from your hand.")
            lines.append(f"You MUST claim they are {RANK_NAMES[target_rank]}.")
            lines.append("The cards you play do NOT have to actually be that rank — you can bluff.")
            lines.append("")
            lines.append("Your action: select card indices from your hand.")
            lines.append('Respond with ONLY a JSON object: {"reasoning": "...", "action": "play", "cards": [indices]}')
            lines.append(f"Card indices are 0 to {len(hand) - 1} as shown above.")
        else:
            # Challenge phase
            last = self._history[-1] if self._history else None
            if last:
                who = self._player_labels[last["player"]]
                lines.append(
                    f"Player {who} just played {last['claim_count']} card(s) "
                    f"claiming {RANK_NAMES[last['claim_rank']]}."
                )
            lines.append("")
            lines.append("Do you want to call BULLSHIT or pass?")
            lines.append("If you call and they lied, THEY pick up the discard pile.")
            lines.append("If you call and they told the truth, YOU pick up the discard pile.")
            lines.append("")
            lines.append('Respond with ONLY a JSON object: {"reasoning": "...", "action": "call"} or {"reasoning": "...", "action": "pass"}')

        # Recent history
        if self._history:
            lines.append("")
            lines.append("Recent plays:")
            for entry in self._history[-8:]:
                who = self._player_labels[entry["player"]]
                result = ""
                if entry.get("challenge_by"):
                    challenger = self._player_labels[entry["challenge_by"]]
                    if entry["was_bluff"]:
                        result = f" → called by {challenger}, WAS BLUFF! {self._player_labels[entry['player']]} picks up pile"
                    else:
                        result = f" → called by {challenger}, was TRUTHFUL! {challenger} picks up pile"
                lines.append(
                    f"  Turn {entry['turn']}: Player {who} played "
                    f"{entry['claim_count']} {RANK_NAMES[entry['claim_rank']]}{result}"
                )

        return "\n".join(lines)

    def get_retry_prompt(self, player_id: str, error_reason: str) -> str:
        return (
            f"Your last action was invalid: {error_reason}\n\n"
            f"{self.get_prompt(player_id)}"
        )

    def validate_action(self, player_id: str, action: dict) -> ValidationResult:
        act = action.get("action")

        if self._phase == Phase.PLAY:
            if act != "play":
                return ValidationResult(
                    legal=False,
                    reason=f"Expected 'play' action during play phase, got '{act}'.",
                )
            cards = action.get("cards")
            if not isinstance(cards, list):
                return ValidationResult(legal=False, reason="'cards' must be a list of indices.")
            if len(cards) < 1 or len(cards) > 4:
                return ValidationResult(legal=False, reason="Must play 1-4 cards.")
            hand = self._hands[player_id]
            # Sort hand same way as displayed in prompt
            sorted_hand = sorted(hand, key=lambda c: (RANKS.index(_card_rank(c)), c[-1]))
            for idx in cards:
                if not isinstance(idx, int) or idx < 0 or idx >= len(sorted_hand):
                    return ValidationResult(
                        legal=False,
                        reason=f"Card index {idx} is out of range (0-{len(sorted_hand)-1}).",
                    )
            if len(set(cards)) != len(cards):
                return ValidationResult(legal=False, reason="Duplicate card indices.")
            return ValidationResult(legal=True)

        elif self._phase == Phase.CHALLENGE:
            if act not in ("call", "pass"):
                return ValidationResult(
                    legal=False,
                    reason=f"Expected 'call' or 'pass' during challenge phase, got '{act}'.",
                )
            return ValidationResult(legal=True)

        return ValidationResult(legal=False, reason="Unknown game phase.")

    def apply_action(self, player_id: str, action: dict) -> None:
        if self._phase == Phase.PLAY:
            self._do_play(player_id, action["cards"])
        else:
            self._do_challenge_response(player_id, action["action"])

    def forfeit_turn(self, player_id: str) -> None:
        if self._phase == Phase.PLAY:
            hand = self._hands[player_id]
            sorted_hand = sorted(hand, key=lambda c: (RANKS.index(_card_rank(c)), c[-1]))
            target = RANKS[self._target_rank_idx]
            # Try to play 1 truthful card
            for i, c in enumerate(sorted_hand):
                if _card_rank(c) == target:
                    self.apply_action(player_id, {"action": "play", "cards": [i]})
                    return
            # No truthful card — play index 0
            self.apply_action(player_id, {"action": "play", "cards": [0]})
        else:
            self.apply_action(player_id, {"action": "pass"})

    def get_state_snapshot(self) -> dict:
        return {
            "game_number": self._game_number,
            "games_per_match": self._games_per_match,
            "turn_number": self._turn_number,
            "phase": self._phase.value,
            "target_rank": RANKS[self._target_rank_idx],
            "current_player": self.current_player(),
            "card_counts": {p: len(self._hands[p]) for p in self._player_ids},
            "discard_pile_size": len(self._discard_pile),
            "discard_pile": list(self._discard_pile),
            "hands": {p: list(self._hands[p]) for p in self._player_ids},
            "last_play": {
                "player": self._last_play_player,
                "cards": list(self._last_play_cards),
                "claim_count": self._last_play_count,
                "claim_rank": self._last_play_rank,
            } if self._last_play_player else None,
            "history": [dict(h) for h in self._history],
            "finish_order": list(self._finish_order),
            "eliminated": list(self._eliminated),
            "terminal": self._terminal,
            "match_scores": dict(self._match_scores),
            "player_stats": {p: dict(self._player_stats[p]) for p in self._player_ids},
        }

    # ------------------------------------------------------------------
    # Game lifecycle
    # ------------------------------------------------------------------

    def _start_new_game(self) -> None:
        self._game_number += 1
        if self._game_number > self._games_per_match:
            self._terminal = True
            return

        # Use 1 deck for <=6 players, 2 decks for 7+
        deck = list(FULL_DECK) if self._num_players <= 6 else list(FULL_DECK) * 2
        self._rng.shuffle(deck)

        self._hands = {p: [] for p in self._player_ids}
        for i, card in enumerate(deck):
            self._hands[self._player_ids[i % self._num_players]].append(card)

        self._discard_pile = []
        self._target_rank_idx = 0  # start with Aces
        self._turn_player_idx = 0  # player_a starts
        self._phase = Phase.PLAY
        self._turn_number = 0
        self._history = []
        self._finish_order = []
        self._eliminated = set()
        self._last_play_player = ""
        self._last_play_cards = []
        self._last_play_count = 0
        self._last_play_rank = ""

        # Reset per-game deception stats
        for p in self._player_ids:
            self._player_stats[p] = {
                "lie_count": 0,
                "truth_count": 0,
                "times_caught": 0,
                "times_called_bs": 0,
                "correct_calls": 0,
            }

    def _finish_game(self) -> None:
        """Score the game and start the next one."""
        # Players not yet in finish_order still have cards — rank by fewest cards
        remaining = [p for p in self._player_ids if p not in self._finish_order]
        remaining.sort(key=lambda p: len(self._hands[p]))
        final_order = list(self._finish_order) + remaining

        # N-1 points for 1st, N-2 for 2nd, ..., 0 for last
        points = [float(self._num_players - 1 - i) for i in range(self._num_players)]
        for i, pid in enumerate(final_order):
            self._match_scores[pid] += points[i]

        self._start_new_game()

    def _advance_turn(self) -> None:
        """Move to the next active player's turn and advance target rank."""
        self._target_rank_idx = (self._target_rank_idx + 1) % len(RANKS)
        # Find next player who still has cards
        for _ in range(self._num_players):
            self._turn_player_idx = (self._turn_player_idx + 1) % self._num_players
            pid = self._player_ids[self._turn_player_idx]
            if pid not in self._eliminated:
                break
        self._phase = Phase.PLAY
        self._turn_number += 1

    # ------------------------------------------------------------------
    # Play phase
    # ------------------------------------------------------------------

    def _do_play(self, player_id: str, card_indices: list[int]) -> None:
        hand = self._hands[player_id]
        sorted_hand = sorted(hand, key=lambda c: (RANKS.index(_card_rank(c)), c[-1]))
        target_rank = RANKS[self._target_rank_idx]

        # Resolve indices to actual cards
        cards = [sorted_hand[i] for i in card_indices]

        # Remove cards from hand
        for card in cards:
            self._hands[player_id].remove(card)

        # Add to discard pile (face-down)
        self._discard_pile.extend(cards)

        self._last_play_player = player_id
        self._last_play_cards = cards
        self._last_play_count = len(cards)
        self._last_play_rank = target_rank
        self._turn_number += 1

        # Check if all played cards actually match the declared rank
        was_truthful = all(_card_rank(c) == target_rank for c in cards)

        # Track deception stats
        if was_truthful:
            self._player_stats[player_id]["truth_count"] += 1
        else:
            self._player_stats[player_id]["lie_count"] += 1

        # Record in history
        self._history.append({
            "turn": self._turn_number,
            "player": player_id,
            "claim_count": len(cards),
            "claim_rank": target_rank,
            "actual_cards": list(cards),  # for telemetry
            "was_truthful": was_truthful,
            # These get filled in during challenge phase
            "challenge_by": None,
            "was_bluff": None,
        })

        # Highlight: playing all 4 of a rank truthfully
        if was_truthful and len(cards) == 4:
            self._highlight_turns.append(self._turn_number)
        # Highlight: big bluff (3-4 cards, none matching)
        if not was_truthful and len(cards) >= 3 and not any(_card_rank(c) == target_rank for c in cards):
            self._highlight_turns.append(self._turn_number)

        # Check if player emptied their hand
        if len(self._hands[player_id]) == 0:
            # Other players get to challenge this last play before they win
            pass

        # Enter challenge phase
        self._challengers = [
            p for p in self._player_ids
            if p != player_id and p not in self._eliminated
        ]
        if not self._challengers:
            # No one to challenge — resolve immediately
            self._resolve_no_challenge()
        else:
            self._phase = Phase.CHALLENGE
            self._challenge_idx = 0

    # ------------------------------------------------------------------
    # Challenge phase
    # ------------------------------------------------------------------

    def _do_challenge_response(self, player_id: str, action: str) -> None:
        if action == "call":
            self._resolve_challenge(player_id)
        else:
            # Pass — next challenger
            self._challenge_idx += 1
            if self._challenge_idx >= len(self._challengers):
                # Everyone passed
                self._resolve_no_challenge()

    def _resolve_challenge(self, caller: str) -> None:
        """Resolve a bullshit call."""
        liar = self._last_play_player
        target = self._last_play_rank
        cards = self._last_play_cards
        was_bluff = not all(_card_rank(c) == target for c in cards)

        # Update history
        if self._history:
            self._history[-1]["challenge_by"] = caller
            self._history[-1]["was_bluff"] = was_bluff

        # Track challenge stats
        self._player_stats[caller]["times_called_bs"] += 1
        if was_bluff:
            self._player_stats[caller]["correct_calls"] += 1
            self._player_stats[liar]["times_caught"] += 1

        # Highlight: successful calls and caught big bluffs
        self._highlight_turns.append(self._turn_number)

        if was_bluff:
            # Liar picks up the entire discard pile
            self._hands[liar].extend(self._discard_pile)
            self._discard_pile = []
            # If liar had emptied their hand, they're back in
            self._eliminated.discard(liar)
            if liar in self._finish_order:
                self._finish_order.remove(liar)
        else:
            # Caller picks up the entire discard pile
            self._hands[caller].extend(self._discard_pile)
            self._discard_pile = []

        # Check if the play-maker emptied their hand and wasn't caught
        # (This can't happen here since was_bluff means they got cards back,
        #  and if truthful the caller got the pile. But the player who played
        #  might still be at 0 cards if they were truthful.)
        self._check_empty_hand(liar)

        self._advance_turn()

    def _resolve_no_challenge(self) -> None:
        """No one challenged — play stands."""
        player = self._last_play_player
        self._check_empty_hand(player)
        self._advance_turn()

    def _check_empty_hand(self, player_id: str) -> None:
        """Check if a player has emptied their hand and handle it."""
        if len(self._hands[player_id]) == 0 and player_id not in self._eliminated:
            self._eliminated.add(player_id)
            self._finish_order.append(player_id)

            # End when <=2 remain — 2-player BS is degenerate
            active = [p for p in self._player_ids if p not in self._eliminated]
            if len(active) <= 2:
                # Rank remaining by fewest cards (tie for last)
                active.sort(key=lambda p: len(self._hands[p]))
                for p in active:
                    self._finish_order.append(p)
                self._finish_game()
