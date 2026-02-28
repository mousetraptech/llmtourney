"""Referee — violation tracking, penalty rulings, and fidelity reporting.

One Referee instance per match. Tracks violations per player across all turns.
Allows one retry per turn per player. Produces a fidelity report at match end.

When a ForfeitEscalationConfig is provided, the referee uses configurable
thresholds for retry/forfeit decisions and tracks cumulative strike counts
toward match forfeit.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from llmtourney.config import ForfeitEscalationConfig


class ViolationKind(Enum):
    MALFORMED_JSON = "malformed_json"
    ILLEGAL_MOVE = "illegal_move"
    TIMEOUT = "timeout"
    INJECTION_ATTEMPT = "injection_attempt"
    EMPTY_RESPONSE = "empty_response"


class Ruling(Enum):
    RETRY = "retry"
    FORFEIT_TURN = "forfeit_turn"
    FORFEIT_MATCH = "forfeit_match"
    ELIMINATE_PLAYER = "eliminate_player"


@dataclass
class _ViolationRecord:
    kind: ViolationKind
    severity: int
    details: str


class Referee:
    """Tracks violations and issues rulings for a single match."""

    # Extra strikes granted at 7+ players so larger tables are more forgiving
    _SCALING_TABLE = {7: 1, 8: 2, 9: 3}

    def __init__(
        self,
        escalation: ForfeitEscalationConfig | None = None,
        num_players: int = 2,
    ) -> None:
        self._violations: dict[str, list[_ViolationRecord]] = defaultdict(list)
        self._retry_used: dict[str, bool] = defaultdict(lambda: False)
        self._turn_violations: dict[str, int] = defaultdict(int)
        self._escalation = escalation
        self._num_players = num_players

        # Strike tracking for forfeit escalation
        self._turn_forfeit_count: dict[str, int] = defaultdict(int)
        self._match_forfeited_by: str | None = None
        self._eliminated_players: list[str] = []

    def record_violation(
        self, player_id: str, kind: ViolationKind, severity: int, details: str
    ) -> Ruling:
        self._violations[player_id].append(
            _ViolationRecord(kind=kind, severity=severity, details=details)
        )
        self._turn_violations[player_id] += 1

        if self._escalation is not None:
            # Configurable threshold: how many violations before forfeit
            if self._turn_violations[player_id] <= (
                self._escalation.turn_forfeit_threshold - 1
            ):
                return Ruling.RETRY
            return Ruling.FORFEIT_TURN

        # Legacy behavior: 1st violation → RETRY, 2nd → FORFEIT_TURN
        if self._turn_violations[player_id] <= 1:
            return Ruling.RETRY
        return Ruling.FORFEIT_TURN

    def _effective_threshold(self) -> int:
        """Return the match forfeit threshold, scaled for large tables."""
        if self._escalation is None:
            return 3  # sensible default
        base = self._escalation.match_forfeit_threshold
        if not self._escalation.match_forfeit_scaling:
            return base
        if self._num_players >= 7:
            extra = self._SCALING_TABLE.get(
                self._num_players, max(0, self._num_players - 6)
            )
            return base + extra
        return base

    def record_turn_forfeit(
        self, player_id: str, violation_kind: ViolationKind
    ) -> Ruling:
        """Record a turn forfeit and check for match/player forfeit.

        Increments strike count if the violation kind is in the configured
        strike_violations list. Returns FORFEIT_MATCH for 2-player matches
        or ELIMINATE_PLAYER for 3+ player matches when the threshold is
        reached.
        """
        if self._escalation is None:
            return Ruling.FORFEIT_TURN

        if violation_kind.value in self._escalation.strike_violations:
            self._turn_forfeit_count[player_id] += 1

        if self._turn_forfeit_count[player_id] >= self._effective_threshold():
            if self._num_players <= 2:
                self._match_forfeited_by = player_id
                return Ruling.FORFEIT_MATCH
            else:
                if player_id not in self._eliminated_players:
                    self._eliminated_players.append(player_id)
                return Ruling.ELIMINATE_PLAYER

        return Ruling.FORFEIT_TURN

    def restore_strikes(self, player_id: str, count: int) -> None:
        """Restore strike count for a player (used when resuming a match)."""
        self._turn_forfeit_count[player_id] = count

    def get_strikes(self, player_id: str) -> int:
        """Return the cumulative strike count for a player."""
        return self._turn_forfeit_count[player_id]

    def get_match_forfeit_player(self) -> str | None:
        """Return the player_id that caused a match forfeit, or None."""
        return self._match_forfeited_by

    @property
    def match_forfeit_threshold(self) -> int | None:
        """Return the effective match forfeit threshold (with scaling), or None."""
        if self._escalation is None:
            return None
        return self._effective_threshold()

    def get_eliminated_players(self) -> list[str]:
        """Return list of player_ids eliminated (in elimination order)."""
        return list(self._eliminated_players)

    def should_retry(self, player_id: str) -> bool:
        return not self._retry_used[player_id]

    def consume_retry(self, player_id: str) -> None:
        self._retry_used[player_id] = True

    def new_turn(self) -> None:
        self._retry_used.clear()
        self._turn_violations.clear()

    def get_fidelity_report(self) -> dict:
        report = {}
        for player_id, violations in self._violations.items():
            counts = {
                "total_violations": len(violations),
                "malformed_json": 0,
                "illegal_move": 0,
                "timeout": 0,
                "empty_response": 0,
                "injection_attempts": 0,
                "total_severity": 0,
                "retries_used": 0,
                "turn_forfeits": self._turn_forfeit_count.get(player_id, 0),
            }
            for v in violations:
                counts["total_severity"] += v.severity
                if v.kind == ViolationKind.MALFORMED_JSON:
                    counts["malformed_json"] += 1
                elif v.kind == ViolationKind.ILLEGAL_MOVE:
                    counts["illegal_move"] += 1
                elif v.kind == ViolationKind.TIMEOUT:
                    counts["timeout"] += 1
                elif v.kind == ViolationKind.INJECTION_ATTEMPT:
                    counts["injection_attempts"] += 1
                elif v.kind == ViolationKind.EMPTY_RESPONSE:
                    counts["empty_response"] += 1
            report[player_id] = counts

        # Include match forfeit info
        if self._match_forfeited_by:
            report["_match_forfeited"] = True
            report["_match_forfeited_by"] = self._match_forfeited_by

        return report
