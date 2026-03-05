"""Gin Rummy engine — 2-player card game.

Best-of-N series. Each game plays hands until a player reaches 100 points
(or 20-hand cap). Single-action turns: draw + action + discard in one JSON.
Reasoning-first schema, emphatic JSON-only prompts.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from llmtourney.events.base import TwoPlayerSeriesEvent, ValidationResult

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

RANKS = ["A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K"]
RANK_ORDER = {r: i for i, r in enumerate(RANKS)}  # A=0 .. K=12
SUITS = ["♣", "♦", "♥", "♠"]
SUIT_SYMBOLS = set(SUITS)
FULL_DECK = [f"{r}{s}" for s in SUITS for r in RANKS]

DEADWOOD_VALUES = {
    "A": 1, "2": 2, "3": 3, "4": 4, "5": 5,
    "6": 6, "7": 7, "8": 8, "9": 9, "10": 10,
    "J": 10, "Q": 10, "K": 10,
}

TARGET_SCORE = 100
HAND_LIMIT = 20
GIN_BONUS = 25
UNDERCUT_BONUS = 25
GAME_BONUS = 100
LINE_BONUS = 25


# ---------------------------------------------------------------------------
# Card helpers
# ---------------------------------------------------------------------------

def _card_suit(card: str) -> str:
    return card[-1]


def _card_rank(card: str) -> str:
    return card[:-1]


def _card_rank_value(card: str) -> int:
    return RANK_ORDER[_card_rank(card)]


def _deadwood_value(card: str) -> int:
    return DEADWOOD_VALUES[_card_rank(card)]


def _sort_hand(hand: list[str]) -> list[str]:
    """Sort hand by suit (♣ ♦ ♥ ♠) then rank within suit."""
    suit_order = {s: i for i, s in enumerate(SUITS)}
    return sorted(hand, key=lambda c: (suit_order[_card_suit(c)], _card_rank_value(c)))


def _normalize_card(card: str) -> str:
    """Handle text suit names → symbols (e.g. '10hearts' → '10♥')."""
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


# ---------------------------------------------------------------------------
# Meld detection algorithm
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class MeldResult:
    """Result of optimal meld assignment."""
    melds: list[tuple[str, ...]]
    deadwood: list[str]
    deadwood_value: int


def _enumerate_all_melds(cards: list[str]) -> list[tuple[str, ...]]:
    """Find all valid sets and runs from a collection of cards.

    Sets: 3 or 4 cards of the same rank.
    Runs: 3+ consecutive cards of the same suit (ace LOW only, no wrap).
    """
    melds: list[tuple[str, ...]] = []

    # --- Sets: group by rank ---
    by_rank: dict[str, list[str]] = {}
    for c in cards:
        by_rank.setdefault(_card_rank(c), []).append(c)

    for _rank, group in by_rank.items():
        if len(group) >= 3:
            # 3-of-a-kind combinations
            for i in range(len(group)):
                for j in range(i + 1, len(group)):
                    for k in range(j + 1, len(group)):
                        melds.append((group[i], group[j], group[k]))
            # 4-of-a-kind
            if len(group) == 4:
                melds.append(tuple(group))

    # --- Runs: group by suit, find consecutive sequences ---
    by_suit: dict[str, list[str]] = {}
    for c in cards:
        by_suit.setdefault(_card_suit(c), []).append(c)

    for _suit, group in by_suit.items():
        # Sort by rank order (A=0, 2=1, ..., K=12)
        sorted_group = sorted(group, key=_card_rank_value)
        rank_vals = [_card_rank_value(c) for c in sorted_group]

        # Find all consecutive subsequences of length >= 3
        n = len(sorted_group)
        for start in range(n):
            run = [sorted_group[start]]
            for end in range(start + 1, n):
                if rank_vals[end] == rank_vals[end - 1] + 1:
                    run.append(sorted_group[end])
                    if len(run) >= 3:
                        melds.append(tuple(run))
                else:
                    break

    return melds


def find_optimal_melds(cards: list[str]) -> MeldResult:
    """Recursive backtracking to find meld assignment minimizing deadwood.

    Tries each possible meld, removes its cards, recurses on remainder.
    Returns the assignment with the lowest total deadwood value.
    """
    card_set = set(cards)

    best: list[MeldResult] = []

    def _backtrack(remaining: set[str], chosen: list[tuple[str, ...]]) -> None:
        # Compute candidate melds from remaining cards
        candidates = _enumerate_all_melds(list(remaining))

        # Current solution
        dw = sorted(remaining, key=lambda c: (SUITS.index(_card_suit(c)), _card_rank_value(c)))
        dw_val = sum(_deadwood_value(c) for c in remaining)
        result = MeldResult(
            melds=list(chosen),
            deadwood=dw,
            deadwood_value=dw_val,
        )

        if not best or dw_val < best[0].deadwood_value:
            best.clear()
            best.append(result)

        # Prune: if no candidates, we're done
        if not candidates:
            return

        # Try each candidate meld
        seen: set[frozenset[str]] = set()
        for meld in candidates:
            key = frozenset(meld)
            if key in seen:
                continue
            seen.add(key)

            new_remaining = remaining - set(meld)
            chosen.append(meld)
            _backtrack(new_remaining, chosen)
            chosen.pop()

    _backtrack(card_set, [])
    return best[0] if best else MeldResult(melds=[], deadwood=list(cards), deadwood_value=sum(_deadwood_value(c) for c in cards))


# ---------------------------------------------------------------------------
# Layoff computation
# ---------------------------------------------------------------------------

def _can_lay_off(card: str, meld: tuple[str, ...]) -> bool:
    """Check if card can extend a meld (set or run)."""
    # Determine if meld is a set or run
    ranks = [_card_rank(c) for c in meld]
    suits = [_card_suit(c) for c in meld]

    if len(set(ranks)) == 1:
        # Set — can add if same rank and set has < 4 cards
        return len(meld) < 4 and _card_rank(card) == ranks[0] and _card_suit(card) not in suits
    else:
        # Run — can add to either end
        suit = suits[0]
        if _card_suit(card) != suit:
            return False
        vals = sorted(_card_rank_value(c) for c in meld)
        card_val = _card_rank_value(card)
        return card_val == vals[0] - 1 or card_val == vals[-1] + 1


def compute_layoffs(
    defender_deadwood: list[str],
    knocker_melds: list[tuple[str, ...]],
) -> tuple[list[str], list[tuple[str, ...]]]:
    """Iteratively lay off defender's deadwood onto knocker's melds.

    Returns (remaining_deadwood, updated_melds). Repeats until stable
    since laying off a card can enable further layoffs.
    """
    remaining = list(defender_deadwood)
    melds = [tuple(m) for m in knocker_melds]

    changed = True
    while changed:
        changed = False
        still_remaining: list[str] = []
        for card in remaining:
            laid_off = False
            for i, meld in enumerate(melds):
                if _can_lay_off(card, meld):
                    # Extend the meld
                    extended = list(meld) + [card]
                    # Sort by rank value for runs
                    ranks = [_card_rank(c) for c in extended]
                    if len(set(ranks)) > 1:  # run
                        extended.sort(key=_card_rank_value)
                    melds[i] = tuple(extended)
                    laid_off = True
                    changed = True
                    break
            if not laid_off:
                still_remaining.append(card)
        remaining = still_remaining

    return remaining, melds


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class GinRummyEvent(TwoPlayerSeriesEvent):
    """2-player Gin Rummy — draw-and-discard card game."""

    def __init__(self, games_per_match: int = 3) -> None:
        super().__init__(games_per_match=games_per_match)

        # RNG — created in reset()
        self._rng: random.Random | None = None

        # Game-level state (persists across hands within a game)
        self._game_scores: dict[str, int] = {}
        self._hands_won: dict[str, int] = {}
        self._hand_number: int = 0
        self._dealer: str = ""

        # Hand-level state
        self._hands: dict[str, list[str]] = {}
        self._stock: list[str] = []
        self._discard_pile: list[str] = []
        self._discard_history: list[dict] = []

        # Tracking
        self._hand_history: list[dict] = []
        self._highlight_turns: list[int] = []
        self._turn_number: int = 0

    @property
    def display_name(self) -> str:
        return "Gin Rummy"

    # ------------------------------------------------------------------
    # Game lifecycle
    # ------------------------------------------------------------------

    def reset(self, seed: int) -> None:
        self._rng = random.Random(seed)
        super().reset(seed)

    def _init_game_state(self) -> None:
        """Reset game-level scores and start first hand."""
        self._game_scores = {p: 0 for p in self._player_ids}
        self._hands_won = {p: 0 for p in self._player_ids}
        self._hand_number = 0
        self._hand_history = []
        self._highlight_turns = []
        self._turn_number = 0
        # Dealer alternates by game: game 1 = player_a, game 2 = player_b, etc.
        self._dealer = self._player_ids[(self._game_number - 1) % 2]
        self._start_new_hand()

    def _start_new_hand(self) -> None:
        """Shuffle, deal 10 each, flip first discard. Non-dealer goes first."""
        self._hand_number += 1
        # Alternate dealer each hand
        if self._hand_number > 1:
            self._dealer = self._opponent(self._dealer)

        deck = list(FULL_DECK)
        assert self._rng is not None
        self._rng.shuffle(deck)

        # Deal 10 cards each
        non_dealer = self._opponent(self._dealer)
        self._hands = {
            non_dealer: _sort_hand(deck[:10]),
            self._dealer: _sort_hand(deck[10:20]),
        }
        # 21st card starts discard pile, rest is stock
        self._discard_pile = [deck[20]]
        self._stock = deck[21:]
        self._discard_history = []

        # Non-dealer goes first
        self._active_player = non_dealer

    # ------------------------------------------------------------------
    # Turn management
    # ------------------------------------------------------------------

    def current_player(self) -> str:
        return self._active_player

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate_action(self, player_id: str, action: dict) -> ValidationResult:
        draw = action.get("draw", "")
        discard_card = _normalize_card(action.get("discard", ""))
        act = action.get("action", "")

        # 1. Draw source
        if draw not in ("stock", "discard"):
            return ValidationResult(
                legal=False,
                reason=f"'draw' must be 'stock' or 'discard', got '{draw}'.",
            )

        # 2. Build 11-card hand
        hand = list(self._hands[player_id])
        if draw == "stock":
            if not self._stock:
                return ValidationResult(legal=False, reason="Stock is empty.")
            drawn_card = self._stock[0]  # peek
        else:
            if not self._discard_pile:
                return ValidationResult(legal=False, reason="Discard pile is empty.")
            drawn_card = self._discard_pile[-1]

        hand_11 = hand + [drawn_card]

        # 3. Discard must be in 11-card hand
        if discard_card not in hand_11:
            return ValidationResult(
                legal=False,
                reason=f"Card '{discard_card}' is not in your hand after drawing. "
                       f"Your hand after draw: {', '.join(_sort_hand(hand_11))}",
            )

        # 4. Cannot draw from discard and immediately re-discard the same card
        if draw == "discard" and discard_card == drawn_card:
            return ValidationResult(
                legal=False,
                reason="You cannot draw from the discard pile and immediately discard the same card.",
            )

        # 5. Action validation
        if act not in ("continue", "knock", "gin"):
            return ValidationResult(
                legal=False,
                reason=f"'action' must be 'continue', 'knock', or 'gin', got '{act}'.",
            )

        # Compute hand after discard
        hand_after = list(hand_11)
        hand_after.remove(discard_card)
        result = find_optimal_melds(hand_after)

        if act == "knock" and result.deadwood_value > 10:
            return ValidationResult(
                legal=False,
                reason=f"Cannot knock with deadwood {result.deadwood_value} (must be ≤ 10). "
                       f"Your deadwood: {', '.join(result.deadwood)} = {result.deadwood_value}.",
            )

        if act == "gin" and result.deadwood_value != 0:
            return ValidationResult(
                legal=False,
                reason=f"Cannot declare gin with deadwood {result.deadwood_value} (must be 0). "
                       f"Deadwood: {', '.join(result.deadwood)} = {result.deadwood_value}.",
            )

        return ValidationResult(legal=True, reason=None)

    # ------------------------------------------------------------------
    # Action application
    # ------------------------------------------------------------------

    def apply_action(self, player_id: str, action: dict) -> None:
        self._turn_number += 1
        self._game_turn += 1

        draw = action["draw"]
        discard_card = _normalize_card(action["discard"])
        act = action["action"]

        # 1. Draw
        if draw == "stock":
            drawn_card = self._stock.pop(0)
        else:
            drawn_card = self._discard_pile.pop()

        self._hands[player_id].append(drawn_card)

        # 2. Discard
        self._hands[player_id].remove(discard_card)
        self._discard_pile.append(discard_card)
        self._hands[player_id] = _sort_hand(self._hands[player_id])

        # Record discard history
        self._discard_history.append({
            "player": player_id,
            "drew_from": draw,
            "discarded": discard_card,
            "action": act,
        })

        # 3. Handle action
        if act == "gin":
            self._score_hand(player_id, is_gin=True)
            return

        if act == "knock":
            self._score_hand(player_id, is_gin=False)
            return

        # 4. Check stock depletion
        if len(self._stock) <= 2:
            self._handle_draw_hand()
            return

        # 5. Switch to opponent
        self._active_player = self._opponent(player_id)

    # ------------------------------------------------------------------
    # Hand scoring
    # ------------------------------------------------------------------

    def _score_hand(self, knocker: str, is_gin: bool) -> None:
        """Score a completed hand (gin or knock)."""
        defender = self._opponent(knocker)

        knocker_result = find_optimal_melds(self._hands[knocker])
        defender_result = find_optimal_melds(self._hands[defender])

        hand_record: dict = {
            "hand_number": self._hand_number,
            "knocker": knocker,
            "is_gin": is_gin,
            "knocker_melds": [list(m) for m in knocker_result.melds],
            "knocker_deadwood": list(knocker_result.deadwood),
            "knocker_deadwood_value": knocker_result.deadwood_value,
            "defender_melds": [list(m) for m in defender_result.melds],
            "defender_deadwood": list(defender_result.deadwood),
            "defender_deadwood_value": defender_result.deadwood_value,
        }

        if is_gin:
            # Gin: knocker gets GIN_BONUS + defender's full deadwood (no layoffs)
            points = GIN_BONUS + defender_result.deadwood_value
            hand_record["result"] = "gin"
            hand_record["points_awarded"] = points
            hand_record["winner"] = knocker
            self._game_scores[knocker] += points
            self._hands_won[knocker] += 1
            self._highlight_turns.append(self._turn_number)
        else:
            # Knock: defender can lay off deadwood onto knocker's melds
            remaining_dw, _updated_melds = compute_layoffs(
                defender_result.deadwood, knocker_result.melds,
            )
            defender_final_dw = sum(_deadwood_value(c) for c in remaining_dw)
            knocker_dw = knocker_result.deadwood_value

            hand_record["defender_layoffs"] = [
                c for c in defender_result.deadwood if c not in remaining_dw
            ]
            hand_record["defender_final_deadwood"] = list(remaining_dw)
            hand_record["defender_final_deadwood_value"] = defender_final_dw

            if defender_final_dw <= knocker_dw:
                # Undercut! Defender wins
                points = UNDERCUT_BONUS + (knocker_dw - defender_final_dw)
                hand_record["result"] = "undercut"
                hand_record["points_awarded"] = points
                hand_record["winner"] = defender
                self._game_scores[defender] += points
                self._hands_won[defender] += 1
                self._highlight_turns.append(self._turn_number)
            else:
                # Knocker wins
                points = defender_final_dw - knocker_dw
                hand_record["result"] = "knock"
                hand_record["points_awarded"] = points
                hand_record["winner"] = knocker
                self._game_scores[knocker] += points
                self._hands_won[knocker] += 1

        self._hand_history.append(hand_record)

        # Check game end
        if self._check_game_end():
            return

        self._start_new_hand()

    def _handle_draw_hand(self) -> None:
        """Stock depleted to ≤2 cards — hand is a draw."""
        hand_record = {
            "hand_number": self._hand_number,
            "result": "draw",
            "points_awarded": 0,
            "winner": None,
        }
        self._hand_history.append(hand_record)

        if self._check_game_end():
            return

        self._start_new_hand()

    def _check_game_end(self) -> bool:
        """Check if either player has reached TARGET_SCORE or HAND_LIMIT hit."""
        if any(s >= TARGET_SCORE for s in self._game_scores.values()):
            self._end_game()
            return True

        if self._hand_number >= HAND_LIMIT:
            self._end_game()
            return True

        return False

    def _end_game(self) -> None:
        """Score the game: game bonus, line bonus, shutout doubling."""
        # Determine game winner (higher score)
        pa, pb = self._player_ids
        winner = pa if self._game_scores[pa] >= self._game_scores[pb] else pb
        loser = self._opponent(winner)

        # Game bonus: +100 to winner
        total = dict(self._game_scores)
        total[winner] += GAME_BONUS

        # Line bonus: +25 per net hand won
        net_hands = self._hands_won[winner] - self._hands_won[loser]
        total[winner] += LINE_BONUS * max(net_hands, 0)

        # Shutout: double winner's total if loser won 0 hands
        if self._hands_won[loser] == 0:
            total[winner] *= 2

        # Add to series scores (only winner's total matters — gin rummy scores are one-sided)
        self._series_scores[winner] += float(total[winner])
        self._series_scores[loser] += float(total[loser])

        self._advance_or_end()

    # ------------------------------------------------------------------
    # Forfeit
    # ------------------------------------------------------------------

    def forfeit_turn(self, player_id: str) -> None:
        """Draw from stock, discard highest deadwood card, knock/gin if able."""
        hand = list(self._hands[player_id])

        # Default: draw from stock
        draw = "stock"
        if not self._stock:
            draw = "discard"

        # Build 11-card hand
        if draw == "stock":
            drawn_card = self._stock[0]
        else:
            drawn_card = self._discard_pile[-1]
        hand_11 = hand + [drawn_card]

        # Find best discard: maximize deadwood reduction
        best_discard = None
        best_dw = float("inf")
        for card in hand_11:
            # Can't re-discard the card we drew from discard
            if draw == "discard" and card == drawn_card:
                continue
            trial = [c for c in hand_11 if c != card]
            # Handle duplicates: only remove one copy
            trial = list(hand_11)
            trial.remove(card)
            result = find_optimal_melds(trial)
            if result.deadwood_value < best_dw:
                best_dw = result.deadwood_value
                best_discard = card

        if best_discard is None:
            best_discard = hand_11[0]

        # Determine action
        if best_dw == 0:
            action = "gin"
        elif best_dw <= 10:
            action = "knock"
        else:
            action = "continue"

        self.apply_action(player_id, {
            "reasoning": "forfeit",
            "draw": draw,
            "discard": best_discard,
            "action": action,
        })

    def award_forfeit_wins(self, forfeiting_player_id: str) -> None:
        """Award remaining games to opponent with default scoring."""
        opponent = self._opponent(forfeiting_player_id)
        remaining = self._games_per_match - len(self._game_results)
        # Give opponent a solid score per remaining game
        self._series_scores[opponent] += float(TARGET_SCORE + GAME_BONUS) * remaining
        self._terminal = True

    # ------------------------------------------------------------------
    # Prompt
    # ------------------------------------------------------------------

    def get_prompt(self, player_id: str) -> str:
        opponent = self._opponent(player_id)
        hand = _sort_hand(self._hands[player_id])
        result = find_optimal_melds(hand)

        lines: list[str] = []
        lines.append("You are playing Gin Rummy.")
        lines.append("")

        # Series info
        if self._games_per_match > 1:
            lines.append(f"=== Game {self._game_number} of {self._games_per_match} ===")
            lines.append(f"Series scores: You {self._series_scores[player_id]:.0f}, "
                         f"Opponent {self._series_scores[opponent]:.0f}")
            lines.append("")

        # Game scores
        lines.append(f"Hand {self._hand_number} of up to {HAND_LIMIT}.")
        lines.append(f"Game score: You {self._game_scores[player_id]}, "
                     f"Opponent {self._game_scores[opponent]} (first to {TARGET_SCORE} wins)")
        lines.append(f"Hands won: You {self._hands_won[player_id]}, "
                     f"Opponent {self._hands_won[opponent]}")
        lines.append("")

        # Hand
        lines.append(f"Your hand ({len(hand)} cards): {', '.join(hand)}")
        lines.append("")

        # Current optimal melds
        if result.melds:
            meld_strs = [" ".join(m) for m in result.melds]
            lines.append(f"Your current melds: {' | '.join(meld_strs)}")
        else:
            lines.append("Your current melds: none")
        if result.deadwood:
            lines.append(f"Deadwood ({result.deadwood_value}): {', '.join(result.deadwood)}")
        else:
            lines.append("Deadwood: 0 (GIN!)")
        lines.append("")

        # Discard pile top
        if self._discard_pile:
            lines.append(f"Top of discard pile: {self._discard_pile[-1]}")
        else:
            lines.append("Discard pile: empty")

        # Next stock card (visible for informed decision)
        if self._stock:
            lines.append(f"Next stock card (if you draw from stock): {self._stock[0]}")
        else:
            lines.append("Stock: empty")
        lines.append(f"Stock remaining: {len(self._stock)} cards")
        lines.append("")

        # Recent discards
        if self._discard_history:
            recent = self._discard_history[-5:]
            discard_strs = []
            for d in recent:
                who = "You" if d["player"] == player_id else "Opponent"
                discard_strs.append(f"{who} discarded {d['discarded']}")
            lines.append(f"Recent discards: {'; '.join(discard_strs)}")
            lines.append("")

        # Rules summary
        lines.append("=== RULES ===")
        lines.append("1. DRAW one card: 'stock' (face-down) or 'discard' (top of discard pile)")
        lines.append("2. DISCARD one card from your hand")
        lines.append("3. ACTION: 'continue' (keep playing), 'knock' (deadwood ≤ 10), or 'gin' (deadwood = 0)")
        lines.append("")
        lines.append("Melds: Sets (3-4 same rank) or Runs (3+ consecutive same suit, ace LOW only: A-2-3 is valid, Q-K-A is NOT)")
        lines.append("Deadwood: cards not in melds. A=1, 2-10=face value, J/Q/K=10")
        lines.append("")
        lines.append("Knock: your deadwood must be ≤ 10 after discarding. Opponent can lay off deadwood onto your melds.")
        lines.append("Gin: deadwood = 0. Bonus 25 points + opponent's full deadwood (no layoffs).")
        lines.append("Undercut: if you knock and opponent's deadwood ≤ yours after layoffs, opponent gets 25 + difference.")
        lines.append("You CANNOT draw from the discard pile and immediately discard the same card.")
        lines.append("")
        lines.append("IMPORTANT: Respond with ONLY a valid JSON object. No markdown, no explanation, no text outside the JSON.")
        lines.append('{"reasoning": "your strategic thinking here", "draw": "stock", "action": "continue", "discard": "K♣"}')
        lines.append("The reasoning field MUST come first. Think through your melds and deadwood before choosing.")

        return "\n".join(lines)

    def get_retry_prompt(self, player_id: str, error_reason: str) -> str:
        return (
            f"Your last action was invalid: {error_reason}\n\n"
            f"{self.get_prompt(player_id)}"
        )

    # ------------------------------------------------------------------
    # State snapshot
    # ------------------------------------------------------------------

    def get_state_snapshot(self) -> dict:
        return {
            "game_number": self._game_number,
            "games_per_match": self._games_per_match,
            "hand_number": self._hand_number,
            "turn_number": self._turn_number,
            "dealer": self._dealer,
            "active_player": self._active_player,
            "hands": {p: list(self._hands.get(p, [])) for p in self._player_ids},
            "stock_size": len(self._stock),
            "discard_pile": list(self._discard_pile),
            "discard_history": list(self._discard_history),
            "game_scores": dict(self._game_scores),
            "hands_won": dict(self._hands_won),
            "series_scores": dict(self._series_scores),
            "hand_history": list(self._hand_history),
            "terminal": self._terminal,
        }

    def get_scores(self) -> dict[str, float]:
        return dict(self._series_scores)

    def get_highlight_hands(self) -> list[int]:
        return list(self._highlight_turns)
