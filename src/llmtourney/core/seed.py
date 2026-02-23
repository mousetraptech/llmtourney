"""SeedManager — deterministic, HMAC-derived RNG per match.

Seeds are derived via HMAC-SHA256 so adding/removing matches
never shifts seeds for other matches.
"""

import hashlib
import hmac
import random


class SeedManager:
    """Produces deterministic, isolated Random instances for each match."""

    def __init__(self, tournament_seed: int):
        self._tournament_seed = tournament_seed

    def get_match_seed(self, event: str, round_num: int, match_num: int) -> int:
        """Derive a match seed via HMAC. Same inputs always produce the same seed."""
        key = self._tournament_seed.to_bytes(8, byteorder="big", signed=True)
        msg = f"{event}:{round_num}:{match_num}".encode("utf-8")
        digest = hmac.new(key, msg, hashlib.sha256).digest()
        return int.from_bytes(digest[:8], byteorder="big")

    def get_rng(self, match_seed: int) -> random.Random:
        """Return an isolated Random instance. Never touches global state."""
        return random.Random(match_seed)
