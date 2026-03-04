"""Spades engine — 4-player partnership trick-taking game.

Team 1 = player_a + player_c (seated across)
Team 2 = player_b + player_d (seated across)
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

TARGET_SCORE = 500
HAND_LIMIT = 25
FLOOR_SCORE = -200
NIL_BONUS = 100
BAG_PENALTY_THRESHOLD = 10
BAG_PENALTY = -100
FORFEIT_BID = 2

# Team definitions: team_1 = player_a + player_c, team_2 = player_b + player_d
TEAMS = {"team_1": ("player_a", "player_c"), "team_2": ("player_b", "player_d")}
PLAYER_TEAM = {}
for _team, _members in TEAMS.items():
    for _pid in _members:
        PLAYER_TEAM[_pid] = _team

PARTNER = {
    "player_a": "player_c",
    "player_c": "player_a",
    "player_b": "player_d",
    "player_d": "player_b",
}

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
    """Determine the winner of a trick.

    Returns the player_id of the winner.
    Highest spade wins if any spades played; otherwise highest of led suit.
    """
    best_player = trick_cards[0]["player"]
    best_card = trick_cards[0]["card"]
    best_is_trump = _card_suit(best_card) == "♠"
    best_rank = _card_rank_value(best_card)

    for entry in trick_cards[1:]:
        card = entry["card"]
        suit = _card_suit(card)
        rank = _card_rank_value(card)
        is_trump = suit == "♠"

        if is_trump and not best_is_trump:
            # Trump beats non-trump
            best_player = entry["player"]
            best_card = card
            best_is_trump = True
            best_rank = rank
        elif is_trump and best_is_trump:
            # Higher trump wins
            if rank > best_rank:
                best_player = entry["player"]
                best_card = card
                best_rank = rank
        elif not is_trump and not best_is_trump:
            # Both non-trump: only cards of led suit compete
            if suit == led_suit and _card_suit(best_card) != led_suit:
                best_player = entry["player"]
                best_card = card
                best_rank = rank
            elif suit == led_suit and _card_suit(best_card) == led_suit and rank > best_rank:
                best_player = entry["player"]
                best_card = card
                best_rank = rank
        # else: non-trump can't beat trump — skip

    return best_player


# ---------------------------------------------------------------------------
# Phase enum
# ---------------------------------------------------------------------------


class Phase(Enum):
    BID = "bid"
    PLAY = "play"


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


class SpadesEvent(MultiplayerSeriesEvent):
    """4-player partnership Spades."""

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

        # Per-game state (initialized in _start_new_game)
        self._phase: Phase = Phase.BID
        self._hand_number: int = 0
        self._trick_number: int = 0
        self._turn_number: int = 0
        self._dealer_idx: int = -1  # incremented to 0 on first hand

        # Hands
        self._hands: dict[str, list[str]] = {}

        # Bidding
        self._bids: dict[str, int | None] = {}
        self._bid_order_idx: int = 0
        self._bid_start_idx: int = 0

        # Trick play
        self._current_trick: list[dict] = []  # [{"player": pid, "card": str}, ...]
        self._trick_leader: str = "player_a"
        self._trick_play_idx: int = 0  # index within the 4-player trick cycle
        self._spades_broken: bool = False

        # Per-hand tracking
        self._tricks_taken: dict[str, int] = {}  # per-player tricks this hand
        self._team_contracts: dict[str, int] = {}

        # Per-game scoring
        self._scores: dict[str, int] = {"team_1": 0, "team_2": 0}
        self._bags: dict[str, int] = {"team_1": 0, "team_2": 0}

        # History / highlights
        self._trick_history: list[dict] = []  # tricks this hand
        self._hand_history: list[dict] = []  # completed hands this game
        self._highlight_turns: list[int] = []

    @property
    def display_name(self) -> str:
        return "Spades"

    # ------------------------------------------------------------------
    # Team helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _get_team(player_id: str) -> str:
        return PLAYER_TEAM[player_id]

    @staticmethod
    def _get_partner(player_id: str) -> str:
        return PARTNER[player_id]

    def _team_tricks(self, team: str) -> int:
        return sum(self._tricks_taken[p] for p in TEAMS[team])

    # ------------------------------------------------------------------
    # MultiplayerSeriesEvent interface
    # ------------------------------------------------------------------

    def _start_new_game(self) -> None:
        self._game_number += 1
        if self._game_number > self._games_per_match:
            self._terminal = True
            return

        self._scores = {"team_1": 0, "team_2": 0}
        self._bags = {"team_1": 0, "team_2": 0}
        self._hand_number = 0
        self._dealer_idx = -1  # will increment to 0 on first hand
        self._hand_history = []
        self._highlight_turns = []
        self._turn_number = 0

        self._start_new_hand()

    def _start_new_hand(self) -> None:
        self._hand_number += 1
        self._dealer_idx = (self._dealer_idx + 1) % 4
        # Player left of dealer leads bidding and trick 1
        leader_idx = (self._dealer_idx + 1) % 4
        self._phase = Phase.BID
        self._bid_order_idx = 0
        self._bid_start_idx = leader_idx  # offset for bid rotation
        self._bids = {p: None for p in self._player_ids}
        self._trick_number = 0
        self._current_trick = []
        self._trick_leader = PLAY_ORDER[leader_idx]
        self._trick_play_idx = 0
        self._spades_broken = False
        self._tricks_taken = {p: 0 for p in self._player_ids}
        self._team_contracts = {"team_1": 0, "team_2": 0}
        self._trick_history = []

        # Deal
        deck = list(FULL_DECK)
        self._rng.shuffle(deck)
        for i, pid in enumerate(PLAY_ORDER):
            self._hands[pid] = _sort_hand(deck[i * 13 : (i + 1) * 13])

    # ------------------------------------------------------------------
    # Core interface
    # ------------------------------------------------------------------

    def current_player(self) -> str:
        if self._phase == Phase.BID:
            return PLAY_ORDER[(self._bid_start_idx + self._bid_order_idx) % 4]
        else:
            # Play phase: cycle from trick leader
            leader_idx = PLAY_ORDER.index(self._trick_leader)
            idx = (leader_idx + self._trick_play_idx) % 4
            return PLAY_ORDER[idx]

    def get_prompt(self, player_id: str) -> str:
        label = self._player_labels[player_id]
        partner = self._get_partner(player_id)
        partner_label = self._player_labels[partner]
        team = self._get_team(player_id)
        opp_team = "team_2" if team == "team_1" else "team_1"

        lines: list[str] = []
        lines.append(f"You are Player {label} in a game of Spades.")
        lines.append(f"Your partner is Player {partner_label}. You are on {team.replace('_', ' ').title()}.")
        lines.append("")

        # Match context
        if self._games_per_match > 1:
            lines.append(f"Game {self._game_number} of {self._games_per_match}.")
            score_parts = [
                f"{self._player_labels[p]}: {self._match_scores[p]:.0f}"
                for p in self._player_ids
            ]
            lines.append(f"Match scores: {', '.join(score_parts)}")
            lines.append("")

        # Game score
        lines.append(f"Game score — {team.replace('_', ' ').title()}: {self._scores[team]}, "
                      f"{opp_team.replace('_', ' ').title()}: {self._scores[opp_team]}")
        lines.append(f"Bags — Your team: {self._bags[team]}, Opponents: {self._bags[opp_team]}")
        lines.append(f"Hand {self._hand_number} of up to {self._hand_limit}. First to {self._target_score} wins.")
        lines.append("")

        # Hand
        hand = _sort_hand(self._hands[player_id])
        lines.append(f"Your hand ({len(hand)} cards): {', '.join(hand)}")
        lines.append("")

        if self._phase == Phase.BID:
            lines.extend(self._bid_prompt_lines(player_id))
        else:
            lines.extend(self._play_prompt_lines(player_id))

        return "\n".join(lines)

    def _bid_prompt_lines(self, player_id: str) -> list[str]:
        lines: list[str] = []
        lines.append("=== BIDDING PHASE ===")
        lines.append("")

        # Show bids already made
        any_bid = False
        for pid in PLAY_ORDER:
            if self._bids[pid] is not None:
                bl = self._player_labels[pid]
                team_label = self._get_team(pid).replace("_", " ").title()
                bid_desc = "Nil" if self._bids[pid] == 0 else str(self._bids[pid])
                lines.append(f"  Player {bl} ({team_label}): {bid_desc}")
                any_bid = True
        if any_bid:
            lines.append("")

        partner = self._get_partner(player_id)
        if self._bids[partner] is not None:
            lines.append(f"Your partner bid {self._bids[partner]}.")
        else:
            lines.append("Your partner has not bid yet.")
        lines.append("")

        lines.append("Bid the number of tricks (0-13) you expect to take individually.")
        lines.append("Your bid will be combined with your partner's to form your team contract.")
        lines.append("A bid of 0 is a Nil bid — you must take zero tricks (bonus +100 if successful, penalty -100 if not).")
        lines.append("")
        lines.append('Respond with ONLY a JSON object: {"reasoning": "...", "action": "bid", "bid": <0-13>}')
        lines.append("Do NOT write anything outside the JSON.")

        return lines

    def _play_prompt_lines(self, player_id: str) -> list[str]:
        lines: list[str] = []
        lines.append("=== TRICK PLAY ===")
        lines.append("")

        # Contracts
        lines.append("Team contracts:")
        for t in ("team_1", "team_2"):
            members = TEAMS[t]
            bids = [f"Player {self._player_labels[p]}: {self._bids[p]}" for p in members]
            nil_note = ""
            for p in members:
                if self._bids[p] == 0:
                    nil_note += f" (Player {self._player_labels[p]} bid Nil!)"
            lines.append(f"  {t.replace('_', ' ').title()}: {self._team_contracts[t]} ({', '.join(bids)}){nil_note}")
        lines.append("")

        # Tricks taken
        lines.append("Tricks taken this hand:")
        for t in ("team_1", "team_2"):
            team_total = self._team_tricks(t)
            individual = ", ".join(
                f"Player {self._player_labels[p]}: {self._tricks_taken[p]}" for p in TEAMS[t]
            )
            lines.append(f"  {t.replace('_', ' ').title()}: {team_total} ({individual})")
        lines.append("")

        lines.append(f"Trick {self._trick_number + 1} of 13.")
        lines.append(f"Spades broken: {'Yes' if self._spades_broken else 'No'}")
        lines.append("")

        # Current trick
        if self._current_trick:
            led_suit = _card_suit(self._current_trick[0]["card"])
            lines.append(f"Suit led: {led_suit}")
            lines.append("Cards played this trick:")
            for entry in self._current_trick:
                lines.append(f"  Player {self._player_labels[entry['player']]}: {entry['card']}")
            lines.append("")

            # Check if must follow suit
            hand = self._hands[player_id]
            has_led_suit = any(_card_suit(c) == led_suit for c in hand)
            if has_led_suit:
                lines.append(f"You MUST follow suit ({led_suit}).")
            else:
                lines.append(f"You are void in {led_suit} — you may play any card.")
        else:
            lines.append("You are leading this trick.")
            if not self._spades_broken:
                hand = self._hands[player_id]
                has_non_spade = any(_card_suit(c) != "♠" for c in hand)
                if has_non_spade:
                    lines.append("Spades have NOT been broken — you cannot lead a spade unless you have only spades.")
                else:
                    lines.append("You have only spades remaining — you may lead a spade.")
        lines.append("")

        lines.append("Rules: Must follow the led suit if able. Highest card of the led suit wins, "
                      "unless trumped by a spade (highest spade wins). "
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

    def validate_action(self, player_id: str, action: dict) -> ValidationResult:
        if self._phase == Phase.BID:
            return self._validate_bid(player_id, action)
        else:
            return self._validate_play(player_id, action)

    def _validate_bid(self, player_id: str, action: dict) -> ValidationResult:
        if action.get("action") != "bid":
            return ValidationResult(legal=False, reason="Expected action 'bid' during bidding phase.")

        bid = action.get("bid")
        if not isinstance(bid, int) or bid < 0 or bid > 13:
            return ValidationResult(legal=False, reason="Bid must be an integer from 0 to 13.")

        return ValidationResult(legal=True, reason=None)

    def _validate_play(self, player_id: str, action: dict) -> ValidationResult:
        if action.get("action") != "play":
            return ValidationResult(legal=False, reason="Expected action 'play' during trick play phase.")

        card = action.get("card", "")
        hand = self._hands[player_id]

        # Normalize card string: accept common variations
        card = self._normalize_card(card)

        if card not in hand:
            return ValidationResult(
                legal=False,
                reason=f"Card '{action.get('card', '')}' is not in your hand. Your hand: {', '.join(hand)}",
            )

        # Follow suit
        if self._current_trick:
            led_suit = _card_suit(self._current_trick[0]["card"])
            has_led_suit = any(_card_suit(c) == led_suit for c in hand)
            if has_led_suit and _card_suit(card) != led_suit:
                return ValidationResult(
                    legal=False,
                    reason=f"You must follow suit ({led_suit}). You have cards of that suit.",
                )
        else:
            # Leading: can't lead spades unless broken or only spades
            if _card_suit(card) == "♠" and not self._spades_broken:
                has_non_spade = any(_card_suit(c) != "♠" for c in hand)
                if has_non_spade:
                    return ValidationResult(
                        legal=False,
                        reason="Spades have not been broken. You cannot lead a spade unless you have only spades.",
                    )

        return ValidationResult(legal=True, reason=None)

    @staticmethod
    def _normalize_card(card: str) -> str:
        """Accept common card format variations and normalize to our format."""
        # Map text suit names to symbols
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

    def apply_action(self, player_id: str, action: dict) -> None:
        self._turn_number += 1
        if self._phase == Phase.BID:
            self._apply_bid(player_id, action)
        else:
            self._apply_play(player_id, action)

    def _apply_bid(self, player_id: str, action: dict) -> None:
        bid = action["bid"]
        self._bids[player_id] = bid

        # Highlight nil bids
        if bid == 0:
            self._highlight_turns.append(self._turn_number)

        self._bid_order_idx += 1

        if self._bid_order_idx >= 4:
            # All bids in — compute team contracts and transition to play
            for t, members in TEAMS.items():
                # Nil bids contribute 0 to team contract
                self._team_contracts[t] = sum(
                    b for p in members if (b := self._bids[p] or 0) > 0
                )
            self._phase = Phase.PLAY
            self._trick_number = 0
            self._trick_play_idx = 0
            self._current_trick = []
            self._trick_leader = "player_a"

    def _apply_play(self, player_id: str, action: dict) -> None:
        card = self._normalize_card(action["card"])
        self._hands[player_id].remove(card)

        self._current_trick.append({"player": player_id, "card": card})

        # Check if spades broken
        if _card_suit(card) == "♠" and not self._spades_broken:
            self._spades_broken = True
            self._highlight_turns.append(self._turn_number)

        self._trick_play_idx += 1

        if self._trick_play_idx >= 4:
            # Trick complete — resolve
            self._resolve_trick()

    def _resolve_trick(self) -> None:
        led_suit = _card_suit(self._current_trick[0]["card"])
        winner = _trick_winner(self._current_trick, led_suit)
        self._tricks_taken[winner] += 1

        self._trick_history.append({
            "trick_number": self._trick_number + 1,
            "leader": self._trick_leader,
            "cards": list(self._current_trick),
            "winner": winner,
            "led_suit": led_suit,
        })

        self._trick_number += 1

        if self._trick_number >= 13:
            # Hand complete
            self._score_hand()
        else:
            # Next trick
            self._trick_leader = winner
            self._trick_play_idx = 0
            self._current_trick = []

    def _score_hand(self) -> None:
        """Score the completed hand and check game-end conditions."""
        hand_result: dict = {"hand_number": self._hand_number, "bids": dict(self._bids), "teams": {}}
        prev_scores = dict(self._scores)

        for team, members in TEAMS.items():
            team_tricks = self._team_tricks(team)
            contract = self._team_contracts[team]
            hand_points = 0
            nil_results: list[dict] = []

            # Score nil bids individually
            for pid in members:
                if self._bids[pid] is not None and self._bids[pid] == 0:
                    if self._tricks_taken[pid] == 0:
                        hand_points += NIL_BONUS
                        nil_results.append({"player": pid, "success": True})
                        self._highlight_turns.append(self._turn_number)
                    else:
                        hand_points -= NIL_BONUS
                        nil_results.append({"player": pid, "success": False})
                        self._highlight_turns.append(self._turn_number)

            # Score non-nil contract (only non-nil players' tricks count toward contract)
            non_nil_tricks = sum(
                self._tricks_taken[p] for p in members if (self._bids[p] or 0) > 0
            )

            if contract > 0:
                if non_nil_tricks >= contract:
                    overtricks = non_nil_tricks - contract
                    hand_points += contract * 10 + overtricks
                    self._bags[team] += overtricks

                    # Bag penalty check
                    if self._bags[team] >= BAG_PENALTY_THRESHOLD:
                        hand_points += BAG_PENALTY
                        self._bags[team] -= BAG_PENALTY_THRESHOLD
                        self._highlight_turns.append(self._turn_number)
                else:
                    # Set
                    hand_points -= contract * 10
                    self._highlight_turns.append(self._turn_number)

            self._scores[team] += hand_points

            hand_result["teams"][team] = {
                "contract": contract,
                "tricks": team_tricks,
                "non_nil_tricks": non_nil_tricks,
                "hand_points": hand_points,
                "nil_results": nil_results,
                "total_score": self._scores[team],
                "bags": self._bags[team],
            }

        # Detect lead change
        was_leading = prev_scores["team_1"] > prev_scores["team_2"]
        now_leading = self._scores["team_1"] > self._scores["team_2"]
        if prev_scores["team_1"] != prev_scores["team_2"] and was_leading != now_leading:
            self._highlight_turns.append(self._turn_number)

        # Detect game point (team at 400+)
        for team in ("team_1", "team_2"):
            if self._scores[team] >= 400 and prev_scores[team] < 400:
                self._highlight_turns.append(self._turn_number)

        self._hand_history.append(hand_result)

        # Check game-end conditions
        if self._check_game_end():
            return

        # Start next hand
        self._start_new_hand()

    def _check_game_end(self) -> bool:
        """Check if the game is over. Returns True if game ended."""
        t1 = self._scores["team_1"]
        t2 = self._scores["team_2"]

        # Floor check: team at -200 or below loses immediately
        if t1 <= FLOOR_SCORE or t2 <= FLOOR_SCORE:
            self._end_game()
            return True

        # Target check: first to 500
        if t1 >= self._target_score or t2 >= self._target_score:
            self._end_game()
            return True

        # Hand limit
        if self._hand_number >= self._hand_limit:
            self._end_game()
            return True

        return False

    def _end_game(self) -> None:
        """Finalize game scores and check if match is over."""
        t1 = self._scores["team_1"]
        t2 = self._scores["team_2"]

        # Both players on winning team get the team score
        # Both players on losing team get their team score
        for pid in self._player_ids:
            team = self._get_team(pid)
            self._match_scores[pid] += float(self._scores[team])

        # Check if more games to play
        if self._game_number >= self._games_per_match:
            self._terminal = True
        else:
            self._start_new_game()

    def forfeit_turn(self, player_id: str) -> None:
        if self._phase == Phase.BID:
            self.apply_action(player_id, {"action": "bid", "bid": FORFEIT_BID, "reasoning": "forfeit"})
        else:
            card = self._forfeit_card(player_id)
            self.apply_action(player_id, {"action": "play", "card": card, "reasoning": "forfeit"})

    def _forfeit_card(self, player_id: str) -> str:
        """Choose a legal card for forfeit: lowest legal card."""
        hand = self._hands[player_id]

        if self._current_trick:
            led_suit = _card_suit(self._current_trick[0]["card"])
            suited = [c for c in hand if _card_suit(c) == led_suit]
            if suited:
                # Must follow suit — play lowest of that suit
                return min(suited, key=_card_rank_value)
            # Void — play lowest non-spade if possible, else lowest spade
            non_spades = [c for c in hand if _card_suit(c) != "♠"]
            if non_spades:
                return min(non_spades, key=_card_rank_value)
            return min(hand, key=_card_rank_value)
        else:
            # Leading
            if not self._spades_broken:
                non_spades = [c for c in hand if _card_suit(c) != "♠"]
                if non_spades:
                    return min(non_spades, key=_card_rank_value)
            return min(hand, key=_card_rank_value)

    def get_scores(self) -> dict[str, float]:
        return dict(self._match_scores)

    def get_state_snapshot(self) -> dict:
        return {
            "phase": self._phase.value,
            "game_number": self._game_number,
            "games_per_match": self._games_per_match,
            "hand_number": self._hand_number,
            "trick_number": self._trick_number + 1,
            "turn_number": self._turn_number,
            "hands": {p: list(self._hands.get(p, [])) for p in self._player_ids},
            "bids": {p: self._bids.get(p) for p in self._player_ids},
            "team_contracts": dict(self._team_contracts),
            "tricks_taken": {p: self._tricks_taken.get(p, 0) for p in self._player_ids},
            "current_trick": list(self._current_trick),
            "trick_leader": self._trick_leader,
            "dealer": PLAY_ORDER[self._dealer_idx],
            "scores": dict(self._scores),
            "bags": dict(self._bags),
            "spades_broken": self._spades_broken,
            "trick_history": [dict(t) for t in self._trick_history],
            "hand_history": [dict(h) for h in self._hand_history],
            "terminal": self._terminal,
            "match_scores": dict(self._match_scores),
            "mode": self._mode,
        }

    def get_highlight_hands(self) -> list[int]:
        return list(self._highlight_turns)

    # ------------------------------------------------------------------
    # Match forfeit
    # ------------------------------------------------------------------

    def award_forfeit_wins(self, forfeiting_player_id: str) -> None:
        """Award remaining game points to non-forfeiting team."""
        forfeiting_team = self._get_team(forfeiting_player_id)
        winning_team = "team_2" if forfeiting_team == "team_1" else "team_1"

        # Give winning team target score for remaining games
        remaining = self._games_per_match - self._game_number + 1
        for pid in self._player_ids:
            team = self._get_team(pid)
            if team == winning_team:
                self._match_scores[pid] += float(self._target_score * remaining)

        self._terminal = True
