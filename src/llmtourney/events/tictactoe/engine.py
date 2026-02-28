"""Tic-Tac-Toe engine — implements the Event ABC for multi-game series.

A single tic-tac-toe game is at most 9 turns. Matches play a series of games
(default 9) with alternating first-player to reduce positional advantage.
Scoring: 1.0 per win, 0.5 per draw, 0.0 per loss.
"""

from __future__ import annotations

from llmtourney.events.base import TwoPlayerSeriesEvent, ValidationResult

__all__ = ["TicTacToeEvent"]

# Eight lines to check for a win: 3 rows, 3 cols, 2 diagonals
_WIN_LINES = [
    # Rows
    [(0, 0), (0, 1), (0, 2)],
    [(1, 0), (1, 1), (1, 2)],
    [(2, 0), (2, 1), (2, 2)],
    # Columns
    [(0, 0), (1, 0), (2, 0)],
    [(0, 1), (1, 1), (2, 1)],
    [(0, 2), (1, 2), (2, 2)],
    # Diagonals
    [(0, 0), (1, 1), (2, 2)],
    [(0, 2), (1, 1), (2, 0)],
]


class TicTacToeEvent(TwoPlayerSeriesEvent):
    """Multi-game tic-tac-toe series engine."""

    def __init__(self, games_per_match: int = 9) -> None:
        super().__init__(games_per_match)
        self._board: list[list[str]] = []
        self._winner: str | None = None

        # Telemetry extras
        self._last_position: list[int] | None = None
        self._last_was_valid: bool = True
        self._last_violation_type: str | None = None

    # ------------------------------------------------------------------
    # Event ABC
    # ------------------------------------------------------------------

    def reset(self, seed: int) -> None:
        super().reset(seed)

    def current_player(self) -> str:
        return self._active_player

    def get_prompt(self, player_id: str) -> str:
        mark = self._mark_for(player_id)
        opponent = self._opponent(player_id)
        opp_mark = self._mark_for(opponent)

        board_str = self._render_board()
        available = self._available_squares()
        avail_str = ", ".join(f"[{r}, {c}]" for r, c in available)

        lines = [
            f"You are playing Tic-Tac-Toe. You are {mark} "
            f"(opponent is {opp_mark}).",
            "",
            f"Series score: You {self._series_scores[player_id]} - "
            f"Opponent {self._series_scores[opponent]}",
            f"Game {self._game_number} of {self._games_per_match}",
            "",
            "Board:",
            board_str,
            "",
            "Row 0 is the top row, col 0 is the left column.",
            f"Available squares: {avail_str}",
            "",
            "Respond with a JSON object like:",
            '  {"action": "play", "position": [row, col], '
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

        position = action.get("position")
        if not isinstance(position, list) or len(position) != 2:
            return ValidationResult(
                legal=False, reason="Position must be [row, col]."
            )

        row, col = position[0], position[1]
        if not (0 <= row <= 2 and 0 <= col <= 2):
            return ValidationResult(
                legal=False,
                reason=f"Position [{row}, {col}] out of bounds. "
                f"Row and col must be 0-2.",
            )

        if self._board[row][col] != "":
            return ValidationResult(
                legal=False,
                reason=f"Square [{row}, {col}] is already occupied "
                f"by '{self._board[row][col]}'.",
            )

        return ValidationResult(legal=True)

    def apply_action(self, player_id: str, action: dict) -> None:
        row, col = action["position"]
        mark = self._mark_for(player_id)

        self._board[row][col] = mark
        self._turn_number += 1
        self._game_turn += 1

        # Telemetry
        self._last_position = [row, col]
        self._last_was_valid = True
        self._last_violation_type = None

        # Check for win or draw
        winner = self._check_winner()
        if winner:
            self._winner = player_id
            self._record_game_result(
                "x_wins" if mark == "X" else "o_wins"
            )
            self._advance_or_end()
        elif self._game_turn >= 9:
            # Board full, draw
            self._winner = None
            self._record_game_result("draw")
            self._advance_or_end()
        else:
            self._active_player = self._opponent(player_id)

    def forfeit_turn(self, player_id: str) -> None:
        """Place mark in first empty square (row-major scan)."""
        mark = self._mark_for(player_id)

        # Find first empty square
        for r in range(3):
            for c in range(3):
                if self._board[r][c] == "":
                    self._board[r][c] = mark
                    self._turn_number += 1
                    self._game_turn += 1

                    self._last_position = [r, c]
                    self._last_was_valid = False
                    self._last_violation_type = "forfeit"

                    # Check for win or draw
                    winner = self._check_winner()
                    if winner:
                        self._winner = player_id
                        self._record_game_result(
                            "x_wins" if mark == "X" else "o_wins"
                        )
                        self._advance_or_end()
                    elif self._game_turn >= 9:
                        self._winner = None
                        self._record_game_result("draw")
                        self._advance_or_end()
                    else:
                        self._active_player = self._opponent(player_id)
                    return

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
            "position_played": self._last_position,
            "was_valid": self._last_was_valid,
            "violation_type": self._last_violation_type,
        }

    def get_highlight_hands(self) -> list[int]:
        """Return game numbers where a player won."""
        highlights = []
        for i, result in enumerate(self._game_results):
            if result in ("x_wins", "o_wins"):
                highlights.append(i + 1)
        return highlights

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _init_game_state(self) -> None:
        """Reset board for a new game."""
        self._board = [["", "", ""], ["", "", ""], ["", "", ""]]
        self._winner = None
        self._clear_telemetry()

    def _mark_for(self, player_id: str) -> str:
        """Return 'X' or 'O' based on who goes first this game."""
        if player_id == self._first_player:
            return "X"
        return "O"

    def _render_board(self) -> str:
        """Render ASCII board with labeled axes."""
        symbols = {
            "": ".",
            "X": "X",
            "O": "O",
        }
        lines = ["     0   1   2"]
        for r in range(3):
            cells = " | ".join(
                f" {symbols[self._board[r][c]]}" for c in range(3)
            )
            lines.append(f"{r}   {cells}")
            if r < 2:
                lines.append("    ---+---+---")
        return "\n".join(lines)

    def _available_squares(self) -> list[tuple[int, int]]:
        """Return list of empty (row, col) tuples."""
        return [
            (r, c)
            for r in range(3)
            for c in range(3)
            if self._board[r][c] == ""
        ]

    def _check_winner(self) -> str | None:
        """Check all 8 win lines. Return winning mark or None."""
        for line in _WIN_LINES:
            marks = [self._board[r][c] for r, c in line]
            if marks[0] != "" and marks[0] == marks[1] == marks[2]:
                return marks[0]
        return None

    def _record_game_result(self, result: str) -> None:
        """Record game result and update series scores."""
        self._game_results.append(result)

        if result == "x_wins":
            x_player = self._first_player
            o_player = self._opponent(self._first_player)
            self._series_scores[x_player] += 1.0
        elif result == "o_wins":
            o_player = self._opponent(self._first_player)
            self._series_scores[o_player] += 1.0
        else:  # draw
            self._series_scores["player_a"] += 0.5
            self._series_scores["player_b"] += 0.5

    def _clear_telemetry(self) -> None:
        self._last_position = None
        self._last_was_valid = True
        self._last_violation_type = None
