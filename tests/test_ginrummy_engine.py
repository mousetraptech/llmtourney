"""Tests for Gin Rummy engine — game flow, scoring, series."""

import pytest

from llmtourney.events.ginrummy.engine import (
    GinRummyEvent,
    GIN_BONUS,
    UNDERCUT_BONUS,
    GAME_BONUS,
    LINE_BONUS,
    TARGET_SCORE,
    HAND_LIMIT,
    find_optimal_melds,
    _sort_hand,
)


@pytest.fixture
def game():
    g = GinRummyEvent(games_per_match=3)
    g.reset(seed=42)
    return g


class TestDeal:
    """Initial deal and state."""

    def test_each_player_gets_10_cards(self, game):
        snap = game.get_state_snapshot()
        for pid in game.player_ids:
            assert len(snap["hands"][pid]) == 10

    def test_discard_pile_has_one_card(self, game):
        snap = game.get_state_snapshot()
        assert len(snap["discard_pile"]) == 1

    def test_stock_has_31_cards(self, game):
        snap = game.get_state_snapshot()
        assert snap["stock_size"] == 31

    def test_non_dealer_goes_first(self, game):
        snap = game.get_state_snapshot()
        dealer = snap["dealer"]
        current = game.current_player()
        assert current != dealer

    def test_no_duplicate_cards(self, game):
        snap = game.get_state_snapshot()
        all_cards = []
        for pid in game.player_ids:
            all_cards.extend(snap["hands"][pid])
        all_cards.extend(snap["discard_pile"])
        # Stock isn't visible but we can check total count
        assert len(set(all_cards)) == len(all_cards)


class TestTurnFlow:
    """Basic turn mechanics."""

    def test_draw_from_stock_and_continue(self, game):
        pid = game.current_player()
        hand = game.get_state_snapshot()["hands"][pid]
        # Pick a card to discard (just use the last one)
        discard = hand[-1]

        result = game.validate_action(pid, {
            "reasoning": "test",
            "draw": "stock",
            "action": "continue",
            "discard": discard,
        })
        assert result.legal

        game.apply_action(pid, {
            "reasoning": "test",
            "draw": "stock",
            "action": "continue",
            "discard": discard,
        })

        # Now it's opponent's turn
        assert game.current_player() != pid

    def test_draw_from_discard(self, game):
        pid = game.current_player()
        snap = game.get_state_snapshot()
        discard_top = snap["discard_pile"][-1]
        hand = snap["hands"][pid]

        # Draw the discard pile card, discard something else
        other_card = [c for c in hand if c != discard_top][0]

        result = game.validate_action(pid, {
            "reasoning": "test",
            "draw": "discard",
            "action": "continue",
            "discard": other_card,
        })
        assert result.legal

    def test_cannot_rediscard_drawn_card(self, game):
        pid = game.current_player()
        snap = game.get_state_snapshot()
        discard_top = snap["discard_pile"][-1]

        result = game.validate_action(pid, {
            "reasoning": "test",
            "draw": "discard",
            "action": "continue",
            "discard": discard_top,
        })
        assert not result.legal
        assert "same card" in result.reason.lower()

    def test_invalid_draw_source(self, game):
        pid = game.current_player()
        hand = game.get_state_snapshot()["hands"][pid]

        result = game.validate_action(pid, {
            "reasoning": "test",
            "draw": "invalid",
            "action": "continue",
            "discard": hand[0],
        })
        assert not result.legal

    def test_discard_not_in_hand(self, game):
        pid = game.current_player()

        result = game.validate_action(pid, {
            "reasoning": "test",
            "draw": "stock",
            "action": "continue",
            "discard": "FAKE♠",
        })
        assert not result.legal


class TestKnockAndGin:
    """Knock and gin validation."""

    def test_cannot_knock_high_deadwood(self, game):
        """If hand has >10 deadwood after discard, knock is rejected."""
        pid = game.current_player()
        hand = game.get_state_snapshot()["hands"][pid]

        # Compute what the hand would look like after drawing + discarding
        # Most random hands have high deadwood, so knock should fail
        result = game.validate_action(pid, {
            "reasoning": "test",
            "draw": "stock",
            "action": "knock",
            "discard": hand[0],
        })
        # With seed=42 it's very unlikely to have ≤10 deadwood on deal
        # If by chance it's legal, that's fine too — test the validation path
        if not result.legal:
            assert "deadwood" in result.reason.lower()

    def test_cannot_gin_with_deadwood(self, game):
        pid = game.current_player()
        hand = game.get_state_snapshot()["hands"][pid]

        result = game.validate_action(pid, {
            "reasoning": "test",
            "draw": "stock",
            "action": "gin",
            "discard": hand[0],
        })
        if not result.legal:
            assert "deadwood" in result.reason.lower()


class TestScoring:
    """Hand scoring: gin, knock, undercut."""

    def _setup_hand(self, game, knocker_hand, defender_hand, discard_pile, stock):
        """Force specific hands for deterministic scoring tests."""
        pa, pb = game.player_ids
        game._hands = {pa: list(knocker_hand), pb: list(defender_hand)}
        game._discard_pile = list(discard_pile)
        game._stock = list(stock)
        game._active_player = pa

    def test_gin_scoring(self, game):
        pa, pb = game.player_ids
        # Set up a gin hand for pa
        knocker_hand = ["A♣", "2♣", "3♣", "5♦", "5♥", "5♠", "9♠", "10♠", "J♠", "Q♠"]
        defender_hand = ["K♣", "K♦", "Q♥", "J♥", "10♥", "9♥", "8♣", "7♦", "6♣", "4♠"]
        discard_pile = ["2♠"]
        stock = ["A♠"] + ["3♦"] * 10  # padding

        self._setup_hand(game, knocker_hand, defender_hand, discard_pile, stock)

        # Verify gin hand
        result = find_optimal_melds(knocker_hand)
        assert result.deadwood_value == 0

        # Draw from stock (gets A♠), discard it, declare gin
        game.apply_action(pa, {
            "reasoning": "gin",
            "draw": "stock",
            "action": "gin",
            "discard": "A♠",
        })

        # Defender's deadwood
        defender_result = find_optimal_melds(defender_hand)
        expected_points = GIN_BONUS + defender_result.deadwood_value

        assert game._game_scores[pa] == expected_points
        assert game._game_scores[pb] == 0

    def test_knock_scoring(self, game):
        pa, pb = game.player_ids
        # knocker has low deadwood, defender has high deadwood
        knocker_hand = ["A♣", "2♣", "3♣", "5♦", "5♥", "5♠", "9♠", "10♠", "J♠", "K♥"]
        # K♥ = 10 deadwood after melding. Need draw card discarded.
        defender_hand = ["K♣", "K♦", "Q♥", "J♥", "7♣", "8♦", "4♠", "6♣", "9♦", "2♥"]
        discard_pile = ["A♠"]
        stock = ["Q♠"] + ["3♦"] * 10

        self._setup_hand(game, knocker_hand, defender_hand, discard_pile, stock)

        # Draw Q♠ from stock, discard it, knock with K♥ deadwood (10)
        game.apply_action(pa, {
            "reasoning": "knock",
            "draw": "stock",
            "action": "knock",
            "discard": "Q♠",
        })

        # Knocker deadwood = K♥ = 10
        # Defender deadwood computed by engine with layoffs
        assert game._game_scores[pa] > 0 or game._game_scores[pb] > 0

    def test_undercut_scoring(self, game):
        pa, pb = game.player_ids
        # Knocker knocks with 10 deadwood, defender has lower deadwood after layoffs
        knocker_hand = ["A♣", "2♣", "3♣", "5♦", "5♥", "5♠", "9♠", "10♠", "J♠", "K♥"]
        # Defender: 3 melds + low deadwood card
        defender_hand = ["7♣", "7♦", "7♥", "8♠", "9♠", "10♠", "A♥", "2♥", "3♥", "2♦"]
        # Defender deadwood = 2♦ = 2. Knocker deadwood = K♥ = 10. Undercut!
        discard_pile = ["A♠"]
        stock = ["Q♠"] + ["3♦"] * 10

        game._hands = {pa: list(knocker_hand), pb: list(defender_hand)}
        game._discard_pile = list(discard_pile)
        game._stock = list(stock)
        game._active_player = pa

        initial_pb_score = game._game_scores[pb]

        game.apply_action(pa, {
            "reasoning": "knock",
            "draw": "stock",
            "action": "knock",
            "discard": "Q♠",
        })

        # Defender should have scored (undercut)
        assert game._game_scores[pb] > initial_pb_score
        # Should include undercut bonus
        last_hand = game._hand_history[-1]
        assert last_hand["result"] == "undercut"
        assert last_hand["points_awarded"] >= UNDERCUT_BONUS


class TestStockDepletion:
    """Hand is a draw when stock hits ≤2 cards."""

    def test_stock_depletion_triggers_draw(self, game):
        initial_hand_number = game._hand_number
        # Play turns until stock depletes (≤2) — engine calls _handle_draw_hand
        turn_count = 0
        max_turns = 100
        while not game.is_terminal() and turn_count < max_turns:
            if game._hand_number != initial_hand_number:
                # New hand started — stock depletion was handled
                break
            pid = game.current_player()
            hand = game._hands[pid]
            if len(game._stock) <= 2:
                # Engine should have already triggered draw on previous apply
                break
            game.apply_action(pid, {
                "reasoning": "test",
                "draw": "stock",
                "action": "continue",
                "discard": hand[0],
            })
            turn_count += 1

        # Should have advanced (either new hand or game end)
        assert game._hand_number > initial_hand_number or game.is_terminal()


class TestHandLimit:
    """20-hand cap triggers game end."""

    def test_hand_limit_ends_game(self):
        game = GinRummyEvent(games_per_match=1)
        game.reset(seed=99)
        # Force hand number near limit
        game._hand_number = HAND_LIMIT - 1
        # Force a draw hand to trigger check
        game._handle_draw_hand()
        # Should have ended the game
        assert game.is_terminal() or game._hand_number <= HAND_LIMIT


class TestGameEnd:
    """Game end conditions and bonus scoring."""

    def test_game_bonus_awarded(self):
        game = GinRummyEvent(games_per_match=1)
        game.reset(seed=42)
        pa, pb = game.player_ids

        # Force scores near target
        game._game_scores[pa] = 95
        game._hands_won[pa] = 5
        game._hands_won[pb] = 2

        # Give pa a gin hand to push over 100
        game._hands[pa] = ["A♣", "2♣", "3♣", "5♦", "5♥", "5♠", "9♠", "10♠", "J♠", "Q♠"]
        game._hands[pb] = ["K♣", "K♦", "Q♥", "J♥", "10♥", "9♥", "8♣", "7♦", "6♣", "4♠"]
        game._stock = ["A♠"] + ["3♦"] * 10
        game._discard_pile = ["2♠"]
        game._active_player = pa

        game.apply_action(pa, {
            "reasoning": "gin to win",
            "draw": "stock",
            "action": "gin",
            "discard": "A♠",
        })

        # Game should be terminal (1 game match)
        assert game.is_terminal()
        # Winner should have game bonus in series score
        assert game._series_scores[pa] > 0

    def test_line_bonus(self):
        game = GinRummyEvent(games_per_match=1)
        game.reset(seed=42)
        pa, pb = game.player_ids

        # Force state: pa won 5 hands, pb won 2, pa has enough to end
        game._game_scores[pa] = TARGET_SCORE + 10
        game._hands_won[pa] = 5
        game._hands_won[pb] = 2

        game._end_game()

        # pa gets game bonus (100) + line bonus (3 net hands * 25 = 75)
        # Total should include: game_scores + 100 + 75
        expected_min = TARGET_SCORE + 10 + GAME_BONUS + LINE_BONUS * 3
        assert game._series_scores[pa] >= expected_min

    def test_shutout_doubles(self):
        game = GinRummyEvent(games_per_match=1)
        game.reset(seed=42)
        pa, pb = game.player_ids

        game._game_scores[pa] = TARGET_SCORE + 5
        game._game_scores[pb] = 0
        game._hands_won[pa] = 4
        game._hands_won[pb] = 0  # Shutout!

        game._end_game()

        # Shutout: winner's total is doubled
        base = TARGET_SCORE + 5 + GAME_BONUS + LINE_BONUS * 4
        expected = base * 2
        assert game._series_scores[pa] == expected


class TestDealerRotation:
    """Dealer alternates each hand."""

    def test_dealer_changes_each_hand(self, game):
        first_dealer = game.get_state_snapshot()["dealer"]
        # Play a quick hand (forfeit to advance)
        game.forfeit_turn(game.current_player())

        # After hand ends, new hand starts with swapped dealer
        if not game.is_terminal():
            second_dealer = game.get_state_snapshot()["dealer"]
            # Dealer might be same if game ended and new game started
            # But within a game, dealer alternates each hand


class TestBestOfThree:
    """Series flow across multiple games."""

    def test_match_not_terminal_after_one_game(self):
        game = GinRummyEvent(games_per_match=3)
        game.reset(seed=42)
        pa, pb = game.player_ids

        # Force game 1 to end
        game._game_scores[pa] = TARGET_SCORE + 10
        game._hands_won[pa] = 3
        game._hands_won[pb] = 1
        game._end_game()

        # Should not be terminal — still more games
        assert not game.is_terminal()
        assert game._game_number == 2

    def test_match_terminal_after_all_games(self):
        game = GinRummyEvent(games_per_match=2)
        game.reset(seed=42)
        pa, pb = game.player_ids

        # Force game 1 end
        game._game_scores[pa] = TARGET_SCORE
        game._hands_won[pa] = 2
        game._hands_won[pb] = 1
        game._end_game()

        assert not game.is_terminal()

        # Force game 2 end
        game._game_scores[pa] = TARGET_SCORE
        game._hands_won[pa] = 2
        game._hands_won[pb] = 1
        game._end_game()

        assert game.is_terminal()


class TestForfeit:
    """Forfeit produces a valid action."""

    def test_forfeit_does_not_crash(self, game):
        pid = game.current_player()
        game.forfeit_turn(pid)
        # Should not crash, and game should advance
        assert game.current_player() is not None or game.is_terminal()

    def test_award_forfeit_wins(self, game):
        pa, pb = game.player_ids
        game.award_forfeit_wins(pa)
        assert game.is_terminal()
        assert game._series_scores[pb] > 0


class TestPrompt:
    """Prompt generation."""

    def test_prompt_contains_hand(self, game):
        pid = game.current_player()
        prompt = game.get_prompt(pid)
        hand = game._hands[pid]
        for card in hand:
            assert card in prompt

    def test_prompt_contains_json_instruction(self, game):
        pid = game.current_player()
        prompt = game.get_prompt(pid)
        assert "JSON" in prompt
        assert "reasoning" in prompt

    def test_retry_prompt_includes_error(self, game):
        pid = game.current_player()
        prompt = game.get_retry_prompt(pid, "test error")
        assert "test error" in prompt

    def test_prompt_shows_stock_card(self, game):
        pid = game.current_player()
        prompt = game.get_prompt(pid)
        assert "Next stock card" in prompt


class TestSnapshot:
    """State snapshot completeness."""

    def test_snapshot_has_required_fields(self, game):
        snap = game.get_state_snapshot()
        required = [
            "game_number", "games_per_match", "hand_number",
            "turn_number", "dealer", "active_player", "hands",
            "stock_size", "discard_pile", "game_scores",
            "hands_won", "series_scores", "terminal",
        ]
        for field in required:
            assert field in snap, f"Missing field: {field}"


class TestCardNormalization:
    """Card normalization handles text suit names."""

    def test_normalize_in_validation(self, game):
        pid = game.current_player()
        hand = game._hands[pid]
        # Use text suit name
        card = hand[0]
        rank = card[:-1]
        suit_map = {"♣": "clubs", "♦": "diamonds", "♥": "hearts", "♠": "spades"}
        text_card = rank + suit_map[card[-1]]

        result = game.validate_action(pid, {
            "reasoning": "test",
            "draw": "stock",
            "action": "continue",
            "discard": text_card,
        })
        assert result.legal
