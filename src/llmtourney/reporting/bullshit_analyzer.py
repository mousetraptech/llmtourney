"""Bullshit match analyzer — extracts behavioral metrics from telemetry.

Produces a BullshitReport with per-model stats, suboptimal play detection,
card trajectories, rolling rates, and cost data. Game-agnostic fields
(tokens, latency) are computed by the base analyzer.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from .reader import MatchData, Turn


@dataclass
class ModelStats:
    """Aggregated stats for one model in a Bullshit match."""

    model: str
    player_id: str
    finish_position: int
    total_plays: int
    truth_count: int
    lie_count: int
    bluff_rate: float
    times_caught: int
    bs_calls: int
    correct_calls: int
    call_accuracy: float
    total_turns: int
    avg_output_tokens: float
    avg_latency_ms: float
    bluff_with_truth_count: int
    truthful_opportunity_count: int


@dataclass
class SuboptimalPlay:
    """A single instance of bluffing while holding the correct rank."""

    turn_number: int
    model: str
    player_id: str
    target_rank: str
    matching_held: list[str]
    cards_played: list[str]
    unused_matching: list[str]
    reasoning: str
    failure_mode: str  # "hallucination" or "strategic_error"


@dataclass
class BullshitReport:
    """Complete analysis of a Bullshit match."""

    match_id: str
    num_players: int
    total_turns: int
    total_plays: int
    total_calls: int
    total_passes: int
    finish_order: list[str]  # model names in finish order

    model_stats: dict[str, ModelStats]  # model -> stats
    suboptimal_plays: list[SuboptimalPlay]

    # Time series data
    card_trajectories: dict[str, list[int]]  # model -> card counts per play
    trajectory_indices: list[int]  # play numbers for x-axis
    bluff_timeline: dict[str, list[tuple[int, float]]]  # model -> (play#, rolling%)
    call_timeline: dict[str, list[tuple[int, float]]]  # model -> (call#, rolling%)

    # Challenge behavior
    challenge_counts: dict[str, dict[str, int]]  # model -> {calls, passes}

    # Cost/efficiency
    token_totals: dict[str, dict[str, int]]  # model -> {input, output, count}


def _parse_hand_from_prompt(prompt: str) -> dict[int, str]:
    """Extract card index -> card string mapping from prompt text."""
    hand_cards: dict[int, str] = {}
    for line in prompt.split("\n"):
        if "Your hand" in line and "cards):" in line:
            card_part = line.split("):")[1].strip()
            for token in card_part.split(","):
                token = token.strip()
                if token.startswith("["):
                    try:
                        idx = int(token.split("]")[0][1:])
                        card = token.split("]")[1].strip().rstrip(",")
                        hand_cards[idx] = card
                    except (ValueError, IndexError):
                        continue
    return hand_cards


def _parse_target_rank(prompt: str) -> str | None:
    """Extract target rank from prompt text."""
    for line in prompt.split("\n"):
        if "TARGET RANK THIS TURN:" in line:
            return line.split(":")[1].strip().split(" ")[0]
    return None


def _card_rank(card: str) -> str:
    """Extract rank from card string (e.g., '10♥' -> '10', 'A♠' -> 'A')."""
    return card[:-1]


def analyze(match: MatchData) -> BullshitReport:
    """Run full analysis on a Bullshit match."""
    assert match.game_type == "bullshit", f"Expected bullshit, got {match.game_type}"

    valid = match.valid_turns
    plays = match.turns_by_action("play")
    calls = match.turns_by_action("call")
    passes = match.turns_by_action("pass")

    # --- Finish order ---
    last_snap = match.last_snapshot
    finish_order_pids = last_snap.get("finish_order", [])
    finish_order = [match.models.get(pid, pid) for pid in finish_order_pids]

    # --- Per-model stats from final snapshot ---
    model_stats: dict[str, ModelStats] = {}
    player_stats_raw = last_snap.get("player_stats", {})

    # Token/latency aggregation
    token_totals: defaultdict[str, dict[str, int]] = defaultdict(
        lambda: {"input": 0, "output": 0, "count": 0, "latency_total": 0}
    )
    for t in valid:
        m = match.models[t.player_id]
        token_totals[m]["input"] += t.input_tokens
        token_totals[m]["output"] += t.output_tokens
        token_totals[m]["count"] += 1
        token_totals[m]["latency_total"] += int(t.latency_ms)

    for pid in sorted(match.models.keys()):
        model = match.models[pid]
        stats = player_stats_raw.get(pid, {})
        total_plays = stats.get("lie_count", 0) + stats.get("truth_count", 0)
        bluff_rate = (
            stats.get("lie_count", 0) / total_plays * 100 if total_plays else 0
        )
        bs_calls = stats.get("times_called_bs", 0)
        correct = stats.get("correct_calls", 0)
        call_acc = correct / bs_calls * 100 if bs_calls else 0

        tt = token_totals[model]
        pos = finish_order_pids.index(pid) + 1 if pid in finish_order_pids else 0

        model_stats[model] = ModelStats(
            model=model,
            player_id=pid,
            finish_position=pos,
            total_plays=total_plays,
            truth_count=stats.get("truth_count", 0),
            lie_count=stats.get("lie_count", 0),
            bluff_rate=round(bluff_rate, 1),
            times_caught=stats.get("times_caught", 0),
            bs_calls=bs_calls,
            correct_calls=correct,
            call_accuracy=round(call_acc, 1),
            total_turns=tt["count"],
            avg_output_tokens=round(tt["output"] / tt["count"], 1) if tt["count"] else 0,
            avg_latency_ms=round(tt["latency_total"] / tt["count"], 0) if tt["count"] else 0,
            bluff_with_truth_count=0,  # filled below
            truthful_opportunity_count=0,  # filled below
        )

    # --- Suboptimal play detection ---
    suboptimal: list[SuboptimalPlay] = []
    bwt_counts: defaultdict[str, int] = defaultdict(int)
    opp_counts: defaultdict[str, int] = defaultdict(int)

    for t in plays:
        target_rank = _parse_target_rank(t.prompt)
        if not target_rank:
            continue

        hand_cards = _parse_hand_from_prompt(t.prompt)
        if not hand_cards:
            continue

        matching = [i for i, c in hand_cards.items() if _card_rank(c) == target_rank]
        played = t.action.get("cards", []) if t.action else []
        model = match.models[t.player_id]

        if matching:
            opp_counts[model] += 1
            non_matching_played = [i for i in played if i not in matching]
            if non_matching_played:
                bwt_counts[model] += 1

                matching_cards = [hand_cards[i] for i in matching]
                played_cards = [hand_cards[i] for i in played if i in hand_cards]
                unused = [hand_cards[i] for i in matching if i not in played]

                # Detect failure mode
                reasoning = (t.action.get("reasoning", "") if t.action else "") or ""
                has_no_claim = any(
                    phrase in reasoning.lower()
                    for phrase in [
                        "i have no",
                        "i don't have",
                        "no actual",
                        "i do not have",
                        "don't have any",
                    ]
                )
                failure_mode = "hallucination" if has_no_claim else "strategic_error"

                suboptimal.append(
                    SuboptimalPlay(
                        turn_number=t.turn_number,
                        model=model,
                        player_id=t.player_id,
                        target_rank=target_rank,
                        matching_held=matching_cards,
                        cards_played=played_cards,
                        unused_matching=unused,
                        reasoning=reasoning[:300],
                        failure_mode=failure_mode,
                    )
                )

    # Update model stats with bluff-with-truth counts
    for model in model_stats:
        model_stats[model].bluff_with_truth_count = bwt_counts.get(model, 0)
        model_stats[model].truthful_opportunity_count = opp_counts.get(model, 0)

    # --- Card count trajectories ---
    card_trajectories: defaultdict[str, list[int]] = defaultdict(list)
    trajectory_indices: list[int] = []
    play_idx = 0
    for t in plays:
        snap = t.snapshot
        if "card_counts" in snap:
            play_idx += 1
            trajectory_indices.append(play_idx)
            for pid in sorted(match.models.keys()):
                model = match.models[pid]
                card_trajectories[model].append(snap["card_counts"].get(pid, 0))

    # --- Rolling bluff rate ---
    bluff_timeline: defaultdict[str, list[tuple[int, float]]] = defaultdict(list)
    bluff_history: defaultdict[str, list[bool]] = defaultdict(list)
    bluff_counter: defaultdict[str, int] = defaultdict(int)

    for t in plays:
        model = match.models[t.player_id]
        hist = t.snapshot.get("history", [])
        if hist:
            last = hist[-1]
            was_bluff = not last.get("was_truthful", True)
            bluff_history[model].append(was_bluff)
            bluff_counter[model] += 1
            window = bluff_history[model][-10:]
            rate = sum(window) / len(window) * 100
            bluff_timeline[model].append((bluff_counter[model], round(rate, 1)))

    # --- Rolling call accuracy ---
    call_timeline: defaultdict[str, list[tuple[int, float]]] = defaultdict(list)
    call_history: defaultdict[str, list[bool]] = defaultdict(list)
    call_counter: defaultdict[str, int] = defaultdict(int)

    for t in calls:
        model = match.models[t.player_id]
        hist = t.snapshot.get("history", [])
        if hist:
            last = hist[-1]
            was_correct = last.get("was_bluff")
            if was_correct is not None:
                call_history[model].append(bool(was_correct))
                call_counter[model] += 1
                window = call_history[model][-10:]
                rate = sum(window) / len(window) * 100
                call_timeline[model].append((call_counter[model], round(rate, 1)))

    # --- Challenge counts ---
    challenge_counts: defaultdict[str, dict[str, int]] = defaultdict(
        lambda: {"calls": 0, "passes": 0}
    )
    for t in calls:
        challenge_counts[match.models[t.player_id]]["calls"] += 1
    for t in passes:
        challenge_counts[match.models[t.player_id]]["passes"] += 1

    return BullshitReport(
        match_id=match.match_id,
        num_players=match.num_players,
        total_turns=len(valid),
        total_plays=len(plays),
        total_calls=len(calls),
        total_passes=len(passes),
        finish_order=finish_order,
        model_stats=model_stats,
        suboptimal_plays=suboptimal,
        card_trajectories=dict(card_trajectories),
        trajectory_indices=trajectory_indices,
        bluff_timeline=dict(bluff_timeline),
        call_timeline=dict(call_timeline),
        challenge_counts=dict(challenge_counts),
        token_totals={
            m: {"input": v["input"], "output": v["output"], "count": v["count"]}
            for m, v in token_totals.items()
        },
    )
