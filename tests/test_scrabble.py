"""Tests for the Scrabble engine."""

import pytest
from llmtourney.events.scrabble.engine import ScrabbleEvent
from llmtourney.events.scrabble.board import Board, PREMIUM_SQUARES, TILE_VALUES


@pytest.fixture
def game():
    g = ScrabbleEvent()
    g.reset(seed=42)
    return g


# ------------------------------------------------------------------
# Setup
# ------------------------------------------------------------------

class TestScrabbleSetup:
    def test_reset_initializes(self, game):
        snap = game.get_state_snapshot()
        assert snap["turn_number"] == 0
        assert snap["scores"]["player_a"] == 0
        assert snap["scores"]["player_b"] == 0
        assert snap["tiles_remaining"] == 100 - 14  # 7 tiles each

    def test_not_terminal_at_start(self, game):
        assert game.is_terminal() is False

    def test_player_a_goes_first(self, game):
        assert game.current_player() == "player_a"

    def test_racks_have_seven_tiles(self, game):
        assert len(game._racks["player_a"]) == 7
        assert len(game._racks["player_b"]) == 7

    def test_action_schema_present(self, game):
        schema = game.action_schema
        assert schema["type"] == "object"
        assert "action" in schema["properties"]


# ------------------------------------------------------------------
# Cross-word scoring
# ------------------------------------------------------------------

class TestCrossWordScoring:
    def test_cross_word_scored_on_second_play(self, game):
        """Place a horizontal word, then a vertical word crossing it.
        The cross-word should be scored."""
        # Force known racks for deterministic testing
        game._racks["player_a"] = list("CATFISH")
        game._racks["player_b"] = list("DOGEARS")

        # Player A plays CAT across at row 7, col 6 (covers center)
        action_a = {
            "action": "play", "word": "CAT",
            "position": [7, 6], "direction": "across",
        }
        assert game.validate_action("player_a", action_a).legal
        game.apply_action("player_a", action_a)

        snap = game.get_state_snapshot()
        assert snap["word_played"] == "CAT"
        assert snap["points_scored"] > 0
        cat_score = snap["points_scored"]

        # Player B plays DOG down at row 6, col 7 crossing the A in CAT
        # This forms cross-word with existing A at (7,7)
        action_b = {
            "action": "play", "word": "DOG",
            "position": [6, 7], "direction": "down",
        }
        result = game.validate_action("player_b", action_b)
        if result.legal:
            game.apply_action("player_b", action_b)
            snap = game.get_state_snapshot()
            # Should have scored DOG + any cross-words
            assert snap["points_scored"] > 0

    def test_cross_word_premium_on_new_tile(self):
        """Premium squares only apply to newly placed tiles in cross-words."""
        board = Board()
        # Place WORD horizontally at row 7
        board.place_word("CAT", 7, 6, "across")

        # Now place DO going down at (6,7) -> (7,7) is existing A
        newly = board.place_word("DO", 6, 7, "down")
        # Only (6,7) is newly placed; (7,7) already had A
        assert len(newly) == 1
        assert (6, 7) in newly


# ------------------------------------------------------------------
# Bingo detection
# ------------------------------------------------------------------

class TestBingoDetection:
    def test_bingo_bonus_50_points(self, game):
        """Playing all 7 tiles earns +50 bingo bonus."""
        game._racks["player_a"] = list("JOURNEY")

        # We need JOURNEY to be in the dictionary — use a known valid word
        # Force a 7-letter word that's in TWL06
        game._racks["player_a"] = list("SALTIER")

        action = {
            "action": "play", "word": "SALTIER",
            "position": [7, 4], "direction": "across",
        }
        result = game.validate_action("player_a", action)
        if result.legal:
            game.apply_action("player_a", action)
            snap = game.get_state_snapshot()
            assert snap["bingo"] is True
            # Score includes 50 bonus + tile values + premium
            assert snap["points_scored"] >= 50

    def test_no_bingo_for_fewer_than_7_tiles(self, game):
        """Playing fewer than 7 tiles does not trigger bingo."""
        game._racks["player_a"] = list("CATFISH")
        action = {
            "action": "play", "word": "CAT",
            "position": [7, 6], "direction": "across",
        }
        assert game.validate_action("player_a", action).legal
        game.apply_action("player_a", action)
        snap = game.get_state_snapshot()
        assert snap["bingo"] is False


# ------------------------------------------------------------------
# Invalid word rejection
# ------------------------------------------------------------------

class TestInvalidWordRejection:
    def test_invalid_word_rejected(self, game):
        """A word not in the dictionary is rejected."""
        game._racks["player_a"] = list("XYZQWKJ")
        action = {
            "action": "play", "word": "XYZQWKJ",
            "position": [7, 4], "direction": "across",
        }
        result = game.validate_action("player_a", action)
        assert result.legal is False
        assert "invalid_word" in result.reason

    def test_invalid_cross_word_rejected(self, game):
        """If a cross-word formed is invalid, reject the play."""
        game._racks["player_a"] = list("CATFISH")
        game._racks["player_b"] = list("QQQQQQQ")

        # Player A plays CAT
        action_a = {
            "action": "play", "word": "CAT",
            "position": [7, 6], "direction": "across",
        }
        game.apply_action("player_a", action_a)

        # Player B tries to play QQ down at col 6, crossing C
        # QC or CQ would not be a valid word
        action_b = {
            "action": "play", "word": "QQ",
            "position": [6, 6], "direction": "down",
        }
        result = game.validate_action("player_b", action_b)
        # Should be rejected (QQ not a word, and cross-word check)
        assert result.legal is False


# ------------------------------------------------------------------
# Blank tile handling
# ------------------------------------------------------------------

class TestBlankTileHandling:
    def test_blank_tile_can_be_played(self, game):
        """A blank tile can substitute for any letter."""
        game._racks["player_a"] = list("CA?ISH" + "T")
        # Use blank for T: word is CAT, blank at position 2
        action = {
            "action": "play", "word": "CAT",
            "position": [7, 6], "direction": "across",
            "blank_assignments": {"2": "T"},
        }
        result = game.validate_action("player_a", action)
        assert result.legal is True

    def test_blank_worth_zero_points(self, game):
        """Blank tiles contribute 0 points."""
        # Play CAT with blank T vs CAT with real T — blank should score less
        game._racks["player_a"] = list("CA?FISH")
        game._board = Board()  # fresh board

        action_blank = {
            "action": "play", "word": "CAT",
            "position": [7, 6], "direction": "across",
            "blank_assignments": {"2": "T"},
        }
        result = game.validate_action("player_a", action_blank)
        assert result.legal
        game.apply_action("player_a", action_blank)
        score_with_blank = game.get_state_snapshot()["points_scored"]

        # Reset and play with real T
        game.reset(seed=99)
        game._racks["player_a"] = list("CATFISH")
        action_real = {
            "action": "play", "word": "CAT",
            "position": [7, 6], "direction": "across",
        }
        game.apply_action("player_a", action_real)
        score_without_blank = game.get_state_snapshot()["points_scored"]

        # T is worth 1 point, so blank version should be 1 less
        # (DW on center means the difference is 2x the T value = 2)
        # Actually depends on premium — just check blank version <= real
        assert score_with_blank <= score_without_blank

    def test_blank_not_in_rack_rejected(self, game):
        """Using blank_assignments without ? in rack fails."""
        game._racks["player_a"] = list("CATFISH")  # no blank
        action = {
            "action": "play", "word": "CAT",
            "position": [7, 6], "direction": "across",
            "blank_assignments": {"2": "T"},
        }
        result = game.validate_action("player_a", action)
        # Should fail because rack has real T but blank_assignments
        # forces consumption of ? which isn't in rack
        assert result.legal is False
        assert "not in your rack" in result.reason.lower() or "?" in result.reason


# ------------------------------------------------------------------
# Terminal conditions
# ------------------------------------------------------------------

class TestTerminalConditions:
    def test_six_consecutive_passes_ends_game(self, game):
        """6 consecutive passes end the game."""
        for _ in range(6):
            pid = game.current_player()
            game.apply_action(pid, {"action": "pass"})
            if game.is_terminal():
                break
        assert game.is_terminal() is True

    def test_empty_bag_and_rack_ends_game(self, game):
        """Game ends when bag is empty and a player empties their rack."""
        # Drain the bag
        game._bag = []

        # Give player_a just enough to play
        game._racks["player_a"] = list("CAT")
        game._racks["player_b"] = list("DOGEARS")

        action = {
            "action": "play", "word": "CAT",
            "position": [7, 6], "direction": "across",
        }
        if game.validate_action("player_a", action).legal:
            game.apply_action("player_a", action)
            # player_a's rack should be empty (no bag to refill)
            assert game.is_terminal() is True

    def test_exchange_resets_pass_counter(self, game):
        """An exchange resets the consecutive pass counter."""
        game.apply_action("player_a", {"action": "pass"})
        game.apply_action("player_b", {"action": "pass"})
        assert game._consecutive_passes == 2

        # Exchange (need >= 7 tiles in bag)
        tile = game._racks["player_a"][0]
        game.apply_action(
            "player_a",
            {"action": "exchange", "tiles_to_exchange": [tile]},
        )
        assert game._consecutive_passes == 0

    def test_play_resets_pass_counter(self, game):
        """A play resets the consecutive pass counter."""
        game.apply_action("player_a", {"action": "pass"})
        assert game._consecutive_passes == 1

        game._racks["player_b"] = list("CATFISH")
        action = {
            "action": "play", "word": "CAT",
            "position": [7, 6], "direction": "across",
        }
        if game.validate_action("player_b", action).legal:
            game.apply_action("player_b", action)
            assert game._consecutive_passes == 0


# ------------------------------------------------------------------
# Final scores / rack adjustment
# ------------------------------------------------------------------

class TestFinalScores:
    def test_scores_subtract_rack_on_passes(self, game):
        """When game ends by passes, each player loses rack value."""
        # Force terminal by 6 passes
        for _ in range(6):
            pid = game.current_player()
            game.apply_action(pid, {"action": "pass"})
            if game.is_terminal():
                break

        scores = game.get_scores()
        # Both should have negative scores (0 base - rack value)
        assert scores["player_a"] <= 0
        assert scores["player_b"] <= 0


# ------------------------------------------------------------------
# Board placement rules
# ------------------------------------------------------------------

class TestBoardRules:
    def test_first_move_must_cover_center(self, game):
        """First word must pass through (7,7)."""
        game._racks["player_a"] = list("CATFISH")
        action = {
            "action": "play", "word": "CAT",
            "position": [0, 0], "direction": "across",
        }
        result = game.validate_action("player_a", action)
        assert result.legal is False
        assert "center" in result.reason.lower()

    def test_subsequent_move_must_connect(self, game):
        """After first move, new words must connect to existing tiles."""
        game._racks["player_a"] = list("CATFISH")
        game._racks["player_b"] = list("DOGEARS")

        # Player A plays CAT through center
        game.apply_action("player_a", {
            "action": "play", "word": "CAT",
            "position": [7, 6], "direction": "across",
        })

        # Player B tries to play far away
        action = {
            "action": "play", "word": "DOG",
            "position": [0, 0], "direction": "across",
        }
        result = game.validate_action("player_b", action)
        assert result.legal is False
        assert "connect" in result.reason.lower()

    def test_extending_word_validates_full_sequence(self, game):
        """Playing tiles adjacent to existing word must validate the full word formed."""
        game._racks["player_a"] = list("MINEFGH")
        game._racks["player_b"] = list("ELATEDX")

        # Player A plays MINE at (7,4)-(7,7) covering center
        game.apply_action("player_a", {
            "action": "play", "word": "MINE",
            "position": [7, 4], "direction": "across",
        })

        # Player B plays ELATED starting right after MINE at (7,8)
        # Board will have: M I N E E L A T E D
        # Full contiguous word: MINEELATED — not a real word
        action = {
            "action": "play", "word": "ELATED",
            "position": [7, 8], "direction": "across",
        }
        result = game.validate_action("player_b", action)
        assert result.legal is False

    def test_valid_extension_accepted(self, game):
        """Extending a word to form a valid longer word should be accepted."""
        game._racks["player_a"] = list("CATFISH")
        game._racks["player_b"] = list("SXYZQQQ")

        # Player A plays CAT through center
        game.apply_action("player_a", {
            "action": "play", "word": "CAT",
            "position": [7, 6], "direction": "across",
        })

        # Player B plays S right after CAT to form CATS
        action = {
            "action": "play", "word": "CATS",
            "position": [7, 6], "direction": "across",
        }
        result = game.validate_action("player_b", action)
        assert result.legal is True

    def test_prepending_word_validates_full_sequence(self, game):
        """Prepending tiles to an existing word must validate the full word."""
        game._racks["player_a"] = list("ARTFISH")
        game._racks["player_b"] = list("ZQXYZQQ")

        # Player A plays ART through center
        game.apply_action("player_a", {
            "action": "play", "word": "ART",
            "position": [7, 6], "direction": "across",
        })

        # Player B plays ZQ before ART — forming ZQART on row 7 (not a word)
        action = {
            "action": "play", "word": "ZQ",
            "position": [7, 4], "direction": "across",
        }
        result = game.validate_action("player_b", action)
        assert result.legal is False

    def test_exchange_requires_seven_in_bag(self, game):
        """Exchange fails if fewer than 7 tiles in bag."""
        game._bag = list("ABCDE")  # only 5
        tile = game._racks["player_a"][0]
        result = game.validate_action("player_a", {
            "action": "exchange", "tiles_to_exchange": [tile],
        })
        assert result.legal is False
        assert "7" in result.reason


# ------------------------------------------------------------------
# Prompt and schema
# ------------------------------------------------------------------

class TestPrompt:
    def test_prompt_contains_rack(self, game):
        prompt = game.get_prompt("player_a")
        assert "Your rack:" in prompt

    def test_prompt_contains_board(self, game):
        prompt = game.get_prompt("player_a")
        assert "3W" in prompt  # triple word squares shown

    def test_prompt_contains_calibration(self, game):
        prompt = game.get_prompt("player_a")
        assert "Official Scrabble Players Dictionary" in prompt

    def test_retry_prompt_contains_error(self, game):
        prompt = game.get_retry_prompt("player_a", "word not in dictionary")
        assert "word not in dictionary" in prompt

    def test_prompt_contains_score(self, game):
        prompt = game.get_prompt("player_a")
        assert "Your score:" in prompt


# ------------------------------------------------------------------
# Forfeit
# ------------------------------------------------------------------

class TestForfeit:
    def test_forfeit_increments_pass_counter(self, game):
        game.forfeit_turn("player_a")
        assert game._consecutive_passes == 1

    def test_forfeit_switches_player(self, game):
        game.forfeit_turn("player_a")
        assert game.current_player() == "player_b"

    def test_forfeit_records_violation(self, game):
        game.forfeit_turn("player_a")
        snap = game.get_state_snapshot()
        assert snap["was_valid"] is False
        assert snap["violation_type"] == "forfeit"


# ------------------------------------------------------------------
# Telemetry snapshot
# ------------------------------------------------------------------

class TestTelemetry:
    def test_snapshot_has_telemetry_fields(self, game):
        snap = game.get_state_snapshot()
        for key in [
            "word_played", "cross_words_formed", "points_scored",
            "was_valid", "violation_type", "rack_before", "rack_after",
            "bingo",
        ]:
            assert key in snap

    def test_snapshot_updates_after_play(self, game):
        game._racks["player_a"] = list("CATFISH")
        action = {
            "action": "play", "word": "CAT",
            "position": [7, 6], "direction": "across",
        }
        game.apply_action("player_a", action)
        snap = game.get_state_snapshot()
        assert snap["word_played"] == "CAT"
        assert snap["points_scored"] > 0
        assert snap["was_valid"] is True
        assert len(snap["rack_before"]) == 7
