"""LeagueRunner — round-robin league tournament with resumable manifest.

Composes a TournamentEngine and calls its _run_match() /
_run_multiplayer_match() methods. Generates all fixtures up front,
persists progress to a JSON manifest after each fixture, and computes
league standings from completed results.

Structural pattern follows bracket.py.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import traceback
import uuid
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from itertools import combinations
from pathlib import Path

from llmtourney.config import TournamentConfig
from llmtourney.tournament import TournamentEngine, MatchResult, _MULTIPLAYER_EVENTS


# ── Data structures ──────────────────────────────────────────────

@dataclass
class Fixture:
    fixture_id: str
    event: str
    models: list[str]
    match_number: int
    match_id: str | None = None
    status: str = "pending"  # pending | in_progress | complete | error
    scores: dict[str, float] = field(default_factory=dict)
    player_models: dict[str, str] = field(default_factory=dict)
    fidelity: dict = field(default_factory=dict)
    error: str | None = None


@dataclass
class StandingsEntry:
    model: str
    played: int = 0
    wins: int = 0
    draws: int = 0
    losses: int = 0
    points_for: float = 0.0
    points_against: float = 0.0
    league_points: float = 0.0

    @property
    def differential(self) -> float:
        return self.points_for - self.points_against


# ── Scoring helpers ──────────────────────────────────────────────

def series_to_league_points(
    scores: dict[str, float],
    player_models: dict[str, str],
) -> dict[str, float]:
    """Convert a 2-player series result to 3/1/0 league points.

    Win = 3pts, Draw = 1pt each, Loss = 0pts.
    Returns {model_name: points}.
    """
    pids = list(player_models.keys())
    sa = scores.get(pids[0], 0.0)
    sb = scores.get(pids[1], 0.0)
    ma = player_models[pids[0]]
    mb = player_models[pids[1]]

    if sa > sb:
        return {ma: 3.0, mb: 0.0}
    elif sb > sa:
        return {ma: 0.0, mb: 3.0}
    else:
        return {ma: 1.0, mb: 1.0}


def multiplayer_positional_points(
    scores: dict[str, float],
    player_models: dict[str, str],
) -> dict[str, float]:
    """Positional scoring for N-player games.

    Nth place = 1pt, 1st place = Npts. Ties get averaged rank points.
    Returns {model_name: points}.
    """
    n = len(player_models)
    # Sort players by score descending
    ranked = sorted(
        player_models.items(),
        key=lambda item: scores.get(item[0], 0.0),
        reverse=True,
    )

    # Group by score for tie handling
    result: dict[str, float] = {}
    i = 0
    while i < len(ranked):
        j = i
        score_val = scores.get(ranked[i][0], 0.0)
        while j < len(ranked) and scores.get(ranked[j][0], 0.0) == score_val:
            j += 1
        # Positions i..j-1 are tied. Rank points: n-pos for 0-indexed pos
        avg_pts = sum(n - k for k in range(i, j)) / (j - i)
        for k in range(i, j):
            model_name = ranked[k][1]
            result[model_name] = avg_pts
        i = j

    return result


# ── Standings computation ────────────────────────────────────────

def compute_standings(
    fixtures: list[Fixture],
    model_names: list[str],
    event: str | None = None,
    is_multiplayer: bool = False,
) -> list[StandingsEntry]:
    """Compute league standings from completed fixtures.

    Args:
        fixtures: All fixtures (filters to complete ones for given event).
        model_names: All models in the league.
        event: Filter to this event, or None for all events.
        is_multiplayer: Use positional scoring instead of 3/1/0.

    Returns sorted standings list.
    """
    entries = {m: StandingsEntry(model=m) for m in model_names}

    for fix in fixtures:
        if fix.status != "complete":
            continue
        if event and fix.event != event:
            continue

        if is_multiplayer:
            lp = multiplayer_positional_points(fix.scores, fix.player_models)
        else:
            lp = series_to_league_points(fix.scores, fix.player_models)

        for model_name in fix.player_models.values():
            e = entries[model_name]
            e.played += 1

        # W/D/L only makes sense for 2-player
        if not is_multiplayer and len(fix.player_models) == 2:
            pids = list(fix.player_models.keys())
            sa = fix.scores.get(pids[0], 0.0)
            sb = fix.scores.get(pids[1], 0.0)
            ma = fix.player_models[pids[0]]
            mb = fix.player_models[pids[1]]
            if sa > sb:
                entries[ma].wins += 1
                entries[mb].losses += 1
            elif sb > sa:
                entries[mb].wins += 1
                entries[ma].losses += 1
            else:
                entries[ma].draws += 1
                entries[mb].draws += 1

            entries[ma].points_for += sa
            entries[ma].points_against += sb
            entries[mb].points_for += sb
            entries[mb].points_against += sa
        else:
            # Multiplayer: points_for = own score, points_against = avg others
            for pid, model_name in fix.player_models.items():
                own_score = fix.scores.get(pid, 0.0)
                entries[model_name].points_for += own_score

        for model_name, pts in lp.items():
            entries[model_name].league_points += pts

    # Sort: league_points desc → differential desc → wins desc
    result = sorted(
        entries.values(),
        key=lambda e: (e.league_points, e.differential, e.wins),
        reverse=True,
    )
    return result


# ── LeagueRunner ─────────────────────────────────────────────────

class LeagueRunner:
    """Runs a round-robin league tournament with resumability."""

    def __init__(self, config: TournamentConfig) -> None:
        self.config = config
        self.engine = TournamentEngine(config)
        self.model_names = list(config.models.keys())
        self.manifest_path = self.engine.telemetry_dir / f"league-{config.name}.json"
        self._manifest_lock = threading.Lock()

        # One engine per event for thread safety
        self._engines: dict[str, TournamentEngine] = {}
        for event_name in config.events:
            self._engines[event_name] = TournamentEngine(config)

        # Load existing or generate fresh fixtures
        self.fixtures: list[Fixture] = []
        if self.manifest_path.exists():
            self._load_manifest()
        else:
            self.fixtures = self._generate_fixtures()

    def run(self) -> dict:
        """Execute all pending fixtures, parallelized by event."""
        total = len(self.fixtures)
        completed = sum(1 for f in self.fixtures if f.status == "complete")
        pending = sum(1 for f in self.fixtures if f.status == "pending")

        print(f"League: {self.config.name}")
        print(f"Fixtures: {total} total, {completed} complete, {pending} pending")
        print()

        if pending == 0:
            print("All fixtures complete.")
            self.print_standings()
            return self._build_manifest()

        # Write initial manifest
        self._write_manifest()

        # Group pending fixtures by event
        by_event: dict[str, list[Fixture]] = defaultdict(list)
        for fix in self.fixtures:
            if fix.status not in ("complete", "error"):
                by_event[fix.event].append(fix)

        event_names = list(by_event.keys())
        print(f"Running {len(event_names)} events in parallel: {', '.join(event_names)}")
        print()

        # Run each event's fixtures in a separate thread
        with ThreadPoolExecutor(max_workers=len(event_names)) as pool:
            futures = {
                pool.submit(self._run_event_fixtures, event, fixtures): event
                for event, fixtures in by_event.items()
            }
            for future in as_completed(futures):
                event = futures[future]
                try:
                    future.result()
                    print(f"\n{'='*40} {event.upper()} COMPLETE {'='*40}\n")
                except Exception as exc:
                    print(f"\n{event} thread failed: {exc}")
                    traceback.print_exc()

        self.print_standings()
        return self._build_manifest()

    def _run_event_fixtures(self, event: str, fixtures: list[Fixture]) -> None:
        """Run all fixtures for a single event (called from thread)."""
        engine = self._engines[event]
        total_event = len(fixtures)

        for i, fix in enumerate(fixtures):
            if fix.status in ("complete", "error"):
                continue

            is_mp = fix.event in _MULTIPLAYER_EVENTS and len(fix.models) > 2
            models_str = (
                " vs ".join(fix.models) if len(fix.models) <= 4
                else f"{len(fix.models)} models"
            )
            print(f"[{fix.event} {i+1}/{total_event}] {models_str}")

            fix.status = "in_progress"
            fix.match_id = (
                f"{fix.event}-{'-vs-'.join(fix.models[:2])}-{uuid.uuid4().hex[:6]}"
            )
            with self._manifest_lock:
                self._write_manifest()

            try:
                event_cfg = self.config.events[fix.event]
                if is_mp:
                    result = engine._run_multiplayer_match(
                        fix.event, event_cfg, fix.models, match_id=fix.match_id,
                    )
                else:
                    result = engine._run_match(
                        fix.event, event_cfg, fix.models[0], fix.models[1],
                        match_id=fix.match_id,
                    )

                fix.status = "complete"
                fix.scores = result.scores
                fix.player_models = result.player_models
                fix.fidelity = result.fidelity

                ranked = sorted(
                    result.scores.items(),
                    key=lambda x: x[1],
                    reverse=True,
                )
                lines = [f"  {result.player_models[pid]:20s} {sc:>6.1f}" for pid, sc in ranked]
                print(f"[{fix.event} {i+1}/{total_event}] DONE\n" + "\n".join(lines))

            except Exception as exc:
                fix.status = "error"
                fix.error = str(exc)
                print(f"[{fix.event} {i+1}/{total_event}] ERROR: {exc}")
                traceback.print_exc()

            with self._manifest_lock:
                self._write_manifest()

    # ── Fixture generation ───────────────────────────────────────

    def _generate_fixtures(self) -> list[Fixture]:
        """Build the flat list of all fixtures."""
        fixtures: list[Fixture] = []
        match_num = 0

        for event_name, event_cfg in self.config.events.items():
            is_mp = (
                event_name in _MULTIPLAYER_EVENTS
                and len(self.model_names) > 2
            )

            if is_mp:
                # Multiplayer: `rounds` fixtures, each with all models
                for r in range(1, event_cfg.rounds + 1):
                    match_num += 1
                    fid = f"{event_name}-round-{r}"
                    fixtures.append(Fixture(
                        fixture_id=fid,
                        event=event_name,
                        models=list(self.model_names),
                        match_number=match_num,
                    ))
            else:
                # 2-player: one fixture per pair
                for model_a, model_b in combinations(self.model_names, 2):
                    match_num += 1
                    fid = f"{event_name}-{model_a}-vs-{model_b}"
                    fixtures.append(Fixture(
                        fixture_id=fid,
                        event=event_name,
                        models=[model_a, model_b],
                        match_number=match_num,
                    ))

        return fixtures

    # ── Manifest persistence ─────────────────────────────────────

    def _load_manifest(self) -> None:
        """Load fixtures from existing manifest. Reset in_progress → pending."""
        with open(self.manifest_path) as f:
            data = json.load(f)

        self.fixtures = []
        for fd in data.get("fixtures", []):
            fix = Fixture(
                fixture_id=fd["fixture_id"],
                event=fd["event"],
                models=fd["models"],
                match_number=fd["match_number"],
                match_id=fd.get("match_id"),
                status=fd.get("status", "pending"),
                scores=fd.get("scores", {}),
                player_models=fd.get("player_models", {}),
                fidelity=fd.get("fidelity", {}),
                error=fd.get("error"),
            )
            # Reset interrupted fixtures
            if fix.status == "in_progress":
                fix.status = "pending"
                fix.match_id = None
            self.fixtures.append(fix)

        resumed = sum(1 for f in self.fixtures if f.status == "complete")
        print(f"Resumed from manifest: {resumed}/{len(self.fixtures)} complete")

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

    def _build_manifest(self) -> dict:
        """Build the full manifest dict with fixtures and standings."""
        fixtures_data = []
        for fix in self.fixtures:
            fixtures_data.append({
                "fixture_id": fix.fixture_id,
                "event": fix.event,
                "models": fix.models,
                "match_number": fix.match_number,
                "match_id": fix.match_id,
                "status": fix.status,
                "scores": fix.scores,
                "player_models": fix.player_models,
                "fidelity": fix.fidelity,
                "error": fix.error,
            })

        # Per-event standings
        event_standings = {}
        for event_name in self.config.events:
            is_mp = (
                event_name in _MULTIPLAYER_EVENTS
                and len(self.model_names) > 2
            )
            standings = compute_standings(
                self.fixtures, self.model_names, event=event_name,
                is_multiplayer=is_mp,
            )
            event_standings[event_name] = [
                {
                    "model": e.model,
                    "played": e.played,
                    "W": e.wins,
                    "D": e.draws,
                    "L": e.losses,
                    "points_for": e.points_for,
                    "points_against": e.points_against,
                    "league_points": e.league_points,
                }
                for e in standings
            ]

        total = len(self.fixtures)
        complete = sum(1 for f in self.fixtures if f.status == "complete")

        return {
            "tournament_name": self.config.name,
            "format": "league",
            "models": self.model_names,
            "events": list(self.config.events.keys()),
            "total_fixtures": total,
            "completed_fixtures": complete,
            "status": "complete" if complete == total else "in_progress",
            "fixtures": fixtures_data,
            "standings": event_standings,
        }

    # ── Display ──────────────────────────────────────────────────

    def print_standings(self) -> None:
        """Print formatted league tables to stdout."""
        for event_name in self.config.events:
            is_mp = (
                event_name in _MULTIPLAYER_EVENTS
                and len(self.model_names) > 2
            )
            standings = compute_standings(
                self.fixtures, self.model_names, event=event_name,
                is_multiplayer=is_mp,
            )

            print(f"\n{'='*60}")
            print(f"  {event_name.upper()} STANDINGS")
            print(f"{'='*60}")

            if is_mp:
                print(f"  {'Model':<25s} {'P':>3s} {'Pts':>6s}")
                print(f"  {'-'*25} {'-'*3} {'-'*6}")
                for e in standings:
                    print(f"  {e.model:<25s} {e.played:>3d} {e.league_points:>6.1f}")
            else:
                print(f"  {'Model':<25s} {'P':>3s} {'W':>3s} {'D':>3s} {'L':>3s} {'PF':>6s} {'PA':>6s} {'Pts':>6s}")
                print(f"  {'-'*25} {'-'*3} {'-'*3} {'-'*3} {'-'*3} {'-'*6} {'-'*6} {'-'*6}")
                for e in standings:
                    print(
                        f"  {e.model:<25s} {e.played:>3d} {e.wins:>3d} "
                        f"{e.draws:>3d} {e.losses:>3d} {e.points_for:>6.1f} "
                        f"{e.points_against:>6.1f} {e.league_points:>6.1f}"
                    )
        print()
