"""Tests for the Checkers engine."""

import pytest
from llmtourney.events.checkers.board import (
    Move,
    check_game_over,
    count_pieces,
    create_initial_board,
    execute_move,
    find_captures,
    get_all_valid_moves,
    render_board,
)
from llmtourney.events.checkers.engine import CheckersEvent


@pytest.fixture
def game():
    g = CheckersEvent()
    g.reset(seed=42)
    return g


def _empty_board() -> list[list[str]]:
    return [[""] * 8 for _ in range(8)]


# ------------------------------------------------------------------
# Board setup
# ------------------------------------------------------------------

class TestBoardSetup:
    def test_initial_board_dimensions(self):
        board = create_initial_board()
        assert len(board) == 8
        assert all(len(row) == 8 for row in board)

    def test_black_pieces_in_rows_0_to_2(self):
        board = create_initial_board()
        for r in range(3):
            for c in range(8):
                if (r + c) % 2 == 1:
                    assert board[r][c] == "b"
                else:
                    assert board[r][c] == ""

    def test_red_pieces_in_rows_5_to_7(self):
        board = create_initial_board()
        for r in range(5, 8):
            for c in range(8):
                if (r + c) % 2 == 1:
                    assert board[r][c] == "r"
                else:
                    assert board[r][c] == ""

    def test_middle_rows_empty(self):
        board = create_initial_board()
        for r in range(3, 5):
            for c in range(8):
                assert board[r][c] == ""

    def test_12_pieces_each(self):
        board = create_initial_board()
        counts = count_pieces(board)
        assert counts["black"] == 12
        assert counts["red"] == 12

    def test_light_squares_always_empty(self):
        board = create_initial_board()
        for r in range(8):
            for c in range(8):
                if (r + c) % 2 == 0:
                    assert board[r][c] == ""


# ------------------------------------------------------------------
# Move generation
# ------------------------------------------------------------------

class TestMoveGeneration:
    def test_initial_black_moves(self):
        board = create_initial_board()
        moves = get_all_valid_moves(board, "black")
        # Row 2 pieces can move down — 7 pieces on row 2, each at most 2 dirs
        # but some blocked by other pieces. Only row 2 can move (rows 0,1 blocked)
        assert len(moves) == 7

    def test_initial_red_moves(self):
        board = create_initial_board()
        moves = get_all_valid_moves(board, "red")
        # Symmetric — row 5 pieces can move up
        assert len(moves) == 7

    def test_black_moves_down(self):
        board = _empty_board()
        board[3][2] = "b"
        moves = get_all_valid_moves(board, "black")
        destinations = {m.to for m in moves}
        assert (4, 1) in destinations
        assert (4, 3) in destinations
        assert len(moves) == 2

    def test_red_moves_up(self):
        board = _empty_board()
        board[4][3] = "r"
        moves = get_all_valid_moves(board, "red")
        destinations = {m.to for m in moves}
        assert (3, 2) in destinations
        assert (3, 4) in destinations
        assert len(moves) == 2

    def test_king_moves_all_directions(self):
        board = _empty_board()
        board[4][3] = "B"  # black king
        moves = get_all_valid_moves(board, "black")
        destinations = {m.to for m in moves}
        assert (3, 2) in destinations  # up-left
        assert (3, 4) in destinations  # up-right
        assert (5, 2) in destinations  # down-left
        assert (5, 4) in destinations  # down-right
        assert len(moves) == 4

    def test_edge_piece_limited_moves(self):
        board = _empty_board()
        board[3][0] = "b"
        moves = get_all_valid_moves(board, "black")
        # Left edge — can only go down-right
        assert len(moves) == 1
        assert moves[0].to == (4, 1)

    def test_no_moves_returns_empty(self):
        board = _empty_board()
        board[7][0] = "b"  # corner, can't move down further
        moves = get_all_valid_moves(board, "black")
        assert len(moves) == 0


# ------------------------------------------------------------------
# Captures
# ------------------------------------------------------------------

class TestCaptures:
    def test_simple_capture(self):
        board = _empty_board()
        board[3][2] = "b"
        board[4][3] = "r"  # enemy adjacent
        moves = get_all_valid_moves(board, "black")
        assert len(moves) == 1
        m = moves[0]
        assert m.fr == (3, 2)
        assert m.to == (5, 4)
        assert m.captures == [(4, 3)]

    def test_mandatory_capture(self):
        """When captures exist, simple moves are not returned."""
        board = _empty_board()
        board[3][2] = "b"  # this piece can capture
        board[4][3] = "r"
        board[3][4] = "b"  # this piece could move simply
        moves = get_all_valid_moves(board, "black")
        # Only capture moves returned
        assert all(m.captures for m in moves)

    def test_multi_jump(self):
        board = _empty_board()
        board[2][1] = "b"
        board[3][2] = "r"
        board[5][4] = "r"
        moves = get_all_valid_moves(board, "black")
        # Should find the double jump: (2,1) -> (4,3) -> (6,5)
        multi = [m for m in moves if len(m.captures) == 2]
        assert len(multi) == 1
        assert multi[0].fr == (2, 1)
        assert multi[0].to == (6, 5)
        assert (3, 2) in multi[0].captures
        assert (5, 4) in multi[0].captures

    def test_capture_removes_piece(self):
        board = _empty_board()
        board[3][2] = "b"
        board[4][3] = "r"
        moves = get_all_valid_moves(board, "black")
        new_board = execute_move(board, moves[0])
        assert new_board[4][3] == ""  # captured piece removed
        assert new_board[3][2] == ""  # origin cleared
        assert new_board[5][4] == "b"  # piece landed

    def test_cant_jump_own_piece(self):
        board = _empty_board()
        board[3][2] = "b"
        board[4][3] = "b"  # own piece — can't jump
        moves = get_all_valid_moves(board, "black")
        # Should have simple move (4,1) only, not a jump
        assert not any(m.captures for m in moves)

    def test_cant_jump_to_occupied(self):
        board = _empty_board()
        board[3][2] = "b"
        board[4][3] = "r"
        board[5][4] = "b"  # landing occupied — blocks the capture
        moves = get_all_valid_moves(board, "black")
        # No captures possible (landing blocked)
        capture = [m for m in moves if m.captures]
        assert len(capture) == 0
        # Both black pieces have simple moves
        moves_from_32 = [m for m in moves if m.fr == (3, 2)]
        assert len(moves_from_32) == 1  # (3,2)->(4,1) only

    def test_king_captures_backward(self):
        board = _empty_board()
        board[5][4] = "B"  # black king
        board[4][3] = "r"  # enemy above-left
        moves = get_all_valid_moves(board, "black")
        caps = [m for m in moves if m.captures]
        assert len(caps) == 1
        assert caps[0].to == (3, 2)


# ------------------------------------------------------------------
# King promotion
# ------------------------------------------------------------------

class TestPromotion:
    def test_black_promotes_at_row_7(self):
        board = _empty_board()
        board[6][1] = "b"
        move = Move(fr=(6, 1), to=(7, 0))
        new_board = execute_move(board, move)
        assert new_board[7][0] == "B"

    def test_red_promotes_at_row_0(self):
        board = _empty_board()
        board[1][0] = "r"
        move = Move(fr=(1, 0), to=(0, 1))
        new_board = execute_move(board, move)
        assert new_board[0][1] == "R"

    def test_no_promotion_mid_board(self):
        board = _empty_board()
        board[3][2] = "b"
        move = Move(fr=(3, 2), to=(4, 3))
        new_board = execute_move(board, move)
        assert new_board[4][3] == "b"  # still regular


# ------------------------------------------------------------------
# Game over detection
# ------------------------------------------------------------------

class TestGameOver:
    def test_no_pieces_loses(self):
        board = _empty_board()
        board[4][3] = "b"  # only black has pieces
        result = check_game_over(board, "red")
        assert result == "black_wins"

    def test_no_moves_loses(self):
        board = _empty_board()
        board[7][0] = "b"  # corner, can't move
        result = check_game_over(board, "black")
        assert result == "red_wins"

    def test_game_continues(self):
        board = create_initial_board()
        result = check_game_over(board, "black")
        assert result is None


# ------------------------------------------------------------------
# Engine setup
# ------------------------------------------------------------------

class TestCheckersSetup:
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

    def test_initial_board(self, game):
        counts = count_pieces(game._board)
        assert counts["black"] == 12
        assert counts["red"] == 12

    def test_action_schema_present(self, game):
        schema = game.action_schema
        assert schema["type"] == "object"
        assert "action" in schema["properties"]
        assert "from" in schema["properties"]
        assert "to" in schema["properties"]

    def test_initial_scores_zero(self, game):
        scores = game.get_scores()
        assert scores["player_a"] == 0.0
        assert scores["player_b"] == 0.0


# ------------------------------------------------------------------
# Engine validation
# ------------------------------------------------------------------

class TestCheckersValidation:
    def test_wrong_player_rejected(self, game):
        result = game.validate_action(
            "player_b", {"action": "move", "from": [5, 0], "to": [4, 1]}
        )
        assert result.legal is False
        assert "not your turn" in result.reason.lower()

    def test_unknown_action_rejected(self, game):
        result = game.validate_action(
            "player_a", {"action": "jump", "from": [2, 1], "to": [3, 0]}
        )
        assert result.legal is False

    def test_invalid_move_rejected(self, game):
        result = game.validate_action(
            "player_a", {"action": "move", "from": [0, 0], "to": [1, 1]}
        )
        assert result.legal is False  # [0,0] is a light square, no piece there

    def test_valid_move_accepted(self, game):
        result = game.validate_action(
            "player_a", {"action": "move", "from": [2, 1], "to": [3, 0]}
        )
        assert result.legal is True


# ------------------------------------------------------------------
# Engine play
# ------------------------------------------------------------------

class TestCheckersPlay:
    def test_apply_action(self, game):
        game.apply_action(
            "player_a", {"action": "move", "from": [2, 1], "to": [3, 0]}
        )
        assert game._board[3][0] == "b"
        assert game._board[2][1] == ""

    def test_turns_alternate(self, game):
        assert game.current_player() == "player_a"
        game.apply_action(
            "player_a", {"action": "move", "from": [2, 1], "to": [3, 0]}
        )
        assert game.current_player() == "player_b"

    def test_forfeit_plays_first_move(self, game):
        game.forfeit_turn("player_a")
        snap = game.get_state_snapshot()
        assert snap["was_valid"] is False
        assert snap["violation_type"] == "forfeit"
        assert snap["last_move"] is not None

    def test_force_forfeit_match(self, game):
        game.force_forfeit_match("player_a")
        assert game.is_terminal() is True


# ------------------------------------------------------------------
# Engine scoring
# ------------------------------------------------------------------

class TestCheckersScoring:
    def _play_until_over(self, game):
        """Brute-force play by always taking first available move."""
        while not game.is_terminal():
            pid = game.current_player()
            color = game._color_map[pid]
            moves = get_all_valid_moves(game._board, color)
            if not moves:
                break
            m = moves[0]
            game.apply_action(
                pid,
                {"action": "move", "from": list(m.fr), "to": list(m.to),
                 "path": [list(p) for p in m.path] if m.path else None},
            )

    def test_scores_add_up(self):
        """After a 1-game series, scores sum to 1.0 (win) or 1.0 (draw)."""
        game = CheckersEvent(games_per_match=1)
        game.reset(seed=42)
        self._play_until_over(game)
        scores = game.get_scores()
        total = scores["player_a"] + scores["player_b"]
        assert total == 1.0  # win (1+0) or draw (0.5+0.5)


# ------------------------------------------------------------------
# Draw by move limit
# ------------------------------------------------------------------

class TestDrawRule:
    def test_40_moves_without_capture_is_draw(self):
        game = CheckersEvent(games_per_match=1)
        game.reset(seed=42)
        # Set up a board with kings far apart, pre-advance the counter
        game._board = _empty_board()
        game._board[0][1] = "B"  # black king
        game._board[7][6] = "R"  # red king
        game._moves_without_capture = 38  # only 2 more to trigger draw

        # Two moves should trigger the draw
        for _ in range(2):
            pid = game.current_player()
            color = game._color_map[pid]
            moves = get_all_valid_moves(game._board, color)
            m = moves[0]
            game.apply_action(
                pid,
                {"action": "move", "from": list(m.fr), "to": list(m.to)},
            )

        assert game._game_results[-1] == "draw"
        assert game.is_terminal() is True


# ------------------------------------------------------------------
# Draw by repetition
# ------------------------------------------------------------------

class TestRepetitionDraw:
    def test_threefold_repetition_is_draw(self):
        game = CheckersEvent(games_per_match=1)
        game.reset(seed=42)
        # Set up two kings that will shuffle back and forth
        game._board = _empty_board()
        game._board[0][1] = "B"  # black king top-left area
        game._board[7][6] = "R"  # red king bottom-right area
        game._position_history = {}
        game._record_position()  # record initial position

        # Shuffle back and forth — same 2 positions repeat
        moves_sequence = [
            # black king: (0,1)->(1,2), red king: (7,6)->(6,5)
            # black king: (1,2)->(0,1), red king: (6,5)->(7,6)  -- back to start
            ("player_a", [0, 1], [1, 2]),
            ("player_b", [7, 6], [6, 5]),
            ("player_a", [1, 2], [0, 1]),
            ("player_b", [6, 5], [7, 6]),  # position repeated 2x
            ("player_a", [0, 1], [1, 2]),
            ("player_b", [7, 6], [6, 5]),
            ("player_a", [1, 2], [0, 1]),
            ("player_b", [6, 5], [7, 6]),  # position repeated 3x → draw
        ]
        for pid, fr, to in moves_sequence:
            if game.is_terminal():
                break
            game.apply_action(pid, {"action": "move", "from": fr, "to": to})

        assert game.is_terminal() is True
        assert game._game_results[-1] == "draw"


# ------------------------------------------------------------------
# Multi-game series
# ------------------------------------------------------------------

class TestMultiGameSeries:
    def test_alternating_colors(self):
        game = CheckersEvent(games_per_match=2)
        game.reset(seed=42)
        assert game._color_map["player_a"] == "black"
        # Simulate game 1 ending
        game._record_game_result("black_wins")
        game._advance_or_end()
        assert game._color_map["player_a"] == "red"  # swapped

    def test_board_resets_between_games(self):
        game = CheckersEvent(games_per_match=2)
        game.reset(seed=42)
        game._record_game_result("black_wins")
        game._advance_or_end()
        counts = count_pieces(game._board)
        assert counts["black"] == 12
        assert counts["red"] == 12


# ------------------------------------------------------------------
# Prompt
# ------------------------------------------------------------------

class TestCheckersPrompt:
    def test_prompt_contains_board(self, game):
        prompt = game.get_prompt("player_a")
        assert "Board:" in prompt

    def test_prompt_contains_identity(self, game):
        prompt = game.get_prompt("player_a")
        assert "You are black" in prompt

    def test_prompt_contains_available_moves(self, game):
        prompt = game.get_prompt("player_a")
        assert "Available moves:" in prompt
        assert "[2,1]" in prompt  # at least one valid move

    def test_prompt_contains_json_instruction(self, game):
        prompt = game.get_prompt("player_a")
        assert "ONLY a single JSON object" in prompt

    def test_prompt_contains_series_info(self, game):
        prompt = game.get_prompt("player_a")
        assert "Game 1 of 5" in prompt
        assert "Series score" in prompt

    def test_retry_prompt_contains_error(self, game):
        prompt = game.get_retry_prompt("player_a", "invalid move")
        assert "invalid move" in prompt


# ------------------------------------------------------------------
# Snapshot
# ------------------------------------------------------------------

class TestCheckersSnapshot:
    def test_snapshot_has_all_keys(self, game):
        snap = game.get_state_snapshot()
        expected_keys = [
            "board", "scores", "series_scores", "hand_number",
            "game_turn", "turn_number", "active_player", "result",
            "terminal", "last_move", "pieces_remaining",
            "moves_without_capture", "color_map", "was_valid",
            "violation_type",
        ]
        for key in expected_keys:
            assert key in snap, f"Missing key: {key}"

    def test_snapshot_updates_after_move(self, game):
        game.apply_action(
            "player_a", {"action": "move", "from": [2, 1], "to": [3, 0]}
        )
        snap = game.get_state_snapshot()
        assert snap["last_move"]["from"] == [2, 1]
        assert snap["last_move"]["to"] == [3, 0]
        assert snap["was_valid"] is True
        assert snap["turn_number"] == 1


# ------------------------------------------------------------------
# Board rendering
# ------------------------------------------------------------------

class TestRenderBoard:
    def test_render_has_column_headers(self):
        board = create_initial_board()
        text = render_board(board)
        assert "0   1   2   3   4   5   6   7" in text

    def test_render_shows_pieces(self):
        board = create_initial_board()
        text = render_board(board)
        assert "b" in text
        assert "r" in text
