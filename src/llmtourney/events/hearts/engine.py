"""Hearts engine — 4-player trick-avoidance card game.

Free-for-all: no teams, no trump. Players avoid taking hearts (1pt each)
and Queen of Spades (13pts). Shooting the Moon inverts scoring.
"""

from __future__ import annotations

from enum import Enum

from llmtourney.events.base import MultiplayerSeriesEvent, ValidationResult

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

RANKS = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A"]
RANK_ORDER = {r: i for i, r in enumerate(RANKS)}  # 2=0 .. A=12
SUITS = ["♣", "♦", "♥", "♠"]
SUIT_SYMBOLS = set(SUITS)
FULL_DECK = [f"{r}{s}" for s in SUITS for r in RANKS]

TARGET_SCORE = 100
HAND_LIMIT = 20

QUEEN_OF_SPADES = "Q♠"
TWO_OF_CLUBS = "2♣"

PASS_DIRECTIONS = ["left", "right", "across", "none"]

PLAY_ORDER = ["player_a", "player_b", "player_c", "player_d"]


def _card_suit(card: str) -> str:
    return card[-1]


def _card_rank(card: str) -> str:
    return card[:-1]


def _card_rank_value(card: str) -> int:
    return RANK_ORDER[_card_rank(card)]


def _sort_hand(hand: list[str]) -> list[str]:
    """Sort hand by suit (♣ ♦ ♥ ♠) then rank within suit."""
    suit_order = {s: i for i, s in enumerate(SUITS)}
    return sorted(hand, key=lambda c: (suit_order[_card_suit(c)], _card_rank_value(c)))


def _trick_winner(trick_cards: list[dict], led_suit: str) -> str:
    """Highest card of led suit wins. No trump in Hearts."""
    best_player = None
    best_rank = -1
    for entry in trick_cards:
        if _card_suit(entry["card"]) == led_suit:
            rank = _card_rank_value(entry["card"])
            if rank > best_rank:
                best_player = entry["player"]
                best_rank = rank
    return best_player


def _penalty_points(card: str) -> int:
    """Return penalty points for a card."""
    if _card_suit(card) == "♥":
        return 1
    if card == QUEEN_OF_SPADES:
        return 13
    return 0


def _pass_targets(direction: str) -> dict[int, int]:
    """Map passer index → receiver index for given direction."""
    if direction == "left":
        return {0: 1, 1: 2, 2: 3, 3: 0}
    elif direction == "right":
        return {0: 3, 1: 0, 2: 1, 3: 2}
    elif direction == "across":
        return {0: 2, 1: 3, 2: 0, 3: 1}
    else:  # "none"
        return {}


class Phase(Enum):
    PASS = "pass"
    PLAY = "play"


class HeartsEvent(MultiplayerSeriesEvent):
    """4-player Hearts — trick-avoidance card game."""

    def __init__(
        self,
        games_per_match: int = 1,
        num_players: int = 4,
        mode: str = "standard",
        target_score: int = TARGET_SCORE,
        hand_limit: int = HAND_LIMIT,
    ) -> None:
        super().__init__(games_per_match=games_per_match, num_players=num_players)
        self._mode = mode
        self._target_score = target_score
        self._hand_limit = hand_limit

        self._phase: Phase = Phase.PASS
        self._hand_number: int = 0
        self._trick_number: int = 0
        self._turn_number: int = 0
        self._dealer_idx: int = -1

        self._hands: dict[str, list[str]] = {}

        # Pass phase state
        self._pass_direction: str = "left"
        self._passed_cards: dict[str, list[str]] = {}
        self._received_cards: dict[str, list[str]] = {}
        self._pass_collect_idx: int = 0

        # Play phase state
        self._current_trick: list[dict] = []
        self._trick_leader: str = "player_a"
        self._trick_play_idx: int = 0
        self._hearts_broken: bool = False

        # Per-hand scoring
        self._penalty_this_hand: dict[str, int] = {}
        self._queen_taken_by: str | None = None

        # Game-level cumulative scores (penalty points — lower is better)
        self._game_scores: dict[str, int] = {}

        self._trick_history: list[dict] = []
        self._hand_history: list[dict] = []
        self._highlight_turns: list[int] = []

    @property
    def display_name(self) -> str:
        return "Hearts"

    # ------------------------------------------------------------------
    # Game lifecycle
    # ------------------------------------------------------------------

    def _start_new_game(self) -> None:
        self._game_number += 1
        if self._game_number > self._games_per_match:
            self._terminal = True
            return

        self._game_scores = {p: 0 for p in self._player_ids}
        self._hand_number = 0
        self._dealer_idx = -1
        self._hand_history = []
        self._highlight_turns = []
        self._turn_number = 0

        self._start_new_hand()

    def _start_new_hand(self) -> None:
        self._hand_number += 1
        self._dealer_idx = (self._dealer_idx + 1) % 4

        # Deal
        deck = list(FULL_DECK)
        self._rng.shuffle(deck)
        for i, pid in enumerate(PLAY_ORDER):
            self._hands[pid] = _sort_hand(deck[i * 13 : (i + 1) * 13])

        # Pass direction: hand 1=left, 2=right, 3=across, 4=none, 5=left, ...
        self._pass_direction = PASS_DIRECTIONS[(self._hand_number - 1) % 4]

        # Reset per-hand state
        self._penalty_this_hand = {p: 0 for p in self._player_ids}
        self._queen_taken_by = None
        self._hearts_broken = False
        self._trick_number = 0
        self._current_trick = []
        self._trick_history = []

        # Pass phase
        self._passed_cards = {}
        self._received_cards = {}

        if self._pass_direction == "none":
            # Skip pass phase entirely
            self._phase = Phase.PLAY
            self._setup_first_trick()
        else:
            self._phase = Phase.PASS
            self._pass_collect_idx = 0

    def _setup_first_trick(self) -> None:
        """Find holder of 2♣ and set as trick leader."""
        for pid in PLAY_ORDER:
            if TWO_OF_CLUBS in self._hands[pid]:
                self._trick_leader = pid
                break
        self._trick_play_idx = 0

    # ------------------------------------------------------------------
    # Turn management
    # ------------------------------------------------------------------

    def current_player(self) -> str:
        if self._phase == Phase.PASS:
            return PLAY_ORDER[self._pass_collect_idx]
        else:
            leader_idx = PLAY_ORDER.index(self._trick_leader)
            idx = (leader_idx + self._trick_play_idx) % 4
            return PLAY_ORDER[idx]

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate_action(self, player_id: str, action: dict) -> ValidationResult:
        if self._phase == Phase.PASS:
            return self._validate_pass(player_id, action)
        else:
            return self._validate_play(player_id, action)

    def _validate_pass(self, player_id: str, action: dict) -> ValidationResult:
        if action.get("action") != "pass":
            return ValidationResult(legal=False, reason="Expected action 'pass' during passing phase.")

        cards = action.get("cards", [])
        if not isinstance(cards, list) or len(cards) != 3:
            return ValidationResult(legal=False, reason="Must pass exactly 3 cards.")

        hand = self._hands[player_id]
        normalized = [self._normalize_card(c) for c in cards]

        # Check for duplicates
        if len(set(normalized)) != 3:
            return ValidationResult(legal=False, reason="Duplicate cards in pass selection.")

        for card in normalized:
            if card not in hand:
                return ValidationResult(
                    legal=False,
                    reason=f"Card '{card}' is not in your hand. Your hand: {', '.join(hand)}",
                )

        return ValidationResult(legal=True, reason=None)

    def _validate_play(self, player_id: str, action: dict) -> ValidationResult:
        if action.get("action") != "play":
            return ValidationResult(legal=False, reason="Expected action 'play' during trick play phase.")

        card = self._normalize_card(action.get("card", ""))
        hand = self._hands[player_id]

        if card not in hand:
            return ValidationResult(
                legal=False,
                reason=f"Card '{action.get('card', '')}' is not in your hand. Your hand: {', '.join(hand)}",
            )

        # First trick, first card: must be 2♣
        if self._trick_number == 0 and len(self._current_trick) == 0:
            if card != TWO_OF_CLUBS:
                return ValidationResult(
                    legal=False,
                    reason=f"The player holding 2♣ must lead it on the first trick.",
                )

        if self._current_trick:
            # Following — must follow suit if able
            led_suit = _card_suit(self._current_trick[0]["card"])
            has_led_suit = any(_card_suit(c) == led_suit for c in hand)
            if has_led_suit and _card_suit(card) != led_suit:
                return ValidationResult(
                    legal=False,
                    reason=f"You must follow suit ({led_suit}). You have cards of that suit.",
                )

            # First trick restriction: no hearts or Q♠ even when void
            if self._trick_number == 0 and not has_led_suit:
                if _penalty_points(card) > 0:
                    # Exception: hand is ONLY penalty cards
                    non_penalty = [c for c in hand if _penalty_points(c) == 0]
                    # Also exclude cards of the led suit (already checked — we're void)
                    non_penalty_non_led = [c for c in non_penalty if _card_suit(c) != led_suit]
                    if non_penalty_non_led:
                        return ValidationResult(
                            legal=False,
                            reason="Cannot play hearts or Q♠ on the first trick (unless your hand contains only penalty cards).",
                        )
        else:
            # Leading
            if _card_suit(card) == "♥" and not self._hearts_broken:
                has_non_heart = any(_card_suit(c) != "♥" for c in hand)
                if has_non_heart:
                    return ValidationResult(
                        legal=False,
                        reason="Hearts have not been broken. You cannot lead a heart unless you have only hearts.",
                    )

        return ValidationResult(legal=True, reason=None)

    @staticmethod
    def _normalize_card(card: str) -> str:
        replacements = {
            "spades": "♠", "spade": "♠",
            "hearts": "♥", "heart": "♥",
            "diamonds": "♦", "diamond": "♦",
            "clubs": "♣", "club": "♣",
        }
        c = card.strip()
        for word, sym in replacements.items():
            if c.lower().endswith(word):
                c = c[: -len(word)] + sym
                break
        return c

    # ------------------------------------------------------------------
    # Action application
    # ------------------------------------------------------------------

    def apply_action(self, player_id: str, action: dict) -> None:
        self._turn_number += 1
        if self._phase == Phase.PASS:
            self._apply_pass(player_id, action)
        else:
            self._apply_play(player_id, action)

    def _apply_pass(self, player_id: str, action: dict) -> None:
        cards = [self._normalize_card(c) for c in action["cards"]]
        self._passed_cards[player_id] = cards

        self._pass_collect_idx += 1

        if self._pass_collect_idx >= 4:
            self._execute_pass_swap()
            self._phase = Phase.PLAY
            self._setup_first_trick()

    def _execute_pass_swap(self) -> None:
        """Execute the batch card swap after all 4 players have chosen."""
        targets = _pass_targets(self._pass_direction)
        self._received_cards = {p: [] for p in self._player_ids}

        # Remove passed cards from hands
        for pid in self._player_ids:
            for card in self._passed_cards[pid]:
                self._hands[pid].remove(card)

        # Add received cards to hands
        for passer_idx, receiver_idx in targets.items():
            passer = PLAY_ORDER[passer_idx]
            receiver = PLAY_ORDER[receiver_idx]
            self._received_cards[receiver] = self._passed_cards[passer]
            self._hands[receiver].extend(self._passed_cards[passer])

        # Re-sort all hands
        for pid in self._player_ids:
            self._hands[pid] = _sort_hand(self._hands[pid])

    def _apply_play(self, player_id: str, action: dict) -> None:
        card = self._normalize_card(action["card"])
        self._hands[player_id].remove(card)

        self._current_trick.append({"player": player_id, "card": card})

        # Check hearts broken
        if _card_suit(card) == "♥" and not self._hearts_broken:
            if self._current_trick[0]["card"] != card:
                # Played a heart while not leading (void in led suit) — hearts broken
                self._hearts_broken = True
                self._highlight_turns.append(self._turn_number)
            elif len(self._current_trick) == 1:
                # Leading a heart — hearts must already be broken (or only hearts)
                # Mark as broken if somehow not yet
                self._hearts_broken = True

        self._trick_play_idx += 1

        if self._trick_play_idx >= 4:
            self._resolve_trick()

    def _resolve_trick(self) -> None:
        led_suit = _card_suit(self._current_trick[0]["card"])
        winner = _trick_winner(self._current_trick, led_suit)

        # Accumulate penalty points
        trick_penalty = 0
        for entry in self._current_trick:
            pts = _penalty_points(entry["card"])
            if pts > 0:
                self._penalty_this_hand[winner] += pts
                trick_penalty += pts
                if entry["card"] == QUEEN_OF_SPADES:
                    self._queen_taken_by = winner
                    self._highlight_turns.append(self._turn_number)

        self._trick_history.append({
            "trick_number": self._trick_number + 1,
            "leader": self._trick_leader,
            "cards": list(self._current_trick),
            "winner": winner,
            "led_suit": led_suit,
            "penalty_points": trick_penalty,
        })

        self._trick_number += 1

        if self._trick_number >= 13:
            self._score_hand()
        else:
            self._trick_leader = winner
            self._trick_play_idx = 0
            self._current_trick = []

    # ------------------------------------------------------------------
    # Scoring
    # ------------------------------------------------------------------

    def _score_hand(self) -> None:
        # Shoot the Moon check
        shooter = None
        for pid in self._player_ids:
            if self._penalty_this_hand[pid] == 26:
                shooter = pid
                break

        hand_result: dict = {
            "hand_number": self._hand_number,
            "penalty": dict(self._penalty_this_hand),
            "shoot_the_moon": shooter,
        }

        if shooter:
            # Shooter gets 0, everyone else gets +26
            for pid in self._player_ids:
                if pid == shooter:
                    pass  # 0 added
                else:
                    self._game_scores[pid] += 26
            self._highlight_turns.append(self._turn_number)
        else:
            for pid in self._player_ids:
                self._game_scores[pid] += self._penalty_this_hand[pid]

        hand_result["game_scores"] = dict(self._game_scores)
        self._hand_history.append(hand_result)

        # Check for score milestones
        for pid in self._player_ids:
            prev = self._game_scores[pid] - (0 if shooter and pid != shooter else self._penalty_this_hand[pid])
            curr = self._game_scores[pid]
            if shooter and pid != shooter:
                prev = curr - 26
            for milestone in (50, 75):
                if prev < milestone <= curr:
                    self._highlight_turns.append(self._turn_number)

        if self._check_game_end():
            return

        self._start_new_hand()

    def _check_game_end(self) -> bool:
        # Anyone reached target score?
        if any(s >= self._target_score for s in self._game_scores.values()):
            self._end_game()
            return True

        if self._hand_number >= self._hand_limit:
            self._end_game()
            return True

        return False

    def _end_game(self) -> None:
        """Score inversion: lowest penalty → highest match score.

        match_scores += max_game_score - player_game_score
        This ensures the player with the fewest penalty points gets the
        most match points, compatible with hybrid_normalize.
        """
        max_score = max(self._game_scores.values())
        for pid in self._player_ids:
            self._match_scores[pid] += float(max_score - self._game_scores[pid])

        if self._game_number >= self._games_per_match:
            self._terminal = True
        else:
            self._start_new_game()

    # ------------------------------------------------------------------
    # Forfeit
    # ------------------------------------------------------------------

    def forfeit_turn(self, player_id: str) -> None:
        if self._phase == Phase.PASS:
            cards = self._forfeit_pass(player_id)
            self.apply_action(player_id, {"action": "pass", "cards": cards, "reasoning": "forfeit"})
        else:
            card = self._forfeit_card(player_id)
            self.apply_action(player_id, {"action": "play", "card": card, "reasoning": "forfeit"})

    def _forfeit_pass(self, player_id: str) -> list[str]:
        """Pass the 3 highest hearts; fill with highest cards from longest suit."""
        hand = self._hands[player_id]
        hearts = sorted([c for c in hand if _card_suit(c) == "♥"], key=_card_rank_value, reverse=True)
        chosen = hearts[:3]

        if len(chosen) < 3:
            # Fill with highest cards from non-heart suits, preferring longest suit
            remaining = [c for c in hand if c not in chosen]
            # Sort by suit length (desc), then rank (desc)
            suit_counts: dict[str, int] = {}
            for c in remaining:
                s = _card_suit(c)
                suit_counts[s] = suit_counts.get(s, 0) + 1
            remaining.sort(key=lambda c: (-suit_counts.get(_card_suit(c), 0), -_card_rank_value(c)))
            # Actually, spec says "highest cards from longest suit" — take highest overall
            remaining.sort(key=_card_rank_value, reverse=True)
            chosen.extend(remaining[: 3 - len(chosen)])

        return chosen

    def _forfeit_card(self, player_id: str) -> str:
        """Strategically sane forfeit play."""
        hand = self._hands[player_id]

        # First trick, leading: must play 2♣
        if self._trick_number == 0 and len(self._current_trick) == 0:
            return TWO_OF_CLUBS

        if self._current_trick:
            led_suit = _card_suit(self._current_trick[0]["card"])
            suited = [c for c in hand if _card_suit(c) == led_suit]
            if suited:
                # Follow suit: play lowest to avoid winning
                return min(suited, key=_card_rank_value)
            else:
                # Void — dump penalty cards
                # First trick restriction: can't play penalty cards (usually)
                if self._trick_number == 0:
                    non_penalty = [c for c in hand if _penalty_points(c) == 0]
                    if non_penalty:
                        return max(non_penalty, key=_card_rank_value)

                # Dump Q♠ if we have it
                if QUEEN_OF_SPADES in hand:
                    return QUEEN_OF_SPADES
                # Dump highest heart
                hearts = [c for c in hand if _card_suit(c) == "♥"]
                if hearts:
                    return max(hearts, key=_card_rank_value)
                # Dump highest card
                return max(hand, key=_card_rank_value)
        else:
            # Leading: play lowest non-heart
            non_hearts = [c for c in hand if _card_suit(c) != "♥"]
            if non_hearts and not (not self._hearts_broken and not non_hearts):
                if non_hearts:
                    return min(non_hearts, key=_card_rank_value)
            # Only hearts: play lowest
            return min(hand, key=_card_rank_value)

    def award_forfeit_wins(self, forfeiting_player_id: str) -> None:
        """Non-forfeiting players each get target_score * remaining_games."""
        remaining = self._games_per_match - self._game_number + 1
        for pid in self._player_ids:
            if pid != forfeiting_player_id:
                self._match_scores[pid] += float(self._target_score * remaining)
        self._terminal = True

    # ------------------------------------------------------------------
    # Prompts
    # ------------------------------------------------------------------

    def get_prompt(self, player_id: str) -> str:
        label = self._player_labels[player_id]

        lines: list[str] = []
        lines.append(f"You are Player {label} in a game of Hearts.")
        lines.append("Hearts is a trick-avoidance game — you want to AVOID taking penalty cards.")
        lines.append("")

        if self._games_per_match > 1:
            lines.append(f"Game {self._game_number} of {self._games_per_match}.")
            score_parts = [
                f"{self._player_labels[p]}: {self._match_scores[p]:.0f}"
                for p in self._player_ids
            ]
            lines.append(f"Match scores: {', '.join(score_parts)}")
            lines.append("")

        # Cumulative game scores
        score_parts = [
            f"Player {self._player_labels[p]}: {self._game_scores.get(p, 0)}"
            for p in self._player_ids
        ]
        lines.append(f"Cumulative penalty scores: {', '.join(score_parts)}")
        lines.append(f"First to {self._target_score} penalty points loses. Lowest score wins.")
        lines.append(f"Hand {self._hand_number} of up to {self._hand_limit}.")
        lines.append("")

        hand = _sort_hand(self._hands[player_id])
        lines.append(f"Your hand ({len(hand)} cards): {', '.join(hand)}")
        lines.append("")

        if self._phase == Phase.PASS:
            lines.extend(self._pass_prompt_lines(player_id))
        else:
            lines.extend(self._play_prompt_lines(player_id))

        return "\n".join(lines)

    def _pass_prompt_lines(self, player_id: str) -> list[str]:
        lines: list[str] = []
        lines.append("=== CARD PASSING PHASE ===")
        lines.append("")
        lines.append(f"Pass direction: {self._pass_direction}")

        # Who are we passing to?
        my_idx = PLAY_ORDER.index(player_id)
        targets = _pass_targets(self._pass_direction)
        if my_idx in targets:
            receiver = PLAY_ORDER[targets[my_idx]]
            lines.append(f"You are passing 3 cards to Player {self._player_labels[receiver]}.")
        lines.append("")

        lines.append("Select 3 cards from your hand to pass.")
        lines.append("Strategy: pass high hearts, Q♠, and cards that leave you void in a suit.")
        lines.append("")
        lines.append('Respond with ONLY a JSON object: {"reasoning": "...", "action": "pass", "cards": ["card1", "card2", "card3"]}')
        lines.append('Example card format: "A♠", "10♥", "3♣", "K♦", "Q♠"')
        lines.append("Do NOT write anything outside the JSON.")

        return lines

    def _play_prompt_lines(self, player_id: str) -> list[str]:
        lines: list[str] = []
        lines.append("=== TRICK PLAY ===")
        lines.append("")

        # Penalty this hand
        lines.append("Penalty points taken this hand:")
        for pid in self._player_ids:
            label = self._player_labels[pid]
            pts = self._penalty_this_hand.get(pid, 0)
            marker = " (you)" if pid == player_id else ""
            lines.append(f"  Player {label}: {pts}{marker}")
        lines.append("")

        lines.append(f"Trick {self._trick_number + 1} of 13.")
        lines.append(f"Hearts broken: {'Yes' if self._hearts_broken else 'No'}")
        lines.append("")

        if self._current_trick:
            led_suit = _card_suit(self._current_trick[0]["card"])
            lines.append(f"Suit led: {led_suit}")
            lines.append("Cards played this trick:")
            for entry in self._current_trick:
                lines.append(f"  Player {self._player_labels[entry['player']]}: {entry['card']}")
            lines.append("")

            hand = self._hands[player_id]
            has_led_suit = any(_card_suit(c) == led_suit for c in hand)
            if has_led_suit:
                lines.append(f"You MUST follow suit ({led_suit}).")
            else:
                lines.append(f"You are void in {led_suit} — you may play any card.")
                if self._trick_number == 0:
                    lines.append("First trick restriction: you cannot play hearts or Q♠ (unless you have only penalty cards).")
        else:
            lines.append("You are leading this trick.")
            if self._trick_number == 0:
                lines.append("You must lead the 2♣.")
            elif not self._hearts_broken:
                hand = self._hands[player_id]
                has_non_heart = any(_card_suit(c) != "♥" for c in hand)
                if has_non_heart:
                    lines.append("Hearts have NOT been broken — you cannot lead a heart unless you have only hearts.")
                else:
                    lines.append("You have only hearts remaining — you may lead a heart.")
        lines.append("")

        lines.append("Scoring: Each heart = 1 penalty point. Queen of spades (Q♠) = 13 penalty points.")
        lines.append("Shoot the Moon: If you take ALL 26 penalty points, you score 0 and everyone else gets +26.")
        lines.append("")
        lines.append("Rules: Must follow the led suit if able. Highest card of the led suit wins. "
                      "There is NO trump suit in Hearts. "
                      "Card ranks: A > K > Q > J > 10 > 9 > 8 > 7 > 6 > 5 > 4 > 3 > 2.")
        lines.append("")
        lines.append('Respond with ONLY a JSON object: {"reasoning": "...", "action": "play", "card": "<card>"}')
        lines.append('Example card format: "A♠", "10♥", "3♣", "K♦"')
        lines.append("Do NOT write anything outside the JSON.")

        return lines

    def get_retry_prompt(self, player_id: str, error_reason: str) -> str:
        return (
            f"Your last action was invalid: {error_reason}\n\n"
            f"{self.get_prompt(player_id)}"
        )

    # ------------------------------------------------------------------
    # State snapshot
    # ------------------------------------------------------------------

    def get_scores(self) -> dict[str, float]:
        return dict(self._match_scores)

    def get_state_snapshot(self) -> dict:
        return {
            "phase": self._phase.value,
            "game_number": self._game_number,
            "games_per_match": self._games_per_match,
            "hand_number": self._hand_number,
            "pass_direction": self._pass_direction,
            "trick_number": self._trick_number + 1,
            "turn_number": self._turn_number,
            "hands": {p: list(self._hands.get(p, [])) for p in self._player_ids},
            "passed_cards": {p: list(self._passed_cards.get(p, [])) for p in self._player_ids},
            "received_cards": {p: list(self._received_cards.get(p, [])) for p in self._player_ids},
            "current_trick": list(self._current_trick),
            "trick_leader": self._trick_leader,
            "dealer": PLAY_ORDER[self._dealer_idx],
            "penalty_this_hand": dict(self._penalty_this_hand),
            "game_scores": dict(self._game_scores),
            "hearts_broken": self._hearts_broken,
            "queen_taken_by": self._queen_taken_by,
            "trick_history": [dict(t) for t in self._trick_history],
            "hand_history": [dict(h) for h in self._hand_history],
            "terminal": self._terminal,
            "match_scores": dict(self._match_scores),
            "mode": self._mode,
        }

    def get_highlight_hands(self) -> list[int]:
        return list(self._highlight_turns)
