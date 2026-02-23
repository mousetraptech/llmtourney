"""TelemetryLogger — JSONL match logging.

One logger per match. Writes one JSONL line per turn plus a match summary
as the final line. All entries include schema version and match ID.
"""

import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path

import llmtourney

_SCHEMA_VERSION = "1.0.0"


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


class TelemetryLogger:
    """Writes JSONL telemetry for a single match."""

    def __init__(self, output_dir: Path, match_id: str):
        self._output_dir = Path(output_dir)
        self._match_id = match_id
        self._output_dir.mkdir(parents=True, exist_ok=True)
        self._file_path = self._output_dir / f"{match_id}.jsonl"

    @property
    def file_path(self) -> Path:
        return self._file_path

    def log_turn(self, entry: TelemetryEntry) -> None:
        record = asdict(entry)
        record["schema_version"] = _SCHEMA_VERSION
        record["match_id"] = self._match_id
        record["timestamp"] = datetime.now(timezone.utc).isoformat()
        self._append(record)

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
        }
        if extra:
            record.update(extra)
        self._append(record)

    def _append(self, record: dict) -> None:
        with open(self._file_path, "a") as f:
            f.write(json.dumps(record, default=str) + "\n")
