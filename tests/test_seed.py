"""Tests for SeedManager — deterministic RNG per match."""

from llmtourney.core.seed import SeedManager


class TestSeedManager:
    def test_same_inputs_same_seed(self):
        sm = SeedManager(42)
        s1 = sm.get_match_seed("holdem", 1, 1)
        s2 = sm.get_match_seed("holdem", 1, 1)
        assert s1 == s2

    def test_different_events_different_seeds(self):
        sm = SeedManager(42)
        s1 = sm.get_match_seed("holdem", 1, 1)
        s2 = sm.get_match_seed("yahtzee", 1, 1)
        assert s1 != s2

    def test_different_rounds_different_seeds(self):
        sm = SeedManager(42)
        s1 = sm.get_match_seed("holdem", 1, 1)
        s2 = sm.get_match_seed("holdem", 2, 1)
        assert s1 != s2

    def test_different_tournament_seeds_different_output(self):
        sm1 = SeedManager(42)
        sm2 = SeedManager(99)
        s1 = sm1.get_match_seed("holdem", 1, 1)
        s2 = sm2.get_match_seed("holdem", 1, 1)
        assert s1 != s2

    def test_get_rng_deterministic(self):
        sm = SeedManager(42)
        seed = sm.get_match_seed("holdem", 1, 1)
        rng1 = sm.get_rng(seed)
        rng2 = sm.get_rng(seed)
        vals1 = [rng1.random() for _ in range(10)]
        vals2 = [rng2.random() for _ in range(10)]
        assert vals1 == vals2

    def test_get_rng_isolated_from_global(self):
        """RNG instances don't affect global random state."""
        import random
        random.seed(0)
        global_before = random.random()
        random.seed(0)

        sm = SeedManager(42)
        seed = sm.get_match_seed("holdem", 1, 1)
        rng = sm.get_rng(seed)
        _ = [rng.random() for _ in range(100)]

        global_after = random.random()
        assert global_before == global_after
