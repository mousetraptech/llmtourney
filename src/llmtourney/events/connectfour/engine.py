"""Connect Four engine — implements the Event ABC for multi-game series.

A single Connect Four game has at most 42 turns (6×7 board). Matches play
a series of games (default 9) with alternating first-player to reduce
positional advantage. Scoring: 1.0 per win, 0.5 per draw, 0.0 per loss.
"""

from __future__ import annotations

from pathlib import Path

from llmtourney.events.base import Event, ValidationResult
from llmtourney.core.schemas import load_schema

__all__ = ["ConnectFourEvent"]

ROWS = 6
COLS = 7


class ConnectFourEvent(Event):
    """Multi-game Connect Four series engine.

    Implements the Event ABC for use in the llmtourney tournament system.
    """

    def __init__(self, games_per_match: int = 9) -> None:
        schema_path = Path(__file__).parent / "schema.json"
        self._action_schema = load_schema(schema_path)
        self._games_per_match = games_per_match

        # State initialised by reset()
        self._board: list[list[str]] = []
        self._active_player: str = ""
        self._game_number: int = 0
        self._game_results: list[str] = []
        self._series_scores: dict[str, float] = {}
        self._turn_number: int = 0
        self._game_turn: int = 0
        self._terminal: bool = False
        self._first_player: str = ""
        self._winner: str | None = None

        # Telemetry extras
        self._last_column: int | None = None
        self._last_row: int | None = None
        self._last_was_valid: bool = True
        self._last_violation_type: str | None = None

    # ------------------------------------------------------------------
    # Event ABC
    # ------------------------------------------------------------------

    def reset(self, seed: int) -> None:
        self._board = [[""] * COLS for _ in range(ROWS)]
        self._active_player = "player_a"
        self._game_number = 1
        self._game_results = []
        self._series_scores = {"player_a": 0.0, "player_b": 0.0}
        self._turn_number = 0
        self._game_turn = 0
        self._terminal = False
        self._first_player = "player_a"
        self._winner = None
        self._clear_telemetry()

    def current_player(self) -> str:
        return self._active_player

    def get_prompt(self, player_id: str) -> str:
        mark = self._mark_for(player_id)
        opponent = self._opponent(player_id)

        board_str = self._render_board()
        available = self._available_columns()
        avail_str = ", ".join(str(c) for c in available)

        lines = [
            f"Connect Four \u2014 Game {self._game_number}/{self._games_per_match}",
            f"You are {mark} ({player_id}). "
            f"Series: You {self._series_scores[player_id]}, "
            f"Opponent {self._series_scores[opponent]}",
            "",
            "Board (6 rows \u00d7 7 columns, pieces drop to bottom):",
            board_str,
            "",
            f"Available columns: [{avail_str}]",
            "",
            'Respond with JSON: {"action": "play", "column": <0-6>, '
            '"reasoning": "..."}',
            "",
            "IMPORTANT: Respond with ONLY a single JSON object. "
            "No markdown fences, no explanation before or after. "
            "Just the raw JSON.",
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
        if act != "play":
            return ValidationResult(
                legal=False, reason=f"Unknown action: {act!r}. Use 'play'."
            )

        col = action.get("column")
        if not isinstance(col, int) or not (0 <= col < COLS):
            return ValidationResult(
                legal=False,
                reason=f"Column must be an integer 0-6. Got: {col!r}.",
            )

        # Check column not full (top row empty)
        if self._board[0][col] != "":
            return ValidationResult(
                legal=False,
                reason=f"Column {col} is full.",
            )

        return ValidationResult(legal=True)

    def apply_action(self, player_id: str, action: dict) -> None:
        col = action["column"]
        mark = self._mark_for(player_id)

        # Drop piece to lowest empty row
        row = self._drop_row(col)
        self._board[row][col] = mark
        self._turn_number += 1
        self._game_turn += 1

        # Telemetry
        self._last_column = col
        self._last_row = row
        self._last_was_valid = True
        self._last_violation_type = None

        # Check for win or draw
        if self._check_winner():
            self._winner = player_id
            self._record_game_result(
                "x_wins" if mark == "X" else "o_wins"
            )
            self._advance_or_end()
        elif self._is_draw():
            self._winner = None
            self._record_game_result("draw")
            self._advance_or_end()
        else:
            self._active_player = self._opponent(player_id)

    def forfeit_turn(self, player_id: str) -> None:
        """Place piece in first non-full column (left to right)."""
        mark = self._mark_for(player_id)

        for col in range(COLS):
            if self._board[0][col] == "":
                row = self._drop_row(col)
                self._board[row][col] = mark
                self._turn_number += 1
                self._game_turn += 1

                self._last_column = col
                self._last_row = row
                self._last_was_valid = False
                self._last_violation_type = "forfeit"

                if self._check_winner():
                    self._winner = player_id
                    self._record_game_result(
                        "x_wins" if mark == "X" else "o_wins"
                    )
                    self._advance_or_end()
                elif self._is_draw():
                    self._winner = None
                    self._record_game_result("draw")
                    self._advance_or_end()
                else:
                    self._active_player = self._opponent(player_id)
                return

    def force_forfeit_match(self, player_id: str) -> None:
        """Force-end the match due to stuck-loop detection."""
        self._terminal = True

    def is_terminal(self) -> bool:
        return self._terminal

    def get_scores(self) -> dict[str, float]:
        return dict(self._series_scores)

    def get_state_snapshot(self) -> dict:
        return {
            "board": [row[:] for row in self._board],
            "scores": dict(self._series_scores),
            "hand_number": self._game_number,
            "game_turn": self._game_turn,
            "turn_number": self._turn_number,
            "active_player": self._active_player,
            "result": self._game_results[-1] if self._game_results else None,
            "series_scores": dict(self._series_scores),
            "terminal": self._terminal,
            # Telemetry
            "last_column": self._last_column,
            "last_row": self._last_row,
            "was_valid": self._last_was_valid,
            "violation_type": self._last_violation_type,
        }

    @property
    def action_schema(self) -> dict:
        return self._action_schema

    def get_highlight_hands(self) -> list[int]:
        """Return game numbers where a player won."""
        highlights = []
        for i, result in enumerate(self._game_results):
            if result in ("x_wins", "o_wins"):
                highlights.append(i + 1)  # 1-indexed
        return highlights

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _mark_for(self, player_id: str) -> str:
        """Return 'X' or 'O' based on who goes first this game."""
        if player_id == self._first_player:
            return "X"
        return "O"

    def _drop_row(self, col: int) -> int:
        """Find the lowest empty row in a column (gravity)."""
        for r in range(ROWS - 1, -1, -1):
            if self._board[r][col] == "":
                return r
        raise ValueError(f"Column {col} is full")

    def _available_columns(self) -> list[int]:
        """Return list of columns that are not full."""
        return [c for c in range(COLS) if self._board[0][c] == ""]

    def _render_board(self) -> str:
        """Render ASCII board with column numbers and row indices."""
        symbols = {"": " ", "X": "X", "O": "O"}
        lines = ["  " + "   ".join(f"{c}" for c in range(COLS))]
        lines.append("+---" * COLS + "+")
        for r in range(ROWS):
            cells = "| " + " | ".join(
                f"{symbols[self._board[r][c]]}" for c in range(COLS)
            ) + " |"
            lines.append(f"{cells}  {r}")
            lines.append("+---" * COLS + "+")
        return "\n".join(lines)

    def _check_winner(self) -> str | None:
        """Scan all groups of 4 for a win. Return winning mark or None."""
        b = self._board
        # Horizontal
        for r in range(ROWS):
            for c in range(COLS - 3):
                if b[r][c] != "" and b[r][c] == b[r][c+1] == b[r][c+2] == b[r][c+3]:
                    return b[r][c]
        # Vertical
        for r in range(ROWS - 3):
            for c in range(COLS):
                if b[r][c] != "" and b[r][c] == b[r+1][c] == b[r+2][c] == b[r+3][c]:
                    return b[r][c]
        # Diagonal down-right
        for r in range(ROWS - 3):
            for c in range(COLS - 3):
                if b[r][c] != "" and b[r][c] == b[r+1][c+1] == b[r+2][c+2] == b[r+3][c+3]:
                    return b[r][c]
        # Diagonal up-right
        for r in range(3, ROWS):
            for c in range(COLS - 3):
                if b[r][c] != "" and b[r][c] == b[r-1][c+1] == b[r-2][c+2] == b[r-3][c+3]:
                    return b[r][c]
        return None

    def _is_draw(self) -> bool:
        """All 42 cells filled with no winner."""
        return self._game_turn >= ROWS * COLS

    def _record_game_result(self, result: str) -> None:
        """Record game result and update series scores."""
        self._game_results.append(result)

        if result == "x_wins":
            x_player = self._first_player
            self._series_scores[x_player] += 1.0
        elif result == "o_wins":
            o_player = self._opponent(self._first_player)
            self._series_scores[o_player] += 1.0
        else:  # draw
            self._series_scores["player_a"] += 0.5
            self._series_scores["player_b"] += 0.5

    def _advance_or_end(self) -> None:
        """Start next game or end the match."""
        self._game_number += 1
        if self._game_number > self._games_per_match:
            self._terminal = True
            return

        # Reset board for next game
        self._board = [[""] * COLS for _ in range(ROWS)]
        self._game_turn = 0
        self._winner = None
        # Alternate first player
        self._first_player = self._opponent(self._first_player)
        self._active_player = self._first_player
        self._clear_telemetry()

    def _clear_telemetry(self) -> None:
        self._last_column = None
        self._last_row = None
        self._last_was_valid = True
        self._last_violation_type = None

    @staticmethod
    def _opponent(player_id: str) -> str:
        return "player_b" if player_id == "player_a" else "player_a"
