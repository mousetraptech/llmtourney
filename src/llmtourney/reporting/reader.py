"""Telemetry reader — loads and parses JSONL match files into structured data.

Usage:
    match = MatchData.from_file("path/to/match.jsonl")
    print(match.game_type)       # "bullshit"
    print(match.models)          # {"player_a": "claude-haiku-4.5", ...}
    print(len(match.turns))      # 703
    print(match.summary)         # final match summary record or None
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


def _detect_game_type(snapshot: dict) -> str:
    """Detect game type from state snapshot keys."""
    if "target_rank" in snapshot:
        return "bullshit"
    if "community_cards" in snapshot:
        return "holdem"
    if "board" in snapshot:
        board = snapshot["board"]
        if isinstance(board, list) and len(board) == 8:
            return "checkers"
        if isinstance(board, list) and len(board) == 3:
            return "tictactoe"
        if isinstance(board, list) and len(board) == 6:
            return "connectfour"
        if isinstance(board, list) and len(board) in (7, 8, 15):
            # Rough heuristic; Reversi is 8x8
            return "reversi"
    if "rack" in snapshot or "tiles_remaining" in snapshot:
        return "scrabble"
    # Fallback: try to detect from board dimensions
    if "board" in snapshot:
        board = snapshot["board"]
        if isinstance(board, list):
            size = len(board)
            if size == 8:
                return "reversi"
    return "unknown"


@dataclass
class Turn:
    """A single turn from telemetry."""

    turn_number: int
    player_id: str
    model_id: str
    action: dict | None
    action_type: str | None  # "play", "call", "pass", "fold", "raise", etc.
    raw_output: str
    reasoning: str | None
    snapshot: dict
    input_tokens: int
    output_tokens: int
    latency_ms: float
    parse_success: bool
    validation_result: str
    violation: str | None
    prompt: str
    time_exceeded: bool = False
    cumulative_strikes: int = 0

    @classmethod
    def from_record(cls, record: dict) -> Turn:
        parsed = record.get("parsed_action")
        action_type = None
        if parsed:
            action_type = parsed.get("action")
        return cls(
            turn_number=record.get("turn_number", 0),
            player_id=record.get("player_id", ""),
            model_id=record.get("model_id", ""),
            action=parsed,
            action_type=action_type,
            raw_output=record.get("raw_output", ""),
            reasoning=record.get("reasoning_output"),
            snapshot=record.get("state_snapshot", {}),
            input_tokens=record.get("input_tokens", 0),
            output_tokens=record.get("output_tokens", 0),
            latency_ms=record.get("latency_ms", 0),
            parse_success=record.get("parse_success", False),
            validation_result=record.get("validation_result", ""),
            violation=record.get("violation"),
            prompt=record.get("prompt", ""),
            time_exceeded=record.get("time_exceeded", False),
            cumulative_strikes=record.get("cumulative_strikes", 0),
        )


@dataclass
class MatchData:
    """Parsed match telemetry."""

    file_path: Path
    match_id: str
    game_type: str
    models: dict[str, str]  # player_id -> short model name
    models_full: dict[str, str]  # player_id -> full model id
    turns: list[Turn]
    summary: dict | None
    schema_version: str

    @classmethod
    def from_file(cls, path: str | Path) -> MatchData:
        path = Path(path)
        turns: list[Turn] = []
        summary: dict | None = None
        models: dict[str, str] = {}
        models_full: dict[str, str] = {}
        match_id = ""
        schema_version = ""
        game_type = "unknown"

        with open(path) as f:
            for line in f:
                record = json.loads(line)
                if record.get("record_type") == "match_summary":
                    summary = record
                    continue

                if not match_id:
                    match_id = record.get("match_id", path.stem)
                if not schema_version:
                    schema_version = record.get("schema_version", "unknown")

                pid = record.get("player_id", "")
                mid = record.get("model_id", "")
                if pid and mid and pid not in models_full:
                    models_full[pid] = mid
                    models[pid] = mid.split("/")[-1]

                # Detect game type from first snapshot
                if game_type == "unknown" and record.get("state_snapshot"):
                    game_type = _detect_game_type(record["state_snapshot"])

                turn = Turn.from_record(record)
                if turn.player_id:  # skip malformed
                    turns.append(turn)

        return cls(
            file_path=path,
            match_id=match_id,
            game_type=game_type,
            models=models,
            models_full=models_full,
            turns=turns,
            summary=summary,
            schema_version=schema_version,
        )

    @property
    def num_players(self) -> int:
        return len(self.models)

    @property
    def valid_turns(self) -> list[Turn]:
        """Turns with successfully parsed actions."""
        return [t for t in self.turns if t.action is not None]

    def turns_by_model(self, model: str) -> list[Turn]:
        """Get all turns for a given short model name."""
        pids = [pid for pid, m in self.models.items() if m == model]
        return [t for t in self.turns if t.player_id in pids]

    def turns_by_action(self, action_type: str) -> list[Turn]:
        """Get all turns with a given action type."""
        return [t for t in self.valid_turns if t.action_type == action_type]

    @property
    def model_names(self) -> list[str]:
        """Sorted unique short model names."""
        return sorted(set(self.models.values()))

    def player_for_model(self, model: str) -> str | None:
        """Get player_id for a model name."""
        for pid, m in self.models.items():
            if m == model:
                return pid
        return None

    @property
    def last_snapshot(self) -> dict:
        """Last state snapshot with player stats."""
        for turn in reversed(self.valid_turns):
            if "player_stats" in turn.snapshot:
                return turn.snapshot
        if self.valid_turns:
            return self.valid_turns[-1].snapshot
        return {}
