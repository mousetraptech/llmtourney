"""Checkers engine — implements the Event ABC for multi-game series.

Each match plays a series of games (default 5) with alternating colors.
Scoring: 1.0 per win, 0.5 per draw, 0.0 per loss.

Draw rules:
- 40 consecutive moves (by either player) without a capture → draw.
- 3-fold repetition (same board position + same player to move) → draw.
"""

from __future__ import annotations

from llmtourney.events.base import TwoPlayerSeriesEvent, ValidationResult

from .board import (
    Move,
    check_game_over,
    count_pieces,
    create_initial_board,
    execute_move,
    get_all_valid_moves,
    render_board,
)

__all__ = ["CheckersEvent"]

_DRAW_MOVE_LIMIT = 40  # moves without capture → draw
_REPETITION_LIMIT = 3  # same position 3 times → draw


def _board_key(board: list[list[str]], color: str) -> str:
    """Hash a board position + side-to-move for repetition detection."""
    return color + "|" + "/".join("".join(row) for row in board)


class CheckersEvent(TwoPlayerSeriesEvent):
    """Multi-game checkers series engine."""

    def __init__(self, games_per_match: int = 5) -> None:
        super().__init__(games_per_match)
        self._board: list[list[str]] = []
        self._current_color: str = ""
        self._moves_without_capture: int = 0
        self._position_history: dict[str, int] = {}
        self._color_map: dict[str, str] = {}

        # Telemetry extras
        self._last_move: dict | None = None
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
        color = self._color_map[player_id]
        opponent = self._opponent(player_id)
        opp_color = self._color_map[opponent]

        board_str = render_board(self._board)
        pieces = count_pieces(self._board)
        moves = get_all_valid_moves(self._board, color)

        has_captures = any(m.captures for m in moves)
        moves_str = "  ".join(
            self._format_move(m) for m in moves
        )

        lines = [
            f"You are playing Checkers. You are {color} (opponent is {opp_color}).",
            "Black moves DOWN the board, red moves UP.",
            "",
            f"Series score: You {self._series_scores[player_id]} - "
            f"Opponent {self._series_scores[opponent]}",
            f"Game {self._game_number} of {self._games_per_match}",
            "",
            "Board:",
            board_str,
            "",
            "b/r = piece, B/R = king. Pieces move diagonally on dark squares only.",
        ]

        if has_captures:
            lines.append("RULE: If a capture is available, you MUST capture.")

        lines.extend([
            "",
            f"Your pieces: {color[0]} ({pieces[color]} remaining)",
            f"Available moves:",
            f"  {moves_str}",
            "",
            "Respond with a JSON object:",
            '  {"action": "move", "from": [row, col], "to": [row, col], "reasoning": "..."}',
            'For multi-jump captures, add "path": [[r1,c1], [r2,c2], ...]',
            "",
            "IMPORTANT: Respond with ONLY a single JSON object. "
            "No markdown fences, no explanation before or after. "
            "Just the raw JSON.",
        ])
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
        if act != "move":
            return ValidationResult(
                legal=False, reason=f"Unknown action: {act!r}. Use 'move'."
            )

        from_sq = action.get("from")
        to_sq = action.get("to")

        if not isinstance(from_sq, list) or len(from_sq) != 2:
            return ValidationResult(
                legal=False, reason="'from' must be [row, col]."
            )
        if not isinstance(to_sq, list) or len(to_sq) != 2:
            return ValidationResult(
                legal=False, reason="'to' must be [row, col]."
            )

        fr = (from_sq[0], from_sq[1])
        to = (to_sq[0], to_sq[1])

        color = self._color_map[player_id]
        valid_moves = get_all_valid_moves(self._board, color)

        # Find matching move(s)
        matching = [m for m in valid_moves if m.fr == fr and m.to == to]
        if not matching:
            return ValidationResult(
                legal=False,
                reason=f"No valid move from {list(fr)} to {list(to)}. "
                f"Check available moves in the prompt.",
            )

        # For multi-jumps, validate path if provided
        path = action.get("path")
        if path and len(matching) > 1:
            path_tuples = [tuple(p) for p in path]
            matching = [m for m in matching if m.path == path_tuples]
            if not matching:
                return ValidationResult(
                    legal=False,
                    reason=f"Path {path} doesn't match any valid capture chain.",
                )

        return ValidationResult(legal=True)

    def apply_action(self, player_id: str, action: dict) -> None:
        fr = tuple(action["from"])
        to = tuple(action["to"])
        color = self._color_map[player_id]

        valid_moves = get_all_valid_moves(self._board, color)
        matching = [m for m in valid_moves if m.fr == fr and m.to == to]

        # Narrow by path if provided
        path = action.get("path")
        if path and len(matching) > 1:
            path_tuples = [tuple(p) for p in path]
            matching = [m for m in matching if m.path == path_tuples]

        move = matching[0]
        self._board = execute_move(self._board, move)
        self._turn_number += 1
        self._game_turn += 1

        # Draw counter
        if move.captures:
            self._moves_without_capture = 0
        else:
            self._moves_without_capture += 1

        # Telemetry
        self._last_move = {
            "from": list(move.fr),
            "to": list(move.to),
            "captures": [list(c) for c in move.captures],
            "path": [list(p) for p in move.path],
        }
        self._last_was_valid = True
        self._last_violation_type = None

        opponent_color = self._color_map[self._opponent(player_id)]
        self._record_position(next_to_move=opponent_color)
        self._check_game_end(player_id)

    def forfeit_turn(self, player_id: str) -> None:
        """Execute the first available move as a forfeit."""
        color = self._color_map[player_id]
        moves = get_all_valid_moves(self._board, color)

        if not moves:
            # No moves available — game should already be over, but handle gracefully
            self._last_was_valid = False
            self._last_violation_type = "forfeit"
            self._last_move = None
            return

        move = moves[0]
        self._board = execute_move(self._board, move)
        self._turn_number += 1
        self._game_turn += 1

        if move.captures:
            self._moves_without_capture = 0
        else:
            self._moves_without_capture += 1

        self._last_move = {
            "from": list(move.fr),
            "to": list(move.to),
            "captures": [list(c) for c in move.captures],
            "path": [list(p) for p in move.path],
        }
        self._last_was_valid = False
        self._last_violation_type = "forfeit"

        opponent_color = self._color_map[self._opponent(player_id)]
        self._record_position(next_to_move=opponent_color)
        self._check_game_end(player_id)

    def get_state_snapshot(self) -> dict:
        pieces = count_pieces(self._board)
        return {
            "board": [row[:] for row in self._board],
            "scores": dict(self._series_scores),
            "series_scores": dict(self._series_scores),
            "hand_number": self._game_number,
            "game_turn": self._game_turn,
            "turn_number": self._turn_number,
            "active_player": self._active_player,
            "result": self._game_results[-1] if self._game_results else None,
            "terminal": self._terminal,
            "last_move": self._last_move,
            "pieces_remaining": pieces,
            "moves_without_capture": self._moves_without_capture,
            "color_map": dict(self._color_map),
            # Telemetry
            "was_valid": self._last_was_valid,
            "violation_type": self._last_violation_type,
        }

    def get_highlight_hands(self) -> list[int]:
        highlights = []
        for i, result in enumerate(self._game_results):
            if result in ("black_wins", "red_wins"):
                highlights.append(i + 1)
        return highlights

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _init_game_state(self) -> None:
        self._board = create_initial_board()
        self._current_color = "black"
        self._moves_without_capture = 0
        self._position_history = {}
        self._color_map = {
            self._first_player: "black",
            self._opponent(self._first_player): "red",
        }
        self._record_position()
        self._clear_telemetry()

    def _check_game_end(self, last_player_id: str) -> None:
        """Check for game over after a move, advance series if needed."""
        opponent_id = self._opponent(last_player_id)
        opponent_color = self._color_map[opponent_id]

        # Draw by repetition
        key = _board_key(self._board, opponent_color)
        if self._position_history.get(key, 0) >= _REPETITION_LIMIT:
            self._record_game_result("draw")
            self._advance_or_end()
            return

        # Draw by move limit
        if self._moves_without_capture >= _DRAW_MOVE_LIMIT:
            self._record_game_result("draw")
            self._advance_or_end()
            return

        # Check if opponent can play
        result = check_game_over(self._board, opponent_color)
        if result:
            self._record_game_result(result)
            self._advance_or_end()
        else:
            # Continue — switch to opponent
            self._active_player = opponent_id
            self._current_color = opponent_color

    def _record_game_result(self, result: str) -> None:
        """Record result and update series scores."""
        self._game_results.append(result)

        if result == "draw":
            self._series_scores["player_a"] += 0.5
            self._series_scores["player_b"] += 0.5
        elif result == "black_wins":
            black_player = self._player_for_color("black")
            self._series_scores[black_player] += 1.0
        elif result == "red_wins":
            red_player = self._player_for_color("red")
            self._series_scores[red_player] += 1.0

    def _player_for_color(self, color: str) -> str:
        """Return the player_id assigned to the given color."""
        for pid, c in self._color_map.items():
            if c == color:
                return pid
        return "player_a"  # fallback

    def _record_position(self, next_to_move: str | None = None) -> None:
        """Record the current board+side-to-move for repetition detection.

        *next_to_move* is the color of the player who will move next from
        this position.  At game start it equals ``self._current_color``
        (black goes first); after a move it is the opponent's color.
        """
        color = next_to_move or self._current_color
        key = _board_key(self._board, color)
        self._position_history[key] = self._position_history.get(key, 0) + 1

    def _clear_telemetry(self) -> None:
        self._last_move = None
        self._last_was_valid = True
        self._last_violation_type = None

    @staticmethod
    def _format_move(m: Move) -> str:
        """Format a move for display in prompts."""
        fr_str = f"[{m.fr[0]},{m.fr[1]}]"
        to_str = f"[{m.to[0]},{m.to[1]}]"
        if m.captures:
            caps = "x".join(f"[{c[0]},{c[1]}]" for c in m.captures)
            return f"{fr_str}->{to_str}(captures:{caps})"
        return f"{fr_str}->{to_str}"

