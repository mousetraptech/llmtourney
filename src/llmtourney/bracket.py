"""BracketRunner — single-elimination bracket tournament.

Composes a TournamentEngine and calls its _run_match() for each bracket
matchup. Runs all matches in a round concurrently, writes an atomic
bracket manifest after each round.
"""

from __future__ import annotations

import json
import os
import tempfile
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path

from llmtourney.config import TournamentConfig
from llmtourney.tournament import TournamentEngine, MatchResult


# ── Round labels ─────────────────────────────────────────────────

_ROUND_LABELS = {
    1: "FINAL",
    2: "SEMIFINALS",
    3: "QUARTERFINALS",
}


def _round_label(rounds_remaining: int, round_number: int, total_rounds: int) -> str:
    """Derive a human-readable label for a bracket round."""
    remaining = total_rounds - round_number + 1
    if remaining in _ROUND_LABELS:
        return _ROUND_LABELS[remaining]
    return f"ROUND {round_number}"


# ── Seeding ──────────────────────────────────────────────────────

def _bracket_pairings(n: int) -> list[tuple[int, int]]:
    """Generate standard bracket pairings for n seeds (1-indexed).

    Arranges so top seeds meet in the final if favorites always win.
    Uses recursive bracket construction:
      - For n=2: [(1,2)]
      - For n=4: [(1,4), (3,2)]  — seeds 1 and 2 in opposite halves
      - For n=8: [(1,8), (4,5), (3,6), (2,7)]
    """
    if n == 2:
        return [(1, 2)]
    # Recursive: pair top half seeds with bottom half seeds
    half = n // 2
    prev = _bracket_pairings(half)
    result = []
    for a, b in prev:
        # Each seed s from the smaller bracket becomes two matches:
        # seed s vs seed (n + 1 - s)
        result.append((a, n + 1 - a))
        result.append((b, n + 1 - b))
    return result


# ── Bracket match bookkeeping ────────────────────────────────────

@dataclass
class BracketMatch:
    position: int
    seed_a: int
    model_a: str
    seed_b: int
    model_b: str
    match_id: str | None = None
    scores: dict[str, float] = field(default_factory=dict)
    winner: str | None = None
    winner_seed: int | None = None


# ── Winner determination ─────────────────────────────────────────

def determine_winner(
    result: MatchResult,
    seed_a: int,
    seed_b: int,
) -> tuple[str, int]:
    """Pick winner from a MatchResult.

    Tiebreakers: higher score → fewer violations → higher seed.
    Returns (winner_model_name, winner_seed).
    """
    model_a = result.player_models["player_a"]
    model_b = result.player_models["player_b"]
    score_a = result.scores.get("player_a", 0.0)
    score_b = result.scores.get("player_b", 0.0)

    if score_a != score_b:
        if score_a > score_b:
            return model_a, seed_a
        return model_b, seed_b

    # Tiebreak: fewer violations
    viol_a = result.fidelity.get("player_a", {}).get("total_violations", 0)
    viol_b = result.fidelity.get("player_b", {}).get("total_violations", 0)
    if viol_a != viol_b:
        if viol_a < viol_b:
            return model_a, seed_a
        return model_b, seed_b

    # Tiebreak: higher seed (lower number)
    if seed_a < seed_b:
        return model_a, seed_a
    return model_b, seed_b


# ── BracketRunner ────────────────────────────────────────────────

class BracketRunner:
    """Runs a single-elimination bracket tournament."""

    def __init__(self, config: TournamentConfig) -> None:
        self.config = config
        self.engine = TournamentEngine(config)
        self._validate()

        self.event_name = list(config.events.keys())[0]
        self.event_cfg = config.events[self.event_name]

        model_names = list(config.models.keys())
        self.num_models = len(model_names)
        self.num_rounds = self.num_models.bit_length() - 1  # log2

        # Build seed map: config order = seed order
        self.seeds: list[dict] = [
            {"seed": i + 1, "model": name}
            for i, name in enumerate(model_names)
        ]
        self.seed_to_model = {s["seed"]: s["model"] for s in self.seeds}

        self.rounds: list[dict] = []
        self.champion: str | None = None
        self.manifest_path = self.engine.telemetry_dir / f"bracket-{config.name}.json"

    def _validate(self) -> None:
        n = len(self.config.models)
        if n < 2 or (n & (n - 1)) != 0:
            raise ValueError(
                f"Bracket mode requires a power-of-2 number of models, got {n}"
            )
        if len(self.config.events) != 1:
            raise ValueError(
                f"Bracket mode requires exactly one event, got {len(self.config.events)}"
            )

    def run(self) -> dict:
        """Execute the full bracket and return the manifest."""
        # Build first round pairings from seeds
        pairings = _bracket_pairings(self.num_models)
        current_matchups = [
            BracketMatch(
                position=i,
                seed_a=sa,
                model_a=self.seed_to_model[sa],
                seed_b=sb,
                model_b=self.seed_to_model[sb],
            )
            for i, (sa, sb) in enumerate(pairings)
        ]

        for round_num in range(1, self.num_rounds + 1):
            label = _round_label(
                self.num_rounds - round_num + 1, round_num, self.num_rounds
            )
            print(f"\n{'='*50}")
            print(f"  {label} (Round {round_num}/{self.num_rounds})")
            print(f"{'='*50}")

            # Pre-generate match_ids so manifest can be written before round starts
            for bm in current_matchups:
                short_id = uuid.uuid4().hex[:6]
                bm.match_id = f"{self.event_name}-{bm.model_a}-vs-{bm.model_b}-{short_id}"

            # Write manifest with in-progress round before matches start
            round_data = {
                "round": round_num,
                "label": label,
                "status": "in_progress",
                "matches": [self._match_to_dict(bm) for bm in current_matchups],
            }
            self.rounds.append(round_data)
            self._write_manifest()

            self._run_round(current_matchups)

            # Update round status to complete with final scores
            self.rounds[-1] = {
                "round": round_num,
                "label": label,
                "status": "complete",
                "matches": [self._match_to_dict(bm) for bm in current_matchups],
            }
            self._write_manifest()

            # Build next round from winners
            if round_num < self.num_rounds:
                next_matchups = []
                for i in range(0, len(current_matchups), 2):
                    w1 = current_matchups[i]
                    w2 = current_matchups[i + 1]
                    next_matchups.append(BracketMatch(
                        position=i // 2,
                        seed_a=w1.winner_seed,
                        model_a=w1.winner,
                        seed_b=w2.winner_seed,
                        model_b=w2.winner,
                    ))
                current_matchups = next_matchups

        # Final winner
        self.champion = current_matchups[0].winner
        self._write_manifest()
        return self._build_manifest()

    def _run_round(self, matchups: list[BracketMatch]) -> None:
        """Run all matches in a round concurrently."""
        with ThreadPoolExecutor(max_workers=len(matchups)) as pool:
            futures = {
                pool.submit(
                    self.engine._run_match,
                    self.event_name,
                    self.event_cfg,
                    bm.model_a,
                    bm.model_b,
                    bm.match_id,
                ): bm
                for bm in matchups
            }
            for future in as_completed(futures):
                bm = futures[future]
                result = future.result()
                bm.scores = {
                    "player_a": result.scores.get("player_a", 0.0),
                    "player_b": result.scores.get("player_b", 0.0),
                }
                winner_name, winner_seed = determine_winner(
                    result, bm.seed_a, bm.seed_b
                )
                bm.winner = winner_name
                bm.winner_seed = winner_seed

                loser = bm.model_b if winner_name == bm.model_a else bm.model_a
                print(f"  {bm.model_a} vs {bm.model_b}")
                print(f"    Score: {bm.scores['player_a']:.0f} - {bm.scores['player_b']:.0f}")
                print(f"    Winner: {winner_name}")

    def _match_to_dict(self, bm: BracketMatch) -> dict:
        return {
            "position": bm.position,
            "seed_a": bm.seed_a,
            "model_a": bm.model_a,
            "seed_b": bm.seed_b,
            "model_b": bm.model_b,
            "match_id": bm.match_id,
            "scores": bm.scores,
            "winner": bm.winner,
        }

    def _build_manifest(self) -> dict:
        return {
            "tournament_name": self.config.name,
            "event": self.event_name,
            "num_models": self.num_models,
            "num_rounds": self.num_rounds,
            "seeds": self.seeds,
            "rounds": self.rounds,
            "champion": self.champion,
            "status": "complete" if self.champion else "in_progress",
        }

    def _write_manifest(self) -> None:
        """Write manifest atomically (tmp + rename)."""
        manifest = self._build_manifest()
        fd, tmp_path = tempfile.mkstemp(
            dir=self.manifest_path.parent,
            suffix=".tmp",
        )
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(manifest, f, indent=2)
            os.replace(tmp_path, self.manifest_path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def print_bracket(self) -> None:
        """Print a text representation of the bracket tree."""
        if not self.rounds:
            return
        print(f"\n{'='*50}")
        print(f"  BRACKET: {self.config.name}")
        print(f"{'='*50}")
        for rd in self.rounds:
            print(f"\n  {rd['label']}:")
            for m in rd["matches"]:
                marker = " *" if m["winner"] else ""
                sa, sb = m["seed_a"], m["seed_b"]
                print(f"    [{sa}] {m['model_a']} vs [{sb}] {m['model_b']}{marker}")
                if m.get("scores"):
                    print(f"        {m['scores'].get('player_a', 0):.0f} - {m['scores'].get('player_b', 0):.0f}")
                if m["winner"]:
                    print(f"        Winner: {m['winner']}")
        if self.champion:
            print(f"\n  CHAMPION: {self.champion}")
