"""Roller Derby — concurrent N-player racing game engine.

All players race simultaneously. Each player progresses through a track of
obstacle segments by making decisions. Response latency is a game mechanic:
faster models get more turns per wall-clock second in concurrent mode.

Track segments (obstacles):
  - straight: choose "jog" (+1 safe) or "sprint" (+2, chance of stumble)
  - hurdle: answer a math question correctly (+2) or wrong (+0)
  - curve: choose "inside" (+2 risky) or "outside" (+1 safe)
  - jam: choose "block" (stay, trap next arrival) or "dodge" (+1 safe)

Finish bonuses: +3/+2/+1 for first three finishers (configurable).
DNF players scored by final position on track.

Unlike other events, Roller Derby is designed for concurrent execution:
each player's state is independent, allowing parallel prompt/response cycles.
"""

from __future__ import annotations

import random
import threading

from llmtourney.events.base import Event, ValidationResult

__all__ = ["RollerDerbyEvent"]

TRACK_LENGTH = 15
OBSTACLE_TYPES = ["straight", "hurdle", "curve", "jam"]

# Math question templates: (format_str, answer_fn)
_MATH_OPS = [
    ("+", lambda a, b: a + b),
    ("-", lambda a, b: a - b),
    ("*", lambda a, b: a * b),
]


def _generate_track(rng: random.Random) -> list[dict]:
    """Generate a track of TRACK_LENGTH obstacle segments."""
    track = []
    for i in range(TRACK_LENGTH):
        otype = rng.choice(OBSTACLE_TYPES)
        segment: dict = {"type": otype, "position": i}

        if otype == "straight":
            # Sprint success probability: 60-80%
            segment["sprint_success"] = rng.randint(60, 80) / 100.0

        elif otype == "hurdle":
            op_sym, op_fn = rng.choice(_MATH_OPS)
            if op_sym == "*":
                a, b = rng.randint(2, 12), rng.randint(2, 12)
            else:
                a, b = rng.randint(10, 99), rng.randint(10, 99)
                if op_sym == "-" and b > a:
                    a, b = b, a  # keep positive
            segment["question"] = f"What is {a} {op_sym} {b}?"
            segment["answer"] = op_fn(a, b)

        elif otype == "curve":
            segment["inside_success"] = rng.randint(50, 70) / 100.0

        elif otype == "jam":
            pass  # no extra params needed

        track.append(segment)
    return track


class RollerDerbyEvent(Event):
    """N-player concurrent racing engine.

    Parameters
    ----------
    races_per_match : int
        Number of races in a match.
    num_players : int
        Number of racers.
    finish_bonus : list[int]
        Bonus points for 1st/2nd/3rd finishers.
    race_timeout_s : float
        Max seconds per race before forced end.
    """

    def __init__(
        self,
        races_per_match: int = 3,
        num_players: int = 7,
        finish_bonus: list[int] | None = None,
        race_timeout_s: float = 300.0,
    ) -> None:
        import string
        self._races_per_match = races_per_match
        self._num_players = num_players
        self._finish_bonus = finish_bonus or [3, 2, 1]
        self._race_timeout_s = race_timeout_s

        self._player_ids = [
            f"player_{string.ascii_lowercase[i]}" for i in range(num_players)
        ]
        self._player_labels = {
            pid: string.ascii_uppercase[i]
            for i, pid in enumerate(self._player_ids)
        }
        self._action_schema = self._load_event_schema()

        # Match state
        self._rng: random.Random | None = None
        self._terminal: bool = False
        self._race_number: int = 0
        self._match_scores: dict[str, float] = {p: 0.0 for p in self._player_ids}
        self._highlight_turns: list[int] = []

        # Per-race state
        self._track: list[dict] = []
        self._positions: dict[str, int] = {}
        self._turn_counts: dict[str, int] = {}
        self._finish_order: list[str] = []
        self._eliminated: set[str] = set()
        self._blocked_spaces: dict[int, str] = {}  # space -> blocker_id
        self._stumbles: dict[str, int] = {}  # player -> stumble count
        self._turn_number: int = 0

        # Per-race stats (for telemetry)
        self._player_stats: dict[str, dict] = {}

        # Thread safety for concurrent access
        self._lock = threading.Lock()

        # Concurrent mode: track which player should go next
        # In concurrent mode, ALL players go simultaneously
        self._concurrent = True

    @property
    def display_name(self) -> str:
        return "Roller Derby"

    @property
    def race_timeout_s(self) -> float:
        return self._race_timeout_s

    @property
    def concurrent(self) -> bool:
        return self._concurrent

    def reset(self, seed: int) -> None:
        self._rng = random.Random(seed)
        self._race_number = 0
        self._terminal = False
        self._match_scores = {p: 0.0 for p in self._player_ids}
        self._highlight_turns = []
        self._turn_number = 0
        self._start_new_race()

    def _start_new_race(self) -> None:
        self._race_number += 1
        if self._race_number > self._races_per_match:
            self._terminal = True
            return

        self._track = _generate_track(self._rng)
        self._positions = {p: 0 for p in self._player_ids}
        self._turn_counts = {p: 0 for p in self._player_ids}
        self._finish_order = []
        self._eliminated = set()
        self._blocked_spaces = {}
        self._stumbles = {p: 0 for p in self._player_ids}
        self._player_stats = {
            p: {
                "sprints": 0, "jogs": 0, "stumbles": 0,
                "hurdles_correct": 0, "hurdles_wrong": 0,
                "blocks_set": 0, "blocks_hit": 0,
                "dodges": 0, "turns_taken": 0,
                "finish_position": None, "finish_time_turns": None,
            }
            for p in self._player_ids
        }

    def _finish_race(self) -> None:
        """Score the completed race and start the next."""
        # Players who didn't finish: rank by position (higher = better)
        remaining = [
            p for p in self._player_ids
            if p not in self._finish_order and p not in self._eliminated
        ]
        remaining.sort(key=lambda p: self._positions[p], reverse=True)
        final_order = list(self._finish_order) + remaining

        # Add eliminated players last
        elim = [p for p in self._player_ids if p in self._eliminated]
        final_order.extend(elim)

        # Rank points: N-1 for 1st, N-2 for 2nd, ..., 0 for last
        for i, pid in enumerate(final_order):
            rank_pts = float(self._num_players - 1 - i)
            self._match_scores[pid] += rank_pts
            self._player_stats[pid]["finish_position"] = i + 1

        # Finish bonuses for top finishers
        for i, bonus in enumerate(self._finish_bonus):
            if i < len(self._finish_order):
                pid = self._finish_order[i]
                self._match_scores[pid] += float(bonus)

        self._start_new_race()

    # ------------------------------------------------------------------
    # Player state (thread-safe reads)
    # ------------------------------------------------------------------

    def player_finished(self, player_id: str) -> bool:
        with self._lock:
            return (
                player_id in self._finish_order
                or player_id in self._eliminated
            )

    def race_over(self) -> bool:
        """Check if the current race is complete."""
        with self._lock:
            active = [
                p for p in self._player_ids
                if p not in self._finish_order and p not in self._eliminated
            ]
            return len(active) == 0

    def get_player_obstacle(self, player_id: str) -> dict:
        with self._lock:
            pos = self._positions[player_id]
            if pos >= TRACK_LENGTH:
                return {"type": "finish", "position": pos}
            return dict(self._track[pos])

    # ------------------------------------------------------------------
    # Event ABC implementation
    # ------------------------------------------------------------------

    def current_player(self) -> str:
        # In concurrent mode, this cycles through active players.
        # The tournament engine's concurrent runner doesn't use this.
        with self._lock:
            active = [
                p for p in self._player_ids
                if p not in self._finish_order and p not in self._eliminated
            ]
            if not active:
                return self._player_ids[0]
            # Round-robin by turn count
            return min(active, key=lambda p: self._turn_counts[p])

    def get_prompt(self, player_id: str) -> str:
        with self._lock:
            return self._build_prompt(player_id)

    def _build_prompt(self, player_id: str) -> str:
        """Build prompt for a player. Must hold self._lock."""
        label = self._player_labels[player_id]
        pos = self._positions[player_id]

        lines = [
            f"ROLLER DERBY RACE {self._race_number}/{self._races_per_match}",
            f"You are Racer {label}. Track length: {TRACK_LENGTH}. Your position: {pos}/{TRACK_LENGTH}.",
            "",
            "STANDINGS:",
        ]

        # Show all positions
        for pid in self._player_ids:
            plabel = self._player_labels[pid]
            ppos = self._positions[pid]
            status = ""
            if pid in self._finish_order:
                rank = self._finish_order.index(pid) + 1
                status = f" [FINISHED #{rank}]"
            elif pid in self._eliminated:
                status = " [DNF]"
            marker = " <-- YOU" if pid == player_id else ""
            lines.append(f"  Racer {plabel}: position {ppos}{status}{marker}")

        lines.append("")

        if pos >= TRACK_LENGTH:
            lines.append("You have finished the race!")
            return "\n".join(lines)

        segment = self._track[pos]
        otype = segment["type"]

        lines.append(f"OBSTACLE at position {pos}: {otype.upper()}")
        lines.append("")

        if otype == "straight":
            pct = int(segment["sprint_success"] * 100)
            lines.extend([
                "Straightaway ahead. Choose your pace:",
                f'  "jog"    — advance 1 space (guaranteed)',
                f'  "sprint" — advance 2 spaces ({pct}% success, otherwise stumble: +0)',
                "",
                'Respond with ONLY a JSON object:',
                '  {"action": "jog", "reasoning": "..."}',
                '  {"action": "sprint", "reasoning": "..."}',
            ])

        elif otype == "hurdle":
            lines.extend([
                f'Hurdle! Answer correctly to clear it:',
                f'  {segment["question"]}',
                "",
                "Correct answer: advance 2 spaces.",
                "Wrong answer: stumble, advance 0.",
                "",
                'Respond with ONLY a JSON object:',
                '  {"action": "answer", "value": <your_number>, "reasoning": "..."}',
            ])

        elif otype == "curve":
            pct = int(segment["inside_success"] * 100)
            lines.extend([
                "Sharp curve ahead. Choose your line:",
                f'  "inside"  — cut the corner, advance 2 ({pct}% success, otherwise stumble: +0)',
                f'  "outside" — take it wide, advance 1 (guaranteed)',
                "",
                'Respond with ONLY a JSON object:',
                '  {"action": "inside", "reasoning": "..."}',
                '  {"action": "outside", "reasoning": "..."}',
            ])

        elif otype == "jam":
            # Check if there's a block on this space
            blocker = self._blocked_spaces.get(pos)
            if blocker and blocker != player_id:
                lines.extend([
                    f"JAM ZONE! Racer {self._player_labels[blocker]} is blocking here!",
                    '  "dodge"  — slip past, advance 1 space',
                    '  "push"   — shove through, advance 2 but 50% chance of falling (+0)',
                    "",
                    'Respond with ONLY a JSON object:',
                    '  {"action": "dodge", "reasoning": "..."}',
                    '  {"action": "push", "reasoning": "..."}',
                ])
            else:
                lines.extend([
                    "Jam zone. Choose your strategy:",
                    '  "block" — hold position (advance 0), set a trap for the next racer',
                    '  "dodge" — skate through, advance 1 space',
                    "",
                    'Respond with ONLY a JSON object:',
                    '  {"action": "block", "reasoning": "..."}',
                    '  {"action": "dodge", "reasoning": "..."}',
                ])

        lines.extend([
            "",
            "SPEED MATTERS. Faster responses = more turns = more distance.",
            "Keep reasoning brief.",
        ])

        return "\n".join(lines)

    def get_retry_prompt(self, player_id: str, error_reason: str) -> str:
        prompt = self.get_prompt(player_id)
        return (
            f"Your previous response was invalid: {error_reason}\n\n"
            f"{prompt}\n\n"
            "IMPORTANT: Respond with ONLY a JSON object. No markdown, no explanation."
        )

    def validate_action(self, player_id: str, action: dict) -> ValidationResult:
        with self._lock:
            return self._validate(player_id, action)

    def _validate(self, player_id: str, action: dict) -> ValidationResult:
        """Validate action. Must hold self._lock."""
        if player_id in self._finish_order or player_id in self._eliminated:
            return ValidationResult(False, "Player has already finished or been eliminated")

        pos = self._positions[player_id]
        if pos >= TRACK_LENGTH:
            return ValidationResult(False, "Already at finish line")

        segment = self._track[pos]
        otype = segment["type"]
        act = action.get("action", "").lower().strip()

        if otype == "straight":
            if act not in ("jog", "sprint"):
                return ValidationResult(False, f"Invalid action '{act}' for straight. Choose 'jog' or 'sprint'.")

        elif otype == "hurdle":
            if act != "answer":
                return ValidationResult(False, f"Invalid action '{act}' for hurdle. Use 'answer' with a 'value'.")
            if "value" not in action:
                return ValidationResult(False, "Hurdle requires 'value' field with your numeric answer.")

        elif otype == "curve":
            if act not in ("inside", "outside"):
                return ValidationResult(False, f"Invalid action '{act}' for curve. Choose 'inside' or 'outside'.")

        elif otype == "jam":
            blocker = self._blocked_spaces.get(pos)
            if blocker and blocker != player_id:
                if act not in ("dodge", "push"):
                    return ValidationResult(False, f"Invalid action '{act}' for blocked jam. Choose 'dodge' or 'push'.")
            else:
                if act not in ("block", "dodge"):
                    return ValidationResult(False, f"Invalid action '{act}' for jam. Choose 'block' or 'dodge'.")

        return ValidationResult(True)

    def apply_action(self, player_id: str, action: dict) -> None:
        with self._lock:
            self._apply(player_id, action)

    def _apply(self, player_id: str, action: dict) -> None:
        """Apply action. Must hold self._lock."""
        pos = self._positions[player_id]
        segment = self._track[pos]
        otype = segment["type"]
        act = action.get("action", "").lower().strip()
        advance = 0
        stats = self._player_stats[player_id]

        # Use per-player sub-RNG for deterministic but independent outcomes
        player_rng = random.Random(
            hash((self._rng.getstate()[1][0], player_id, self._turn_counts[player_id]))
        )

        if otype == "straight":
            if act == "jog":
                advance = 1
                stats["jogs"] += 1
            elif act == "sprint":
                stats["sprints"] += 1
                if player_rng.random() < segment["sprint_success"]:
                    advance = 2
                else:
                    stats["stumbles"] += 1
                    self._stumbles[player_id] += 1

        elif otype == "hurdle":
            given = action.get("value")
            try:
                given = int(given)
            except (TypeError, ValueError):
                given = None
            if given == segment["answer"]:
                advance = 2
                stats["hurdles_correct"] += 1
            else:
                stats["hurdles_wrong"] += 1
                stats["stumbles"] += 1
                self._stumbles[player_id] += 1

        elif otype == "curve":
            if act == "outside":
                advance = 1
            elif act == "inside":
                if player_rng.random() < segment["inside_success"]:
                    advance = 2
                else:
                    stats["stumbles"] += 1
                    self._stumbles[player_id] += 1

        elif otype == "jam":
            blocker = self._blocked_spaces.get(pos)
            if blocker and blocker != player_id:
                # Hitting a block
                stats["blocks_hit"] += 1
                if act == "dodge":
                    advance = 1
                    stats["dodges"] += 1
                elif act == "push":
                    if player_rng.random() < 0.5:
                        advance = 2
                    else:
                        stats["stumbles"] += 1
                        self._stumbles[player_id] += 1
                # Clear the block after it's been hit
                if pos in self._blocked_spaces and self._blocked_spaces[pos] == blocker:
                    del self._blocked_spaces[pos]
            else:
                if act == "block":
                    advance = 0
                    self._blocked_spaces[pos] = player_id
                    stats["blocks_set"] += 1
                elif act == "dodge":
                    advance = 1
                    stats["dodges"] += 1

        self._positions[player_id] = pos + advance
        self._turn_counts[player_id] += 1
        stats["turns_taken"] += 1
        self._turn_number += 1

        # Check for finish
        if self._positions[player_id] >= TRACK_LENGTH:
            self._positions[player_id] = TRACK_LENGTH
            if player_id not in self._finish_order:
                self._finish_order.append(player_id)
                stats["finish_position"] = len(self._finish_order)
                stats["finish_time_turns"] = stats["turns_taken"]
                # Highlight: crossing the finish line
                self._highlight_turns.append(self._turn_number)

        # Check if race is over (all finished or eliminated)
        active = [
            p for p in self._player_ids
            if p not in self._finish_order and p not in self._eliminated
        ]
        if not active:
            self._finish_race()

    def forfeit_turn(self, player_id: str) -> None:
        """On violation/timeout, player doesn't advance."""
        with self._lock:
            self._turn_counts[player_id] += 1
            self._player_stats[player_id]["turns_taken"] += 1
            self._turn_number += 1

    def eliminate_player(self, player_id: str) -> None:
        """Remove player from the race (stuck-loop)."""
        with self._lock:
            self._eliminated.add(player_id)
            active = [
                p for p in self._player_ids
                if p not in self._finish_order and p not in self._eliminated
            ]
            if not active:
                self._finish_race()

    def force_forfeit_match(self, player_id: str) -> None:
        """Force end of match."""
        with self._lock:
            self._terminal = True

    def award_forfeit_wins(self, forfeiting_player_id: str) -> None:
        """Award remaining races to non-forfeiting players."""
        with self._lock:
            remaining = self._races_per_match - self._race_number + 1
            pts = float(self._num_players - 1)
            for pid in self._player_ids:
                if pid != forfeiting_player_id:
                    self._match_scores[pid] += pts * remaining
            self._terminal = True

    def get_scores(self) -> dict[str, float]:
        with self._lock:
            return dict(self._match_scores)

    def get_state_snapshot(self) -> dict:
        with self._lock:
            return {
                "race_number": self._race_number,
                "races_per_match": self._races_per_match,
                "track": [dict(s) for s in self._track],
                "positions": dict(self._positions),
                "turn_counts": dict(self._turn_counts),
                "finish_order": list(self._finish_order),
                "eliminated": list(self._eliminated),
                "blocked_spaces": dict(self._blocked_spaces),
                "stumbles": dict(self._stumbles),
                "terminal": self._terminal,
                "match_scores": dict(self._match_scores),
                "player_stats": {p: dict(self._player_stats[p]) for p in self._player_ids},
                "player_labels": dict(self._player_labels),
                "track_length": TRACK_LENGTH,
            }

    def get_highlight_hands(self) -> list[int]:
        with self._lock:
            return list(self._highlight_turns)
