"""Tests for shot clock and forfeit escalation features.

Tests cover: shot clock timeout, normal play within limits, per-model overrides,
backward compatibility (no config), prompt injection notice, match forfeit
awarding remaining games, empty response detection, escalation thresholds,
and legacy behavior preservation.
"""

import json
import time
from pathlib import Path
from typing import Any

from llmtourney.config import (
    ComputeCaps,
    EventConfig,
    ForfeitEscalationConfig,
    ModelConfig,
    ShotClockConfig,
    TournamentConfig,
)
from llmtourney.core.adapter import AdapterResponse, MockAdapter, ModelAdapter
from llmtourney.core.referee import Referee, Ruling, ViolationKind
from llmtourney.events.tictactoe.engine import TicTacToeEvent
from llmtourney.tournament import TournamentEngine


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_strategy(raw_text: str, latency_s: float = 0.0):
    """Return a mock strategy that returns fixed text after a delay."""
    def strategy(messages, context):
        if latency_s > 0:
            time.sleep(latency_s)
        return raw_text
    return strategy


def _ttt_play_action(row: int, col: int) -> str:
    return json.dumps({"action": "play", "position": [row, col], "reasoning": "test"})


def _always_valid_ttt_strategy(messages, context):
    """Parse prompt to find first available square and play it."""
    prompt = messages[0]["content"]
    # Extract available squares from the prompt
    import re
    matches = re.findall(r'\[(\d+), (\d+)\]', prompt.split("Available squares:")[-1].split("\n")[0])
    if matches:
        r, c = int(matches[0][0]), int(matches[0][1])
        return json.dumps({"action": "play", "position": [r, c], "reasoning": "auto"})
    return json.dumps({"action": "play", "position": [0, 0], "reasoning": "fallback"})


def _make_config(
    tmp_path: Path,
    strategy_a="always_valid_ttt",
    strategy_b="always_valid_ttt",
    shot_clock: ShotClockConfig | None = None,
    forfeit_escalation: ForfeitEscalationConfig | None = None,
    games_per_match: int = 3,
    adapters: dict | None = None,
) -> TournamentConfig:
    """Build a TicTacToe config with optional shot clock / escalation."""
    return TournamentConfig(
        name="test-shot-clock",
        seed=42,
        version="0.1.0",
        models={
            "model-a": ModelConfig(name="model-a", provider="mock", strategy=strategy_a),
            "model-b": ModelConfig(name="model-b", provider="mock", strategy=strategy_b),
        },
        events={
            "tictactoe": EventConfig(
                name="tictactoe",
                weight=1,
                games_per_match=games_per_match,
                rounds=1,
            ),
        },
        compute_caps=ComputeCaps(max_output_tokens=256, timeout_s=30.0),
        output_dir=tmp_path / "output",
        shot_clock=shot_clock,
        forfeit_escalation=forfeit_escalation,
    )


# Custom strategy registry for tests
_TEST_STRATEGIES = {
    "always_valid_ttt": _always_valid_ttt_strategy,
}


class _TestEngine(TournamentEngine):
    """TournamentEngine subclass that supports custom adapters."""

    def __init__(self, config, custom_adapters=None):
        self._custom_adapters = custom_adapters or {}
        super().__init__(config)

    def _build_adapters(self):
        if self._custom_adapters:
            return dict(self._custom_adapters)
        adapters = {}
        for name, mcfg in self.config.models.items():
            strategy_fn = _TEST_STRATEGIES.get(mcfg.strategy)
            if strategy_fn:
                adapters[name] = MockAdapter(model_id=name, strategy=strategy_fn)
            else:
                adapters[name] = self._build_adapter(mcfg)
        return adapters


# ---------------------------------------------------------------------------
# Tests: Referee escalation logic (unit-level)
# ---------------------------------------------------------------------------

class TestRefereeEscalation:
    def test_escalation_threshold_1_no_retry(self):
        """With turn_forfeit_threshold=1, first violation → immediate forfeit."""
        esc = ForfeitEscalationConfig(
            turn_forfeit_threshold=1,
            match_forfeit_threshold=3,
        )
        ref = Referee(escalation=esc)
        ruling = ref.record_violation(
            "player_a", ViolationKind.MALFORMED_JSON, severity=2, details="bad json"
        )
        assert ruling == Ruling.FORFEIT_TURN

    def test_escalation_threshold_2_allows_retry(self):
        """With turn_forfeit_threshold=2, first violation → RETRY."""
        esc = ForfeitEscalationConfig(
            turn_forfeit_threshold=2,
            match_forfeit_threshold=3,
        )
        ref = Referee(escalation=esc)
        ruling = ref.record_violation(
            "player_a", ViolationKind.MALFORMED_JSON, severity=2, details="bad json"
        )
        assert ruling == Ruling.RETRY
        ruling = ref.record_violation(
            "player_a", ViolationKind.MALFORMED_JSON, severity=2, details="still bad"
        )
        assert ruling == Ruling.FORFEIT_TURN

    def test_no_escalation_preserves_legacy(self):
        """Without escalation config, behavior is identical to legacy."""
        ref = Referee()
        ruling = ref.record_violation(
            "player_a", ViolationKind.MALFORMED_JSON, severity=2, details="x"
        )
        assert ruling == Ruling.RETRY
        ruling = ref.record_violation(
            "player_a", ViolationKind.MALFORMED_JSON, severity=2, details="y"
        )
        assert ruling == Ruling.FORFEIT_TURN

    def test_record_turn_forfeit_counts_strikes(self):
        """record_turn_forfeit increments strike count for configured violations."""
        esc = ForfeitEscalationConfig(
            turn_forfeit_threshold=1,
            match_forfeit_threshold=3,
            strike_violations=["timeout", "malformed_json", "empty_response"],
        )
        ref = Referee(escalation=esc)
        ref.record_turn_forfeit("player_a", ViolationKind.TIMEOUT)
        assert ref.get_strikes("player_a") == 1
        ref.record_turn_forfeit("player_a", ViolationKind.MALFORMED_JSON)
        assert ref.get_strikes("player_a") == 2

    def test_record_turn_forfeit_match_forfeit_at_threshold(self):
        """3 strikes → FORFEIT_MATCH."""
        esc = ForfeitEscalationConfig(
            turn_forfeit_threshold=1,
            match_forfeit_threshold=3,
        )
        ref = Referee(escalation=esc)
        ref.record_turn_forfeit("player_a", ViolationKind.TIMEOUT)
        ref.record_turn_forfeit("player_a", ViolationKind.TIMEOUT)
        ruling = ref.record_turn_forfeit("player_a", ViolationKind.TIMEOUT)
        assert ruling == Ruling.FORFEIT_MATCH
        assert ref.get_match_forfeit_player() == "player_a"

    def test_non_strike_violation_doesnt_count(self):
        """illegal_move not in default strike_violations → no strike increment."""
        esc = ForfeitEscalationConfig(
            turn_forfeit_threshold=1,
            match_forfeit_threshold=3,
            strike_violations=["timeout"],
        )
        ref = Referee(escalation=esc)
        ruling = ref.record_turn_forfeit("player_a", ViolationKind.ILLEGAL_MOVE)
        assert ruling == Ruling.FORFEIT_TURN
        assert ref.get_strikes("player_a") == 0

    def test_empty_response_violation_kind(self):
        """EMPTY_RESPONSE is a valid ViolationKind."""
        ref = Referee()
        ruling = ref.record_violation(
            "player_a", ViolationKind.EMPTY_RESPONSE, severity=2,
            details="empty response",
        )
        assert ruling == Ruling.RETRY
        report = ref.get_fidelity_report()
        assert report["player_a"]["empty_response"] == 1

    def test_fidelity_report_includes_turn_forfeits(self):
        """Fidelity report includes turn_forfeits count."""
        esc = ForfeitEscalationConfig(match_forfeit_threshold=5)
        ref = Referee(escalation=esc)
        ref.record_violation("player_a", ViolationKind.TIMEOUT, 2, "x")
        ref.record_turn_forfeit("player_a", ViolationKind.TIMEOUT)
        report = ref.get_fidelity_report()
        assert report["player_a"]["turn_forfeits"] == 1


# ---------------------------------------------------------------------------
# Tests: Shot clock integration
# ---------------------------------------------------------------------------

class TestShotClockIntegration:
    def test_shot_clock_timeout_forfeits_turn(self, tmp_path):
        """A model that exceeds the shot clock gets its turn forfeited."""
        # Use a very short shot clock (1ms) with a strategy that takes time
        slow_strategy = _make_strategy(
            _ttt_play_action(0, 0), latency_s=0.05
        )
        config = _make_config(
            tmp_path,
            shot_clock=ShotClockConfig(default_ms=1),  # 1ms — will always exceed
            games_per_match=1,
        )
        # Both models are slow — game should still complete via forfeits
        engine = _TestEngine(
            config,
            custom_adapters={
                "model-a": MockAdapter(model_id="model-a", strategy=slow_strategy),
                "model-b": MockAdapter(model_id="model-b", strategy=slow_strategy),
            },
        )
        result = engine.run()
        assert len(result.matches) == 1
        # Check telemetry has timeout violations
        jsonl_file = list(result.telemetry_dir.glob("*.jsonl"))[0]
        lines = jsonl_file.read_text().strip().split("\n")
        turn_entries = [json.loads(l) for l in lines if "turn_number" in json.loads(l)]
        timeouts = [e for e in turn_entries if e.get("violation") == "timeout"]
        assert len(timeouts) > 0
        # All timeout entries should have time_exceeded=True
        for t in timeouts:
            assert t["time_exceeded"] is True

    def test_shot_clock_within_limit_normal(self, tmp_path):
        """Models within shot clock play normally."""
        config = _make_config(
            tmp_path,
            shot_clock=ShotClockConfig(default_ms=30000),  # 30s — plenty of time
            games_per_match=1,
        )
        engine = _TestEngine(config)
        result = engine.run()
        assert len(result.matches) == 1
        # No timeouts should occur
        jsonl_file = list(result.telemetry_dir.glob("*.jsonl"))[0]
        lines = jsonl_file.read_text().strip().split("\n")
        turn_entries = [json.loads(l) for l in lines if "turn_number" in json.loads(l)]
        timeouts = [e for e in turn_entries if e.get("violation") == "timeout"]
        assert len(timeouts) == 0

    def test_shot_clock_model_override(self, tmp_path):
        """Per-model shot clock override works."""
        config = _make_config(
            tmp_path,
            shot_clock=ShotClockConfig(
                default_ms=1,  # Very short default
                model_overrides={"model-a": 30000},  # But model-a gets 30s
            ),
            games_per_match=1,
        )
        engine = _TestEngine(config)
        # model-a should succeed (30s limit), model-b may forfeit (1ms limit)
        time_limit_a = engine._get_time_limit_ms("model-a")
        time_limit_b = engine._get_time_limit_ms("model-b")
        assert time_limit_a == 30000
        assert time_limit_b == 1

    def test_no_shot_clock_ignores_latency(self, tmp_path):
        """Without shot_clock config, latency is ignored."""
        config = _make_config(tmp_path, games_per_match=1)
        assert config.shot_clock is None
        engine = _TestEngine(config)
        assert engine._get_time_limit_ms("anything") is None
        result = engine.run()
        assert len(result.matches) == 1

    def test_shot_clock_prompt_has_timing_notice(self, tmp_path):
        """When shot clock is active, prompt includes timing notice."""
        config = _make_config(
            tmp_path,
            shot_clock=ShotClockConfig(default_ms=15000),
            forfeit_escalation=ForfeitEscalationConfig(
                match_forfeit_threshold=3,
            ),
            games_per_match=1,
        )
        engine = _TestEngine(config)
        result = engine.run()
        # Check that prompts include the timing notice
        jsonl_file = list(result.telemetry_dir.glob("*.jsonl"))[0]
        lines = jsonl_file.read_text().strip().split("\n")
        turn_entries = [json.loads(l) for l in lines if "turn_number" in json.loads(l)]
        assert len(turn_entries) > 0
        for entry in turn_entries:
            assert "[TIME LIMIT:" in entry["prompt"]
            assert "Strikes:" in entry["prompt"]


# ---------------------------------------------------------------------------
# Tests: Match forfeit and award_forfeit_wins
# ---------------------------------------------------------------------------

class TestMatchForfeitAward:
    def test_match_forfeit_awards_remaining_games(self, tmp_path):
        """Series event: forfeit at game 2/9 → opponent gets +7 wins."""
        # Use garbage output for model-b → all forfeits
        garbage_strategy = _make_strategy("this is not json at all")
        config = _make_config(
            tmp_path,
            forfeit_escalation=ForfeitEscalationConfig(
                turn_forfeit_threshold=1,  # immediate forfeit
                match_forfeit_threshold=3,  # 3 forfeits → match over
            ),
            games_per_match=9,
        )
        engine = _TestEngine(
            config,
            custom_adapters={
                "model-a": MockAdapter(model_id="model-a", strategy=_always_valid_ttt_strategy),
                "model-b": MockAdapter(model_id="model-b", strategy=garbage_strategy),
            },
        )
        result = engine.run()
        match = result.matches[0]
        # model-b (player_b) should have forfeited
        jsonl_file = list(result.telemetry_dir.glob("*.jsonl"))[0]
        lines = jsonl_file.read_text().strip().split("\n")
        summary = json.loads(lines[-1])
        assert summary["ruling"] == "match_forfeit"
        assert summary["forfeit_details"]["forfeiting_model"] == "model-b"
        # Opponent (model-a / player_a) should have gained from remaining games
        assert match.scores["player_a"] > match.scores["player_b"]

    def test_empty_response_detected(self, tmp_path):
        """Whitespace-only response → EMPTY_RESPONSE violation."""
        empty_strategy = _make_strategy("   \n  \t  ")
        config = _make_config(
            tmp_path,
            games_per_match=1,
        )
        engine = _TestEngine(
            config,
            custom_adapters={
                "model-a": MockAdapter(model_id="model-a", strategy=_always_valid_ttt_strategy),
                "model-b": MockAdapter(model_id="model-b", strategy=empty_strategy),
            },
        )
        result = engine.run()
        jsonl_file = list(result.telemetry_dir.glob("*.jsonl"))[0]
        lines = jsonl_file.read_text().strip().split("\n")
        turn_entries = [json.loads(l) for l in lines if "turn_number" in json.loads(l)]
        empty_violations = [
            e for e in turn_entries if e.get("violation") == "empty_response"
        ]
        assert len(empty_violations) > 0

    def test_telemetry_has_new_fields(self, tmp_path):
        """Telemetry entries include shot clock fields."""
        config = _make_config(
            tmp_path,
            shot_clock=ShotClockConfig(default_ms=30000),
            forfeit_escalation=ForfeitEscalationConfig(match_forfeit_threshold=5),
            games_per_match=1,
        )
        engine = _TestEngine(config)
        result = engine.run()
        jsonl_file = list(result.telemetry_dir.glob("*.jsonl"))[0]
        lines = jsonl_file.read_text().strip().split("\n")
        turn_entries = [json.loads(l) for l in lines if "turn_number" in json.loads(l)]
        assert len(turn_entries) > 0
        for entry in turn_entries:
            assert "time_limit_ms" in entry
            assert "time_exceeded" in entry
            assert "cumulative_strikes" in entry
            assert "strike_limit" in entry
            assert entry["time_limit_ms"] == 30000
            assert entry["strike_limit"] == 5

    def test_schema_version_bumped(self, tmp_path):
        """Telemetry schema version is 1.1.0."""
        config = _make_config(tmp_path, games_per_match=1)
        engine = _TestEngine(config)
        result = engine.run()
        jsonl_file = list(result.telemetry_dir.glob("*.jsonl"))[0]
        lines = jsonl_file.read_text().strip().split("\n")
        first_entry = json.loads(lines[0])
        assert first_entry["schema_version"] == "1.1.0"


# ---------------------------------------------------------------------------
# Fake adapter: reports configurable latency without sleeping
# ---------------------------------------------------------------------------

class _FakeLatencyAdapter(ModelAdapter):
    """Adapter that wraps a strategy but reports a fake latency_ms.

    Useful for testing shot clock enforcement without slow tests.
    ``latency_fn`` receives the call count (1-indexed) and returns the
    latency_ms to report for that call.
    """

    def __init__(
        self,
        model_id: str,
        strategy,
        latency_fn=None,
    ):
        self._model_id = model_id
        self._strategy = strategy
        self._latency_fn = latency_fn or (lambda n: 0.0)
        self._call_count = 0

    def query(self, messages, max_tokens, timeout_s, context=None):
        self._call_count += 1
        raw = self._strategy(messages, context or {})
        latency = self._latency_fn(self._call_count)
        return AdapterResponse(
            raw_text=raw,
            reasoning_text=None,
            input_tokens=0,
            output_tokens=max(1, len(raw) // 4),
            latency_ms=latency,
            model_id=self._model_id,
            model_version=self._model_id,
        )


# ---------------------------------------------------------------------------
# End-to-end smoke test: aggressive config through full JSONL pipeline
# ---------------------------------------------------------------------------

class TestE2ESmokeTest:
    """Simulate a 10s clock / 2-strike limit against a flaky model.

    Model-A: always plays correctly, fast.
    Model-B: always returns empty string (simulating a model that hangs
    and produces nothing).  With turn_forfeit_threshold=1, each empty
    response is an immediate turn forfeit + strike.  At 2 strikes the
    match is forfeited.

    Validates every new telemetry field across the full adapter →
    tournament loop → JSONL pipeline.
    """

    def test_aggressive_config_full_pipeline(self, tmp_path):
        config = _make_config(
            tmp_path,
            shot_clock=ShotClockConfig(default_ms=10_000),
            forfeit_escalation=ForfeitEscalationConfig(
                turn_forfeit_threshold=1,   # no retries
                match_forfeit_threshold=2,  # 2 strikes → match over
            ),
            games_per_match=9,
        )

        # Model-A: plays correctly, reports 50ms latency (well under 10s)
        fast_adapter = _FakeLatencyAdapter(
            model_id="model-a",
            strategy=_always_valid_ttt_strategy,
            latency_fn=lambda n: 50.0,
        )
        # Model-B: always returns empty string, reports 200ms latency
        empty_adapter = _FakeLatencyAdapter(
            model_id="model-b",
            strategy=lambda msgs, ctx: "",
            latency_fn=lambda n: 200.0,
        )

        engine = _TestEngine(
            config,
            custom_adapters={
                "model-a": fast_adapter,
                "model-b": empty_adapter,
            },
        )
        result = engine.run()

        # ── Parse JSONL ──────────────────────────────────────────────
        assert len(result.matches) == 1
        jsonl_file = list(result.telemetry_dir.glob("*.jsonl"))[0]
        raw_lines = jsonl_file.read_text().strip().split("\n")
        records = [json.loads(line) for line in raw_lines]

        turn_entries = [r for r in records if "turn_number" in r]
        summary = records[-1]
        assert summary["record_type"] == "match_summary"

        # ── Every turn entry has the new fields ──────────────────────
        for entry in turn_entries:
            assert "time_limit_ms" in entry, "missing time_limit_ms"
            assert "time_exceeded" in entry, "missing time_exceeded"
            assert "cumulative_strikes" in entry, "missing cumulative_strikes"
            assert "strike_limit" in entry, "missing strike_limit"
            assert entry["time_limit_ms"] == 10_000
            assert entry["strike_limit"] == 2
            assert entry["schema_version"] == "1.1.0"

        # ── Model-B's turns should all be empty_response forfeits ────
        b_turns = [e for e in turn_entries if e["player_id"] == "player_b"]
        assert len(b_turns) >= 2, f"expected >=2 model-B turns, got {len(b_turns)}"
        for bt in b_turns:
            assert bt["violation"] == "empty_response"
            assert bt["validation_result"] == "forfeit"

        # ── Strikes increment across model-B turns ───────────────────
        b_strikes = [e["cumulative_strikes"] for e in b_turns]
        for i in range(1, len(b_strikes)):
            assert b_strikes[i] >= b_strikes[i - 1], (
                f"strikes should be non-decreasing: {b_strikes}"
            )
        assert b_strikes[-1] == 2, f"final strike count should be 2, got {b_strikes[-1]}"

        # ── The last model-B turn triggers match forfeit ─────────────
        last_b = b_turns[-1]
        assert last_b["ruling"] == "forfeit_match"

        # ── Model-A turns should be clean (no violations) ────────────
        a_turns = [e for e in turn_entries if e["player_id"] == "player_a"]
        for at in a_turns:
            assert at["violation"] is None
            assert at["time_exceeded"] is False
            assert at["cumulative_strikes"] == 0

        # ── Match summary ────────────────────────────────────────────
        assert summary["ruling"] == "match_forfeit"
        assert "forfeit_details" in summary
        fd = summary["forfeit_details"]
        assert fd["forfeiting_player"] == "player_b"
        assert fd["forfeiting_model"] == "model-b"
        assert fd["turn_forfeits"] == 2

        # ── Scores: opponent awarded remaining games ─────────────────
        scores = summary["final_scores"]
        assert scores["player_a"] > scores["player_b"]
        # With 9-game series and match forfeited early, player_a should
        # have gotten credit for remaining games
        assert scores["player_a"] >= 1.0  # at least won 1 game + remaining

        # ── Fidelity report ──────────────────────────────────────────
        fidelity = summary["fidelity_report"]
        assert fidelity["player_b"]["empty_response"] >= 2
        assert fidelity["player_b"]["turn_forfeits"] == 2
        # player_a should be clean
        assert fidelity["player_a"]["total_violations"] == 0

    def test_slow_model_shot_clock_violation_in_telemetry(self, tmp_path):
        """Model exceeds 10s shot clock → time_exceeded: true in JSONL."""
        config = _make_config(
            tmp_path,
            shot_clock=ShotClockConfig(default_ms=10_000),
            forfeit_escalation=ForfeitEscalationConfig(
                turn_forfeit_threshold=1,
                match_forfeit_threshold=2,
            ),
            games_per_match=9,
        )

        fast_adapter = _FakeLatencyAdapter(
            model_id="model-a",
            strategy=_always_valid_ttt_strategy,
            latency_fn=lambda n: 50.0,
        )
        # Model-B: returns valid JSON but reports 15s latency (over 10s clock)
        slow_adapter = _FakeLatencyAdapter(
            model_id="model-b",
            strategy=_always_valid_ttt_strategy,
            latency_fn=lambda n: 15_000.0,  # 15 seconds — over the 10s clock
        )

        engine = _TestEngine(
            config,
            custom_adapters={
                "model-a": fast_adapter,
                "model-b": slow_adapter,
            },
        )
        result = engine.run()

        jsonl_file = list(result.telemetry_dir.glob("*.jsonl"))[0]
        raw_lines = jsonl_file.read_text().strip().split("\n")
        records = [json.loads(line) for line in raw_lines]
        turn_entries = [r for r in records if "turn_number" in r]
        summary = records[-1]

        # Model-B turns should all be timeout violations with time_exceeded
        b_turns = [e for e in turn_entries if e["player_id"] == "player_b"]
        assert len(b_turns) >= 2
        for bt in b_turns:
            assert bt["violation"] == "timeout"
            assert bt["time_exceeded"] is True
            assert bt["time_limit_ms"] == 10_000

        # Match should end in forfeit
        assert summary["ruling"] == "match_forfeit"
        assert summary["forfeit_details"]["forfeiting_model"] == "model-b"

        # Strikes should increment: 1, then 2 (forfeit)
        b_strikes = [e["cumulative_strikes"] for e in b_turns]
        assert b_strikes == [1, 2]

    def test_mixed_failures_accumulate_strikes(self, tmp_path):
        """Mix of empty responses and timeouts both count as strikes."""
        config = _make_config(
            tmp_path,
            shot_clock=ShotClockConfig(default_ms=10_000),
            forfeit_escalation=ForfeitEscalationConfig(
                turn_forfeit_threshold=1,
                match_forfeit_threshold=3,
                strike_violations=["timeout", "empty_response", "malformed_json"],
            ),
            games_per_match=9,
        )

        call_count = {"n": 0}

        def _alternating_flaky(messages, context):
            """Alternates: empty → valid-but-slow → garbage JSON."""
            call_count["n"] += 1
            turn = call_count["n"]
            if turn % 3 == 1:
                return ""           # empty response
            elif turn % 3 == 2:
                return "not json"   # malformed JSON
            else:
                return ""           # empty response again

        fast_adapter = _FakeLatencyAdapter(
            model_id="model-a",
            strategy=_always_valid_ttt_strategy,
            latency_fn=lambda n: 50.0,
        )
        flaky_adapter = _FakeLatencyAdapter(
            model_id="model-b",
            strategy=_alternating_flaky,
            latency_fn=lambda n: 200.0,  # always under clock
        )

        engine = _TestEngine(
            config,
            custom_adapters={
                "model-a": fast_adapter,
                "model-b": flaky_adapter,
            },
        )
        result = engine.run()

        jsonl_file = list(result.telemetry_dir.glob("*.jsonl"))[0]
        raw_lines = jsonl_file.read_text().strip().split("\n")
        records = [json.loads(line) for line in raw_lines]
        summary = records[-1]

        assert summary["ruling"] == "match_forfeit"
        fd = summary["forfeit_details"]
        assert fd["forfeiting_model"] == "model-b"
        assert fd["turn_forfeits"] == 3  # reached the 3-strike limit

        # Verify different violation types all counted
        turn_entries = [r for r in records if "turn_number" in r]
        b_turns = [e for e in turn_entries if e["player_id"] == "player_b"]
        violation_types = {bt["violation"] for bt in b_turns}
        # Should see at least empty_response and malformed_json
        assert "empty_response" in violation_types
        assert "malformed_json" in violation_types
