"""Tests for the Hearts engine."""

from __future__ import annotations

import pytest

from llmtourney.events.hearts.engine import (
    FULL_DECK,
    HAND_LIMIT,
    PASS_DIRECTIONS,
    PLAY_ORDER,
    QUEEN_OF_SPADES,
    RANKS,
    SUITS,
    TARGET_SCORE,
    TWO_OF_CLUBS,
    HeartsEvent,
    Phase,
    _card_rank,
    _card_rank_value,
    _card_suit,
    _pass_targets,
    _penalty_points,
    _sort_hand,
    _trick_winner,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def game():
    g = HeartsEvent(games_per_match=1, num_players=4)
    g.reset(seed=42)
    return g


@pytest.fixture
def game_multi():
    g = HeartsEvent(games_per_match=3, num_players=4)
    g.reset(seed=42)
    return g


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pass_all(game, cards_per_player=None):
    """Submit pass actions for all 4 players.

    If cards_per_player is None, uses first 3 cards from each hand.
    """
    for i in range(4):
        pid = game.current_player()
        if cards_per_player and pid in cards_per_player:
            cards = cards_per_player[pid]
        else:
            cards = game._hands[pid][:3]
        game.apply_action(pid, {"action": "pass", "cards": cards, "reasoning": "test"})


def _play_hand_forfeit(game):
    """Play through a single hand using forfeit_turn."""
    hand = game._hand_number
    safety = 0
    while game._hand_number == hand and not game._terminal and safety < 200:
        pid = game.current_player()
        game.forfeit_turn(pid)
        safety += 1


def _play_full_hand_forfeit(game):
    """Pass (if needed) and play a full hand via forfeit."""
    _play_hand_forfeit(game)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

class TestConstants:
    def test_deck_size(self):
        assert len(FULL_DECK) == 52

    def test_deck_unique(self):
        assert len(set(FULL_DECK)) == 52

    def test_all_suits_present(self):
        suits_in_deck = {_card_suit(c) for c in FULL_DECK}
        assert suits_in_deck == set(SUITS)

    def test_all_ranks_present(self):
        ranks_in_deck = {_card_rank(c) for c in FULL_DECK}
        assert ranks_in_deck == set(RANKS)

    def test_queen_of_spades(self):
        assert QUEEN_OF_SPADES == "Q♠"
        assert QUEEN_OF_SPADES in FULL_DECK

    def test_two_of_clubs(self):
        assert TWO_OF_CLUBS == "2♣"
        assert TWO_OF_CLUBS in FULL_DECK

    def test_pass_directions(self):
        assert PASS_DIRECTIONS == ["left", "right", "across", "none"]


# ---------------------------------------------------------------------------
# Card helpers
# ---------------------------------------------------------------------------

class TestCardHelpers:
    def test_card_suit(self):
        assert _card_suit("A♠") == "♠"
        assert _card_suit("10♥") == "♥"
        assert _card_suit("2♣") == "♣"

    def test_card_rank(self):
        assert _card_rank("A♠") == "A"
        assert _card_rank("10♥") == "10"
        assert _card_rank("2♣") == "2"

    def test_card_rank_value(self):
        assert _card_rank_value("2♣") == 0
        assert _card_rank_value("A♠") == 12
        assert _card_rank_value("K♥") == 11

    def test_sort_hand(self):
        hand = ["A♠", "2♣", "K♥", "3♦"]
        sorted_hand = _sort_hand(hand)
        # Suit order: ♣ ♦ ♥ ♠
        assert sorted_hand == ["2♣", "3♦", "K♥", "A♠"]


# ---------------------------------------------------------------------------
# Trick winner
# ---------------------------------------------------------------------------

class TestTrickWinner:
    def test_highest_of_led_suit_wins(self):
        trick = [
            {"player": "player_a", "card": "5♥"},
            {"player": "player_b", "card": "K♥"},
            {"player": "player_c", "card": "3♥"},
            {"player": "player_d", "card": "J♥"},
        ]
        assert _trick_winner(trick, "♥") == "player_b"

    def test_off_suit_never_wins(self):
        """Unlike Spades, there's no trump — off-suit cards can't win."""
        trick = [
            {"player": "player_a", "card": "5♥"},
            {"player": "player_b", "card": "A♠"},
            {"player": "player_c", "card": "3♥"},
            {"player": "player_d", "card": "K♣"},
        ]
        assert _trick_winner(trick, "♥") == "player_a"

    def test_single_card_of_led_suit(self):
        trick = [
            {"player": "player_a", "card": "2♦"},
            {"player": "player_b", "card": "A♠"},
            {"player": "player_c", "card": "K♣"},
            {"player": "player_d", "card": "Q♥"},
        ]
        assert _trick_winner(trick, "♦") == "player_a"

    def test_ace_high(self):
        trick = [
            {"player": "player_a", "card": "K♣"},
            {"player": "player_b", "card": "A♣"},
            {"player": "player_c", "card": "Q♣"},
            {"player": "player_d", "card": "J♣"},
        ]
        assert _trick_winner(trick, "♣") == "player_b"


# ---------------------------------------------------------------------------
# Pass targets
# ---------------------------------------------------------------------------

class TestPassTargets:
    def test_left(self):
        t = _pass_targets("left")
        assert t == {0: 1, 1: 2, 2: 3, 3: 0}

    def test_right(self):
        t = _pass_targets("right")
        assert t == {0: 3, 1: 0, 2: 1, 3: 2}

    def test_across(self):
        t = _pass_targets("across")
        assert t == {0: 2, 1: 3, 2: 0, 3: 1}

    def test_none(self):
        t = _pass_targets("none")
        assert t == {}


# ---------------------------------------------------------------------------
# Penalty points
# ---------------------------------------------------------------------------

class TestPenaltyPoints:
    def test_hearts_worth_one(self):
        for r in RANKS:
            assert _penalty_points(f"{r}♥") == 1

    def test_queen_of_spades_worth_thirteen(self):
        assert _penalty_points(QUEEN_OF_SPADES) == 13

    def test_non_penalty_cards(self):
        assert _penalty_points("A♠") == 0
        assert _penalty_points("K♣") == 0
        assert _penalty_points("2♦") == 0
        assert _penalty_points("J♠") == 0


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

class TestSetup:
    def test_not_terminal_at_start(self, game):
        assert not game._terminal

    def test_each_player_has_13_cards(self, game):
        for pid in PLAY_ORDER:
            assert len(game._hands[pid]) == 13

    def test_all_52_dealt(self, game):
        all_cards = []
        for pid in PLAY_ORDER:
            all_cards.extend(game._hands[pid])
        assert len(set(all_cards)) == 52

    def test_starts_in_pass_phase(self, game):
        assert game._phase == Phase.PASS

    def test_hand_1_passes_left(self, game):
        assert game._pass_direction == "left"

    def test_initial_scores_zero(self, game):
        for pid in PLAY_ORDER:
            assert game._game_scores[pid] == 0

    def test_schema_has_two_actions(self, game):
        schema = game._action_schema
        assert len(schema["oneOf"]) == 2

    def test_display_name(self, game):
        assert game.display_name == "Hearts"

    def test_player_ids(self, game):
        assert game._player_ids == PLAY_ORDER


# ---------------------------------------------------------------------------
# Card passing
# ---------------------------------------------------------------------------

class TestCardPassing:
    def test_pass_direction_rotation(self):
        """Pass direction cycles: left, right, across, none."""
        g = HeartsEvent(games_per_match=1, num_players=4, target_score=500, hand_limit=30)
        g.reset(seed=42)
        directions = []
        for _ in range(5):
            directions.append(g._pass_direction)
            _play_full_hand_forfeit(g)
            if g._terminal:
                break
        assert directions[:4] == ["left", "right", "across", "none"]
        if len(directions) > 4:
            assert directions[4] == "left"  # Cycle repeats

    def test_pass_validation_wrong_action(self, game):
        pid = game.current_player()
        result = game.validate_action(pid, {"action": "play", "card": "A♠"})
        assert not result.legal

    def test_pass_validation_wrong_count(self, game):
        pid = game.current_player()
        cards = game._hands[pid][:2]
        result = game.validate_action(pid, {"action": "pass", "cards": cards})
        assert not result.legal

    def test_pass_validation_duplicate(self, game):
        pid = game.current_player()
        card = game._hands[pid][0]
        result = game.validate_action(pid, {"action": "pass", "cards": [card, card, game._hands[pid][1]]})
        assert not result.legal

    def test_pass_validation_not_in_hand(self, game):
        pid = game.current_player()
        # Find a card NOT in hand
        missing = [c for c in FULL_DECK if c not in game._hands[pid]][0]
        cards = [game._hands[pid][0], game._hands[pid][1], missing]
        result = game.validate_action(pid, {"action": "pass", "cards": cards})
        assert not result.legal

    def test_pass_swap_correctness(self, game):
        """After passing left, player_a's passed cards should go to player_b."""
        # Record what each player will pass (first 3 cards)
        passed = {}
        hands_before = {}
        for pid in PLAY_ORDER:
            passed[pid] = game._hands[pid][:3]
            hands_before[pid] = list(game._hands[pid])

        _pass_all(game)

        assert game._phase == Phase.PLAY

        # player_a passed to player_b (left)
        for card in passed["player_a"]:
            assert card in game._hands["player_b"]
            assert card not in game._hands["player_a"]

        # player_b passed to player_c
        for card in passed["player_b"]:
            assert card in game._hands["player_c"]
            assert card not in game._hands["player_b"]

    def test_hands_still_13_after_pass(self, game):
        _pass_all(game)
        for pid in PLAY_ORDER:
            assert len(game._hands[pid]) == 13

    def test_none_direction_skips_pass(self):
        """Hand 4 (none direction) should skip directly to play."""
        g = HeartsEvent(games_per_match=1, num_players=4, hand_limit=30, target_score=500)
        g.reset(seed=99)
        # Play through 3 hands to get to hand 4 (none)
        for _ in range(3):
            _play_full_hand_forfeit(g)
            if g._terminal:
                break
        if not g._terminal:
            # We're now at hand 4
            assert g._pass_direction == "none"
            assert g._phase == Phase.PLAY

    def test_received_cards_tracked(self, game):
        _pass_all(game)
        # After pass, received_cards should be populated
        total_received = sum(len(v) for v in game._received_cards.values())
        assert total_received == 12  # 4 players * 3 cards each


# ---------------------------------------------------------------------------
# First trick rules
# ---------------------------------------------------------------------------

class TestFirstTrickRules:
    def test_two_of_clubs_must_lead(self, game):
        _pass_all(game)
        # The player with 2♣ should be the current player
        pid = game.current_player()
        assert TWO_OF_CLUBS in game._hands[pid]

        # Must play 2♣
        other_card = [c for c in game._hands[pid] if c != TWO_OF_CLUBS][0]
        result = game.validate_action(pid, {"action": "play", "card": other_card})
        assert not result.legal

        result = game.validate_action(pid, {"action": "play", "card": TWO_OF_CLUBS})
        assert result.legal

    def test_no_penalty_on_first_trick_when_void(self, game):
        """Can't play hearts or Q♠ on first trick even when void."""
        _pass_all(game)

        # Play 2♣ lead
        leader = game.current_player()
        game.apply_action(leader, {"action": "play", "card": TWO_OF_CLUBS, "reasoning": ""})

        # Set up a player to be void in clubs but have hearts
        pid = game.current_player()
        # Give them only hearts + one non-club non-heart
        game._hands[pid] = ["A♥", "K♥", "Q♥", "J♥", "10♥", "9♥",
                            "8♥", "7♥", "6♥", "5♥", "4♥", "3♠"]
        # They're void in clubs — can they play a heart?
        result = game.validate_action(pid, {"action": "play", "card": "A♥"})
        assert not result.legal  # Can't play hearts on trick 1

        result = game.validate_action(pid, {"action": "play", "card": "3♠"})
        assert result.legal

    def test_penalty_allowed_first_trick_if_only_penalty(self, game):
        """If hand is ONLY penalty cards, can play a heart on first trick."""
        _pass_all(game)

        leader = game.current_player()
        game.apply_action(leader, {"action": "play", "card": TWO_OF_CLUBS, "reasoning": ""})

        pid = game.current_player()
        # All penalty cards — no legal non-penalty play exists
        game._hands[pid] = ["A♥", "K♥", "Q♥", "J♥", "10♥", "9♥",
                            "8♥", "7♥", "6♥", "5♥", "4♥", "3♥", "2♥"]
        result = game.validate_action(pid, {"action": "play", "card": "A♥"})
        assert result.legal


# ---------------------------------------------------------------------------
# Follow suit
# ---------------------------------------------------------------------------

class TestFollowSuit:
    def test_must_follow_suit(self, game):
        _pass_all(game)

        leader = game.current_player()
        game.apply_action(leader, {"action": "play", "card": TWO_OF_CLUBS, "reasoning": ""})

        pid = game.current_player()
        clubs_in_hand = [c for c in game._hands[pid] if _card_suit(c) == "♣"]
        if clubs_in_hand:
            # Try to play a non-club
            non_club = [c for c in game._hands[pid] if _card_suit(c) != "♣"]
            if non_club:
                result = game.validate_action(pid, {"action": "play", "card": non_club[0]})
                assert not result.legal

    def test_void_allows_any(self, game):
        _pass_all(game)

        leader = game.current_player()
        game.apply_action(leader, {"action": "play", "card": TWO_OF_CLUBS, "reasoning": ""})

        pid = game.current_player()
        # Make void in clubs
        game._hands[pid] = [c for c in game._hands[pid] if _card_suit(c) != "♣"]
        if not game._hands[pid]:
            game._hands[pid] = ["A♦", "K♦", "Q♦", "J♦", "10♦",
                                "9♦", "8♦", "7♦", "6♦", "5♦", "4♦", "3♦", "2♦"]
        # Should be able to play any card (but first trick restriction applies)
        non_penalty = [c for c in game._hands[pid] if _penalty_points(c) == 0]
        if non_penalty:
            result = game.validate_action(pid, {"action": "play", "card": non_penalty[0]})
            assert result.legal


# ---------------------------------------------------------------------------
# Hearts breaking
# ---------------------------------------------------------------------------

class TestHeartsBreaking:
    def test_hearts_not_broken_at_start(self, game):
        _pass_all(game)
        assert not game._hearts_broken

    def test_cannot_lead_hearts_until_broken(self, game):
        _pass_all(game)

        # Play first trick with 2♣
        leader = game.current_player()
        game.apply_action(leader, {"action": "play", "card": TWO_OF_CLUBS, "reasoning": ""})
        for _ in range(3):
            game.forfeit_turn(game.current_player())

        # Now try to lead a heart on trick 2
        pid = game.current_player()
        hearts_in_hand = [c for c in game._hands[pid] if _card_suit(c) == "♥"]
        non_hearts = [c for c in game._hands[pid] if _card_suit(c) != "♥"]
        if hearts_in_hand and non_hearts:
            result = game.validate_action(pid, {"action": "play", "card": hearts_in_hand[0]})
            assert not result.legal

    def test_can_lead_hearts_when_only_hearts(self, game):
        _pass_all(game)

        # Play first trick
        leader = game.current_player()
        game.apply_action(leader, {"action": "play", "card": TWO_OF_CLUBS, "reasoning": ""})
        for _ in range(3):
            game.forfeit_turn(game.current_player())

        # Give a player only hearts
        pid = game.current_player()
        game._hands[pid] = ["A♥", "K♥", "Q♥", "J♥", "10♥", "9♥",
                            "8♥", "7♥", "6♥", "5♥", "4♥", "3♥"]
        result = game.validate_action(pid, {"action": "play", "card": "A♥"})
        assert result.legal

    def test_hearts_broken_when_void(self, game):
        """Playing a heart when void in led suit breaks hearts."""
        _pass_all(game)

        # Play first trick normally
        leader = game.current_player()
        game.apply_action(leader, {"action": "play", "card": TWO_OF_CLUBS, "reasoning": ""})
        for _ in range(3):
            game.forfeit_turn(game.current_player())

        # Start trick 2: set up a controlled scenario
        leader = game.current_player()
        non_hearts = [c for c in game._hands[leader] if _card_suit(c) != "♥"]
        if non_hearts:
            led_card = non_hearts[0]
            led_suit = _card_suit(led_card)
            game.apply_action(leader, {"action": "play", "card": led_card, "reasoning": ""})

            # Make next player void in that suit, with only hearts
            pid = game.current_player()
            game._hands[pid] = ["A♥", "K♥", "Q♥"]
            game.apply_action(pid, {"action": "play", "card": "A♥", "reasoning": ""})
            assert game._hearts_broken


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

class TestScoring:
    def test_heart_scores_one(self):
        """Each heart in tricks = 1 penalty point."""
        g = HeartsEvent(games_per_match=1, num_players=4, target_score=200)
        g.reset(seed=42)
        _play_full_hand_forfeit(g)
        # After a hand, total penalty should be 26
        total = sum(g._hand_history[0]["penalty"].values())
        assert total == 26

    def test_queen_of_spades_scores_thirteen(self):
        """Q♠ alone is 13 penalty points."""
        assert _penalty_points(QUEEN_OF_SPADES) == 13

    def test_total_penalty_per_hand_is_26(self):
        """All penalty cards sum to 26."""
        total = sum(_penalty_points(c) for c in FULL_DECK)
        assert total == 26

    def test_game_scores_accumulate(self):
        """Scores carry over across hands."""
        g = HeartsEvent(games_per_match=1, num_players=4, target_score=200)
        g.reset(seed=42)
        _play_full_hand_forfeit(g)
        scores_after_1 = dict(g._game_scores)
        _play_full_hand_forfeit(g)
        # Scores should be >= what they were after hand 1
        for pid in PLAY_ORDER:
            assert g._game_scores[pid] >= scores_after_1[pid]


# ---------------------------------------------------------------------------
# Shoot the Moon
# ---------------------------------------------------------------------------

class TestShootTheMoon:
    def test_shoot_the_moon_detection(self):
        """If one player takes all 26, shoot the moon applies."""
        g = HeartsEvent(games_per_match=1, num_players=4, target_score=200)
        g.reset(seed=42)

        # Skip pass
        if g._phase == Phase.PASS:
            for _ in range(4):
                g.forfeit_turn(g.current_player())

        # Manually set up: after 13 tricks, one player has 26 penalty
        # We'll directly test _score_hand
        g._penalty_this_hand = {
            "player_a": 26,
            "player_b": 0,
            "player_c": 0,
            "player_d": 0,
        }
        g._score_hand()

        # Shooter (a) gets 0 added, others get +26
        assert g._game_scores["player_a"] == 0
        assert g._game_scores["player_b"] == 26
        assert g._game_scores["player_c"] == 26
        assert g._game_scores["player_d"] == 26

    def test_no_shoot_if_partial(self):
        """25 penalty points is NOT a shoot."""
        g = HeartsEvent(games_per_match=1, num_players=4, target_score=200)
        g.reset(seed=42)

        if g._phase == Phase.PASS:
            for _ in range(4):
                g.forfeit_turn(g.current_player())

        g._penalty_this_hand = {
            "player_a": 25,
            "player_b": 1,
            "player_c": 0,
            "player_d": 0,
        }
        g._score_hand()

        assert g._game_scores["player_a"] == 25
        assert g._game_scores["player_b"] == 1


# ---------------------------------------------------------------------------
# Game end
# ---------------------------------------------------------------------------

class TestGameEnd:
    def test_target_score_ends_game(self):
        g = HeartsEvent(games_per_match=1, num_players=4, target_score=30)
        g.reset(seed=42)

        safety = 0
        while not g._terminal and safety < 5000:
            if g._phase == Phase.PASS:
                g.forfeit_turn(g.current_player())
            else:
                g.forfeit_turn(g.current_player())
            safety += 1

        assert g._terminal
        # At least one player should have >= 30
        assert any(s >= 30 for s in g._game_scores.values())

    def test_hand_limit_ends_game(self):
        g = HeartsEvent(games_per_match=1, num_players=4, hand_limit=2, target_score=1000)
        g.reset(seed=42)

        safety = 0
        while not g._terminal and safety < 5000:
            g.forfeit_turn(g.current_player())
            safety += 1

        assert g._terminal
        assert g._hand_number <= 2

    def test_lowest_score_wins(self):
        """Player with lowest penalty should have highest match score."""
        g = HeartsEvent(games_per_match=1, num_players=4, target_score=30)
        g.reset(seed=42)

        safety = 0
        while not g._terminal and safety < 5000:
            g.forfeit_turn(g.current_player())
            safety += 1

        # Find the player with lowest game_score (penalty) and highest match_score
        lowest_penalty_pid = min(g._game_scores, key=g._game_scores.get)
        highest_match_pid = max(g._match_scores, key=g._match_scores.get)
        assert lowest_penalty_pid == highest_match_pid


# ---------------------------------------------------------------------------
# Score inversion
# ---------------------------------------------------------------------------

class TestScoreInversion:
    def test_inversion_formula(self):
        """match_scores = max_game_score - game_scores[pid]."""
        g = HeartsEvent(games_per_match=1, num_players=4, target_score=200)
        g.reset(seed=42)

        # Directly set game scores and call _end_game
        g._game_scores = {
            "player_a": 10,
            "player_b": 50,
            "player_c": 30,
            "player_d": 80,
        }
        g._end_game()

        # max = 80, so: a=70, b=30, c=50, d=0
        assert g._match_scores["player_a"] == 70.0
        assert g._match_scores["player_b"] == 30.0
        assert g._match_scores["player_c"] == 50.0
        assert g._match_scores["player_d"] == 0.0

    def test_inversion_multi_game(self):
        """Match scores accumulate across games."""
        g = HeartsEvent(games_per_match=2, num_players=4, target_score=200)
        g.reset(seed=42)

        # End game 1
        g._game_scores = {
            "player_a": 10,
            "player_b": 50,
            "player_c": 30,
            "player_d": 80,
        }
        g._end_game()

        # Game 2 should start
        assert not g._terminal
        assert g._game_number == 2

        # End game 2
        g._game_scores = {
            "player_a": 20,
            "player_b": 40,
            "player_c": 60,
            "player_d": 10,
        }
        g._end_game()

        assert g._terminal
        # Game 1: 70, 30, 50, 0. Game 2: 40, 20, 0, 50. Total: 110, 50, 50, 50
        assert g._match_scores["player_a"] == 110.0
        assert g._match_scores["player_b"] == 50.0
        assert g._match_scores["player_c"] == 50.0
        assert g._match_scores["player_d"] == 50.0


# ---------------------------------------------------------------------------
# Forfeit
# ---------------------------------------------------------------------------

class TestForfeit:
    def test_forfeit_pass_selects_3_cards(self, game):
        pid = game.current_player()
        hand_before = list(game._hands[pid])
        game.forfeit_turn(pid)
        # Should have passed 3 cards
        assert pid in game._passed_cards
        assert len(game._passed_cards[pid]) == 3

    def test_forfeit_pass_prefers_hearts(self, game):
        pid = game.current_player()
        # Give player lots of hearts
        game._hands[pid] = ["A♥", "K♥", "Q♥", "J♥", "10♥",
                            "2♣", "3♣", "4♣", "5♣", "6♣",
                            "7♦", "8♦", "9♠"]
        game.forfeit_turn(pid)
        passed = game._passed_cards[pid]
        # Should pass the 3 highest hearts: A♥, K♥, Q♥
        assert "A♥" in passed
        assert "K♥" in passed
        assert "Q♥" in passed

    def test_forfeit_play_follows_suit(self, game):
        """Forfeit play should follow suit with lowest card."""
        _pass_all(game)

        # Play first trick with 2♣
        leader = game.current_player()
        game.apply_action(leader, {"action": "play", "card": TWO_OF_CLUBS, "reasoning": ""})

        pid = game.current_player()
        clubs = sorted([c for c in game._hands[pid] if _card_suit(c) == "♣"], key=_card_rank_value)
        hand_before = list(game._hands[pid])
        game.forfeit_turn(pid)
        hand_after = game._hands[pid]
        played = [c for c in hand_before if c not in hand_after]
        assert len(played) == 1
        if clubs:
            assert played[0] == clubs[0]  # Should play lowest club

    def test_forfeit_dumps_queen_when_void(self, game):
        """When void in led suit, forfeit should dump Q♠."""
        _pass_all(game)

        leader = game.current_player()
        game.apply_action(leader, {"action": "play", "card": TWO_OF_CLUBS, "reasoning": ""})

        pid = game.current_player()
        # Make void in clubs, give Q♠
        game._hands[pid] = [QUEEN_OF_SPADES, "A♦", "K♦", "3♠"]
        # It's trick 1 — can't play Q♠ on first trick
        # Move past first trick
        for _ in range(3):
            game.forfeit_turn(game.current_player())

        # Set up trick 2 where player is void
        leader = game.current_player()
        diamonds = [c for c in game._hands[leader] if _card_suit(c) == "♦"]
        non_hearts = [c for c in game._hands[leader] if _card_suit(c) != "♥"]
        if non_hearts:
            game.apply_action(leader, {"action": "play", "card": non_hearts[0], "reasoning": ""})
            pid = game.current_player()
            led_suit = _card_suit(non_hearts[0])
            # Make void in led suit, give Q♠
            game._hands[pid] = [QUEEN_OF_SPADES, "A♥", "K♥"]
            hand_before = list(game._hands[pid])
            game.forfeit_turn(pid)
            played = [c for c in hand_before if c not in game._hands[pid]]
            if played:
                assert played[0] == QUEEN_OF_SPADES

    def test_forfeit_always_legal(self, game):
        """Full hand via forfeit should never crash."""
        _play_full_hand_forfeit(game)
        # No exception = pass


# ---------------------------------------------------------------------------
# Match forfeit (award_forfeit_wins)
# ---------------------------------------------------------------------------

class TestMatchForfeit:
    def test_award_forfeit_wins_terminates(self, game):
        game.award_forfeit_wins("player_a")
        assert game._terminal

    def test_award_forfeit_wins_gives_points(self, game):
        game.award_forfeit_wins("player_a")
        assert game._match_scores["player_a"] == 0.0
        for pid in ["player_b", "player_c", "player_d"]:
            assert game._match_scores[pid] == float(TARGET_SCORE)

    def test_award_forfeit_wins_multi_game(self, game_multi):
        # Play through 1 game first
        safety = 0
        while game_multi._game_number == 1 and not game_multi._terminal and safety < 5000:
            game_multi.forfeit_turn(game_multi.current_player())
            safety += 1

        if not game_multi._terminal:
            scores_before = dict(game_multi._match_scores)
            remaining = game_multi._games_per_match - game_multi._game_number + 1
            game_multi.award_forfeit_wins("player_b")
            assert game_multi._terminal
            for pid in ["player_a", "player_c", "player_d"]:
                assert game_multi._match_scores[pid] == scores_before[pid] + float(TARGET_SCORE * remaining)


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

class TestPrompts:
    def test_pass_prompt_contains_key_info(self, game):
        pid = game.current_player()
        prompt = game.get_prompt(pid)
        assert "CARD PASSING PHASE" in prompt
        assert "pass" in prompt.lower()
        assert "left" in prompt

    def test_play_prompt_contains_key_info(self, game):
        _pass_all(game)
        pid = game.current_player()
        prompt = game.get_prompt(pid)
        assert "TRICK PLAY" in prompt
        assert "penalty" in prompt.lower()
        assert "Hearts" in prompt

    def test_retry_prompt_includes_error(self, game):
        pid = game.current_player()
        prompt = game.get_retry_prompt(pid, "bad card")
        assert "bad card" in prompt


# ---------------------------------------------------------------------------
# Snapshot
# ---------------------------------------------------------------------------

class TestSnapshot:
    def test_snapshot_has_required_fields(self, game):
        snap = game.get_state_snapshot()
        required = [
            "phase", "game_number", "games_per_match", "hand_number",
            "pass_direction", "trick_number", "turn_number", "hands",
            "passed_cards", "received_cards", "current_trick",
            "trick_leader", "dealer", "penalty_this_hand", "game_scores",
            "hearts_broken", "queen_taken_by", "trick_history",
            "hand_history", "terminal", "match_scores", "mode",
        ]
        for field in required:
            assert field in snap, f"Missing field: {field}"

    def test_snapshot_phase_is_string(self, game):
        snap = game.get_state_snapshot()
        assert isinstance(snap["phase"], str)
        assert snap["phase"] in ("pass", "play")

    def test_snapshot_hands_have_13(self, game):
        snap = game.get_state_snapshot()
        for pid in PLAY_ORDER:
            assert len(snap["hands"][pid]) == 13


# ---------------------------------------------------------------------------
# Integration
# ---------------------------------------------------------------------------

class TestIntegration:
    def test_full_game_via_forfeit(self):
        g = HeartsEvent(games_per_match=1, num_players=4, target_score=100)
        g.reset(seed=42)

        safety = 0
        while not g._terminal and safety < 10000:
            g.forfeit_turn(g.current_player())
            safety += 1

        assert g._terminal
        scores = g.get_scores()
        assert len(scores) == 4

    def test_deterministic_with_same_seed(self):
        g1 = HeartsEvent(games_per_match=1, num_players=4, target_score=50)
        g1.reset(seed=123)
        while not g1._terminal:
            g1.forfeit_turn(g1.current_player())

        g2 = HeartsEvent(games_per_match=1, num_players=4, target_score=50)
        g2.reset(seed=123)
        while not g2._terminal:
            g2.forfeit_turn(g2.current_player())

        assert g1.get_scores() == g2.get_scores()

    def test_different_seeds_differ(self):
        g1 = HeartsEvent(games_per_match=1, num_players=4, target_score=50)
        g1.reset(seed=111)
        while not g1._terminal:
            g1.forfeit_turn(g1.current_player())

        g2 = HeartsEvent(games_per_match=1, num_players=4, target_score=50)
        g2.reset(seed=222)
        while not g2._terminal:
            g2.forfeit_turn(g2.current_player())

        assert g1.get_scores() != g2.get_scores()

    def test_multi_game_match(self):
        g = HeartsEvent(games_per_match=3, num_players=4, target_score=50)
        g.reset(seed=42)

        safety = 0
        while not g._terminal and safety < 30000:
            g.forfeit_turn(g.current_player())
            safety += 1

        assert g._terminal
        assert g._game_number == 3

    def test_highlight_hands_returns_list(self):
        g = HeartsEvent(games_per_match=1, num_players=4, target_score=50)
        g.reset(seed=42)
        while not g._terminal:
            g.forfeit_turn(g.current_player())
        assert isinstance(g.get_highlight_hands(), list)
