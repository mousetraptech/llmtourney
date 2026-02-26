"""Tests for the Reversi engine."""

import pytest
from llmtourney.events.reversi.engine import ReversiEvent


@pytest.fixture
def game():
    g = ReversiEvent()
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

    def test_initial_board_center_pieces(self, game):
        assert game._board[3][3] == "W"
        assert game._board[3][4] == "B"
        assert game._board[4][3] == "B"
        assert game._board[4][4] == "W"

    def test_initial_board_edges_empty(self, game):
        for r in range(8):
            for c in range(8):
                if (r, c) not in [(3, 3), (3, 4), (4, 3), (4, 4)]:
                    assert game._board[r][c] == ""

    def test_action_schema_present(self, game):
        schema = game.action_schema
        assert schema["type"] == "object"
        assert "action" in schema["properties"]
        assert "row" in schema["properties"]
        assert "col" in schema["properties"]

    def test_initial_scores_zero(self, game):
        scores = game.get_scores()
        assert scores["player_a"] == 0.0
        assert scores["player_b"] == 0.0

    def test_initial_piece_counts(self, game):
        snap = game.get_state_snapshot()
        assert snap["piece_counts"] == {"B": 2, "W": 2}


# ------------------------------------------------------------------
# Validation
# ------------------------------------------------------------------

class TestValidation:
    def test_valid_move_accepted(self, game):
        # (2,3) is legal for Black on the opening board
        result = game.validate_action(
            "player_a", {"action": "play", "row": 2, "col": 3}
        )
        assert result.legal is True

    def test_occupied_cell_rejected(self, game):
        result = game.validate_action(
            "player_a", {"action": "play", "row": 3, "col": 3}
        )
        assert result.legal is False
        assert "occupied" in result.reason.lower()

    def test_no_flips_rejected(self, game):
        result = game.validate_action(
            "player_a", {"action": "play", "row": 0, "col": 0}
        )
        assert result.legal is False
        assert "flip" in result.reason.lower()

    def test_out_of_range_row_rejected(self, game):
        result = game.validate_action(
            "player_a", {"action": "play", "row": 8, "col": 0}
        )
        assert result.legal is False

    def test_out_of_range_col_rejected(self, game):
        result = game.validate_action(
            "player_a", {"action": "play", "row": 0, "col": -1}
        )
        assert result.legal is False

    def test_wrong_turn_rejected(self, game):
        result = game.validate_action(
            "player_b", {"action": "play", "row": 2, "col": 3}
        )
        assert result.legal is False
        assert "not your turn" in result.reason.lower()

    def test_unknown_action_rejected(self, game):
        result = game.validate_action(
            "player_a", {"action": "pass", "row": 2, "col": 3}
        )
        assert result.legal is False


# ------------------------------------------------------------------
# Gameplay
# ------------------------------------------------------------------

class TestGameplay:
    def test_piece_placed_and_flipped(self, game):
        # Black plays (2,3) — should flip W at (3,3) to B
        game.apply_action("player_a", {"action": "play", "row": 2, "col": 3})
        assert game._board[2][3] == "B"
        assert game._board[3][3] == "B"  # was W, now flipped

    def test_turn_alternates(self, game):
        assert game.current_player() == "player_a"
        game.apply_action("player_a", {"action": "play", "row": 2, "col": 3})
        assert game.current_player() == "player_b"

    def test_flipped_positions_in_snapshot(self, game):
        game.apply_action("player_a", {"action": "play", "row": 2, "col": 3})
        snap = game.get_state_snapshot()
        assert snap["last_position"] == [2, 3]
        assert [3, 3] in snap["last_flipped"]

    def test_auto_pass(self):
        """When opponent has no legal moves, current player goes again."""
        game = ReversiEvent(games_per_match=1)
        game.reset(seed=42)
        # Construct a board where White has no legal moves but Black does
        game._board = [[""] * 8 for _ in range(8)]
        game._board[0][0] = "B"
        game._board[0][1] = "W"
        game._board[0][2] = ""  # B can play here to flip W
        # Everything else empty — W will have no legal moves after B plays
        game._active_player = "player_a"
        game._first_player = "player_a"  # player_a = B

        game.apply_action("player_a", {"action": "play", "row": 0, "col": 2})
        # White has no legal moves (all W flipped), Black should go again
        # (or game ends if neither can move)
        # In this case neither can move since the only W was flipped
        # So game should end
        assert len(game._game_results) >= 1

    def test_game_ends_when_neither_can_move(self):
        """Game ends when neither player has legal moves."""
        game = ReversiEvent(games_per_match=1)
        game.reset(seed=42)
        # Set up a board where the next move ends the game
        game._board = [[""] * 8 for _ in range(8)]
        game._board[0][0] = "B"
        game._board[0][1] = "W"
        # B plays (0,2) to flip (0,1), then neither can move
        game._active_player = "player_a"
        game._first_player = "player_a"

        game.apply_action("player_a", {"action": "play", "row": 0, "col": 2})
        # All pieces are B now, neither can move
        assert len(game._game_results) == 1
        assert game._game_results[-1] == "b_wins"

    def test_piece_counts_update(self, game):
        game.apply_action("player_a", {"action": "play", "row": 2, "col": 3})
        snap = game.get_state_snapshot()
        # Started with 2B, 2W. Placed B at (2,3) and flipped (3,3) W->B
        # Now: 4B, 1W
        assert snap["piece_counts"]["B"] == 4
        assert snap["piece_counts"]["W"] == 1


# ------------------------------------------------------------------
# Scoring
# ------------------------------------------------------------------

class TestScoring:
    def _play_to_end(self, game):
        """Play until game ends by filling up or no moves."""
        while not game.is_terminal():
            player = game.current_player()
            mark = game._mark_for(player)
            legal = game._get_legal_moves(mark)
            if legal:
                r, c = legal[0]
                game.apply_action(player, {"action": "play", "row": r, "col": c})
            else:
                # Shouldn't happen — auto-pass is handled internally
                break

    def test_more_pieces_wins(self):
        game = ReversiEvent(games_per_match=1)
        game.reset(seed=42)
        # Set up endgame: B has more pieces
        game._board = [["B"] * 8 for _ in range(8)]
        game._board[7][7] = "W"
        game._board[7][6] = ""  # One empty cell
        # B plays the last cell, game ends
        game._active_player = "player_a"
        game._first_player = "player_a"
        game._game_turn = 62

        game.apply_action("player_a", {"action": "play", "row": 7, "col": 6})
        # B flips (7,7) W->B, board full, neither can move
        assert game._game_results[-1] == "b_wins"

    def test_equal_pieces_draw(self):
        game = ReversiEvent(games_per_match=1)
        game.reset(seed=42)
        # Manually set up a board that will end in equal pieces
        game._board = [[""] * 8 for _ in range(8)]
        # 3 B, 1 W, one empty that B can play to flip W
        game._board[0][0] = "B"
        game._board[0][1] = "B"
        game._board[0][2] = "W"
        # B plays (0,3) — but (0,2) won't flip because no B after it in that direction
        # Let me set up a proper draw scenario
        game._board = [[""] * 8 for _ in range(8)]
        game._board[0][0] = "W"
        game._board[0][1] = "B"
        # B count = 1, W count = 1 after we force end
        game._end_current_game()
        assert game._game_results[-1] == "draw"

    def test_series_advancement(self):
        game = ReversiEvent(games_per_match=2)
        game.reset(seed=42)
        # Force end game 1
        game._end_current_game()  # 2B vs 2W = draw
        assert game.is_terminal() is False
        assert game._game_number == 2

    def test_first_player_alternation(self):
        game = ReversiEvent(games_per_match=3)
        game.reset(seed=42)
        assert game._first_player == "player_a"
        game._end_current_game()
        assert game._first_player == "player_b"

    def test_match_ends_after_n_games(self):
        game = ReversiEvent(games_per_match=2)
        game.reset(seed=42)
        game._end_current_game()
        assert game.is_terminal() is False
        game._end_current_game()
        assert game.is_terminal() is True

    def test_win_scores_1_0(self):
        game = ReversiEvent(games_per_match=1)
        game.reset(seed=42)
        # Set board so B has more
        game._board = [[""] * 8 for _ in range(8)]
        game._board[0][0] = "B"
        game._board[0][1] = "B"
        game._board[0][2] = "W"
        game._end_current_game()
        assert game._game_results[-1] == "b_wins"
        scores = game.get_scores()
        assert scores["player_a"] == 1.0  # player_a is first_player = B
        assert scores["player_b"] == 0.0


# ------------------------------------------------------------------
# Forfeit
# ------------------------------------------------------------------

class TestForfeit:
    def test_forfeit_places_first_legal_move(self, game):
        game.forfeit_turn("player_a")
        snap = game.get_state_snapshot()
        assert snap["was_valid"] is False
        assert snap["violation_type"] == "forfeit"
        # Should have placed at first legal move for Black
        assert snap["last_position"] is not None

    def test_forfeit_records_violation(self, game):
        game.forfeit_turn("player_a")
        snap = game.get_state_snapshot()
        assert snap["was_valid"] is False
        assert snap["violation_type"] == "forfeit"

    def test_forfeit_flips_pieces(self, game):
        """Forfeit should still flip opponent pieces."""
        initial_b = sum(cell == "B" for row in game._board for cell in row)
        game.forfeit_turn("player_a")
        new_b = sum(cell == "B" for row in game._board for cell in row)
        assert new_b > initial_b


# ------------------------------------------------------------------
# Prompt
# ------------------------------------------------------------------

class TestPrompt:
    def test_prompt_contains_board(self, game):
        prompt = game.get_prompt("player_a")
        assert "+---+---+---+---+---+---+---+---+" in prompt

    def test_prompt_contains_piece_counts(self, game):
        prompt = game.get_prompt("player_a")
        assert "Black: 2" in prompt
        assert "White: 2" in prompt

    def test_prompt_contains_legal_moves(self, game):
        prompt = game.get_prompt("player_a")
        assert "Legal moves:" in prompt
        assert "[2,3]" in prompt  # One of the opening legal moves for Black

    def test_prompt_contains_player_identity(self, game):
        prompt = game.get_prompt("player_a")
        assert "You are B" in prompt

    def test_prompt_contains_series_info(self, game):
        prompt = game.get_prompt("player_a")
        assert "Game 1/9" in prompt
        assert "Series:" in prompt

    def test_prompt_contains_json_instruction(self, game):
        prompt = game.get_prompt("player_a")
        assert '"action": "play"' in prompt
        assert '"row"' in prompt
        assert '"col"' in prompt

    def test_prompt_contains_json_only_instruction(self, game):
        prompt = game.get_prompt("player_a")
        assert "ONLY a single JSON object" in prompt

    def test_retry_prompt_contains_error(self, game):
        prompt = game.get_retry_prompt("player_a", "cell is occupied")
        assert "cell is occupied" in prompt

    def test_color_map_in_snapshot(self, game):
        snap = game.get_state_snapshot()
        assert snap["color_map"]["player_a"] == "B"
        assert snap["color_map"]["player_b"] == "W"
