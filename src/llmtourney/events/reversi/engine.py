"""Reversi (Othello) engine — implements the Event ABC for multi-game series.

Standard 8×8 Reversi with auto-pass when a player has no legal moves.
Matches play a series of games (default 9) with alternating first player.
Scoring: 1.0 per win, 0.5 per draw, 0.0 per loss.
"""

from __future__ import annotations

from pathlib import Path

from llmtourney.events.base import Event, ValidationResult
from llmtourney.core.schemas import load_schema

__all__ = ["ReversiEvent"]

SIZE = 8

# Eight directions: (row_delta, col_delta)
_DIRECTIONS = [
    (-1, -1), (-1, 0), (-1, 1),
    (0, -1),           (0, 1),
    (1, -1),  (1, 0),  (1, 1),
]


class ReversiEvent(Event):
    """Multi-game Reversi series engine.

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
        self._last_position: tuple[int, int] | None = None
        self._last_flipped: list[tuple[int, int]] = []
        self._last_was_valid: bool = True
        self._last_violation_type: str | None = None

    # ------------------------------------------------------------------
    # Event ABC
    # ------------------------------------------------------------------

    def reset(self, seed: int) -> None:
        self._board = [[""] * SIZE for _ in range(SIZE)]
        # Standard starting position
        self._board[3][3] = "W"
        self._board[3][4] = "B"
        self._board[4][3] = "B"
        self._board[4][4] = "W"

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
        b_count, w_count = self._piece_counts()
        legal = self._get_legal_moves(mark)
        legal_str = " ".join(f"[{r},{c}]" for r, c in legal)

        lines = [
            f"Reversi (Othello) \u2014 Game {self._game_number}/{self._games_per_match}",
            f"You are {mark} ({player_id}). "
            f"Series: You {self._series_scores[player_id]}, "
            f"Opponent {self._series_scores[opponent]}",
            "",
            "Board (row 0=top, col 0=left):",
            board_str,
            f"  Black: {b_count}  White: {w_count}",
            "",
            f"Legal moves: {legal_str}",
            "",
            'Respond with JSON: {"action": "play", "row": <0-7>, "col": <0-7>, '
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

        row = action.get("row")
        col = action.get("col")
        if not isinstance(row, int) or not (0 <= row < SIZE):
            return ValidationResult(
                legal=False,
                reason=f"Row must be an integer 0-7. Got: {row!r}.",
            )
        if not isinstance(col, int) or not (0 <= col < SIZE):
            return ValidationResult(
                legal=False,
                reason=f"Col must be an integer 0-7. Got: {col!r}.",
            )

        if self._board[row][col] != "":
            return ValidationResult(
                legal=False,
                reason=f"Cell ({row},{col}) is occupied.",
            )

        mark = self._mark_for(player_id)
        flips = self._get_flips(row, col, mark)
        if not flips:
            return ValidationResult(
                legal=False,
                reason=f"Move ({row},{col}) does not flip any opponent pieces.",
            )

        return ValidationResult(legal=True)

    def apply_action(self, player_id: str, action: dict) -> None:
        row = action["row"]
        col = action["col"]
        mark = self._mark_for(player_id)

        flips = self._get_flips(row, col, mark)
        self._board[row][col] = mark
        for fr, fc in flips:
            self._board[fr][fc] = mark

        self._turn_number += 1
        self._game_turn += 1

        # Telemetry
        self._last_position = (row, col)
        self._last_flipped = list(flips)
        self._last_was_valid = True
        self._last_violation_type = None

        # Check if game continues
        self._try_advance_turn(player_id)

    def forfeit_turn(self, player_id: str) -> None:
        """Place piece at first legal move (row-major scan)."""
        mark = self._mark_for(player_id)
        legal = self._get_legal_moves(mark)

        if legal:
            row, col = legal[0]
            flips = self._get_flips(row, col, mark)
            self._board[row][col] = mark
            for fr, fc in flips:
                self._board[fr][fc] = mark

            self._turn_number += 1
            self._game_turn += 1

            self._last_position = (row, col)
            self._last_flipped = list(flips)
            self._last_was_valid = False
            self._last_violation_type = "forfeit"

            self._try_advance_turn(player_id)
        else:
            # No legal moves — just pass (auto-pass equivalent)
            self._turn_number += 1
            self._last_position = None
            self._last_flipped = []
            self._last_was_valid = False
            self._last_violation_type = "forfeit"
            self._active_player = self._opponent(player_id)

    def force_forfeit_match(self, player_id: str) -> None:
        """Force-end the match due to stuck-loop detection."""
        self._terminal = True

    def award_forfeit_wins(self, forfeiting_player_id: str) -> None:
        """Award remaining games to opponent."""
        opponent = self._opponent(forfeiting_player_id)
        remaining = self._games_per_match - len(self._game_results)
        self._series_scores[opponent] += float(remaining)
        self._terminal = True

    def is_terminal(self) -> bool:
        return self._terminal

    def get_scores(self) -> dict[str, float]:
        return dict(self._series_scores)

    def get_state_snapshot(self) -> dict:
        b_count, w_count = self._piece_counts()
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
            "last_position": list(self._last_position) if self._last_position else None,
            "last_flipped": [list(p) for p in self._last_flipped],
            "was_valid": self._last_was_valid,
            "violation_type": self._last_violation_type,
            # Reversi-specific
            "piece_counts": {"B": b_count, "W": w_count},
            "color_map": {
                self._first_player: "B",
                self._opponent(self._first_player): "W",
            },
        }

    @property
    def action_schema(self) -> dict:
        return self._action_schema

    def get_highlight_hands(self) -> list[int]:
        """Return game numbers where a player won (not draws)."""
        highlights = []
        for i, result in enumerate(self._game_results):
            if result in ("b_wins", "w_wins"):
                highlights.append(i + 1)
        return highlights

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _mark_for(self, player_id: str) -> str:
        """Return 'B' or 'W' based on who goes first this game."""
        if player_id == self._first_player:
            return "B"
        return "W"

    def _piece_counts(self) -> tuple[int, int]:
        """Return (black_count, white_count)."""
        b = sum(cell == "B" for row in self._board for cell in row)
        w = sum(cell == "W" for row in self._board for cell in row)
        return b, w

    def _get_legal_moves(self, mark: str) -> list[tuple[int, int]]:
        """Return list of (row, col) that are legal for the given mark."""
        moves = []
        for r in range(SIZE):
            for c in range(SIZE):
                if self._board[r][c] == "":
                    if self._get_flips(r, c, mark):
                        moves.append((r, c))
        return moves

    def _get_flips(self, row: int, col: int, mark: str) -> list[tuple[int, int]]:
        """Return list of positions flipped by placing mark at (row, col)."""
        opponent = "W" if mark == "B" else "B"
        all_flips: list[tuple[int, int]] = []

        for dr, dc in _DIRECTIONS:
            flips: list[tuple[int, int]] = []
            r, c = row + dr, col + dc
            while 0 <= r < SIZE and 0 <= c < SIZE and self._board[r][c] == opponent:
                flips.append((r, c))
                r += dr
                c += dc
            # Must end on own piece to capture
            if flips and 0 <= r < SIZE and 0 <= c < SIZE and self._board[r][c] == mark:
                all_flips.extend(flips)

        return all_flips

    def _try_advance_turn(self, player_id: str) -> None:
        """After a move, check opponent/current player for legal moves or end game."""
        opponent_id = self._opponent(player_id)
        opponent_mark = self._mark_for(opponent_id)
        current_mark = self._mark_for(player_id)

        if self._get_legal_moves(opponent_mark):
            # Opponent can play
            self._active_player = opponent_id
        elif self._get_legal_moves(current_mark):
            # Auto-pass: opponent has no moves, current player goes again
            self._active_player = player_id
        else:
            # Neither player can move — game over
            self._end_current_game()

    def _end_current_game(self) -> None:
        """Count pieces, determine winner, record result."""
        b_count, w_count = self._piece_counts()
        if b_count > w_count:
            result = "b_wins"
        elif w_count > b_count:
            result = "w_wins"
        else:
            result = "draw"

        # Determine winner player_id
        if result == "b_wins":
            self._winner = self._first_player
        elif result == "w_wins":
            self._winner = self._opponent(self._first_player)
        else:
            self._winner = None

        self._record_game_result(result)
        self._advance_or_end()

    def _record_game_result(self, result: str) -> None:
        """Record game result and update series scores."""
        self._game_results.append(result)

        if result == "b_wins":
            b_player = self._first_player
            self._series_scores[b_player] += 1.0
        elif result == "w_wins":
            w_player = self._opponent(self._first_player)
            self._series_scores[w_player] += 1.0
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
        self._board = [[""] * SIZE for _ in range(SIZE)]
        self._board[3][3] = "W"
        self._board[3][4] = "B"
        self._board[4][3] = "B"
        self._board[4][4] = "W"
        self._game_turn = 0
        self._winner = None
        # Alternate first player
        self._first_player = self._opponent(self._first_player)
        self._active_player = self._first_player
        self._clear_telemetry()

    def _render_board(self) -> str:
        """Render ASCII board with row/col numbers."""
        lines = ["    " + "   ".join(f"{c}" for c in range(SIZE))]
        lines.append("  " + "+---" * SIZE + "+")
        for r in range(SIZE):
            cells = "| " + " | ".join(
                f"{self._board[r][c] if self._board[r][c] else ' '}"
                for c in range(SIZE)
            ) + " |"
            lines.append(f"{r} {cells}")
            lines.append("  " + "+---" * SIZE + "+")
        return "\n".join(lines)

    def _clear_telemetry(self) -> None:
        self._last_position = None
        self._last_flipped = []
        self._last_was_valid = True
        self._last_violation_type = None

    @staticmethod
    def _opponent(player_id: str) -> str:
        return "player_b" if player_id == "player_a" else "player_a"
