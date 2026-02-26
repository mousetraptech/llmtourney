"""Scrabble board — 15×15 with premium squares and scoring."""

from __future__ import annotations

SIZE = 15
CENTER = (7, 7)

# Tile point values (blank = 0, handled separately)
TILE_VALUES: dict[str, int] = {
    "A": 1, "B": 3, "C": 3, "D": 2, "E": 1, "F": 4, "G": 2, "H": 4,
    "I": 1, "J": 8, "K": 5, "L": 1, "M": 3, "N": 1, "O": 1, "P": 3,
    "Q": 10, "R": 1, "S": 1, "T": 1, "U": 1, "V": 4, "W": 4, "X": 8,
    "Y": 4, "Z": 10,
}

# Standard 100-tile distribution: letter -> (count, point_value)
TILE_DISTRIBUTION: dict[str, tuple[int, int]] = {
    "A": (9, 1), "B": (2, 3), "C": (2, 3), "D": (4, 2), "E": (12, 1),
    "F": (2, 4), "G": (3, 2), "H": (2, 4), "I": (9, 1), "J": (1, 8),
    "K": (1, 5), "L": (4, 1), "M": (2, 3), "N": (6, 1), "O": (8, 1),
    "P": (2, 3), "Q": (1, 10), "R": (6, 1), "S": (4, 1), "T": (6, 1),
    "U": (4, 1), "V": (2, 4), "W": (2, 4), "X": (1, 8), "Y": (2, 4),
    "Z": (1, 10), "?": (2, 0),  # ? = blank tile
}

# Premium square positions --------------------------------------------------

# Triple Word Score
_TW_POSITIONS = [
    (0, 0), (0, 7), (0, 14),
    (7, 0), (7, 14),
    (14, 0), (14, 7), (14, 14),
]

# Double Word Score (center star at 7,7 is also DW)
_DW_POSITIONS = [
    (1, 1), (2, 2), (3, 3), (4, 4),
    (1, 13), (2, 12), (3, 11), (4, 10),
    (10, 4), (11, 3), (12, 2), (13, 1),
    (10, 10), (11, 11), (12, 12), (13, 13),
    (7, 7),
]

# Triple Letter Score
_TL_POSITIONS = [
    (1, 5), (1, 9),
    (5, 1), (5, 5), (5, 9), (5, 13),
    (9, 1), (9, 5), (9, 9), (9, 13),
    (13, 5), (13, 9),
]

# Double Letter Score
_DL_POSITIONS = [
    (0, 3), (0, 11),
    (2, 6), (2, 8),
    (3, 0), (3, 7), (3, 14),
    (6, 2), (6, 6), (6, 8), (6, 12),
    (7, 3), (7, 11),
    (8, 2), (8, 6), (8, 8), (8, 12),
    (11, 0), (11, 7), (11, 14),
    (12, 6), (12, 8),
    (14, 3), (14, 11),
]

PREMIUM_SQUARES: dict[tuple[int, int], str] = {}
for _pos in _TW_POSITIONS:
    PREMIUM_SQUARES[_pos] = "TW"
for _pos in _DW_POSITIONS:
    PREMIUM_SQUARES[_pos] = "DW"
for _pos in _TL_POSITIONS:
    PREMIUM_SQUARES[_pos] = "TL"
for _pos in _DL_POSITIONS:
    PREMIUM_SQUARES[_pos] = "DL"


def create_full_bag() -> list[str]:
    """Create the standard 100-tile bag."""
    bag: list[str] = []
    for letter, (count, _) in TILE_DISTRIBUTION.items():
        bag.extend([letter] * count)
    return bag


def tile_value(letter: str) -> int:
    """Point value of a tile letter. Blanks ('?') are 0."""
    if letter == "?":
        return 0
    return TILE_VALUES.get(letter.upper(), 0)


def rack_value(rack: list[str]) -> int:
    """Sum of point values of tiles in a rack."""
    return sum(tile_value(t) for t in rack)


class Board:
    """15×15 Scrabble board with premium squares."""

    def __init__(self) -> None:
        # grid[row][col] = None | (letter: str, is_blank: bool)
        self._grid: list[list[tuple[str, bool] | None]] = [
            [None] * SIZE for _ in range(SIZE)
        ]
        self._is_empty: bool = True

    @property
    def is_empty(self) -> bool:
        return self._is_empty

    def get(self, row: int, col: int) -> tuple[str, bool] | None:
        """Get tile at (row, col). Returns (letter, is_blank) or None."""
        if 0 <= row < SIZE and 0 <= col < SIZE:
            return self._grid[row][col]
        return None

    def place_word(
        self,
        word: str,
        row: int,
        col: int,
        direction: str,
        blank_positions: set[int] | None = None,
    ) -> set[tuple[int, int]]:
        """Place a word on the board.

        Returns set of (row, col) positions where NEW tiles were placed.
        blank_positions: set of 0-indexed positions in ``word`` that use blanks.
        """
        blank_positions = blank_positions or set()
        newly_placed: set[tuple[int, int]] = set()

        for i, letter in enumerate(word):
            r = row + (i if direction == "down" else 0)
            c = col + (i if direction == "across" else 0)

            if self._grid[r][c] is None:
                is_blank = i in blank_positions
                self._grid[r][c] = (letter.upper(), is_blank)
                newly_placed.add((r, c))

        if newly_placed:
            self._is_empty = False
        return newly_placed

    # ------------------------------------------------------------------
    # Scoring
    # ------------------------------------------------------------------

    def score_placement(
        self,
        word: str,
        row: int,
        col: int,
        direction: str,
        newly_placed: set[tuple[int, int]],
    ) -> tuple[int, list[str]]:
        """Score a word placement including all cross-words.

        Returns (total_score, list_of_cross_word_strings).
        Premium squares only apply to newly placed tiles.
        """
        total = 0
        cross_words: list[str] = []

        # --- Score main word ---
        main_score = 0
        word_mult = 1

        for i, letter in enumerate(word):
            r = row + (i if direction == "down" else 0)
            c = col + (i if direction == "across" else 0)

            cell = self._grid[r][c]
            if cell is not None and cell[1]:  # blank tile
                lv = 0
            else:
                lv = TILE_VALUES.get(letter.upper(), 0)

            if (r, c) in newly_placed:
                premium = PREMIUM_SQUARES.get((r, c))
                if premium == "DL":
                    lv *= 2
                elif premium == "TL":
                    lv *= 3
                elif premium == "DW":
                    word_mult *= 2
                elif premium == "TW":
                    word_mult *= 3

            main_score += lv

        total += main_score * word_mult

        # --- Score cross-words for each newly placed tile ---
        cross_dir = "down" if direction == "across" else "across"

        for r, c in newly_placed:
            cw_positions = self._get_word_positions(r, c, cross_dir)
            if cw_positions is None or len(cw_positions) < 2:
                continue  # no cross-word formed

            cw_score = 0
            cw_mult = 1
            cw_letters: list[str] = []

            for cr, cc in cw_positions:
                cell = self._grid[cr][cc]
                letter = cell[0]
                cw_letters.append(letter)

                if cell[1]:  # blank
                    lv = 0
                else:
                    lv = TILE_VALUES.get(letter, 0)

                if (cr, cc) == (r, c):
                    premium = PREMIUM_SQUARES.get((cr, cc))
                    if premium == "DL":
                        lv *= 2
                    elif premium == "TL":
                        lv *= 3
                    elif premium == "DW":
                        cw_mult *= 2
                    elif premium == "TW":
                        cw_mult *= 3

                cw_score += lv

            total += cw_score * cw_mult
            cross_words.append("".join(cw_letters))

        return total, cross_words

    # ------------------------------------------------------------------
    # Cross-word helpers (used by engine for validation without mutation)
    # ------------------------------------------------------------------

    def get_cross_word_if_placed(
        self, row: int, col: int, letter: str, main_direction: str
    ) -> str | None:
        """Return the cross-word that WOULD form if ``letter`` were placed here.

        Does not modify the board. Returns None if no cross-word.
        """
        cross_dir = "down" if main_direction == "across" else "across"
        chars: list[str] = []

        if cross_dir == "across":
            # extend left
            c = col - 1
            while c >= 0 and self._grid[row][c] is not None:
                chars.insert(0, self._grid[row][c][0])
                c -= 1
            chars.append(letter.upper())
            # extend right
            c = col + 1
            while c < SIZE and self._grid[row][c] is not None:
                chars.append(self._grid[row][c][0])
                c += 1
        else:
            # extend up
            r = row - 1
            while r >= 0 and self._grid[r][col] is not None:
                chars.insert(0, self._grid[r][col][0])
                r -= 1
            chars.append(letter.upper())
            # extend down
            r = row + 1
            while r < SIZE and self._grid[r][col] is not None:
                chars.append(self._grid[r][col][0])
                r += 1

        if len(chars) > 1:
            return "".join(chars)
        return None

    def connects_to_existing(
        self, word: str, row: int, col: int, direction: str
    ) -> bool:
        """Check if placing ``word`` at (row, col) connects to existing tiles."""
        for i in range(len(word)):
            r = row + (i if direction == "down" else 0)
            c = col + (i if direction == "across" else 0)

            # Tile already on board = connection
            if self._grid[r][c] is not None:
                return True

            # Adjacent tile in any direction = connection
            for dr, dc in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                nr, nc = r + dr, c + dc
                if 0 <= nr < SIZE and 0 <= nc < SIZE:
                    if self._grid[nr][nc] is not None:
                        return True
        return False

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def to_ascii(self) -> str:
        """Render the board as ASCII for LLM prompts."""
        col_hdr = "     " + "".join(f"{c:3d}" for c in range(SIZE))
        lines = [col_hdr]

        for r in range(SIZE):
            cells: list[str] = []
            for c in range(SIZE):
                tile = self._grid[r][c]
                if tile is not None:
                    letter, is_blank = tile
                    if is_blank:
                        cells.append(f" {letter.lower()}")
                    else:
                        cells.append(f"  {letter}")
                else:
                    premium = PREMIUM_SQUARES.get((r, c))
                    if premium == "TW":
                        cells.append(" 3W")
                    elif premium == "DW":
                        cells.append(" 2W")
                    elif premium == "TL":
                        cells.append(" 3L")
                    elif premium == "DL":
                        cells.append(" 2L")
                    else:
                        cells.append("  .")
            lines.append(f" {r:2d} " + "".join(cells))

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _get_word_positions(
        self, row: int, col: int, direction: str
    ) -> list[tuple[int, int]] | None:
        """Get all positions of the word through (row, col) in ``direction``.

        Returns list of (r, c) or None if cell is isolated in that direction.
        """
        positions: list[tuple[int, int]] = [(row, col)]

        if direction == "across":
            c = col - 1
            while c >= 0 and self._grid[row][c] is not None:
                positions.insert(0, (row, c))
                c -= 1
            c = col + 1
            while c < SIZE and self._grid[row][c] is not None:
                positions.append((row, c))
                c += 1
        else:
            r = row - 1
            while r >= 0 and self._grid[r][col] is not None:
                positions.insert(0, (r, col))
                r -= 1
            r = row + 1
            while r < SIZE and self._grid[r][col] is not None:
                positions.append((r, col))
                r += 1

        return positions if len(positions) > 1 else None
