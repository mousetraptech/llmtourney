"""TelemetryLogger — JSONL match logging.

One logger per match. Writes one JSONL line per turn plus a match summary
as the final line. All entries include schema version and match ID.
"""

import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path

import llmtourney

_SCHEMA_VERSION = "1.1.0"


@dataclass
class TelemetryEntry:
    """One turn of match telemetry."""

    turn_number: int
    hand_number: int
    street: str
    player_id: str
    model_id: str
    model_version: str
    prompt: str
    raw_output: str
    reasoning_output: str | None
    parsed_action: dict | None
    parse_success: bool
    validation_result: str
    violation: str | None
    ruling: str | None
    state_snapshot: dict
    input_tokens: int
    output_tokens: int
    latency_ms: float
    engine_version: str
    prompt_version: str
    # Shot clock / forfeit escalation fields (v1.1.0)
    time_limit_ms: int | None = None
    time_exceeded: bool = False
    cumulative_strikes: int = 0
    strike_limit: int | None = None


class TelemetryLogger:
    """Writes JSONL telemetry for a single match."""

    def __init__(self, output_dir: Path, match_id: str, mongo_sink=None, tournament_context=None):
        self._output_dir = Path(output_dir)
        self._match_id = match_id
        self._output_dir.mkdir(parents=True, exist_ok=True)
        self._file_path = self._output_dir / f"{match_id}.jsonl"
        self._sink = mongo_sink
        self._tournament_context = tournament_context or {}

    @property
    def file_path(self) -> Path:
        return self._file_path

    def log_turn(self, entry: TelemetryEntry) -> None:
        record = asdict(entry)
        record["schema_version"] = _SCHEMA_VERSION
        record["match_id"] = self._match_id
        record["timestamp"] = datetime.now(timezone.utc).isoformat()
        self._append(record)
        if self._sink:
            try:
                self._sink.log_turn(self._match_id, entry, self._tournament_context)
            except Exception:
                pass  # sink errors never break JSONL

    def finalize_match(
        self,
        scores: dict[str, float],
        fidelity: dict,
        extra: dict | None = None,
    ) -> None:
        record = {
            "schema_version": _SCHEMA_VERSION,
            "record_type": "match_summary",
            "match_id": self._match_id,
            "final_scores": scores,
            "fidelity_report": fidelity,
            "engine_version": llmtourney.__version__,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event": self._tournament_context.get("event_type"),
            "tournament_name": self._tournament_context.get("tournament_name"),
            "tier": self._tournament_context.get("tier"),
            "round": self._tournament_context.get("round"),
        }
        if extra:
            record.update(extra)
        self._append(record)
        if self._sink:
            try:
                player_models = (extra or {}).get("player_models", {})
                self._sink.finalize_match(
                    self._match_id, scores, fidelity, player_models,
                    self._tournament_context, extra=extra,
                )
            except Exception:
                pass

    def _append(self, record: dict) -> None:
        with open(self._file_path, "a") as f:
            f.write(json.dumps(record, default=str) + "\n")
