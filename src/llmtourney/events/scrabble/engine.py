"""Scrabble engine — implements the Event ABC for standard Scrabble.

Two-player Scrabble with:
- Standard 15×15 board with premium squares
- 100-tile bag with standard distribution
- TWL06 dictionary validation (no retries on invalid words)
- Cross-word scoring
- Bingo bonus (+50 for using all 7 tiles)
- Terminal on empty bag + empty rack, or 6 consecutive passes
"""

from __future__ import annotations

import random

from llmtourney.events.base import Event, ValidationResult
from llmtourney.events.scrabble.board import (
    SIZE,
    CENTER,
    Board,
    create_full_bag,
    rack_value,
    tile_value,
)
from llmtourney.events.scrabble.dictionary import ScrabbleDictionary

__all__ = ["ScrabbleEvent"]

_SYSTEM_INSTRUCTION = (
    "Only play words you are confident exist in the Official Scrabble "
    "Players Dictionary. If uncertain, exchange tiles or pass."
)


class ScrabbleEvent(Event):
    """Standard two-player Scrabble engine.

    Implements the Event ABC for use in the llmtourney tournament system.
    """

    def __init__(self) -> None:
        self._player_ids = ["player_a", "player_b"]
        self._action_schema = self._load_event_schema()
        self._dictionary = ScrabbleDictionary()

        # State initialised by reset()
        self._rng: random.Random | None = None
        self._board: Board = Board()
        self._bag: list[str] = []
        self._racks: dict[str, list[str]] = {}
        self._scores: dict[str, int] = {}
        self._active_player: str = ""
        self._terminal: bool = False
        self._consecutive_passes: int = 0
        self._turn_number: int = 0
        self._highlight_turns: list[int] = []

        # Telemetry extras (updated by apply_action / forfeit_turn)
        self._last_word_played: str | None = None
        self._last_cross_words: list[str] = []
        self._last_points_scored: int = 0
        self._last_was_valid: bool = True
        self._last_violation_type: str | None = None
        self._last_rack_before: list[str] = []
        self._last_rack_after: list[str] = []
        self._last_bingo: bool = False

    # ------------------------------------------------------------------
    # Event ABC
    # ------------------------------------------------------------------

    def reset(self, seed: int) -> None:
        self._rng = random.Random(seed)
        self._board = Board()
        self._bag = create_full_bag()
        self._rng.shuffle(self._bag)
        self._racks = {"player_a": [], "player_b": []}
        self._scores = {"player_a": 0, "player_b": 0}
        self._consecutive_passes = 0
        self._turn_number = 0
        self._terminal = False
        self._highlight_turns = []

        # Deal 7 tiles each
        for pid in ("player_a", "player_b"):
            self._draw_tiles(pid, 7)

        # Player A goes first
        self._active_player = "player_a"
        self._clear_telemetry_extras()

    def current_player(self) -> str:
        return self._active_player

    def get_prompt(self, player_id: str) -> str:
        opponent = self._opponent(player_id)
        label = "A" if player_id == "player_a" else "B"
        rack_str = " ".join(sorted(self._racks[player_id]))
        board_ascii = self._board.to_ascii()

        lines = [
            f"You are playing Scrabble. You are Player {label}.",
            "",
            _SYSTEM_INSTRUCTION,
            "",
            "Game state:",
            f"- Your score: {self._scores[player_id]} | "
            f"Opponent score: {self._scores[opponent]}",
            f"- Tiles remaining in bag: {len(self._bag)}",
            f"- Consecutive passes: {self._consecutive_passes} (game ends at 6)",
            "",
            f"Your rack: {rack_str}",
            "",
            "Board (row, col are 0-indexed; 3W/2W/3L/2L = premium squares; "
            "lowercase = blank tile):",
            board_ascii,
            "",
            "Rules reminder:",
            "- First move must cover the center square (row 7, col 7).",
            "- Every subsequent move must connect to existing tiles on the board.",
            "- All words formed (including cross-words) must be valid.",
            "- Blanks (? in your rack) can represent any letter — declare via "
            "blank_assignments.",
            "- Using all 7 tiles from your rack in one play earns a 50-point bingo bonus.",
            "- Exchange requires at least 7 tiles in the bag.",
            "",
            "IMPORTANT: Respond with ONLY a single JSON object. No markdown fences, "
            "no explanation before or after. Just the raw JSON.",
            "",
            "Examples:",
            '  {"action": "play", "word": "HELLO", "position": [7, 5], '
            '"direction": "across", "reasoning": "..."}',
            '  {"action": "play", "word": "HELLO", "position": [7, 5], '
            '"direction": "across", "blank_assignments": {"4": "O"}, '
            '"reasoning": "..."}',
            '  {"action": "exchange", "tiles_to_exchange": ["Q", "V"], '
            '"reasoning": "..."}',
            '  {"action": "pass", "reasoning": "..."}',
        ]
        return "\n".join(lines)

    def get_retry_prompt(self, player_id: str, error_reason: str) -> str:
        return (
            f"Your last action was invalid: {error_reason}\n\n"
            f"{self.get_prompt(player_id)}"
        )

    def validate_action(self, player_id: str, action: dict) -> ValidationResult:
        if player_id != self._active_player:
            return ValidationResult(legal=False, reason="Not your turn.")

        act = action.get("action")
        if act == "pass":
            return ValidationResult(legal=True)
        if act == "exchange":
            return self._validate_exchange(player_id, action)
        if act == "play":
            return self._validate_play(player_id, action)
        return ValidationResult(legal=False, reason=f"Unknown action: {act}")

    def apply_action(self, player_id: str, action: dict) -> None:
        self._turn_number += 1
        act = action["action"]

        if act == "pass":
            self._apply_pass(player_id)
        elif act == "exchange":
            self._apply_exchange(player_id, action)
        elif act == "play":
            self._apply_play(player_id, action)

        self._check_terminal()
        if not self._terminal:
            self._active_player = self._opponent(player_id)

    def forfeit_turn(self, player_id: str) -> None:
        """Forfeit counts as a pass."""
        self._turn_number += 1
        rack_before = list(self._racks.get(player_id, []))
        self._consecutive_passes += 1

        self._last_word_played = None
        self._last_cross_words = []
        self._last_points_scored = 0
        self._last_was_valid = False
        self._last_violation_type = "forfeit"
        self._last_rack_before = rack_before
        self._last_rack_after = list(self._racks.get(player_id, []))
        self._last_bingo = False

        self._check_terminal()
        if not self._terminal:
            self._active_player = self._opponent(player_id)

    def get_scores(self) -> dict[str, float]:
        """Return final scores with end-of-game rack adjustments."""
        scores = dict(self._scores)

        if not self._terminal:
            return {k: float(v) for k, v in scores.items()}

        # Check if either player went out (empty rack)
        went_out = None
        for pid in ("player_a", "player_b"):
            if len(self._racks[pid]) == 0:
                went_out = pid
                break

        if went_out is not None:
            # Player who went out gets opponent's rack value added
            opp = self._opponent(went_out)
            opp_rack_val = rack_value(self._racks[opp])
            scores[went_out] += opp_rack_val
            scores[opp] -= opp_rack_val
        else:
            # No one went out: each player subtracts own rack value
            for pid in ("player_a", "player_b"):
                scores[pid] -= rack_value(self._racks[pid])

        return {k: float(v) for k, v in scores.items()}

    def get_state_snapshot(self) -> dict:
        return {
            "turn_number": self._turn_number,
            "scores": {k: v for k, v in self._scores.items()},
            "active_player": self._active_player,
            "tiles_remaining": len(self._bag),
            "consecutive_passes": self._consecutive_passes,
            "terminal": self._terminal,
            # Telemetry extras
            "word_played": self._last_word_played,
            "cross_words_formed": list(self._last_cross_words),
            "points_scored": self._last_points_scored,
            "was_valid": self._last_was_valid,
            "violation_type": self._last_violation_type,
            "rack_before": list(self._last_rack_before),
            "rack_after": list(self._last_rack_after),
            "bingo": self._last_bingo,
        }

    def get_highlight_hands(self) -> list[int]:
        return list(self._highlight_turns)

    # ------------------------------------------------------------------
    # Validation helpers
    # ------------------------------------------------------------------

    def _validate_exchange(
        self, player_id: str, action: dict
    ) -> ValidationResult:
        tiles = action.get("tiles_to_exchange", [])
        if not tiles:
            return ValidationResult(
                legal=False, reason="Must specify tiles to exchange."
            )
        if len(self._bag) < 7:
            return ValidationResult(
                legal=False,
                reason=f"Exchange requires >= 7 tiles in bag "
                f"(only {len(self._bag)} remain).",
            )

        # Check tiles are in rack
        rack_copy = list(self._racks[player_id])
        for t in tiles:
            t_upper = t.upper()
            if t_upper in rack_copy:
                rack_copy.remove(t_upper)
            elif "?" in rack_copy and t_upper == "?":
                rack_copy.remove("?")
            else:
                return ValidationResult(
                    legal=False,
                    reason=f"Tile '{t}' not in your rack.",
                )
        return ValidationResult(legal=True)

    def _validate_play(
        self, player_id: str, action: dict
    ) -> ValidationResult:
        word = action.get("word", "").upper()
        position = action.get("position", [])
        direction = action.get("direction", "")
        blank_assignments = action.get("blank_assignments") or {}

        if not word or len(word) < 2:
            return ValidationResult(
                legal=False, reason="Word must be at least 2 letters."
            )
        if direction not in ("across", "down"):
            return ValidationResult(
                legal=False, reason="Direction must be 'across' or 'down'."
            )
        if not isinstance(position, list) or len(position) != 2:
            return ValidationResult(
                legal=False, reason="Position must be [row, col]."
            )

        row, col = int(position[0]), int(position[1])

        # Check bounds
        end_row = row + (len(word) - 1 if direction == "down" else 0)
        end_col = col + (len(word) - 1 if direction == "across" else 0)
        if row < 0 or col < 0 or end_row >= SIZE or end_col >= SIZE:
            return ValidationResult(
                legal=False, reason="Word goes off the board."
            )

        # Parse blank assignments: map position index -> letter
        blank_pos: set[int] = set()
        for key, val in blank_assignments.items():
            try:
                idx = int(key)
            except (ValueError, TypeError):
                return ValidationResult(
                    legal=False,
                    reason=f"Invalid blank_assignments key: {key}. "
                    f"Use 0-indexed position in word.",
                )
            if idx < 0 or idx >= len(word):
                return ValidationResult(
                    legal=False,
                    reason=f"Blank assignment index {idx} out of range.",
                )
            if val.upper() != word[idx]:
                return ValidationResult(
                    legal=False,
                    reason=f"Blank at position {idx} declared as '{val}' "
                    f"but word has '{word[idx]}'.",
                )
            blank_pos.add(idx)

        # Determine which tiles come from rack vs board
        rack_copy = list(self._racks[player_id])
        tiles_needed: list[str] = []  # tiles to consume from rack
        any_new_tile = False

        for i, letter in enumerate(word):
            r = row + (i if direction == "down" else 0)
            c = col + (i if direction == "across" else 0)

            existing = self._board.get(r, c)
            if existing is not None:
                # Board already has a tile here — must match
                if existing[0] != letter:
                    return ValidationResult(
                        legal=False,
                        reason=f"Board has '{existing[0]}' at ({r},{c}) "
                        f"but word needs '{letter}'.",
                    )
                # Don't consume a rack tile for existing board tiles
            else:
                any_new_tile = True
                if i in blank_pos:
                    tiles_needed.append("?")
                else:
                    tiles_needed.append(letter)

        if not any_new_tile:
            return ValidationResult(
                legal=False, reason="Must place at least one new tile."
            )

        # Check rack has the needed tiles
        for t in tiles_needed:
            if t in rack_copy:
                rack_copy.remove(t)
            else:
                return ValidationResult(
                    legal=False,
                    reason=f"Tile '{t}' not in your rack. "
                    f"Rack: {self._racks[player_id]}",
                )

        # First move must cover center
        if self._board.is_empty:
            covers_center = False
            for i in range(len(word)):
                r = row + (i if direction == "down" else 0)
                c = col + (i if direction == "across" else 0)
                if (r, c) == CENTER:
                    covers_center = True
                    break
            if not covers_center:
                return ValidationResult(
                    legal=False,
                    reason="First move must cover the center square "
                    "(row 7, col 7).",
                )
        else:
            # Must connect to existing tiles
            if not self._board.connects_to_existing(word, row, col, direction):
                return ValidationResult(
                    legal=False,
                    reason="Word must connect to existing tiles on the board.",
                )

        # Check main word in dictionary — but first compute the FULL
        # contiguous word on the main axis (extending past the player's
        # stated range into any adjacent existing tiles).
        full_word = self._get_full_word_on_axis(word, row, col, direction)
        if not self._dictionary.is_valid(full_word):
            return ValidationResult(
                legal=False,
                reason=f"invalid_word: '{full_word}' not in dictionary.",
            )

        # Check all cross-words are valid
        for i, letter in enumerate(word):
            r = row + (i if direction == "down" else 0)
            c = col + (i if direction == "across" else 0)

            if self._board.get(r, c) is not None:
                continue  # existing tile, no new cross-word

            cross = self._board.get_cross_word_if_placed(
                r, c, letter, direction
            )
            if cross is not None and not self._dictionary.is_valid(cross):
                return ValidationResult(
                    legal=False,
                    reason=f"invalid_word: cross-word '{cross}' "
                    f"at ({r},{c}) not in dictionary.",
                )

        return ValidationResult(legal=True)

    # ------------------------------------------------------------------
    # Action application
    # ------------------------------------------------------------------

    def _apply_pass(self, player_id: str) -> None:
        rack_before = list(self._racks[player_id])
        self._consecutive_passes += 1

        self._last_word_played = None
        self._last_cross_words = []
        self._last_points_scored = 0
        self._last_was_valid = True
        self._last_violation_type = None
        self._last_rack_before = rack_before
        self._last_rack_after = list(self._racks[player_id])
        self._last_bingo = False

    def _apply_exchange(self, player_id: str, action: dict) -> None:
        tiles = [t.upper() for t in action["tiles_to_exchange"]]
        rack_before = list(self._racks[player_id])

        # Draw new tiles first
        num_to_draw = len(tiles)
        new_tiles = self._bag[:num_to_draw]
        self._bag = self._bag[num_to_draw:]

        # Remove exchanged tiles from rack
        rack = self._racks[player_id]
        for t in tiles:
            rack.remove(t)

        # Add new tiles to rack
        rack.extend(new_tiles)

        # Return exchanged tiles to bag and shuffle
        self._bag.extend(tiles)
        self._rng.shuffle(self._bag)

        # Exchange resets consecutive passes
        self._consecutive_passes = 0

        self._last_word_played = None
        self._last_cross_words = []
        self._last_points_scored = 0
        self._last_was_valid = True
        self._last_violation_type = None
        self._last_rack_before = rack_before
        self._last_rack_after = list(self._racks[player_id])
        self._last_bingo = False

    def _apply_play(self, player_id: str, action: dict) -> None:
        word = action["word"].upper()
        row, col = int(action["position"][0]), int(action["position"][1])
        direction = action["direction"]
        blank_assignments = action.get("blank_assignments") or {}
        blank_pos: set[int] = {int(k) for k in blank_assignments}

        rack_before = list(self._racks[player_id])

        # Remove tiles from rack
        rack = self._racks[player_id]
        for i, letter in enumerate(word):
            r = row + (i if direction == "down" else 0)
            c = col + (i if direction == "across" else 0)
            if self._board.get(r, c) is None:
                if i in blank_pos:
                    rack.remove("?")
                else:
                    rack.remove(letter)

        # Place tiles on board
        newly_placed = self._board.place_word(
            word, row, col, direction, blank_pos
        )

        # Score
        points, cross_words = self._board.score_placement(
            word, row, col, direction, newly_placed
        )

        # Bingo bonus: used all 7 tiles from rack
        bingo = len(newly_placed) == 7
        if bingo:
            points += 50

        self._scores[player_id] += points
        self._consecutive_passes = 0

        # Refill rack
        self._draw_tiles(player_id, 7 - len(rack))

        # Telemetry
        self._last_word_played = word
        self._last_cross_words = cross_words
        self._last_points_scored = points
        self._last_was_valid = True
        self._last_violation_type = None
        self._last_rack_before = rack_before
        self._last_rack_after = list(self._racks[player_id])
        self._last_bingo = bingo

        # Highlight detection
        if bingo or points >= 50:
            self._highlight_turns.append(self._turn_number)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _get_full_word_on_axis(
        self, word: str, row: int, col: int, direction: str
    ) -> str:
        """Compute the full contiguous word on the main axis.

        Extends before and after the player's stated placement to include
        any adjacent existing tiles. This catches invalid extensions like
        playing ELATED next to MINE (forming MINEELATED).
        """
        # Build the letters from the stated placement (using existing board
        # tiles where present, new tiles where not)
        letters: list[str] = list(word.upper())

        if direction == "across":
            # Extend left from start
            c = col - 1
            while c >= 0 and self._board.get(row, c) is not None:
                letters.insert(0, self._board.get(row, c)[0])
                c -= 1
            # Extend right from end
            c = col + len(word)
            while c < SIZE and self._board.get(row, c) is not None:
                letters.append(self._board.get(row, c)[0])
                c += 1
        else:  # down
            # Extend up from start
            r = row - 1
            while r >= 0 and self._board.get(r, col) is not None:
                letters.insert(0, self._board.get(r, col)[0])
                r -= 1
            # Extend down from end
            r = row + len(word)
            while r < SIZE and self._board.get(r, col) is not None:
                letters.append(self._board.get(r, col)[0])
                r += 1

        return "".join(letters)

    def _draw_tiles(self, player_id: str, count: int) -> None:
        """Draw up to ``count`` tiles from the bag into the player's rack."""
        n = min(count, len(self._bag))
        drawn = self._bag[:n]
        self._bag = self._bag[n:]
        self._racks[player_id].extend(drawn)

    def _check_terminal(self) -> None:
        """Check if the game is over."""
        # 6 consecutive passes
        if self._consecutive_passes >= 6:
            self._terminal = True
            return

        # A player emptied their rack and bag is empty
        if len(self._bag) == 0:
            for pid in ("player_a", "player_b"):
                if len(self._racks[pid]) == 0:
                    self._terminal = True
                    return

    def _clear_telemetry_extras(self) -> None:
        self._last_word_played = None
        self._last_cross_words = []
        self._last_points_scored = 0
        self._last_was_valid = True
        self._last_violation_type = None
        self._last_rack_before = []
        self._last_rack_after = []
        self._last_bingo = False

    @staticmethod
    def _opponent(player_id: str) -> str:
        return "player_b" if player_id == "player_a" else "player_a"
