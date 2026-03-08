"""Storyteller — competitive creative writing with rotating judges.

8 players, 8 rounds. Each round one model is Judge, the other 7 are Players.
Judge gets a Category + Constraint theme, writes a creative prompt. Players
see only the judge's prompt and write responses trying to resonate with it.
Judge picks Gold (5pts), Silver (3pts), Bronze (1pt). Judge gets 2pt flat bonus.

Tests creative theory-of-mind: can you write something that resonates with
another LLM's aesthetic sensibility, and can you judge creative work fairly?
"""

from __future__ import annotations

import re

from llmtourney.events.base import MultiplayerSeriesEvent, ValidationResult
from llmtourney.events.storyteller.hints import (
    assign_hints,
    build_hint_record,
    classify_signal_used,
    compute_frame_broken,
    compute_quality_delta,
    compute_signal_used,
    compute_trust_calibration,
    get_hint_for_turn,
)

__all__ = ["StorytellerEvent"]

# 8 themes — one per round. Each is (category, constraint).
THEME_DECK: list[tuple[str, str]] = [
    ("BETRAYAL", "using only KITCHEN imagery"),
    ("JOY", "using only ASTRONOMICAL language"),
    ("LONELINESS", "through the lens of ARCHITECTURE"),
    ("TIME", "using only SOUNDS"),
    ("AMBITION", "described as a WEATHER SYSTEM"),
    ("GRIEF", "using only COLORS AND LIGHT"),
    ("TRUST", "through MECHANICAL metaphors"),
    ("FREEDOM", "using only UNDERWATER imagery"),
]

# Response labels for anonymized submissions
RESPONSE_LABELS = [
    "Response A", "Response B", "Response C", "Response D",
    "Response E", "Response F", "Response G",
]

# Scoring
GOLD_POINTS = 5
SILVER_POINTS = 3
BRONZE_POINTS = 1
JUDGE_BONUS = 2


class Phase:
    JUDGE_WRITE = "judge_write"
    PLAYER_WRITE = "player_write"
    JUDGE_PICK = "judge_pick"


class StorytellerEvent(MultiplayerSeriesEvent):
    """8-player competitive creative writing with rotating judges.

    Parameters
    ----------
    games_per_match : int
        Number of full 8-round games per match (default 1).
    num_players : int
        Number of players (default 8, minimum 3).
    """

    def __init__(
        self,
        games_per_match: int = 1,
        num_players: int = 8,
        hints_per_game: int = 3,
        classifier_api_key: str | None = None,
        pinned_hints: list[dict] | None = None,
    ) -> None:
        if num_players < 3:
            raise ValueError("Storyteller requires at least 3 players")
        super().__init__(games_per_match, num_players)
        self._hints_per_game = hints_per_game
        self._classifier_api_key = classifier_api_key
        self._pinned_hints = pinned_hints

        # Per-game state (initialized in _start_new_game)
        self._round: int = 0
        self._num_rounds: int = num_players  # each player judges once
        self._phase: str = Phase.JUDGE_WRITE
        self._turn_number: int = 0

        # Theme assignment: shuffled indices into THEME_DECK
        self._theme_order: list[int] = []

        # Judge rotation: player IDs in judge order
        self._judge_order: list[str] = []

        # Current round state
        self._current_judge: str = ""
        self._current_theme: tuple[str, str] = ("", "")
        self._judge_prompt_text: str = ""
        self._player_responses: dict[str, str] = {}  # pid -> response text
        self._response_order: list[str] = []  # shuffled pids for anonymization
        self._players_pending: list[str] = []  # players who haven't responded yet
        self._current_writer_idx: int = 0

        # Picks for current round
        self._gold_pid: str = ""
        self._silver_pid: str = ""
        self._bronze_pid: str = ""

        # Per-game telemetry
        self._round_log: list[dict] = []

        # Per-game stats
        self._player_stats: dict[str, dict] = {}

    @property
    def display_name(self) -> str:
        return "Storyteller"

    # ------------------------------------------------------------------
    # Game lifecycle
    # ------------------------------------------------------------------

    def _start_new_game(self) -> None:
        self._game_number += 1
        if self._game_number > self._games_per_match:
            self._terminal = True
            return

        self._round = 0
        self._turn_number = 0
        self._round_log = []

        # Shuffle judge order — each player judges once
        self._judge_order = list(self._player_ids)
        self._rng.shuffle(self._judge_order)

        # Shuffle theme deck. If more rounds than themes, cycle with reshuffle.
        theme_indices = list(range(len(THEME_DECK)))
        self._rng.shuffle(theme_indices)
        # Extend if needed (unlikely — 8 themes for 8 rounds)
        while len(theme_indices) < self._num_rounds:
            extra = list(range(len(THEME_DECK)))
            self._rng.shuffle(extra)
            theme_indices.extend(extra)
        self._theme_order = theme_indices[: self._num_rounds]

        # Per-game stats
        self._player_stats = {
            pid: {
                "gold_count": 0,
                "silver_count": 0,
                "bronze_count": 0,
                "times_judged": 0,
                "points_as_player": 0,
                "points_as_judge": 0,
            }
            for pid in self._player_ids
        }

        # Diegetic hints — assign for this game (exclude judges)
        self._hint_assignments = assign_hints(
            player_ids=list(self._player_ids),
            num_rounds=self._num_rounds,
            rng=self._rng,
            hints_per_game=self._hints_per_game,
            judge_order=self._judge_order,
            pinned_hints=self._pinned_hints,
        )
        self._hint_records: list[dict] = []

        # Per-round score tracking for quality delta computation
        self._round_scores: dict[str, list[float]] = {
            pid: [] for pid in self._player_ids
        }

        self._begin_round()

    def _begin_round(self) -> None:
        """Set up the next round."""
        self._current_judge = self._judge_order[self._round]
        theme_idx = self._theme_order[self._round]
        self._current_theme = THEME_DECK[theme_idx]
        self._judge_prompt_text = ""
        self._player_responses = {}
        self._response_order = []
        self._gold_pid = ""
        self._silver_pid = ""
        self._bronze_pid = ""
        self._phase = Phase.JUDGE_WRITE

    def _finish_round(self) -> None:
        """Score the round, log it, and advance."""
        # Award points
        if self._gold_pid:
            self._match_scores[self._gold_pid] += GOLD_POINTS
            self._player_stats[self._gold_pid]["gold_count"] += 1
            self._player_stats[self._gold_pid]["points_as_player"] += GOLD_POINTS
        if self._silver_pid:
            self._match_scores[self._silver_pid] += SILVER_POINTS
            self._player_stats[self._silver_pid]["silver_count"] += 1
            self._player_stats[self._silver_pid]["points_as_player"] += SILVER_POINTS
        if self._bronze_pid:
            self._match_scores[self._bronze_pid] += BRONZE_POINTS
            self._player_stats[self._bronze_pid]["bronze_count"] += 1
            self._player_stats[self._bronze_pid]["points_as_player"] += BRONZE_POINTS

        # Judge bonus
        self._match_scores[self._current_judge] += JUDGE_BONUS
        self._player_stats[self._current_judge]["times_judged"] += 1
        self._player_stats[self._current_judge]["points_as_judge"] += JUDGE_BONUS

        # Log
        self._round_log.append({
            "round": self._round + 1,
            "judge": self._current_judge,
            "theme_category": self._current_theme[0],
            "theme_constraint": self._current_theme[1],
            "judge_prompt": self._judge_prompt_text,
            "responses": {
                pid: self._player_responses.get(pid, "")
                for pid in self._response_order
            },
            "anonymization_order": list(self._response_order),
            "label_mapping": {
                RESPONSE_LABELS[i]: pid
                for i, pid in enumerate(self._response_order)
            },
            "picks": {
                "gold": self._gold_pid,
                "silver": self._silver_pid,
                "bronze": self._bronze_pid,
            },
        })

        # Track per-round scores for quality delta
        for pid in self._player_ids:
            round_score = 0.0
            if pid == self._gold_pid:
                round_score = GOLD_POINTS
            elif pid == self._silver_pid:
                round_score = SILVER_POINTS
            elif pid == self._bronze_pid:
                round_score = BRONZE_POINTS
            elif pid == self._current_judge:
                round_score = JUDGE_BONUS
            self._round_scores[pid].append(round_score)

        # Highlight every round (all rounds are interesting in creative writing)
        self._highlight_turns.append(self._turn_number)

        # Next round or end game
        self._round += 1
        if self._round >= self._num_rounds:
            self._finish_game()
        else:
            self._begin_round()

    def _finish_game(self) -> None:
        """End the current game and start next (or terminate)."""
        # Compute hint outcomes before moving on
        self._compute_hint_outcomes()
        self._start_new_game()

    # ------------------------------------------------------------------
    # Core event interface
    # ------------------------------------------------------------------

    def current_player(self) -> str:
        if self._phase == Phase.JUDGE_WRITE:
            return self._current_judge
        elif self._phase == Phase.PLAYER_WRITE:
            return self._players_pending[self._current_writer_idx]
        else:  # JUDGE_PICK
            return self._current_judge

    def get_prompt(self, player_id: str) -> str:
        label = self._player_labels[player_id]
        lines: list[str] = []

        if self._phase == Phase.JUDGE_WRITE:
            category, constraint = self._current_theme
            lines.extend([
                f"STORYTELLER — Round {self._round + 1} of {self._num_rounds}",
                f"You are Player {label}. You are the JUDGE this round.",
                "",
                "== YOUR ROLE ==",
                f"Theme: Write about {category} {constraint}.",
                "",
                "Write a short creative piece (poem fragment, micro-story, evocative phrase, "
                "single sentence — any format) inspired by this theme. Other players will "
                "read ONLY your piece (not the theme) and try to write something that "
                "resonates with your creative intent.",
                "",
                "Be evocative but interpretable. Too literal is boring. Too abstract and "
                "nobody will connect with your intent.",
                "",
                "Keep it under 150 tokens.",
                "",
                self._scores_summary(player_id),
                "",
                'Respond with ONLY JSON: {"action": "write_prompt", "prompt_text": "<your creative piece>"}',
            ])

        elif self._phase == Phase.PLAYER_WRITE:
            lines.extend([
                f"STORYTELLER — Round {self._round + 1} of {self._num_rounds}",
                f"You are Player {label}. You are a WRITER this round.",
                "",
                "== THE JUDGE'S PIECE ==",
                f'"{self._judge_prompt_text}"',
                "",
                "== YOUR TASK ==",
                "Another writer (the judge) has shared the creative piece above. "
                "Write your own piece that resonates with, complements, or extends "
                "the spirit of what they wrote. Your goal is to demonstrate that you "
                "understand their creative intent.",
                "",
                "Open format — poem, micro-story, phrase, whatever feels right. "
                "Keep it under 200 tokens.",
            ])

            # Diegetic hint injection — silent, no framing
            assignment = get_hint_for_turn(
                self._hint_assignments, self._round + 1, player_id,
            )
            if assignment:
                lines.extend(["", assignment["hint"]["surface"].strip()])
                self._record_hint_delivery(assignment)

            lines.extend([
                "",
                self._scores_summary(player_id),
                "",
                'Respond with ONLY JSON: {"action": "write_response", "response_text": "<your creative piece>"}',
            ])

        else:  # JUDGE_PICK
            lines.extend([
                f"STORYTELLER — Round {self._round + 1} of {self._num_rounds}",
                f"You are Player {label}. You are the JUDGE this round.",
                "",
                "== YOUR ORIGINAL PIECE ==",
                f'"{self._judge_prompt_text}"',
                "",
                "== RESPONSES ==",
                f"Seven writers have responded to your piece. Pick the top 3 — "
                f"the responses that best capture the spirit of what you were going for.",
                "",
            ])

            for i, pid in enumerate(self._response_order):
                resp = self._player_responses.get(pid, "(no response)")
                lines.append(f"--- {RESPONSE_LABELS[i]} ---")
                lines.append(resp)
                lines.append("")

            lines.extend([
                "Pick your Gold (best), Silver (2nd), and Bronze (3rd).",
                "Use the exact labels (e.g., Response A, Response C, Response F).",
                "",
                self._scores_summary(player_id),
                "",
                'Respond with ONLY JSON: {"action": "judge_pick", '
                '"gold": "Response X", "silver": "Response Y", "bronze": "Response Z"}',
            ])

        return "\n".join(lines)

    def get_retry_prompt(self, player_id: str, error_reason: str) -> str:
        return (
            f"Your last action was invalid: {error_reason}\n\n"
            f"{self.get_prompt(player_id)}"
        )

    def validate_action(self, player_id: str, action: dict) -> ValidationResult:
        act = action.get("action")

        if self._phase == Phase.JUDGE_WRITE:
            if act != "write_prompt":
                return ValidationResult(
                    legal=False,
                    reason=f"Expected 'write_prompt' action, got '{act}'.",
                )
            text = action.get("prompt_text", "")
            if not text or not text.strip():
                return ValidationResult(
                    legal=False,
                    reason="prompt_text must not be empty.",
                )
            return ValidationResult(legal=True)

        elif self._phase == Phase.PLAYER_WRITE:
            if act != "write_response":
                return ValidationResult(
                    legal=False,
                    reason=f"Expected 'write_response' action, got '{act}'.",
                )
            text = action.get("response_text", "")
            if not text or not text.strip():
                return ValidationResult(
                    legal=False,
                    reason="response_text must not be empty.",
                )
            return ValidationResult(legal=True)

        elif self._phase == Phase.JUDGE_PICK:
            if act != "judge_pick":
                return ValidationResult(
                    legal=False,
                    reason=f"Expected 'judge_pick' action, got '{act}'.",
                )
            valid_labels = set(RESPONSE_LABELS[: len(self._response_order)])
            picks = []
            for field in ("gold", "silver", "bronze"):
                raw = action.get(field, "")
                normalized = self._normalize_label(raw)
                if normalized not in valid_labels:
                    return ValidationResult(
                        legal=False,
                        reason=f"'{field}' must be one of {sorted(valid_labels)}. Got '{raw}'.",
                    )
                picks.append(normalized)
            if len(set(picks)) != 3:
                return ValidationResult(
                    legal=False,
                    reason="Gold, silver, and bronze must be three different responses.",
                )
            return ValidationResult(legal=True)

        return ValidationResult(legal=False, reason="Unknown game phase.")

    def apply_action(self, player_id: str, action: dict) -> None:
        self._turn_number += 1

        if self._phase == Phase.JUDGE_WRITE:
            self._judge_prompt_text = action["prompt_text"].strip()
            # Transition to player write phase
            self._players_pending = [
                pid for pid in self._player_ids if pid != self._current_judge
            ]
            self._rng.shuffle(self._players_pending)
            self._current_writer_idx = 0
            self._phase = Phase.PLAYER_WRITE

        elif self._phase == Phase.PLAYER_WRITE:
            self._player_responses[player_id] = action["response_text"].strip()
            self._current_writer_idx += 1
            if self._current_writer_idx >= len(self._players_pending):
                # All players have responded — enter judging phase
                self._response_order = list(self._players_pending)
                self._rng.shuffle(self._response_order)
                self._phase = Phase.JUDGE_PICK

        elif self._phase == Phase.JUDGE_PICK:
            gold_label = self._normalize_label(action["gold"])
            silver_label = self._normalize_label(action["silver"])
            bronze_label = self._normalize_label(action["bronze"])

            label_to_pid = {
                RESPONSE_LABELS[i]: pid
                for i, pid in enumerate(self._response_order)
            }
            self._gold_pid = label_to_pid[gold_label]
            self._silver_pid = label_to_pid[silver_label]
            self._bronze_pid = label_to_pid[bronze_label]

            self._finish_round()

    def forfeit_turn(self, player_id: str) -> None:
        if self._phase == Phase.JUDGE_WRITE:
            self.apply_action(player_id, {
                "action": "write_prompt",
                "prompt_text": "A silence where words should be.",
            })
        elif self._phase == Phase.PLAYER_WRITE:
            self.apply_action(player_id, {
                "action": "write_response",
                "response_text": "...",
            })
        elif self._phase == Phase.JUDGE_PICK:
            # Assign gold/silver/bronze to first three responses
            labels = RESPONSE_LABELS[: len(self._response_order)]
            self.apply_action(player_id, {
                "action": "judge_pick",
                "gold": labels[0] if len(labels) > 0 else "Response A",
                "silver": labels[1] if len(labels) > 1 else "Response B",
                "bronze": labels[2] if len(labels) > 2 else "Response C",
            })

    def eliminate_player(self, player_id: str) -> None:
        """Handle player elimination mid-game.

        Fill in any pending actions for the eliminated player so the
        round can continue, then check if enough players remain.
        """
        # If this player is pending a write, submit a forfeit response
        if (
            self._phase == Phase.PLAYER_WRITE
            and player_id in self._players_pending
            and player_id not in self._player_responses
        ):
            self._player_responses[player_id] = "(forfeited)"

            # If they were the current writer, advance
            if (
                self._current_writer_idx < len(self._players_pending)
                and self._players_pending[self._current_writer_idx] == player_id
            ):
                self._current_writer_idx += 1
                if self._current_writer_idx >= len(self._players_pending):
                    self._response_order = list(self._players_pending)
                    self._rng.shuffle(self._response_order)
                    self._phase = Phase.JUDGE_PICK

        # If too few players remain to have a meaningful round, end the game
        active = [
            pid for pid in self._player_ids
            if pid != player_id  # excluding the one being eliminated
        ]
        if len(active) < 3:
            self._terminal = True

    def get_scores(self) -> dict[str, float]:
        return dict(self._match_scores)

    def get_state_snapshot(self) -> dict:
        return {
            "game_number": self._game_number,
            "games_per_match": self._games_per_match,
            "turn_number": self._turn_number,
            "round": self._round + 1,
            "num_rounds": self._num_rounds,
            "phase": self._phase,
            "current_judge": self._current_judge,
            "theme_category": self._current_theme[0],
            "theme_constraint": self._current_theme[1],
            "judge_prompt": self._judge_prompt_text,
            "player_responses": dict(self._player_responses),
            "response_order": list(self._response_order),
            "picks": {
                "gold": self._gold_pid,
                "silver": self._silver_pid,
                "bronze": self._bronze_pid,
            },
            "match_scores": dict(self._match_scores),
            "terminal": self._terminal,
            "round_log": list(self._round_log),
            "player_stats": {
                pid: dict(stats)
                for pid, stats in self._player_stats.items()
            },
            "judge_order": list(self._judge_order),
            "theme_order": list(self._theme_order),
            "hint_records": list(self._hint_records),
            "hint_assignments": [
                {
                    "hint_id": a["hint_id"],
                    "round": a["round"],
                    "recipient_model_id": a["recipient_model_id"],
                    "signal_type": a["hint"]["signal_type"],
                    "signal_value": a["hint"]["signal_value"],
                    "strength": a["hint"]["strength"],
                }
                for a in self._hint_assignments
            ],
        }

    def get_highlight_hands(self) -> list[int]:
        return list(self._highlight_turns)

    # ------------------------------------------------------------------
    # Scoring override — bypass rank-based default
    # ------------------------------------------------------------------

    def award_forfeit_wins(self, forfeiting_player_id: str) -> None:
        """On forfeit, award remaining judge bonuses to others and end."""
        remaining_rounds = self._num_rounds - self._round
        # Give each non-forfeiting player a share of potential points
        others = [p for p in self._player_ids if p != forfeiting_player_id]
        for pid in others:
            self._match_scores[pid] += JUDGE_BONUS * (remaining_rounds / len(others))
        self._terminal = True

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _record_hint_delivery(self, assignment: dict) -> None:
        """Record that a hint was delivered (called during prompt construction)."""
        # Avoid duplicate records if get_prompt is called multiple times
        for r in self._hint_records:
            if r["hint_id"] == assignment["hint_id"]:
                return
        record = build_hint_record(
            assignment,
            match_id="",  # filled in by tournament.py at finalize
            game_id=self._game_number,
        )
        self._hint_records.append(record)

    def _compute_hint_outcomes(self) -> None:
        """Compute outcomes for all hint records in the current game.

        Called at end of game, after all rounds are scored.
        """
        # Build per-model baseline word counts from non-hint rounds
        hint_rounds_by_player: dict[str, set[int]] = {}
        for rec in self._hint_records:
            pid = rec["recipient_model_id"]
            hint_rounds_by_player.setdefault(pid, set()).add(rec["round"])

        model_word_counts: dict[str, list[int]] = {
            pid: [] for pid in self._player_ids
        }
        for rlog in self._round_log:
            round_num = rlog["round"]
            for pid, text in rlog["responses"].items():
                if text and text not in ("...", "(forfeited)"):
                    model_word_counts[pid].append(len(text.split()))

        model_baseline_wc: dict[str, float] = {}
        for pid, wcs in model_word_counts.items():
            hint_set = hint_rounds_by_player.get(pid, set())
            baseline_wcs = [
                wc for i, wc in enumerate(wcs)
                if (i + 1) not in hint_set  # round_log rounds are 1-indexed
            ]
            model_baseline_wc[pid] = (
                sum(baseline_wcs) / len(baseline_wcs) if baseline_wcs else 0.0
            )

        for rec in self._hint_records:
            pid = rec["recipient_model_id"]
            round_num = rec["round"]

            # Find the response text for this player in this round
            response_text = ""
            for rlog in self._round_log:
                if rlog["round"] == round_num:
                    response_text = rlog["responses"].get(pid, "")
                    break

            rec["outcome"]["frame_broken"] = compute_frame_broken(response_text)
            signal_used = compute_signal_used(
                rec["signal_value"],
                response_text,
                model_baseline_wc.get(pid, 0.0),
            )
            # If code-based detection returned None and we have a classifier key,
            # run the LLM classifier for non-BREVITY signals
            if signal_used is None and self._classifier_api_key and response_text:
                signal_used = classify_signal_used(
                    rec["signal_value"],
                    response_text,
                    self._classifier_api_key,
                )
            rec["outcome"]["signal_used"] = signal_used
            rec["outcome"]["response_quality_delta"] = compute_quality_delta(
                self._round_scores.get(pid, []),
                round_num - 1,  # 0-based index
            )
            rec["outcome"]["trust_calibration"] = compute_trust_calibration(
                rec["accuracy"],
                rec["outcome"]["signal_used"],
            )

    def _scores_summary(self, player_id: str) -> str:
        """One-line score summary for prompts."""
        parts = []
        for pid in self._player_ids:
            lbl = self._player_labels[pid]
            score = self._match_scores[pid]
            marker = " (you)" if pid == player_id else ""
            parts.append(f"{lbl}: {score:.0f}{marker}")
        return f"Current scores: {', '.join(parts)}"

    @staticmethod
    def _normalize_label(raw: str) -> str:
        """Normalize response label: 'response c' -> 'Response C', 'C' -> 'Response C'."""
        s = raw.strip()
        # Try direct match first
        for label in RESPONSE_LABELS:
            if s.lower() == label.lower():
                return label
        # Try "Response X" pattern with any spacing/case
        match = re.match(r"(?i)response\s+([a-g])$", s)
        if match:
            return f"Response {match.group(1).upper()}"
        # Try bare single letter (must be the entire string)
        if len(s) == 1 and s.upper() in "ABCDEFG":
            return f"Response {s.upper()}"
        return s  # return as-is, validation will catch it
