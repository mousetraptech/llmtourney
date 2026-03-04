"""Tests for hybrid scoring."""

from llmtourney.scoring.hybrid import hybrid_holdem_scores, hybrid_normalize


def test_r1_champions_bracket():
    """Verify exact expected scores for the 8-player R1 data."""
    elimination_order = [
        ("deepseek", 29),
        ("haiku", 40),
        ("gpt-4o-mini", 45),
        ("opus", 52),
        ("grok-3-mini", 68),
    ]
    final_chips = {
        "deepseek": 0,
        "haiku": 0,
        "gpt-4o-mini": 0,
        "opus": 0,
        "grok-3-mini": 0,
        "gpt-4o": 328,
        "grok-3": 734,
        "sonnet": 1338,
    }
    scores = hybrid_holdem_scores(elimination_order, final_chips, n_players=8)

    assert scores["deepseek"] == 0.0
    assert scores["haiku"] == 7.1      # 2nd out (H40)
    assert scores["gpt-4o-mini"] == 14.3  # 3rd out (H45)
    assert scores["opus"] == 21.4
    assert scores["grok-3-mini"] == 28.6
    assert scores["gpt-4o"] == 42.5
    assert scores["grok-3"] == 58.1
    assert scores["sonnet"] == 77.9


def test_same_hand_bust():
    """Players busted on the same hand share averaged placements."""
    # 4 players: two bust on hand 5, one survives with 500, one with 500
    elimination_order = [
        ("a", 5),
        ("b", 5),
    ]
    final_chips = {"a": 0, "b": 0, "c": 500, "d": 500}
    scores = hybrid_holdem_scores(elimination_order, final_chips, n_players=4)

    # a and b share placements 1 and 2 → avg 1.5
    # Floor for 1.5: ((1.5 - 1) / 3) * 50 = 8.3
    assert scores["a"] == 8.3
    assert scores["b"] == 8.3

    # c and d are survivors ranked by chips (equal → order from dict)
    # c gets placement 3: ((3-1)/3)*50 = 33.3, chip bonus = 25.0 → 58.3
    # d gets placement 4: ((4-1)/3)*50 = 50.0, chip bonus = 25.0 → 75.0
    # But they have equal chips, so whichever sorts first gets placement 3
    # Total should be 58.3 + 75.0 = 133.3 between them
    assert scores["c"] + scores["d"] == 133.3  # verify total


def test_all_busted_except_one():
    """Winner gets 100 when all others are busted."""
    elimination_order = [
        ("a", 10),
        ("b", 20),
        ("c", 30),
    ]
    final_chips = {"a": 0, "b": 0, "c": 0, "d": 800}
    scores = hybrid_holdem_scores(elimination_order, final_chips, n_players=4)

    # d is the sole survivor: placement 4, floor = 50.0, chip bonus = 50.0
    assert scores["d"] == 100.0
    # a: placement 1, floor 0.0
    assert scores["a"] == 0.0
    # b: placement 2, floor = (1/3)*50 = 16.7
    assert scores["b"] == 16.7
    # c: placement 3, floor = (2/3)*50 = 33.3
    assert scores["c"] == 33.3


def test_two_player():
    """Two-player: winner gets 100, loser gets 0."""
    elimination_order = [("loser", 15)]
    final_chips = {"loser": 0, "winner": 400}
    scores = hybrid_holdem_scores(elimination_order, final_chips, n_players=2)

    assert scores["winner"] == 100.0
    assert scores["loser"] == 0.0


# --- hybrid_normalize tests ---


def test_normalize_storyteller_r2():
    """Verify R2 storyteller normalization."""
    raw = {
        "haiku": 27, "sonnet": 24, "opus": 19,
        "grok-3": 6, "deepseek": 5, "gpt-4o-mini": 3,
        "grok-3-mini": 2, "gpt-4o": 2,
    }
    scores = hybrid_normalize(raw)
    # Winner (haiku) should have highest score, last place lowest
    ranked = sorted(scores, key=lambda p: scores[p], reverse=True)
    assert ranked[0] == "haiku"
    assert ranked[1] == "sonnet"
    assert ranked[2] == "opus"
    # Each score is in [0, 100]
    for s in scores.values():
        assert 0 <= s <= 100


def test_normalize_ties():
    """Tied raw scores share averaged placements."""
    raw = {"a": 10, "b": 10, "c": 5}
    scores = hybrid_normalize(raw)
    # a and b tied → same score
    assert scores["a"] == scores["b"]
    # c is last
    assert scores["c"] < scores["a"]


def test_normalize_two_player():
    """Two players: winner 100, loser 0."""
    raw = {"winner": 10, "loser": 0}
    scores = hybrid_normalize(raw)
    assert scores["winner"] == 100.0
    assert scores["loser"] == 0.0


def test_normalize_all_zero():
    """All zeros: equal placement floor, no proportion bonus."""
    raw = {"a": 0, "b": 0, "c": 0}
    scores = hybrid_normalize(raw)
    # All tied → averaged placements (1+2+3)/3 = 2, floor = (1/2)*50 = 25.0
    assert scores["a"] == 25.0
    assert scores["b"] == 25.0
    assert scores["c"] == 25.0
