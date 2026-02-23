"""TournamentEngine — orchestrates matches between LLM adapters.

Builds adapters from config, generates round-robin matchups, runs the
game loop (prompt -> query -> sanitize -> parse -> validate -> apply),
logs telemetry, and produces aggregate standings.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from pathlib import Path

import llmtourney
from llmtourney.config import TournamentConfig, ModelConfig, EventConfig
from llmtourney.core.adapter import MockAdapter, ModelAdapter
from llmtourney.core.parser import ActionParser
from llmtourney.core.referee import Referee, Ruling, ViolationKind
from llmtourney.core.sanitizer import sanitize_text
from llmtourney.core.seed import SeedManager
from llmtourney.core.telemetry import TelemetryEntry, TelemetryLogger
from llmtourney.events.holdem.engine import HoldemEvent
from llmtourney.events.holdem.strategies import (
    always_call_strategy,
    garbage_strategy,
    injector_strategy,
    simple_heuristic_strategy,
)

_STRATEGY_REGISTRY = {
    "always_call": always_call_strategy,
    "simple_heuristic": simple_heuristic_strategy,
    "garbage": garbage_strategy,
    "injector": injector_strategy,
}


@dataclass
class MatchResult:
    """Result of a single match between two models."""

    match_id: str
    event: str
    scores: dict[str, float]
    fidelity: dict
    player_models: dict[str, str]  # player_id -> model_name


@dataclass
class TournamentResult:
    """Aggregate result of the entire tournament."""

    telemetry_dir: Path
    matches: list[MatchResult]
    standings: dict[str, float]  # model_name -> aggregate score


class TournamentEngine:
    """Runs a tournament defined by a TournamentConfig."""

    def __init__(self, config: TournamentConfig) -> None:
        self.config = config
        self.seed_mgr = SeedManager(config.seed)
        self.telemetry_dir = self._resolve_telemetry_dir()
        self.adapters: dict[str, ModelAdapter] = self._build_adapters()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self) -> TournamentResult:
        """Execute the full tournament and return results."""
        matches: list[MatchResult] = []
        model_names = list(self.config.models.keys())

        for event_name, event_cfg in self.config.events.items():
            for _round in range(1, event_cfg.rounds + 1):
                for matchup in combinations(model_names, 2):
                    result = self._run_match(
                        event_name, event_cfg, matchup[0], matchup[1]
                    )
                    matches.append(result)

        standings = self._compute_standings(matches)
        return TournamentResult(
            telemetry_dir=self.telemetry_dir,
            matches=matches,
            standings=standings,
        )

    # ------------------------------------------------------------------
    # Internal: setup
    # ------------------------------------------------------------------

    def _resolve_telemetry_dir(self) -> Path:
        """Create and return the telemetry output directory."""
        if self.config.output_dir:
            d = Path(self.config.output_dir) / "telemetry"
        else:
            d = Path("output") / "telemetry"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _build_adapters(self) -> dict[str, ModelAdapter]:
        """Map model configs to concrete adapter instances."""
        adapters: dict[str, ModelAdapter] = {}
        for name, mcfg in self.config.models.items():
            adapters[name] = self._build_adapter(mcfg)
        return adapters

    def _build_adapter(self, mcfg: ModelConfig) -> ModelAdapter:
        """Build a single adapter from a ModelConfig."""
        if mcfg.provider == "mock":
            strategy_fn = _STRATEGY_REGISTRY.get(mcfg.strategy or "")
            if strategy_fn is None:
                raise ValueError(
                    f"Unknown mock strategy: {mcfg.strategy!r}. "
                    f"Available: {list(_STRATEGY_REGISTRY)}"
                )
            return MockAdapter(model_id=mcfg.name, strategy=strategy_fn)
        raise ValueError(f"Unsupported provider: {mcfg.provider!r}")

    def _build_event(self, event_name: str, event_cfg: EventConfig) -> HoldemEvent:
        """Instantiate an event engine from config."""
        # Currently only holdem is supported
        if event_name != "holdem":
            raise ValueError(f"Unknown event: {event_name!r}")
        return HoldemEvent(
            hands_per_match=event_cfg.hands_per_match,
            starting_stack=event_cfg.starting_stack,
            blinds=event_cfg.blinds,
        )

    # ------------------------------------------------------------------
    # Internal: match execution
    # ------------------------------------------------------------------

    def _run_match(
        self,
        event_name: str,
        event_cfg: EventConfig,
        model_a: str,
        model_b: str,
    ) -> MatchResult:
        """Execute a single match between two models."""
        match_id = f"{event_name}-{model_a}-vs-{model_b}"
        seed = self.seed_mgr.get_match_seed(
            event_name, 1, hash(match_id) % 10000
        )

        event = self._build_event(event_name, event_cfg)
        event.reset(seed)

        referee = Referee()
        logger = TelemetryLogger(self.telemetry_dir, match_id)
        parser = ActionParser()
        player_models = {"player_a": model_a, "player_b": model_b}

        turn_number = 0

        while not event.is_terminal():
            referee.new_turn()
            player_id = event.current_player()
            model_name = player_models[player_id]
            adapter = self.adapters[model_name]
            prompt = event.get_prompt(player_id)

            # Capture pre-action state
            snapshot = event.get_state_snapshot()

            # Query model
            response = adapter.query(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=self.config.compute_caps.max_output_tokens,
                timeout_s=self.config.compute_caps.timeout_s,
                context={"seed": seed},
            )
            raw_text = sanitize_text(response.raw_text)
            parsed = parser.parse(raw_text, event.action_schema)

            violation = None
            ruling = None

            # Handle parse failure with retry
            if not parsed.success:
                ruling_enum = referee.record_violation(
                    player_id,
                    ViolationKind.MALFORMED_JSON,
                    severity=2,
                    details=parsed.error or "unknown parse error",
                )
                violation = ViolationKind.MALFORMED_JSON.value
                ruling = ruling_enum.value

                if (
                    ruling_enum == Ruling.RETRY
                    and referee.should_retry(player_id)
                ):
                    referee.consume_retry(player_id)
                    retry_prompt = event.get_retry_prompt(
                        player_id, parsed.error or "malformed JSON"
                    )
                    response = adapter.query(
                        messages=[{"role": "user", "content": retry_prompt}],
                        max_tokens=self.config.compute_caps.max_output_tokens,
                        timeout_s=self.config.compute_caps.timeout_s,
                        context={"seed": seed},
                    )
                    raw_text = sanitize_text(response.raw_text)
                    parsed = parser.parse(raw_text, event.action_schema)

                if not parsed.success:
                    turn_number += 1
                    self._log_turn(
                        logger,
                        turn_number=turn_number,
                        snapshot=snapshot,
                        player_id=player_id,
                        response=response,
                        prompt=prompt,
                        raw_text=raw_text,
                        parsed=parsed,
                        validation_result="forfeit",
                        violation=violation,
                        ruling=ruling,
                    )
                    event.forfeit_turn(player_id)
                    continue

            # Validate game legality
            validation = event.validate_action(player_id, parsed.action)
            if not validation.legal:
                ruling_enum = referee.record_violation(
                    player_id,
                    ViolationKind.ILLEGAL_MOVE,
                    severity=1,
                    details=validation.reason or "illegal move",
                )
                violation = ViolationKind.ILLEGAL_MOVE.value
                ruling = ruling_enum.value

                if (
                    ruling_enum == Ruling.RETRY
                    and referee.should_retry(player_id)
                ):
                    referee.consume_retry(player_id)
                    retry_prompt = event.get_retry_prompt(
                        player_id, validation.reason or "illegal move"
                    )
                    response = adapter.query(
                        messages=[{"role": "user", "content": retry_prompt}],
                        max_tokens=self.config.compute_caps.max_output_tokens,
                        timeout_s=self.config.compute_caps.timeout_s,
                        context={"seed": seed},
                    )
                    raw_text = sanitize_text(response.raw_text)
                    parsed = parser.parse(raw_text, event.action_schema)
                    if parsed.success:
                        validation = event.validate_action(
                            player_id, parsed.action
                        )

                if not parsed.success or not validation.legal:
                    turn_number += 1
                    self._log_turn(
                        logger,
                        turn_number=turn_number,
                        snapshot=snapshot,
                        player_id=player_id,
                        response=response,
                        prompt=prompt,
                        raw_text=raw_text,
                        parsed=parsed,
                        validation_result="forfeit",
                        violation=violation,
                        ruling=ruling,
                    )
                    event.forfeit_turn(player_id)
                    continue

            # Check for injection
            if parsed.injection_detected:
                referee.record_violation(
                    player_id,
                    ViolationKind.INJECTION_ATTEMPT,
                    severity=3,
                    details="injection pattern detected",
                )
                violation = ViolationKind.INJECTION_ATTEMPT.value

            # Apply the valid action
            event.apply_action(player_id, parsed.action)

            turn_number += 1
            self._log_turn(
                logger,
                turn_number=turn_number,
                snapshot=snapshot,
                player_id=player_id,
                response=response,
                prompt=prompt,
                raw_text=raw_text,
                parsed=parsed,
                validation_result="legal",
                violation=violation,
                ruling=ruling,
            )

        # Finalize
        scores = event.get_scores()
        fidelity = referee.get_fidelity_report()

        # Ensure fidelity report has entries for both players even if clean
        for pid in ("player_a", "player_b"):
            if pid not in fidelity:
                fidelity[pid] = {
                    "total_violations": 0,
                    "malformed_json": 0,
                    "illegal_move": 0,
                    "timeout": 0,
                    "injection_attempts": 0,
                    "total_severity": 0,
                    "retries_used": 0,
                }

        logger.finalize_match(
            scores=scores,
            fidelity=fidelity,
            extra={
                "event": event_name,
                "player_models": player_models,
                "highlight_hands": event.get_highlight_hands(),
            },
        )

        return MatchResult(
            match_id=match_id,
            event=event_name,
            scores=scores,
            fidelity=fidelity,
            player_models=player_models,
        )

    # ------------------------------------------------------------------
    # Internal: telemetry
    # ------------------------------------------------------------------

    def _log_turn(
        self,
        logger: TelemetryLogger,
        *,
        turn_number: int,
        snapshot: dict,
        player_id: str,
        response,
        prompt: str,
        raw_text: str,
        parsed,
        validation_result: str,
        violation: str | None,
        ruling: str | None,
    ) -> None:
        """Write a single turn entry to the telemetry log."""
        entry = TelemetryEntry(
            turn_number=turn_number,
            hand_number=snapshot.get("hand_number", 0),
            street=snapshot.get("street", "unknown"),
            player_id=player_id,
            model_id=response.model_id,
            model_version=response.model_version,
            prompt=prompt,
            raw_output=raw_text,
            reasoning_output=response.reasoning_text,
            parsed_action=parsed.action,
            parse_success=parsed.success,
            validation_result=validation_result,
            violation=violation,
            ruling=ruling,
            state_snapshot=snapshot,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            latency_ms=response.latency_ms,
            engine_version=llmtourney.__version__,
            prompt_version="1.0.0",
        )
        logger.log_turn(entry)

    # ------------------------------------------------------------------
    # Internal: standings
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_standings(matches: list[MatchResult]) -> dict[str, float]:
        """Aggregate chip scores by model across all matches."""
        standings: dict[str, float] = {}
        for match in matches:
            for pid, model_name in match.player_models.items():
                score = match.scores.get(pid, 0.0)
                standings[model_name] = standings.get(model_name, 0.0) + score
        return standings
