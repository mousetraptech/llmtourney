"""Referee — violation tracking, penalty rulings, and fidelity reporting.

One Referee instance per match. Tracks violations per player across all turns.
Allows one retry per turn per player. Produces a fidelity report at match end.
"""

from collections import defaultdict
from dataclasses import dataclass
from enum import Enum


class ViolationKind(Enum):
    MALFORMED_JSON = "malformed_json"
    ILLEGAL_MOVE = "illegal_move"
    TIMEOUT = "timeout"
    INJECTION_ATTEMPT = "injection_attempt"


class Ruling(Enum):
    RETRY = "retry"
    FORFEIT_TURN = "forfeit_turn"
    FORFEIT_MATCH = "forfeit_match"


@dataclass
class _ViolationRecord:
    kind: ViolationKind
    severity: int
    details: str


class Referee:
    """Tracks violations and issues rulings for a single match."""

    def __init__(self):
        self._violations: dict[str, list[_ViolationRecord]] = defaultdict(list)
        self._retry_used: dict[str, bool] = defaultdict(lambda: False)
        self._turn_violations: dict[str, int] = defaultdict(int)

    def record_violation(
        self, player_id: str, kind: ViolationKind, severity: int, details: str
    ) -> Ruling:
        self._violations[player_id].append(
            _ViolationRecord(kind=kind, severity=severity, details=details)
        )
        self._turn_violations[player_id] += 1

        if self._turn_violations[player_id] <= 1:
            return Ruling.RETRY
        return Ruling.FORFEIT_TURN

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
                "injection_attempts": 0,
                "total_severity": 0,
                "retries_used": 0,
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
            report[player_id] = counts
        return report
