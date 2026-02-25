"""Tests for the Connect Four engine."""

import pytest
from llmtourney.events.connectfour.engine import ConnectFourEvent


@pytest.fixture
def game():
    g = ConnectFourEvent()
    g.reset(seed=42)
    return g


# ------------------------------------------------------------------
# Setup
# ------------------------------------------------------------------

class TestSetup:
    def test_reset_initializes(self, game):
        snap = game.get_state_snapshot()
        assert snap["turn_number"] == 0
        assert snap["hand_number"] == 1
        assert snap["game_turn"] == 0
        assert snap["terminal"] is False

    def test_not_terminal_at_start(self, game):
        assert game.is_terminal() is False

    def test_player_a_goes_first(self, game):
        assert game.current_player() == "player_a"

    def test_empty_board(self, game):
        for row in game._board:
            for cell in row:
                assert cell == ""

    def test_action_schema_present(self, game):
        schema = game.action_schema
        assert schema["type"] == "object"
        assert "action" in schema["properties"]
        assert "column" in schema["properties"]

    def test_initial_scores_zero(self, game):
        scores = game.get_scores()
        assert scores["player_a"] == 0.0
        assert scores["player_b"] == 0.0


# ------------------------------------------------------------------
# Validation
# ------------------------------------------------------------------

class TestValidation:
    def test_valid_column_accepted(self, game):
        result = game.validate_action(
            "player_a", {"action": "play", "column": 3}
        )
        assert result.legal is True

    def test_full_column_rejected(self, game):
        # Fill column 0
        for r in range(6):
            game._board[r][0] = "X"
        result = game.validate_action(
            "player_a", {"action": "play", "column": 0}
        )
        assert result.legal is False
        assert "full" in result.reason.lower()

    def test_out_of_range_rejected(self, game):
        result = game.validate_action(
            "player_a", {"action": "play", "column": 7}
        )
        assert result.legal is False

    def test_negative_column_rejected(self, game):
        result = game.validate_action(
            "player_a", {"action": "play", "column": -1}
        )
        assert result.legal is False

    def test_wrong_turn_rejected(self, game):
        result = game.validate_action(
            "player_b", {"action": "play", "column": 0}
        )
        assert result.legal is False
        assert "not your turn" in result.reason.lower()

    def test_unknown_action_rejected(self, game):
        result = game.validate_action(
            "player_a", {"action": "resign", "column": 0}
        )
        assert result.legal is False


# ------------------------------------------------------------------
# Win conditions
# ------------------------------------------------------------------

class TestWinConditions:
    def _play_columns(self, game, columns):
        """Play a sequence of columns, alternating players starting with current."""
        for col in columns:
            player = game.current_player()
            game.apply_action(player, {"action": "play", "column": col})

    def test_horizontal_win(self, game):
        # X plays cols 0,1,2,3 with O interspersed on different rows
        self._play_columns(game, [0, 0, 1, 1, 2, 2, 3])
        # X: row5 cols 0,1,2,3 — O: row5 would stack but O goes on same cols
        # Actually let me be more explicit:
        # Turn 1: A plays col 0 -> (5,0)=X
        # Turn 2: B plays col 0 -> (4,0)=O
        # Turn 3: A plays col 1 -> (5,1)=X
        # Turn 4: B plays col 1 -> (4,1)=O
        # Turn 5: A plays col 2 -> (5,2)=X
        # Turn 6: B plays col 2 -> (4,2)=O
        # Turn 7: A plays col 3 -> (5,3)=X — horizontal win row 5
        assert game._game_results[-1] == "x_wins"

    def test_vertical_win(self, game):
        # X stacks col 0, O stacks col 1
        self._play_columns(game, [0, 1, 0, 1, 0, 1, 0])
        # X at (5,0),(4,0),(3,0),(2,0) — vertical win
        assert game._game_results[-1] == "x_wins"

    def test_diagonal_down_win(self, game):
        # Build a diagonal from top-left to bottom-right
        # X needs pieces at (r, r) for some offset
        # Col 0: X at row 5
        # Col 1: O at row 5, X at row 4
        # Col 2: O at row 5, O at row 4, X at row 3
        # Col 3: O at row 5, O at row 4, O at row 3, X at row 2
        game.apply_action("player_a", {"action": "play", "column": 0})  # X(5,0)
        game.apply_action("player_b", {"action": "play", "column": 1})  # O(5,1)
        game.apply_action("player_a", {"action": "play", "column": 1})  # X(4,1)
        game.apply_action("player_b", {"action": "play", "column": 2})  # O(5,2)
        game.apply_action("player_a", {"action": "play", "column": 2})  # X(4,2)
        # Need X at (3,2) — but we need O to play something else first
        game.apply_action("player_b", {"action": "play", "column": 2})  # O(3,2)
        # Wait — we need X at row 3, col 2. But O just took (3,2).
        # Let me rethink: we need diagonal (5,0),(4,1),(3,2),(2,3)
        # Restart with a clean approach
        game2 = ConnectFourEvent()
        game2.reset(seed=42)
        # Col 0: just X
        # Col 1: O bottom, X on top
        # Col 2: O,O bottom, X on top
        # Col 3: O,O,O bottom, X on top
        moves = [
            ("player_a", 0),  # X(5,0)
            ("player_b", 1),  # O(5,1)
            ("player_a", 1),  # X(4,1)
            ("player_b", 2),  # O(5,2)
            ("player_a", 6),  # X(5,6) — waste move
            ("player_b", 2),  # O(4,2)
            ("player_a", 2),  # X(3,2)
            ("player_b", 3),  # O(5,3)
            ("player_a", 3),  # X(4,3) — waste? no, we need to stack
            ("player_b", 3),  # O(3,3)
            ("player_a", 3),  # X(2,3) — now diagonal: (5,0),(4,1),(3,2),(2,3)
        ]
        for player, col in moves:
            game2.apply_action(player, {"action": "play", "column": col})
        assert game2._game_results[-1] == "x_wins"

    def test_diagonal_up_win(self, game):
        # Diagonal from bottom-right to top-left: (5,3),(4,2),(3,1),(2,0)
        game2 = ConnectFourEvent()
        game2.reset(seed=42)
        moves = [
            ("player_a", 3),  # X(5,3)
            ("player_b", 2),  # O(5,2)
            ("player_a", 2),  # X(4,2)
            ("player_b", 1),  # O(5,1)
            ("player_a", 6),  # X(5,6) — waste
            ("player_b", 1),  # O(4,1)
            ("player_a", 1),  # X(3,1)
            ("player_b", 0),  # O(5,0)
            ("player_a", 0),  # X(4,0)
            ("player_b", 0),  # O(3,0)
            ("player_a", 0),  # X(2,0) — diagonal: (5,3),(4,2),(3,1),(2,0)
        ]
        for player, col in moves:
            game2.apply_action(player, {"action": "play", "column": col})
        assert game2._game_results[-1] == "x_wins"

    def test_o_can_win(self, game):
        """Player B (O) can also win."""
        # O stacks col 3, X wastes on cols 0,1
        moves = [
            ("player_a", 0),  # X(5,0)
            ("player_b", 3),  # O(5,3)
            ("player_a", 1),  # X(5,1)
            ("player_b", 3),  # O(4,3)
            ("player_a", 0),  # X(4,0)
            ("player_b", 3),  # O(3,3)
            ("player_a", 1),  # X(4,1)
            ("player_b", 3),  # O(2,3) — vertical win
        ]
        for player, col in moves:
            game.apply_action(player, {"action": "play", "column": col})
        assert game._game_results[-1] == "o_wins"


# ------------------------------------------------------------------
# Draw
# ------------------------------------------------------------------

class TestDraw:
    def test_draw_on_full_board(self):
        """Fill the board with no winner -> draw."""
        game = ConnectFourEvent(games_per_match=1)
        game.reset(seed=42)
        # Fill board in a pattern that avoids 4-in-a-row
        # Pattern per column (bottom to top):
        # Col 0: X O X O X O
        # Col 1: X O X O X O
        # Col 2: X O X O X O
        # Col 3: O X O X O X  (shifted)
        # Col 4: O X O X O X
        # Col 5: O X O X O X
        # Col 6: X O X O X O
        # This requires careful move ordering.
        # Easier: directly set the board and game_turn, then play last move.
        game._board = [
            ["O", "O", "X", "X", "O", "O", "X"],  # row 0 (top)
            ["X", "X", "O", "O", "X", "X", "O"],  # row 1
            ["O", "O", "X", "X", "O", "O", "X"],  # row 2
            ["X", "X", "O", "O", "X", "X", "O"],  # row 3
            ["O", "O", "X", "X", "O", "O", "X"],  # row 4
            ["X", "X", "O", "O", "X", "X", ""],    # row 5 (bottom) — one empty
        ]
        game._game_turn = 41
        game._active_player = "player_a"
        game._first_player = "player_a"  # X
        game.apply_action("player_a", {"action": "play", "column": 6})
        assert game._game_results[-1] == "draw"


# ------------------------------------------------------------------
# Forfeit
# ------------------------------------------------------------------

class TestForfeit:
    def test_forfeit_places_in_first_column(self, game):
        game.forfeit_turn("player_a")
        assert game._board[5][0] == "X"

    def test_forfeit_switches_player(self, game):
        game.forfeit_turn("player_a")
        assert game.current_player() == "player_b"

    def test_forfeit_records_violation(self, game):
        game.forfeit_turn("player_a")
        snap = game.get_state_snapshot()
        assert snap["was_valid"] is False
        assert snap["violation_type"] == "forfeit"

    def test_forfeit_skips_full_column(self, game):
        """Forfeit should find the first non-full column."""
        # Fill column 0 with alternating marks (no 4-in-a-row)
        for r in range(6):
            game._board[r][0] = "X" if r % 2 == 0 else "O"
        game._game_turn = 6
        game.forfeit_turn("player_a")
        # Should place in column 1 instead
        assert game._board[5][1] == "X"


# ------------------------------------------------------------------
# Scoring
# ------------------------------------------------------------------

class TestScoring:
    def _play_vertical_win(self, game):
        """X stacks col 0, O stacks col 1 — X wins vertically."""
        cols = [0, 1, 0, 1, 0, 1, 0]
        for col in cols:
            player = game.current_player()
            game.apply_action(player, {"action": "play", "column": col})

    def test_win_scores_1_0(self, game):
        self._play_vertical_win(game)
        scores = game.get_scores()
        assert scores["player_a"] == 1.0
        assert scores["player_b"] == 0.0

    def test_series_advancement(self):
        game = ConnectFourEvent(games_per_match=2)
        game.reset(seed=42)
        # Game 1: quick vertical win for X
        for col in [0, 1, 0, 1, 0, 1, 0]:
            player = game.current_player()
            game.apply_action(player, {"action": "play", "column": col})
        assert game.is_terminal() is False
        assert game._game_number == 2

    def test_first_player_alternation(self):
        game = ConnectFourEvent(games_per_match=3)
        game.reset(seed=42)
        assert game._first_player == "player_a"
        # Win game 1
        for col in [0, 1, 0, 1, 0, 1, 0]:
            player = game.current_player()
            game.apply_action(player, {"action": "play", "column": col})
        assert game._first_player == "player_b"

    def test_match_ends_after_n_games(self):
        game = ConnectFourEvent(games_per_match=2)
        game.reset(seed=42)
        # Game 1
        for col in [0, 1, 0, 1, 0, 1, 0]:
            player = game.current_player()
            game.apply_action(player, {"action": "play", "column": col})
        assert game.is_terminal() is False
        # Game 2 (player_b is first/X now)
        for col in [0, 1, 0, 1, 0, 1, 0]:
            player = game.current_player()
            game.apply_action(player, {"action": "play", "column": col})
        assert game.is_terminal() is True


# ------------------------------------------------------------------
# Prompt
# ------------------------------------------------------------------

class TestPrompt:
    def test_prompt_contains_board(self, game):
        prompt = game.get_prompt("player_a")
        assert "+---+---+---+---+---+---+---+" in prompt

    def test_prompt_contains_available_columns(self, game):
        prompt = game.get_prompt("player_a")
        assert "Available columns:" in prompt
        assert "0" in prompt

    def test_prompt_contains_player_identity(self, game):
        prompt = game.get_prompt("player_a")
        assert "You are X" in prompt

    def test_prompt_contains_series_info(self, game):
        prompt = game.get_prompt("player_a")
        assert "Game 1/9" in prompt
        assert "Series:" in prompt

    def test_prompt_contains_json_instruction(self, game):
        prompt = game.get_prompt("player_a")
        assert '"action": "play"' in prompt
        assert '"column"' in prompt

    def test_prompt_contains_json_only_instruction(self, game):
        prompt = game.get_prompt("player_a")
        assert "ONLY a single JSON object" in prompt

    def test_retry_prompt_contains_error(self, game):
        prompt = game.get_retry_prompt("player_a", "column is full")
        assert "column is full" in prompt
