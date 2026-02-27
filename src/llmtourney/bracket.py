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
    event_scores: dict[str, dict] = field(default_factory=dict)
    event_match_ids: dict[str, str] = field(default_factory=dict)
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


def determine_multi_event_winner(
    results: list[MatchResult],
    seed_a: int,
    seed_b: int,
    model_a: str,
    model_b: str,
) -> tuple[str, int, dict[str, float], dict[str, dict]]:
    """Pick winner from multiple event results using event points.

    Each event: win = 1pt, draw = 0.5pt, loss = 0pt.
    Tiebreaker: total violations across all events, then higher seed.
    Returns (winner_name, winner_seed, aggregate_scores, event_scores_dict).
    """
    points_a = 0.0
    points_b = 0.0
    total_viol_a = 0
    total_viol_b = 0
    event_scores = {}

    for result in results:
        sa = result.scores.get("player_a", 0.0)
        sb = result.scores.get("player_b", 0.0)
        if sa > sb:
            pa, pb = 1.0, 0.0
        elif sb > sa:
            pa, pb = 0.0, 1.0
        else:
            pa, pb = 0.5, 0.5
        points_a += pa
        points_b += pb
        total_viol_a += result.fidelity.get("player_a", {}).get("total_violations", 0)
        total_viol_b += result.fidelity.get("player_b", {}).get("total_violations", 0)
        event_scores[result.event] = {
            "score_a": sa, "score_b": sb,
            "point_a": pa, "point_b": pb,
        }

    aggregate = {"player_a": points_a, "player_b": points_b}

    if points_a != points_b:
        if points_a > points_b:
            return model_a, seed_a, aggregate, event_scores
        return model_b, seed_b, aggregate, event_scores

    # Tiebreak: fewer total violations
    if total_viol_a != total_viol_b:
        if total_viol_a < total_viol_b:
            return model_a, seed_a, aggregate, event_scores
        return model_b, seed_b, aggregate, event_scores

    # Tiebreak: higher seed
    if seed_a < seed_b:
        return model_a, seed_a, aggregate, event_scores
    return model_b, seed_b, aggregate, event_scores


# ── BracketRunner ────────────────────────────────────────────────

class BracketRunner:
    """Runs a single-elimination bracket tournament."""

    def __init__(self, config: TournamentConfig, pause_before_final: bool = False) -> None:
        self.config = config
        self.engine = TournamentEngine(config)
        self.pause_before_final = pause_before_final
        self._validate()

        self.event_names = list(config.events.keys())
        self.multi_event = len(self.event_names) > 1
        self.event_name = self.event_names[0]  # primary (for single-event compat)
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

            if round_num == self.num_rounds and self.pause_before_final:
                bm = current_matchups[0]
                print(f"\n  >>> {bm.model_a} vs {bm.model_b}")
                input("  Press Enter to start the FINAL... ")

            # Pre-generate match_ids so manifest can be written before round starts
            for bm in current_matchups:
                short_id = uuid.uuid4().hex[:6]
                prefix = self.config.name.split("-bracket")[0] if self.multi_event else self.event_name
                bm.match_id = f"{prefix}-{bm.model_a}-vs-{bm.model_b}-{short_id}"
                if self.multi_event:
                    for event_name in self.event_names:
                        eid = uuid.uuid4().hex[:6]
                        bm.event_match_ids[event_name] = f"{event_name}-{bm.model_a}-vs-{bm.model_b}-{eid}"

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

    def _run_multi_event_match(self, bm: BracketMatch) -> None:
        """Run all events for a single bracket match and aggregate results."""
        results = []
        for event_name in self.event_names:
            event_cfg = self.config.events[event_name]
            event_match_id = bm.event_match_ids[event_name]
            result = self.engine._run_match(
                event_name, event_cfg, bm.model_a, bm.model_b, event_match_id
            )
            results.append(result)
            # Print per-event result
            sa = result.scores.get("player_a", 0.0)
            sb = result.scores.get("player_b", 0.0)
            w = "A" if sa > sb else "B" if sb > sa else "="
            print(f"    {event_name}: {sa:.0f}-{sb:.0f} ({w})")

            # Update intermediate event_scores and manifest so spectator
            # can track per-event progress in real time
            pa = 1.0 if sa > sb else (0.0 if sb > sa else 0.5)
            pb = 1.0 - pa if pa != 0.5 else 0.5
            bm.event_scores[event_name] = {
                "score_a": sa, "score_b": sb,
                "point_a": pa, "point_b": pb,
            }
            bm.scores = {
                "player_a": sum(es["point_a"] for es in bm.event_scores.values()),
                "player_b": sum(es["point_b"] for es in bm.event_scores.values()),
            }
            self._write_manifest()

        winner_name, winner_seed, aggregate, event_scores = determine_multi_event_winner(
            results, bm.seed_a, bm.seed_b, bm.model_a, bm.model_b
        )
        bm.scores = aggregate
        bm.event_scores = event_scores
        bm.winner = winner_name
        bm.winner_seed = winner_seed

    def _run_round(self, matchups: list[BracketMatch]) -> None:
        """Run all matches in a round concurrently."""
        with ThreadPoolExecutor(max_workers=len(matchups)) as pool:
            if self.multi_event:
                futures = {
                    pool.submit(self._run_multi_event_match, bm): bm
                    for bm in matchups
                }
            else:
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
                if not self.multi_event:
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
                else:
                    future.result()  # already handled in _run_multi_event_match
                    winner_name = bm.winner

                print(f"  {bm.model_a} vs {bm.model_b}")
                print(f"    Score: {bm.scores['player_a']:.1f} - {bm.scores['player_b']:.1f}")
                print(f"    Winner: {winner_name}")

    def _match_to_dict(self, bm: BracketMatch) -> dict:
        d = {
            "position": bm.position,
            "seed_a": bm.seed_a,
            "model_a": bm.model_a,
            "seed_b": bm.seed_b,
            "model_b": bm.model_b,
            "match_id": bm.match_id,
            "scores": bm.scores,
            "winner": bm.winner,
        }
        if bm.event_scores:
            d["event_scores"] = bm.event_scores
        if bm.event_match_ids:
            d["event_match_ids"] = bm.event_match_ids
        return d

    def _build_manifest(self) -> dict:
        d = {
            "tournament_name": self.config.name,
            "event": "+".join(self.event_names) if self.multi_event else self.event_name,
            "num_models": self.num_models,
            "num_rounds": self.num_rounds,
            "seeds": self.seeds,
            "rounds": self.rounds,
            "champion": self.champion,
            "status": "complete" if self.champion else "in_progress",
        }
        if self.multi_event:
            d["events"] = self.event_names
            d["scoring"] = "event_points"
        return d

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
                    pa = m['scores'].get('player_a', 0)
                    pb = m['scores'].get('player_b', 0)
                    fmt = ".1f" if self.multi_event else ".0f"
                    print(f"        {pa:{fmt}} - {pb:{fmt}}")
                if m.get("event_scores"):
                    for ev, es in m["event_scores"].items():
                        w = "A" if es["point_a"] > es["point_b"] else "B" if es["point_b"] > es["point_a"] else "="
                        print(f"          {ev}: {es['score_a']:.0f}-{es['score_b']:.0f} ({w})")
                if m["winner"]:
                    print(f"        Winner: {m['winner']}")
        if self.champion:
            print(f"\n  CHAMPION: {self.champion}")
