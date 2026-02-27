"""Tests for scripts.backfill_mongo — JSONL backfill to MongoDB."""

import json
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Helpers: build JSONL content
# ---------------------------------------------------------------------------

def _turn_line(
    match_id: str = "match-001",
    turn_number: int = 1,
    hand_number: int = 1,
    player_id: str = "player_a",
    model_id: str = "gpt-4o",
    **overrides,
) -> str:
    """Return a JSON string representing a single turn entry."""
    doc = {
        "turn_number": turn_number,
        "hand_number": hand_number,
        "street": "preflop",
        "player_id": player_id,
        "model_id": model_id,
        "model_version": model_id,
        "prompt": "Your turn",
        "raw_output": '{"action":"call"}',
        "reasoning_output": None,
        "parsed_action": {"action": "call"},
        "parse_success": True,
        "validation_result": "ok",
        "violation": None,
        "ruling": None,
        "state_snapshot": {"pot": 4},
        "input_tokens": 50,
        "output_tokens": 5,
        "latency_ms": 12.3,
        "engine_version": "0.1.0",
        "prompt_version": "holdem-v1",
        "schema_version": "1.1.0",
        "match_id": match_id,
        "timestamp": "2026-02-27T12:00:00+00:00",
    }
    doc.update(overrides)
    return json.dumps(doc)


def _summary_line(
    match_id: str = "match-001",
    event: str = "holdem",
    scores: dict | None = None,
    player_models: dict | None = None,
    tournament_name: str | None = None,
    tier: str | None = None,
    round_num: int | None = None,
) -> str:
    """Return a JSON string representing a match_summary record."""
    doc = {
        "record_type": "match_summary",
        "match_id": match_id,
        "event": event,
        "final_scores": scores or {"player_a": 10, "player_b": 5},
        "fidelity_report": {
            "player_a": {"total_violations": 0},
            "player_b": {"total_violations": 2},
        },
        "player_models": player_models or {"player_a": "gpt-4o", "player_b": "claude-sonnet-4.5"},
        "engine_version": "0.1.0",
        "schema_version": "1.1.0",
        "timestamp": "2026-02-27T12:05:00+00:00",
    }
    if tournament_name is not None:
        doc["tournament_name"] = tournament_name
    if tier is not None:
        doc["tier"] = tier
    if round_num is not None:
        doc["round"] = round_num
    return json.dumps(doc)


def _write_jsonl(path: Path, *lines: str) -> Path:
    """Write lines to a .jsonl file and return the path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n")
    return path


# ---------------------------------------------------------------------------
# Tests: parse_jsonl_file
# ---------------------------------------------------------------------------

class TestParseJsonlFile:
    def test_separates_turns_from_summary(self, tmp_path):
        from scripts.backfill_mongo import parse_jsonl_file

        f = _write_jsonl(
            tmp_path / "match-001.jsonl",
            _turn_line(turn_number=1),
            _turn_line(turn_number=2),
            _summary_line(),
        )
        turns, summary = parse_jsonl_file(f)

        assert len(turns) == 2
        assert turns[0]["turn_number"] == 1
        assert turns[1]["turn_number"] == 2
        assert summary is not None
        assert summary["record_type"] == "match_summary"

    def test_no_summary(self, tmp_path):
        from scripts.backfill_mongo import parse_jsonl_file

        f = _write_jsonl(
            tmp_path / "match-002.jsonl",
            _turn_line(turn_number=1),
            _turn_line(turn_number=2),
        )
        turns, summary = parse_jsonl_file(f)

        assert len(turns) == 2
        assert summary is None

    def test_empty_file(self, tmp_path):
        from scripts.backfill_mongo import parse_jsonl_file

        f = tmp_path / "empty.jsonl"
        f.write_text("")
        turns, summary = parse_jsonl_file(f)

        assert turns == []
        assert summary is None

    def test_blank_lines_skipped(self, tmp_path):
        from scripts.backfill_mongo import parse_jsonl_file

        f = _write_jsonl(
            tmp_path / "match-003.jsonl",
            _turn_line(turn_number=1),
            "",
            "  ",
            _turn_line(turn_number=2),
        )
        turns, summary = parse_jsonl_file(f)
        assert len(turns) == 2


# ---------------------------------------------------------------------------
# Tests: dry-run mode
# ---------------------------------------------------------------------------

class TestDryRun:
    def test_dry_run_prints_counts_no_writes(self, tmp_path, capsys):
        from scripts.backfill_mongo import run_backfill

        telemetry_dir = tmp_path / "telemetry"
        _write_jsonl(
            telemetry_dir / "match-001.jsonl",
            _turn_line(turn_number=1),
            _turn_line(turn_number=2),
            _summary_line(),
        )
        _write_jsonl(
            telemetry_dir / "match-002.jsonl",
            _turn_line(match_id="match-002", turn_number=1),
        )

        # Should NOT attempt any MongoDB connection
        run_backfill(telemetry_dir, dry_run=True)

        captured = capsys.readouterr().out
        assert "match-001.jsonl" in captured
        assert "match-002.jsonl" in captured
        # Should report totals
        assert "3" in captured  # 3 total turns
        assert "1" in captured  # 1 match summary


# ---------------------------------------------------------------------------
# Tests: missing context fields default gracefully
# ---------------------------------------------------------------------------

class TestMissingContextDefaults:
    def test_summary_without_tournament_fields(self, tmp_path):
        from scripts.backfill_mongo import parse_jsonl_file, _build_match_doc

        f = _write_jsonl(
            tmp_path / "match-004.jsonl",
            _turn_line(turn_number=1),
            _summary_line(match_id="match-004"),
        )
        turns, summary = parse_jsonl_file(f)
        assert summary is not None

        match_doc = _build_match_doc(summary)

        # Missing fields should get defaults
        assert match_doc["tournament_name"] == "unknown"
        assert match_doc["tier"] == "unknown"
        assert match_doc["round"] == 0

    def test_summary_with_tournament_fields(self, tmp_path):
        from scripts.backfill_mongo import parse_jsonl_file, _build_match_doc

        f = _write_jsonl(
            tmp_path / "match-005.jsonl",
            _summary_line(
                match_id="match-005",
                tournament_name="season-1",
                tier="midtier",
                round_num=2,
            ),
        )
        _, summary = parse_jsonl_file(f)
        assert summary is not None

        match_doc = _build_match_doc(summary)
        assert match_doc["tournament_name"] == "season-1"
        assert match_doc["tier"] == "midtier"
        assert match_doc["round"] == 2


# ---------------------------------------------------------------------------
# Tests: winner derivation
# ---------------------------------------------------------------------------

class TestWinnerDerivation:
    def test_clear_winner(self, tmp_path):
        from scripts.backfill_mongo import _build_match_doc

        summary = json.loads(_summary_line(
            scores={"player_a": 10, "player_b": 5},
            player_models={"player_a": "gpt-4o", "player_b": "sonnet"},
        ))
        doc = _build_match_doc(summary)
        assert doc["winner"] == "gpt-4o"

    def test_tie(self, tmp_path):
        from scripts.backfill_mongo import _build_match_doc

        summary = json.loads(_summary_line(
            scores={"player_a": 10, "player_b": 10},
            player_models={"player_a": "gpt-4o", "player_b": "sonnet"},
        ))
        doc = _build_match_doc(summary)
        assert doc["winner"] is None


# ---------------------------------------------------------------------------
# Tests: event_type derivation
# ---------------------------------------------------------------------------

class TestEventTypeDerivation:
    def test_event_type_from_event_field(self):
        from scripts.backfill_mongo import _build_match_doc

        summary = json.loads(_summary_line(event="reversi"))
        doc = _build_match_doc(summary)
        assert doc["event_type"] == "reversi"

    def test_event_type_defaults_unknown(self):
        from scripts.backfill_mongo import _build_match_doc

        summary = json.loads(_summary_line())
        summary.pop("event", None)
        doc = _build_match_doc(summary)
        assert doc["event_type"] == "unknown"


# ---------------------------------------------------------------------------
# Tests: turn document enrichment
# ---------------------------------------------------------------------------

class TestTurnEnrichment:
    def test_turns_get_ingested_at(self, tmp_path):
        from scripts.backfill_mongo import _enrich_turns
        from datetime import datetime

        turns = [json.loads(_turn_line(turn_number=i)) for i in range(3)]
        enriched = _enrich_turns(turns, "unknown", "unknown", "unknown", 0)

        for t in enriched:
            assert "_ingested_at" in t
            assert isinstance(t["_ingested_at"], datetime)

    def test_turns_get_context_fields(self, tmp_path):
        from scripts.backfill_mongo import _enrich_turns

        turns = [json.loads(_turn_line())]
        enriched = _enrich_turns(turns, "holdem", "season-1", "midtier", 2)

        assert enriched[0]["event_type"] == "holdem"
        assert enriched[0]["tournament_name"] == "season-1"
        assert enriched[0]["tier"] == "midtier"
        assert enriched[0]["round"] == 2
