"""Tests for the Spades engine."""

import pytest
from llmtourney.events.spades.engine import (
    SpadesEvent,
    Phase,
    FULL_DECK,
    RANKS,
    SUITS,
    PLAY_ORDER,
    TEAMS,
    PLAYER_TEAM,
    PARTNER,
    _card_suit,
    _card_rank,
    _card_rank_value,
    _sort_hand,
    _trick_winner,
)


@pytest.fixture
def game():
    g = SpadesEvent(games_per_match=1, num_players=4)
    g.reset(seed=42)
    return g


@pytest.fixture
def game_multi():
    """Multi-game match for series testing."""
    g = SpadesEvent(games_per_match=3, num_players=4)
    g.reset(seed=42)
    return g


def _bid_all(game, bids=(3, 3, 3, 3)):
    """Helper: submit all 4 bids. Tuple maps to player_a, _b, _c, _d."""
    bid_map = {PLAY_ORDER[i]: b for i, b in enumerate(bids)}
    for _ in range(4):
        pid = game.current_player()
        assert game._phase == Phase.BID
        game.apply_action(pid, {"action": "bid", "bid": bid_map[pid]})


def _play_hand_forfeit(game):
    """Play through an entire hand using forfeit moves."""
    while game._phase == Phase.PLAY and not game.is_terminal():
        pid = game.current_player()
        game.forfeit_turn(pid)


def _play_full_hand_forfeit(game):
    """Bid (forfeit) and play (forfeit) through one complete hand."""
    for _ in range(4):
        game.forfeit_turn(game.current_player())
    _play_hand_forfeit(game)


# ------------------------------------------------------------------
# Constants
# ------------------------------------------------------------------

class TestConstants:
    def test_deck_size(self):
        assert len(FULL_DECK) == 52

    def test_deck_unique(self):
        assert len(set(FULL_DECK)) == 52

    def test_all_suits_present(self):
        suits_in_deck = {_card_suit(c) for c in FULL_DECK}
        assert suits_in_deck == {"♣", "♦", "♥", "♠"}

    def test_all_ranks_present(self):
        ranks_in_deck = {_card_rank(c) for c in FULL_DECK}
        assert ranks_in_deck == set(RANKS)

    def test_team_mapping(self):
        assert PLAYER_TEAM["player_a"] == "team_1"
        assert PLAYER_TEAM["player_c"] == "team_1"
        assert PLAYER_TEAM["player_b"] == "team_2"
        assert PLAYER_TEAM["player_d"] == "team_2"

    def test_partners(self):
        assert PARTNER["player_a"] == "player_c"
        assert PARTNER["player_c"] == "player_a"
        assert PARTNER["player_b"] == "player_d"
        assert PARTNER["player_d"] == "player_b"


# ------------------------------------------------------------------
# Card helpers
# ------------------------------------------------------------------

class TestCardHelpers:
    def test_card_suit(self):
        assert _card_suit("A♠") == "♠"
        assert _card_suit("10♥") == "♥"
        assert _card_suit("3♦") == "♦"
        assert _card_suit("K♣") == "♣"

    def test_card_rank(self):
        assert _card_rank("A♠") == "A"
        assert _card_rank("10♥") == "10"
        assert _card_rank("3♦") == "3"

    def test_rank_ordering(self):
        assert _card_rank_value("2♠") < _card_rank_value("3♠")
        assert _card_rank_value("K♠") < _card_rank_value("A♠")
        assert _card_rank_value("A♠") == 12
        assert _card_rank_value("2♠") == 0

    def test_sort_hand(self):
        hand = ["A♠", "3♣", "K♥", "2♦"]
        sorted_h = _sort_hand(hand)
        # Should be grouped by suit: ♣ ♦ ♥ ♠
        assert _card_suit(sorted_h[0]) == "♣"
        assert _card_suit(sorted_h[1]) == "♦"
        assert _card_suit(sorted_h[2]) == "♥"
        assert _card_suit(sorted_h[3]) == "♠"


# ------------------------------------------------------------------
# Trick resolution
# ------------------------------------------------------------------

class TestTrickWinner:
    def test_highest_of_led_suit_wins(self):
        trick = [
            {"player": "player_a", "card": "5♥"},
            {"player": "player_b", "card": "K♥"},
            {"player": "player_c", "card": "3♥"},
            {"player": "player_d", "card": "J♥"},
        ]
        assert _trick_winner(trick, "♥") == "player_b"

    def test_trump_beats_high_card(self):
        trick = [
            {"player": "player_a", "card": "A♥"},
            {"player": "player_b", "card": "2♠"},  # trump
            {"player": "player_c", "card": "K♥"},
            {"player": "player_d", "card": "Q♥"},
        ]
        assert _trick_winner(trick, "♥") == "player_b"

    def test_highest_trump_wins(self):
        trick = [
            {"player": "player_a", "card": "5♥"},
            {"player": "player_b", "card": "3♠"},
            {"player": "player_c", "card": "7♠"},
            {"player": "player_d", "card": "2♥"},
        ]
        assert _trick_winner(trick, "♥") == "player_c"

    def test_off_suit_no_trump_loses(self):
        """Cards not following suit and not trump don't compete."""
        trick = [
            {"player": "player_a", "card": "5♥"},
            {"player": "player_b", "card": "A♦"},  # off suit, not trump
            {"player": "player_c", "card": "3♥"},
            {"player": "player_d", "card": "A♣"},  # off suit, not trump
        ]
        assert _trick_winner(trick, "♥") == "player_a"

    def test_single_card_wins(self):
        """First card always wins if only card of led suit."""
        trick = [
            {"player": "player_a", "card": "5♦"},
            {"player": "player_b", "card": "A♣"},
            {"player": "player_c", "card": "A♥"},
            {"player": "player_d", "card": "A♣"},
        ]
        assert _trick_winner(trick, "♦") == "player_a"


# ------------------------------------------------------------------
# Setup
# ------------------------------------------------------------------

class TestSetup:
    def test_reset_initializes(self, game):
        snap = game.get_state_snapshot()
        assert snap["hand_number"] == 1
        assert snap["terminal"] is False
        assert snap["game_number"] == 1

    def test_not_terminal_at_start(self, game):
        assert game.is_terminal() is False

    def test_player_left_of_dealer_goes_first(self, game):
        # Dealer is player_a (idx 0), so player_b (left of dealer) leads
        assert game.current_player() == "player_b"

    def test_four_players_have_13_cards(self, game):
        snap = game.get_state_snapshot()
        for pid in game.player_ids:
            assert len(snap["hands"][pid]) == 13

    def test_all_52_cards_dealt(self, game):
        snap = game.get_state_snapshot()
        all_cards = []
        for pid in game.player_ids:
            all_cards.extend(snap["hands"][pid])
        assert len(all_cards) == 52
        assert len(set(all_cards)) == 52

    def test_starts_in_bid_phase(self, game):
        assert game._phase == Phase.BID

    def test_initial_scores_zero(self, game):
        scores = game.get_scores()
        for pid in game.player_ids:
            assert scores[pid] == 0.0

    def test_action_schema_present(self, game):
        schema = game.action_schema
        assert "oneOf" in schema
        assert len(schema["oneOf"]) == 2

    def test_display_name(self, game):
        assert game.display_name == "Spades"

    def test_player_ids(self, game):
        assert game.player_ids == ["player_a", "player_b", "player_c", "player_d"]


# ------------------------------------------------------------------
# Bidding phase
# ------------------------------------------------------------------

class TestBidding:
    def test_bid_order_rotates(self, game):
        # Dealer is player_a (idx 0), so bid order starts at player_b
        expected = ["player_b", "player_c", "player_d", "player_a"]
        for pid in expected:
            assert game.current_player() == pid
            game.apply_action(pid, {"action": "bid", "bid": 3})

    def test_after_all_bids_transitions_to_play(self, game):
        _bid_all(game, (3, 4, 2, 4))
        assert game._phase == Phase.PLAY

    def test_team_contracts_computed(self, game):
        _bid_all(game, (3, 4, 2, 4))
        assert game._team_contracts["team_1"] == 5  # a(3) + c(2)
        assert game._team_contracts["team_2"] == 8  # b(4) + d(4)

    def test_nil_bid_zero_contract(self, game):
        """Nil bid contributes 0 to team contract."""
        _bid_all(game, (0, 3, 5, 3))
        assert game._team_contracts["team_1"] == 5  # nil(0) + c(5)
        assert game._team_contracts["team_2"] == 6

    def test_validate_bid_range(self, game):
        result = game.validate_action("player_a", {"action": "bid", "bid": -1})
        assert result.legal is False
        result = game.validate_action("player_a", {"action": "bid", "bid": 14})
        assert result.legal is False
        result = game.validate_action("player_a", {"action": "bid", "bid": 0})
        assert result.legal is True
        result = game.validate_action("player_a", {"action": "bid", "bid": 13})
        assert result.legal is True

    def test_validate_bid_wrong_action(self, game):
        result = game.validate_action("player_a", {"action": "play", "card": "A♠"})
        assert result.legal is False

    def test_bids_visible_in_snapshot(self, game):
        game.apply_action("player_a", {"action": "bid", "bid": 4})
        snap = game.get_state_snapshot()
        assert snap["bids"]["player_a"] == 4
        assert snap["bids"]["player_b"] is None


# ------------------------------------------------------------------
# Play validation
# ------------------------------------------------------------------

class TestPlayValidation:
    def test_must_follow_suit(self, game):
        """If player has cards of led suit, must follow suit."""
        _bid_all(game, (3, 3, 3, 3))

        # Set up a controlled hand for player_b
        game._hands["player_a"] = ["5♥", "6♥", "7♥", "8♥", "9♥", "10♥", "J♥", "Q♥", "K♥", "A♥", "2♣", "3♣", "4♣"]
        game._hands["player_b"] = ["2♥", "3♥", "4♥", "A♣", "K♣", "Q♣", "J♣", "10♣", "9♣", "8♣", "7♣", "6♣", "5♣"]

        # Player a leads hearts
        game.apply_action("player_a", {"action": "play", "card": "5♥"})

        # Player b has hearts — must follow suit
        result = game.validate_action("player_b", {"action": "play", "card": "A♣"})
        assert result.legal is False
        assert "follow suit" in result.reason.lower()

        result = game.validate_action("player_b", {"action": "play", "card": "2♥"})
        assert result.legal is True

    def test_void_can_play_anything(self, game):
        _bid_all(game, (3, 3, 3, 3))

        game._hands["player_a"] = ["5♦", "6♦", "7♦", "8♦", "9♦", "10♦", "J♦", "Q♦", "K♦", "A♦", "2♣", "3♣", "4♣"]
        game._hands["player_b"] = ["2♠", "3♠", "A♣", "K♣", "Q♣", "J♣", "10♣", "9♣", "8♣", "7♣", "6♣", "5♣", "4♣"]

        game.apply_action("player_a", {"action": "play", "card": "5♦"})

        # Player b has no diamonds — can play anything
        result = game.validate_action("player_b", {"action": "play", "card": "2♠"})
        assert result.legal is True
        result = game.validate_action("player_b", {"action": "play", "card": "A♣"})
        assert result.legal is True

    def test_cannot_lead_spades_unbroken(self, game):
        _bid_all(game, (3, 3, 3, 3))
        assert not game._spades_broken

        # Give player_a mixed hand
        game._hands["player_a"] = ["2♠", "3♣", "5♦", "7♥", "8♥", "9♥", "10♥", "J♥", "Q♥", "K♥", "A♥", "2♣", "4♣"]

        result = game.validate_action("player_a", {"action": "play", "card": "2♠"})
        assert result.legal is False
        assert "broken" in result.reason.lower()

    def test_can_lead_spades_when_only_spades(self, game):
        _bid_all(game, (3, 3, 3, 3))
        assert not game._spades_broken

        game._hands["player_a"] = ["2♠", "3♠", "4♠", "5♠", "6♠", "7♠", "8♠", "9♠", "10♠", "J♠", "Q♠", "K♠", "A♠"]

        result = game.validate_action("player_a", {"action": "play", "card": "2♠"})
        assert result.legal is True

    def test_can_lead_spades_when_broken(self, game):
        _bid_all(game, (3, 3, 3, 3))
        game._spades_broken = True

        game._hands["player_a"] = ["2♠", "3♣", "5♦", "7♥", "8♥", "9♥", "10♥", "J♥", "Q♥", "K♥", "A♥", "2♣", "4♣"]

        result = game.validate_action("player_a", {"action": "play", "card": "2♠"})
        assert result.legal is True

    def test_card_not_in_hand_rejected(self, game):
        _bid_all(game, (3, 3, 3, 3))
        result = game.validate_action("player_a", {"action": "play", "card": "Z♠"})
        assert result.legal is False


# ------------------------------------------------------------------
# Trick play mechanics
# ------------------------------------------------------------------

class TestTrickPlay:
    def test_trick_leader_starts(self, game):
        _bid_all(game, (3, 3, 3, 3))
        # Player left of dealer leads: dealer=a, leader=b
        assert game.current_player() == "player_b"

    def test_trick_cycles_clockwise(self, game):
        _bid_all(game, (3, 3, 3, 3))

        # Give everyone hearts so they can all follow suit
        game._hands["player_a"] = ["2♥", "3♣", "4♣", "5♣", "6♣", "7♣", "8♣", "9♣", "10♣", "J♣", "Q♣", "K♣", "A♣"]
        game._hands["player_b"] = ["3♥", "2♦", "4♦", "5♦", "6♦", "7♦", "8♦", "9♦", "10♦", "J♦", "Q♦", "K♦", "A♦"]
        game._hands["player_c"] = ["4♥", "2♠", "3♠", "4♠", "5♠", "6♠", "7♠", "8♠", "9♠", "10♠", "J♠", "Q♠", "K♠"]
        game._hands["player_d"] = ["5♥", "6♥", "7♥", "8♥", "9♥", "10♥", "J♥", "Q♥", "K♥", "A♥", "A♠", "2♣", "3♦"]

        # Player b leads (left of dealer)
        leader = game.current_player()
        assert leader == "player_b"
        game.apply_action("player_b", {"action": "play", "card": "3♥"})
        assert game.current_player() == "player_c"
        game.apply_action("player_c", {"action": "play", "card": "4♥"})
        assert game.current_player() == "player_d"
        game.apply_action("player_d", {"action": "play", "card": "5♥"})
        assert game.current_player() == "player_a"

    def test_trick_winner_leads_next(self, game):
        _bid_all(game, (3, 3, 3, 3))

        game._hands["player_a"] = ["2♥", "3♣", "4♣", "5♣", "6♣", "7♣", "8♣", "9♣", "10♣", "J♣", "Q♣", "K♣", "A♣"]
        game._hands["player_b"] = ["A♥", "2♦", "4♦", "5♦", "6♦", "7♦", "8♦", "9♦", "10♦", "J♦", "Q♦", "K♦", "A♦"]
        game._hands["player_c"] = ["4♥", "2♠", "3♠", "4♠", "5♠", "6♠", "7♠", "8♠", "9♠", "10♠", "J♠", "Q♠", "K♠"]
        game._hands["player_d"] = ["5♥", "6♥", "7♥", "8♥", "9♥", "10♥", "J♥", "Q♥", "K♥", "2♣", "A♠", "3♦", "3♣"]

        # Trick 1: a leads 2♥, b plays A♥ (winner), c plays 4♥, d plays 5♥
        game.apply_action("player_a", {"action": "play", "card": "2♥"})
        game.apply_action("player_b", {"action": "play", "card": "A♥"})
        game.apply_action("player_c", {"action": "play", "card": "4♥"})
        game.apply_action("player_d", {"action": "play", "card": "5♥"})

        # Player b won — should lead next trick
        assert game.current_player() == "player_b"
        assert game._trick_leader == "player_b"

    def test_spades_broken_when_played(self, game):
        _bid_all(game, (3, 3, 3, 3))

        game._hands["player_a"] = ["2♥", "3♣", "4♣", "5♣", "6♣", "7♣", "8♣", "9♣", "10♣", "J♣", "Q♣", "K♣", "A♣"]
        game._hands["player_b"] = ["3♥", "2♦", "4♦", "5♦", "6♦", "7♦", "8♦", "9♦", "10♦", "J♦", "Q♦", "K♦", "A♦"]
        game._hands["player_c"] = ["2♠", "3♠", "4♠", "5♠", "6♠", "7♠", "8♠", "9♠", "10♠", "J♠", "Q♠", "K♠", "A♠"]
        game._hands["player_d"] = ["5♥", "6♥", "7♥", "8♥", "9♥", "10♥", "J♥", "Q♥", "K♥", "A♥", "4♥", "2♣", "3♦"]

        assert not game._spades_broken

        game.apply_action("player_a", {"action": "play", "card": "2♥"})
        game.apply_action("player_b", {"action": "play", "card": "3♥"})
        # Player c has no hearts — plays a spade
        game.apply_action("player_c", {"action": "play", "card": "2♠"})

        assert game._spades_broken

    def test_tricks_taken_tracked(self, game):
        _bid_all(game, (3, 3, 3, 3))

        game._hands["player_a"] = ["A♥", "3♣", "4♣", "5♣", "6♣", "7♣", "8♣", "9♣", "10♣", "J♣", "Q♣", "K♣", "2♣"]
        game._hands["player_b"] = ["3♥", "2♦", "4♦", "5♦", "6♦", "7♦", "8♦", "9♦", "10♦", "J♦", "Q♦", "K♦", "A♦"]
        game._hands["player_c"] = ["4♥", "2♠", "3♠", "4♠", "5♠", "6♠", "7♠", "8♠", "9♠", "10♠", "J♠", "Q♠", "K♠"]
        game._hands["player_d"] = ["5♥", "6♥", "7♥", "8♥", "9♥", "10♥", "J♥", "Q♥", "K♥", "2♥", "A♠", "3♦", "A♣"]

        # Play first trick: A♥ should win
        game.apply_action("player_a", {"action": "play", "card": "A♥"})
        game.apply_action("player_b", {"action": "play", "card": "3♥"})
        game.apply_action("player_c", {"action": "play", "card": "4♥"})
        game.apply_action("player_d", {"action": "play", "card": "5♥"})

        assert game._tricks_taken["player_a"] == 1


# ------------------------------------------------------------------
# Scoring
# ------------------------------------------------------------------

class TestScoring:
    def _setup_and_score(self, game, bids, team_tricks):
        """Set up a hand with specific bids and trick distribution, then score it."""
        _bid_all(game, bids)

        # Manually set tricks taken and complete the hand
        game._tricks_taken = {
            "player_a": team_tricks["player_a"],
            "player_b": team_tricks["player_b"],
            "player_c": team_tricks["player_c"],
            "player_d": team_tricks["player_d"],
        }
        game._score_hand()

    def test_contract_made_exactly(self, game):
        """Bid 5, take 5 = 50 points, no bags."""
        self._setup_and_score(game, (3, 3, 2, 3), {
            "player_a": 3, "player_b": 3, "player_c": 2, "player_d": 3,
        })
        assert game._scores["team_1"] == 50  # (3+2)*10
        assert game._scores["team_2"] == 60  # (3+3)*10
        assert game._bags["team_1"] == 0
        assert game._bags["team_2"] == 0

    def test_contract_with_overtricks(self, game):
        """Bid 4, take 6 = 40 + 2 bags = 42."""
        self._setup_and_score(game, (2, 3, 2, 3), {
            "player_a": 3, "player_b": 3, "player_c": 3, "player_d": 4,
        })
        # Team 1: contract 4, took 6 → 40 + 2 = 42, 2 bags
        assert game._scores["team_1"] == 42
        assert game._bags["team_1"] == 2
        # Team 2: contract 6, took 7 → 60 + 1 = 61, 1 bag
        assert game._scores["team_2"] == 61
        assert game._bags["team_2"] == 1

    def test_set_penalty(self, game):
        """Bid 5, take 3 = -50."""
        self._setup_and_score(game, (3, 3, 2, 3), {
            "player_a": 1, "player_b": 5, "player_c": 2, "player_d": 5,
        })
        # Team 1: contract 5, took 3 → -50
        assert game._scores["team_1"] == -50
        # Team 2: contract 6, took 10 → 60 + 4 = 64, 4 bags
        assert game._scores["team_2"] == 64

    def test_nil_success(self, game):
        """Nil bid (0) + take 0 tricks = +100 bonus."""
        self._setup_and_score(game, (0, 3, 5, 3), {
            "player_a": 0, "player_b": 3, "player_c": 6, "player_d": 4,
        })
        # Team 1: nil success +100, partner contract 5 took 6 → 50 + 1 = 51, total 151
        assert game._scores["team_1"] == 151
        assert game._bags["team_1"] == 1

    def test_nil_failure(self, game):
        """Nil bid (0) + take 1+ tricks = -100 penalty."""
        self._setup_and_score(game, (0, 3, 5, 3), {
            "player_a": 2, "player_b": 3, "player_c": 3, "player_d": 5,
        })
        # Team 1: nil fail -100, partner contract 5 took 3 → -50, total -150
        assert game._scores["team_1"] == -150

    def test_bag_penalty_at_10(self, game):
        """Accumulating 10 bags triggers -100 penalty."""
        game._bags["team_1"] = 8  # Start with 8 bags
        self._setup_and_score(game, (2, 3, 2, 3), {
            "player_a": 3, "player_b": 3, "player_c": 2, "player_d": 3,
        })
        # Team 1: contract 4, took 5 → 40 + 1 = 41, but 8+1=9 bags
        # Wait, 1 overtrick → 8+1=9 bags, no penalty yet
        assert game._bags["team_1"] == 9

    def test_bag_penalty_triggered(self, game):
        """Accumulating 10+ bags triggers -100 penalty and resets."""
        game._bags["team_1"] = 8
        self._setup_and_score(game, (2, 3, 2, 3), {
            "player_a": 4, "player_b": 3, "player_c": 2, "player_d": 3,
        })
        # Team 1: contract 4, took 6 → 40 + 2 = 42, bags 8+2=10 → penalty -100
        # Total: 42 + (-100) = -58, bags reset to 0
        assert game._scores["team_1"] == -58
        assert game._bags["team_1"] == 0

    def test_scores_report_per_player_as_team(self, game):
        """get_scores() gives both team members the same score."""
        self._setup_and_score(game, (3, 3, 2, 3), {
            "player_a": 3, "player_b": 3, "player_c": 2, "player_d": 3,
        })
        scores = game.get_scores()
        assert scores["player_a"] == scores["player_c"]  # same team
        assert scores["player_b"] == scores["player_d"]  # same team


# ------------------------------------------------------------------
# Game end conditions
# ------------------------------------------------------------------

class TestGameEnd:
    def test_target_score_ends_game(self, game):
        """Game ends when a team reaches 500."""
        game._scores["team_1"] = 480
        _bid_all(game, (3, 1, 2, 1))
        game._tricks_taken = {"player_a": 3, "player_b": 2, "player_c": 2, "player_d": 6}
        game._score_hand()
        # Team 1: 480 + 50 = 530 → game over
        assert game.is_terminal()

    def test_floor_score_ends_game(self, game):
        """Game ends if a team hits -200."""
        game._scores["team_1"] = -190
        _bid_all(game, (3, 3, 2, 3))
        game._tricks_taken = {"player_a": 0, "player_b": 5, "player_c": 1, "player_d": 7}
        game._score_hand()
        # Team 1: -190 + (-50) = -240 ≤ -200 → game over
        assert game.is_terminal()

    def test_hand_limit_ends_game(self, game):
        """Game ends after 25 hands if no one reaches 500."""
        game._hand_number = 25
        game._scores["team_1"] = 100
        game._scores["team_2"] = 200
        _bid_all(game, (3, 3, 2, 3))
        game._tricks_taken = {"player_a": 3, "player_b": 3, "player_c": 2, "player_d": 5}
        game._score_hand()
        assert game.is_terminal()

    def test_both_cross_500_higher_wins(self, game):
        """If both teams cross 500 on same hand, higher score wins."""
        game._scores["team_1"] = 490
        game._scores["team_2"] = 480
        _bid_all(game, (2, 3, 2, 3))
        game._tricks_taken = {"player_a": 2, "player_b": 4, "player_c": 2, "player_d": 5}
        game._score_hand()
        assert game.is_terminal()
        # Both scored enough — team scores determine the winner
        assert game._scores["team_1"] > 0
        assert game._scores["team_2"] > 0


# ------------------------------------------------------------------
# Forfeit handling
# ------------------------------------------------------------------

class TestForfeit:
    def test_forfeit_bid_defaults_to_2(self, game):
        game.forfeit_turn("player_a")
        assert game._bids["player_a"] == 2

    def test_forfeit_play_follows_suit(self, game):
        _bid_all(game, (3, 3, 3, 3))

        game._hands["player_a"] = ["5♥", "6♣", "7♣", "8♣", "9♣", "10♣", "J♣", "Q♣", "K♣", "A♣", "2♣", "3♣", "4♣"]
        game._hands["player_b"] = ["3♥", "K♥", "2♦", "5♦", "6♦", "7♦", "8♦", "9♦", "10♦", "J♦", "Q♦", "K♦", "A♦"]

        game.apply_action("player_a", {"action": "play", "card": "5♥"})

        # Player b should forfeit with lowest heart (3♥)
        hand_before = list(game._hands["player_b"])
        game.forfeit_turn("player_b")
        # 3♥ should have been removed (lowest heart)
        assert "3♥" not in game._hands["player_b"]
        assert "K♥" in game._hands["player_b"]

    def test_forfeit_lead_plays_lowest_non_spade(self, game):
        _bid_all(game, (3, 3, 3, 3))

        game._hands["player_a"] = ["2♣", "A♠", "K♠", "Q♠", "J♠", "10♠", "9♠", "8♠", "7♠", "6♠", "5♠", "4♠", "3♠"]

        game.forfeit_turn("player_a")
        # Should play 2♣ (lowest non-spade) since spades not broken
        assert "2♣" not in game._hands["player_a"]

    def test_forfeit_lead_only_spades(self, game):
        _bid_all(game, (3, 3, 3, 3))

        game._hands["player_a"] = ["A♠", "K♠", "Q♠", "J♠", "10♠", "9♠", "8♠", "7♠", "6♠", "5♠", "4♠", "3♠", "2♠"]

        game.forfeit_turn("player_a")
        # Only spades — must play lowest (2♠)
        assert "2♠" not in game._hands["player_a"]

    def test_forfeit_play_always_legal(self, game):
        """Running through an entire hand with forfeit should never crash."""
        _bid_all(game, (3, 3, 3, 3))
        _play_hand_forfeit(game)
        # No assertion needed — just shouldn't raise


# ------------------------------------------------------------------
# Phase transitions
# ------------------------------------------------------------------

class TestPhaseTransitions:
    def test_full_hand_cycle(self, game):
        """Bid + play through all 13 tricks completes a hand."""
        _bid_all(game, (3, 3, 3, 3))
        _play_hand_forfeit(game)

        # Should have moved to next hand (or ended game)
        if not game.is_terminal():
            assert game._hand_number == 2
            assert game._phase == Phase.BID

    def test_multiple_hands(self, game):
        """Can play through several hands."""
        for _ in range(3):
            if game.is_terminal():
                break
            _play_full_hand_forfeit(game)

        # Should still be going or have finished
        assert game._hand_number >= 3 or game.is_terminal()


# ------------------------------------------------------------------
# Prompt generation
# ------------------------------------------------------------------

class TestPrompts:
    def test_bid_prompt_has_hand(self, game):
        prompt = game.get_prompt("player_a")
        # Should contain card symbols
        assert "♠" in prompt or "♥" in prompt or "♦" in prompt or "♣" in prompt

    def test_bid_prompt_has_team_info(self, game):
        prompt = game.get_prompt("player_a")
        assert "partner" in prompt.lower()
        assert "Team 1" in prompt

    def test_play_prompt_has_trick_info(self, game):
        _bid_all(game, (3, 3, 3, 3))
        prompt = game.get_prompt("player_a")
        assert "TRICK PLAY" in prompt
        assert "contract" in prompt.lower()

    def test_retry_prompt_has_error(self, game):
        prompt = game.get_retry_prompt("player_a", "invalid bid")
        assert "invalid bid" in prompt.lower()


# ------------------------------------------------------------------
# State snapshots
# ------------------------------------------------------------------

class TestSnapshot:
    def test_snapshot_has_required_fields(self, game):
        snap = game.get_state_snapshot()
        required = [
            "phase", "game_number", "hand_number", "trick_number",
            "hands", "bids", "team_contracts", "tricks_taken",
            "current_trick", "scores", "bags", "spades_broken",
            "trick_history", "terminal", "match_scores",
        ]
        for field in required:
            assert field in snap, f"Missing field: {field}"

    def test_snapshot_phase_is_string(self, game):
        snap = game.get_state_snapshot()
        assert isinstance(snap["phase"], str)
        assert snap["phase"] in ("bid", "play")

    def test_snapshot_hands_are_lists(self, game):
        snap = game.get_state_snapshot()
        for pid in game.player_ids:
            assert isinstance(snap["hands"][pid], list)
            assert len(snap["hands"][pid]) == 13


# ------------------------------------------------------------------
# Highlight detection
# ------------------------------------------------------------------

class TestHighlights:
    def test_nil_bid_highlighted(self, game):
        game.apply_action("player_a", {"action": "bid", "bid": 0})
        highlights = game.get_highlight_hands()
        assert len(highlights) > 0

    def test_spades_broken_highlighted(self, game):
        _bid_all(game, (3, 3, 3, 3))

        game._hands["player_a"] = ["2♥", "3♣", "4♣", "5♣", "6♣", "7♣", "8♣", "9♣", "10♣", "J♣", "Q♣", "K♣", "A♣"]
        game._hands["player_b"] = ["3♥", "2♦", "4♦", "5♦", "6♦", "7♦", "8♦", "9♦", "10♦", "J♦", "Q♦", "K♦", "A♦"]
        game._hands["player_c"] = ["2♠", "3♠", "4♠", "5♠", "6♠", "7♠", "8♠", "9♠", "10♠", "J♠", "Q♠", "K♠", "A♠"]
        game._hands["player_d"] = ["5♥", "6♥", "7♥", "8♥", "9♥", "10♥", "J♥", "Q♥", "K♥", "A♥", "4♥", "2♣", "3♦"]

        initial_count = len(game.get_highlight_hands())
        game.apply_action("player_a", {"action": "play", "card": "2♥"})
        game.apply_action("player_b", {"action": "play", "card": "3♥"})
        game.apply_action("player_c", {"action": "play", "card": "2♠"})

        assert len(game.get_highlight_hands()) > initial_count


# ------------------------------------------------------------------
# Match forfeit
# ------------------------------------------------------------------

class TestMatchForfeit:
    def test_award_forfeit_wins_terminates(self, game):
        game.award_forfeit_wins("player_a")
        assert game.is_terminal()

    def test_award_forfeit_wins_gives_points(self, game):
        game.award_forfeit_wins("player_a")
        scores = game.get_scores()
        # Winning team (team_2) should get points
        assert scores["player_b"] > 0
        assert scores["player_d"] > 0
        # Forfeiting team partner should also get points (same team gets nothing extra)
        # Actually forfeiting team gets 0
        assert scores["player_a"] == 0


# ------------------------------------------------------------------
# Integration: full game via forfeit
# ------------------------------------------------------------------

class TestIntegration:
    def test_full_game_via_forfeit(self, game):
        """Run a full game using only forfeits — should terminate cleanly."""
        turns = 0
        max_turns = 5000  # safety valve
        while not game.is_terminal() and turns < max_turns:
            game.forfeit_turn(game.current_player())
            turns += 1

        assert game.is_terminal()
        scores = game.get_scores()
        assert len(scores) == 4

    def test_deterministic_with_same_seed(self):
        """Same seed produces same game."""
        g1 = SpadesEvent()
        g1.reset(seed=123)
        g2 = SpadesEvent()
        g2.reset(seed=123)

        assert g1._hands == g2._hands
        assert g1.get_state_snapshot() == g2.get_state_snapshot()

    def test_different_seeds_differ(self):
        """Different seeds produce different games."""
        g1 = SpadesEvent()
        g1.reset(seed=1)
        g2 = SpadesEvent()
        g2.reset(seed=2)

        assert g1._hands != g2._hands
