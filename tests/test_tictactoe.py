"""Tests for the Tic-Tac-Toe engine."""

import pytest
from llmtourney.events.tictactoe.engine import TicTacToeEvent


@pytest.fixture
def game():
    g = TicTacToeEvent()
    g.reset(seed=42)
    return g


# ------------------------------------------------------------------
# Setup
# ------------------------------------------------------------------

class TestTicTacToeSetup:
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
        assert "position" in schema["properties"]

    def test_initial_scores_zero(self, game):
        scores = game.get_scores()
        assert scores["player_a"] == 0.0
        assert scores["player_b"] == 0.0


# ------------------------------------------------------------------
# Win detection — all 8 lines
# ------------------------------------------------------------------

class TestWinDetection:
    """Test all 8 win lines: 3 rows, 3 cols, 2 diagonals."""

    def _play_sequence(self, game, moves):
        """Play a sequence of (player, row, col) tuples."""
        for player, row, col in moves:
            game.apply_action(player, {"action": "play", "position": [row, col]})

    def test_win_row_0(self, game):
        self._play_sequence(game, [
            ("player_a", 0, 0), ("player_b", 1, 0),
            ("player_a", 0, 1), ("player_b", 1, 1),
            ("player_a", 0, 2),
        ])
        assert game._game_results[-1] == "x_wins"

    def test_win_row_1(self, game):
        self._play_sequence(game, [
            ("player_a", 1, 0), ("player_b", 0, 0),
            ("player_a", 1, 1), ("player_b", 0, 1),
            ("player_a", 1, 2),
        ])
        assert game._game_results[-1] == "x_wins"

    def test_win_row_2(self, game):
        self._play_sequence(game, [
            ("player_a", 2, 0), ("player_b", 0, 0),
            ("player_a", 2, 1), ("player_b", 0, 1),
            ("player_a", 2, 2),
        ])
        assert game._game_results[-1] == "x_wins"

    def test_win_col_0(self, game):
        self._play_sequence(game, [
            ("player_a", 0, 0), ("player_b", 0, 1),
            ("player_a", 1, 0), ("player_b", 1, 1),
            ("player_a", 2, 0),
        ])
        assert game._game_results[-1] == "x_wins"

    def test_win_col_1(self, game):
        self._play_sequence(game, [
            ("player_a", 0, 1), ("player_b", 0, 0),
            ("player_a", 1, 1), ("player_b", 1, 0),
            ("player_a", 2, 1),
        ])
        assert game._game_results[-1] == "x_wins"

    def test_win_col_2(self, game):
        self._play_sequence(game, [
            ("player_a", 0, 2), ("player_b", 0, 0),
            ("player_a", 1, 2), ("player_b", 1, 0),
            ("player_a", 2, 2),
        ])
        assert game._game_results[-1] == "x_wins"

    def test_win_diag_main(self, game):
        self._play_sequence(game, [
            ("player_a", 0, 0), ("player_b", 0, 1),
            ("player_a", 1, 1), ("player_b", 0, 2),
            ("player_a", 2, 2),
        ])
        assert game._game_results[-1] == "x_wins"

    def test_win_diag_anti(self, game):
        self._play_sequence(game, [
            ("player_a", 0, 2), ("player_b", 0, 0),
            ("player_a", 1, 1), ("player_b", 1, 0),
            ("player_a", 2, 0),
        ])
        assert game._game_results[-1] == "x_wins"

    def test_o_can_win(self, game):
        """Player B (O) can also win."""
        self._play_sequence(game, [
            ("player_a", 0, 0), ("player_b", 1, 0),
            ("player_a", 0, 1), ("player_b", 1, 1),
            ("player_a", 2, 2), ("player_b", 1, 2),
        ])
        assert game._game_results[-1] == "o_wins"


# ------------------------------------------------------------------
# Draw
# ------------------------------------------------------------------

class TestDraw:
    def test_draw_on_full_board(self, game):
        """Fill board with no winner -> draw."""
        # X O X
        # X X O
        # O X O
        moves = [
            ("player_a", 0, 0), ("player_b", 0, 1),
            ("player_a", 0, 2), ("player_b", 1, 2),
            ("player_a", 1, 0), ("player_b", 2, 0),
            ("player_a", 1, 1), ("player_b", 2, 2),
            ("player_a", 2, 1),
        ]
        for player, row, col in moves:
            game.apply_action(player, {"action": "play", "position": [row, col]})
        assert game._game_results[-1] == "draw"


# ------------------------------------------------------------------
# Forfeit
# ------------------------------------------------------------------

class TestForfeit:
    def test_forfeit_places_in_first_empty(self, game):
        game.forfeit_turn("player_a")
        assert game._board[0][0] == "X"

    def test_forfeit_switches_player(self, game):
        game.forfeit_turn("player_a")
        assert game.current_player() == "player_b"

    def test_forfeit_records_violation(self, game):
        game.forfeit_turn("player_a")
        snap = game.get_state_snapshot()
        assert snap["was_valid"] is False
        assert snap["violation_type"] == "forfeit"

    def test_forfeit_skips_occupied(self, game):
        """Forfeit should find the first truly empty square."""
        game._board[0][0] = "X"
        game._board[0][1] = "O"
        game._game_turn = 2
        game.forfeit_turn("player_a")
        assert game._board[0][2] == "X"


# ------------------------------------------------------------------
# Scoring
# ------------------------------------------------------------------

class TestScoring:
    def test_win_scores_1_0(self, game):
        """Winner gets 1.0, loser gets 0.0."""
        # X wins quickly
        moves = [
            ("player_a", 0, 0), ("player_b", 1, 0),
            ("player_a", 0, 1), ("player_b", 1, 1),
            ("player_a", 0, 2),
        ]
        for player, row, col in moves:
            game.apply_action(player, {"action": "play", "position": [row, col]})
        scores = game.get_scores()
        assert scores["player_a"] == 1.0
        assert scores["player_b"] == 0.0

    def test_draw_scores_half(self, game):
        """Draw gives 0.5 each."""
        moves = [
            ("player_a", 0, 0), ("player_b", 0, 1),
            ("player_a", 0, 2), ("player_b", 1, 2),
            ("player_a", 1, 0), ("player_b", 2, 0),
            ("player_a", 1, 1), ("player_b", 2, 2),
            ("player_a", 2, 1),
        ]
        for player, row, col in moves:
            game.apply_action(player, {"action": "play", "position": [row, col]})
        scores = game.get_scores()
        assert scores["player_a"] == 0.5
        assert scores["player_b"] == 0.5


# ------------------------------------------------------------------
# Terminal conditions
# ------------------------------------------------------------------

class TestTerminal:
    def test_game_ends_on_win(self, game):
        """After a win, the current game ends (board resets for next)."""
        moves = [
            ("player_a", 0, 0), ("player_b", 1, 0),
            ("player_a", 0, 1), ("player_b", 1, 1),
            ("player_a", 0, 2),
        ]
        for player, row, col in moves:
            game.apply_action(player, {"action": "play", "position": [row, col]})
        # Match not terminal yet (still more games)
        assert game.is_terminal() is False
        # But a game result was recorded
        assert len(game._game_results) == 1

    def test_game_ends_on_draw(self, game):
        moves = [
            ("player_a", 0, 0), ("player_b", 0, 1),
            ("player_a", 0, 2), ("player_b", 1, 2),
            ("player_a", 1, 0), ("player_b", 2, 0),
            ("player_a", 1, 1), ("player_b", 2, 2),
            ("player_a", 2, 1),
        ]
        for player, row, col in moves:
            game.apply_action(player, {"action": "play", "position": [row, col]})
        assert game.is_terminal() is False
        assert len(game._game_results) == 1

    def test_match_ends_after_n_games(self):
        """Match is terminal after games_per_match games complete."""
        game = TicTacToeEvent(games_per_match=2)
        game.reset(seed=42)

        # Game 1: X wins
        for p, r, c in [
            ("player_a", 0, 0), ("player_b", 1, 0),
            ("player_a", 0, 1), ("player_b", 1, 1),
            ("player_a", 0, 2),
        ]:
            game.apply_action(p, {"action": "play", "position": [r, c]})
        assert game.is_terminal() is False

        # Game 2: O wins (player_b goes first now)
        for p, r, c in [
            ("player_b", 0, 0), ("player_a", 1, 0),
            ("player_b", 0, 1), ("player_a", 1, 1),
            ("player_b", 0, 2),
        ]:
            game.apply_action(p, {"action": "play", "position": [r, c]})
        assert game.is_terminal() is True

    def test_force_forfeit_match(self, game):
        game.force_forfeit_match("player_a")
        assert game.is_terminal() is True


# ------------------------------------------------------------------
# Validation
# ------------------------------------------------------------------

class TestValidation:
    def test_out_of_bounds_rejected(self, game):
        result = game.validate_action(
            "player_a", {"action": "play", "position": [3, 0]}
        )
        assert result.legal is False
        assert "out of bounds" in result.reason.lower()

    def test_negative_position_rejected(self, game):
        result = game.validate_action(
            "player_a", {"action": "play", "position": [-1, 0]}
        )
        assert result.legal is False

    def test_occupied_square_rejected(self, game):
        game.apply_action("player_a", {"action": "play", "position": [1, 1]})
        result = game.validate_action(
            "player_b", {"action": "play", "position": [1, 1]}
        )
        assert result.legal is False
        assert "occupied" in result.reason.lower()

    def test_wrong_player_rejected(self, game):
        result = game.validate_action(
            "player_b", {"action": "play", "position": [0, 0]}
        )
        assert result.legal is False
        assert "not your turn" in result.reason.lower()

    def test_unknown_action_rejected(self, game):
        result = game.validate_action(
            "player_a", {"action": "resign", "position": [0, 0]}
        )
        assert result.legal is False

    def test_valid_move_accepted(self, game):
        result = game.validate_action(
            "player_a", {"action": "play", "position": [1, 1]}
        )
        assert result.legal is True


# ------------------------------------------------------------------
# Multi-game series
# ------------------------------------------------------------------

class TestMultiGame:
    def _play_x_wins(self, game):
        """Play a quick X-wins game. Returns after game ends."""
        first = game.current_player()
        second = "player_b" if first == "player_a" else "player_a"
        moves = [
            (first, 0, 0), (second, 1, 0),
            (first, 0, 1), (second, 1, 1),
            (first, 0, 2),
        ]
        for player, row, col in moves:
            game.apply_action(player, {"action": "play", "position": [row, col]})

    def test_alternating_first_player(self):
        game = TicTacToeEvent(games_per_match=3)
        game.reset(seed=42)

        # Game 1: player_a is first (X)
        assert game._first_player == "player_a"
        self._play_x_wins(game)

        # Game 2: player_b is first (X)
        assert game._first_player == "player_b"
        self._play_x_wins(game)

        # Game 3: player_a is first again
        assert game._first_player == "player_a"

    def test_cumulative_scores(self):
        game = TicTacToeEvent(games_per_match=3)
        game.reset(seed=42)

        # Game 1: X wins (player_a is X)
        self._play_x_wins(game)
        assert game.get_scores()["player_a"] == 1.0

        # Game 2: X wins (player_b is X now)
        self._play_x_wins(game)
        assert game.get_scores()["player_b"] == 1.0

        # Game 3: X wins (player_a is X again)
        self._play_x_wins(game)
        assert game.get_scores()["player_a"] == 2.0
        assert game.get_scores()["player_b"] == 1.0

    def test_board_resets_between_games(self):
        game = TicTacToeEvent(games_per_match=2)
        game.reset(seed=42)

        self._play_x_wins(game)
        # Board should be clean for next game
        for row in game._board:
            for cell in row:
                assert cell == ""

    def test_game_number_increments(self):
        game = TicTacToeEvent(games_per_match=3)
        game.reset(seed=42)
        assert game._game_number == 1
        self._play_x_wins(game)
        assert game._game_number == 2
        self._play_x_wins(game)
        assert game._game_number == 3


# ------------------------------------------------------------------
# Prompt
# ------------------------------------------------------------------

class TestPrompt:
    def test_prompt_contains_board(self, game):
        prompt = game.get_prompt("player_a")
        assert "---+---+---" in prompt

    def test_prompt_contains_coordinates(self, game):
        prompt = game.get_prompt("player_a")
        assert "Row 0 is the top row" in prompt
        assert "col 0 is the left column" in prompt

    def test_prompt_contains_json_example(self, game):
        prompt = game.get_prompt("player_a")
        assert '"action": "play"' in prompt
        assert '"position"' in prompt

    def test_prompt_contains_player_identity(self, game):
        prompt = game.get_prompt("player_a")
        assert "You are X" in prompt

    def test_prompt_contains_series_info(self, game):
        prompt = game.get_prompt("player_a")
        assert "Game 1 of 9" in prompt
        assert "Series score" in prompt

    def test_prompt_contains_available_squares(self, game):
        prompt = game.get_prompt("player_a")
        assert "Available squares" in prompt
        assert "[0, 0]" in prompt

    def test_prompt_contains_json_only_instruction(self, game):
        prompt = game.get_prompt("player_a")
        assert "ONLY a single JSON object" in prompt

    def test_retry_prompt_contains_error(self, game):
        prompt = game.get_retry_prompt("player_a", "square is occupied")
        assert "square is occupied" in prompt


# ------------------------------------------------------------------
# State snapshot
# ------------------------------------------------------------------

class TestSnapshot:
    def test_snapshot_has_all_keys(self, game):
        snap = game.get_state_snapshot()
        expected_keys = [
            "board", "scores", "hand_number", "game_turn",
            "turn_number", "active_player", "result", "series_scores",
            "terminal", "position_played", "was_valid", "violation_type",
        ]
        for key in expected_keys:
            assert key in snap, f"Missing key: {key}"

    def test_snapshot_updates_after_move(self, game):
        game.apply_action("player_a", {"action": "play", "position": [1, 1]})
        snap = game.get_state_snapshot()
        assert snap["position_played"] == [1, 1]
        assert snap["was_valid"] is True
        assert snap["turn_number"] == 1
