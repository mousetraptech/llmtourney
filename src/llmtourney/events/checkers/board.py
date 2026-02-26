"""Checkers board logic — 8×8 row/col representation.

Ported from the TypeScript engine at ~/projects/checkers/.
Uses direct (row, col) coordinates instead of the TS 32-index system.
Dark squares: (row + col) % 2 == 1.

Piece encoding (strings on an 8×8 grid):
  ""  — empty (or light square)
  "b" — black piece
  "r" — red piece
  "B" — black king
  "R" — red king

Black moves DOWN the board (increasing row).
Red moves UP the board (decreasing row).
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Move:
    """A single move (simple or multi-jump capture)."""

    fr: tuple[int, int]  # (row, col) origin
    to: tuple[int, int]  # (row, col) final destination
    captures: list[tuple[int, int]] = field(default_factory=list)
    path: list[tuple[int, int]] = field(default_factory=list)  # waypoints including final


def create_initial_board() -> list[list[str]]:
    """Return a fresh 8×8 board with pieces in starting positions."""
    board: list[list[str]] = [[""] * 8 for _ in range(8)]
    for r in range(8):
        for c in range(8):
            if (r + c) % 2 != 1:
                continue  # light square
            if r < 3:
                board[r][c] = "b"
            elif r > 4:
                board[r][c] = "r"
    return board


def _is_dark(r: int, c: int) -> bool:
    return (r + c) % 2 == 1


def _in_bounds(r: int, c: int) -> bool:
    return 0 <= r < 8 and 0 <= c < 8


def _owner(piece: str) -> str | None:
    """Return 'black' or 'red' for a piece, None for empty."""
    if piece in ("b", "B"):
        return "black"
    if piece in ("r", "R"):
        return "red"
    return None


def _is_king(piece: str) -> bool:
    return piece in ("B", "R")


def _directions(piece: str) -> list[tuple[int, int]]:
    """Return diagonal direction vectors for a piece."""
    if _is_king(piece):
        return [(1, -1), (1, 1), (-1, -1), (-1, 1)]
    if piece == "b":
        return [(1, -1), (1, 1)]
    if piece == "r":
        return [(-1, -1), (-1, 1)]
    return []


def _enemy(player: str) -> str:
    return "red" if player == "black" else "black"


# ── Move generation ──────────────────────────────────────────────


def find_captures(
    board: list[list[str]],
    row: int,
    col: int,
    piece: str,
    captured: list[tuple[int, int]],
    path: list[tuple[int, int]],
    origin: tuple[int, int] | None = None,
) -> list[Move]:
    """Recursively find all capture chains from (row, col).

    Returns a list of complete Move objects. Each Move records the
    original starting square, the final landing square, all captured
    positions, and the full path of waypoints.
    """
    if origin is None:
        origin = (row, col)
    dirs = _directions(piece)
    moves: list[Move] = []

    for dr, dc in dirs:
        mid_r, mid_c = row + dr, col + dc
        land_r, land_c = row + dr * 2, col + dc * 2

        if not _in_bounds(land_r, land_c):
            continue

        mid_piece = board[mid_r][mid_c]
        if not mid_piece:
            continue
        if _owner(mid_piece) == _owner(piece):
            continue  # can't jump own piece
        if (mid_r, mid_c) in captured:
            continue  # already captured this chain

        if board[land_r][land_c] != "":
            continue  # landing square occupied

        # Valid jump — simulate it
        new_captured = captured + [(mid_r, mid_c)]
        new_path = path + [(land_r, land_c)]

        # Temporarily modify board for recursion
        orig_mid = board[mid_r][mid_c]
        orig_land = board[land_r][land_c]
        orig_start = board[row][col]
        board[mid_r][mid_c] = ""
        board[land_r][land_c] = piece
        board[row][col] = ""

        continuations = find_captures(
            board, land_r, land_c, piece, new_captured, new_path, origin
        )

        # Restore board
        board[row][col] = orig_start
        board[mid_r][mid_c] = orig_mid
        board[land_r][land_c] = orig_land

        if continuations:
            moves.extend(continuations)
        else:
            moves.append(
                Move(
                    fr=origin,
                    to=(land_r, land_c),
                    captures=new_captured,
                    path=new_path,
                )
            )

    return moves


def get_all_valid_moves(
    board: list[list[str]], player: str
) -> list[Move]:
    """Return all legal moves for *player* ('black' or 'red').

    Mandatory capture: if any capture exists, only captures are returned.
    """
    capture_moves: list[Move] = []
    simple_moves: list[Move] = []

    for r in range(8):
        for c in range(8):
            piece = board[r][c]
            if not piece or _owner(piece) != player:
                continue

            # Check captures first
            caps = find_captures(board, r, c, piece, [], [])
            if caps:
                capture_moves.extend(caps)
                continue

            # Simple moves (only used if no captures anywhere)
            for dr, dc in _directions(piece):
                nr, nc = r + dr, c + dc
                if _in_bounds(nr, nc) and board[nr][nc] == "":
                    simple_moves.append(
                        Move(fr=(r, c), to=(nr, nc), captures=[], path=[(nr, nc)])
                    )

    if capture_moves:
        return capture_moves
    return simple_moves


# ── Move execution ───────────────────────────────────────────────


def execute_move(board: list[list[str]], move: Move) -> list[list[str]]:
    """Execute a move, returning a new board. Handles captures and king promotion."""
    new_board = [row[:] for row in board]

    piece = new_board[move.fr[0]][move.fr[1]]
    new_board[move.fr[0]][move.fr[1]] = ""

    # Remove captured pieces
    for cr, cc in move.captures:
        new_board[cr][cc] = ""

    # King promotion
    dest_r, dest_c = move.to
    if piece == "b" and dest_r == 7:
        piece = "B"
    elif piece == "r" and dest_r == 0:
        piece = "R"

    new_board[dest_r][dest_c] = piece
    return new_board


# ── Game-over detection ──────────────────────────────────────────


def check_game_over(board: list[list[str]], current_player: str) -> str | None:
    """Check if the game is over.

    Returns 'black_wins', 'red_wins', or None (game continues).
    The current_player is the one whose turn it is — if they have no
    pieces or no moves, they lose.
    """
    has_piece = False
    for r in range(8):
        for c in range(8):
            if _owner(board[r][c]) == current_player:
                has_piece = True
                break
        if has_piece:
            break

    if not has_piece:
        return "red_wins" if current_player == "black" else "black_wins"

    moves = get_all_valid_moves(board, current_player)
    if not moves:
        return "red_wins" if current_player == "black" else "black_wins"

    return None


def count_pieces(board: list[list[str]]) -> dict[str, int]:
    """Count remaining pieces for each side."""
    counts = {"black": 0, "red": 0}
    for r in range(8):
        for c in range(8):
            owner = _owner(board[r][c])
            if owner:
                counts[owner] += 1
    return counts


def render_board(board: list[list[str]]) -> str:
    """Render ASCII board for prompts."""
    lines = ["     0   1   2   3   4   5   6   7"]
    for r in range(8):
        cells = []
        for c in range(8):
            piece = board[r][c]
            cells.append(f" {piece if piece else '.'}")
        lines.append(f"{r}   " + " | ".join(cells))
        if r < 7:
            lines.append("    " + "----+" * 7 + "----")
    return "\n".join(lines)
