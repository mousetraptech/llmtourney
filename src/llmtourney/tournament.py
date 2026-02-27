"""TournamentEngine — orchestrates matches between LLM adapters.

Builds adapters from config, generates round-robin matchups, runs the
game loop (prompt -> query -> sanitize -> parse -> validate -> apply),
logs telemetry, and produces aggregate standings.
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path

import llmtourney
from llmtourney.config import TournamentConfig, ModelConfig, EventConfig
from llmtourney.core.adapter import AdapterError, AdapterResponse, MockAdapter, ModelAdapter
from llmtourney.core.openai_adapter import OpenAIAdapter
from llmtourney.core.anthropic_adapter import AnthropicAdapter
from llmtourney.core.openrouter_adapter import OpenRouterAdapter
from llmtourney.core.parser import ActionParser
from llmtourney.core.referee import Referee, Ruling, ViolationKind
from llmtourney.core.sanitizer import sanitize_text
from llmtourney.core.seed import SeedManager
from llmtourney.core.telemetry import TelemetryEntry, TelemetryLogger
from llmtourney.events.base import Event
from llmtourney.events.holdem.engine import HoldemEvent
from llmtourney.events.holdem.strategies import (
    always_call_strategy,
    garbage_strategy,
    injector_strategy,
    simple_heuristic_strategy,
)
from llmtourney.events.checkers.engine import CheckersEvent
from llmtourney.events.scrabble.engine import ScrabbleEvent
from llmtourney.events.tictactoe.engine import TicTacToeEvent
from llmtourney.events.connectfour.engine import ConnectFourEvent
from llmtourney.events.reversi.engine import ReversiEvent
from llmtourney.events.bullshit.engine import BullshitEvent

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

        api_key = self._resolve_api_key(mcfg)

        if mcfg.provider == "openai":
            return OpenAIAdapter(
                model_id=mcfg.model_id or mcfg.name,
                api_key=api_key,
                base_url=mcfg.base_url,
                temperature=mcfg.temperature,
            )
        if mcfg.provider == "anthropic":
            return AnthropicAdapter(
                model_id=mcfg.model_id or mcfg.name,
                api_key=api_key,
                temperature=mcfg.temperature,
            )
        if mcfg.provider == "openrouter":
            return OpenRouterAdapter(
                model_id=mcfg.model_id or mcfg.name,
                api_key=api_key,
                temperature=mcfg.temperature,
                site_url=mcfg.site_url,
                app_name=mcfg.app_name,
            )
        raise ValueError(f"Unsupported provider: {mcfg.provider!r}")

    def _resolve_api_key(self, mcfg: ModelConfig) -> str:
        """Resolve API key from environment variable."""
        if not mcfg.api_key_env:
            raise ValueError(
                f"Model {mcfg.name!r}: api_key_env is required for "
                f"provider {mcfg.provider!r}"
            )
        key = os.environ.get(mcfg.api_key_env)
        if not key:
            raise ValueError(
                f"Model {mcfg.name!r}: env var {mcfg.api_key_env!r} is not set"
            )
        return key

    def _safe_query(
        self, adapter, messages: list[dict[str, str]], model_name: str, seed: int
    ) -> tuple[AdapterResponse, bool]:
        """Call adapter.query, catching AdapterError.

        Returns (response, success). On failure, returns a dummy response.
        """
        try:
            response = adapter.query(
                messages=messages,
                max_tokens=self.config.compute_caps.max_output_tokens,
                timeout_s=self.config.compute_caps.timeout_s,
                context={"seed": seed},
            )
            return response, True
        except AdapterError as exc:
            print(f"[WARN] adapter error for {model_name}: {exc}")
            return AdapterResponse(
                raw_text="",
                reasoning_text=None,
                input_tokens=0,
                output_tokens=0,
                latency_ms=0.0,
                model_id=model_name,
                model_version=model_name,
            ), False
        except Exception as exc:
            print(f"[WARN] unexpected error querying {model_name}: {exc}")
            return AdapterResponse(
                raw_text="",
                reasoning_text=None,
                input_tokens=0,
                output_tokens=0,
                latency_ms=0.0,
                model_id=model_name,
                model_version=model_name,
            ), False

    def _build_event(self, event_name: str, event_cfg: EventConfig) -> Event:
        """Instantiate an event engine from config."""
        if event_name == "checkers":
            return CheckersEvent(games_per_match=event_cfg.games_per_match)
        if event_name == "holdem":
            return HoldemEvent(
                hands_per_match=event_cfg.hands_per_match,
                starting_stack=event_cfg.starting_stack,
                blinds=event_cfg.blinds,
                blind_schedule=event_cfg.blind_schedule,
            )
        if event_name == "scrabble":
            return ScrabbleEvent()
        if event_name == "tictactoe":
            return TicTacToeEvent(games_per_match=event_cfg.games_per_match)
        if event_name == "connectfour":
            return ConnectFourEvent(games_per_match=event_cfg.games_per_match)
        if event_name == "reversi":
            return ReversiEvent(games_per_match=event_cfg.games_per_match)
        if event_name == "bullshit":
            return BullshitEvent(games_per_match=event_cfg.games_per_match)
        raise ValueError(f"Unknown event: {event_name!r}")

    def _get_time_limit_ms(self, model_name: str) -> int | None:
        """Resolve per-model shot clock limit, or None if disabled."""
        sc = self.config.shot_clock
        if sc is None:
            return None
        return sc.model_overrides.get(model_name, sc.default_ms)

    # ------------------------------------------------------------------
    # Internal: match execution
    # ------------------------------------------------------------------

    def _run_match(
        self,
        event_name: str,
        event_cfg: EventConfig,
        model_a: str,
        model_b: str,
        match_id: str | None = None,
    ) -> MatchResult:
        """Execute a single match between two models."""
        return self._run_multiplayer_match(
            event_name, event_cfg, [model_a, model_b], match_id=match_id,
        )

    def _run_multiplayer_match(
        self,
        event_name: str,
        event_cfg: EventConfig,
        models: list[str],
        match_id: str | None = None,
    ) -> MatchResult:
        """Execute a match with N players."""
        if match_id is None:
            short_id = uuid.uuid4().hex[:6]
            match_id = f"{event_name}-{'-vs-'.join(models)}-{short_id}"
        deterministic_key = f"{event_name}-{'-vs-'.join(models)}"
        seed = self.seed_mgr.get_match_seed(
            event_name, 1, hash(deterministic_key) % 10000
        )

        event = self._build_event(event_name, event_cfg)
        event.reset(seed)

        player_ids = event.player_ids
        if len(models) != len(player_ids):
            raise ValueError(
                f"Event {event_name!r} requires {len(player_ids)} players, got {len(models)}"
            )

        referee = Referee(escalation=self.config.forfeit_escalation)
        logger = TelemetryLogger(self.telemetry_dir, match_id)
        parser = ActionParser()
        player_models = dict(zip(player_ids, models))

        turn_number = 0
        match_forfeit_ruling: str | None = None  # "completed" or "match_forfeit"

        # Stuck-loop detection: 3 consecutive violations of the same kind
        # triggers match forfeit. Independent safety net alongside escalation.
        _last_violation_key: dict[str, tuple] = {}
        _violation_streak: dict[str, int] = {pid: 0 for pid in player_ids}
        STUCK_LOOP_LIMIT = 3

        def _check_stuck_loop(pid: str, vtype: str, action: dict | None = None):
            """Increment streak and force-forfeit if stuck."""
            if action and vtype == "illegal_move":
                vkey = (vtype, action.get("word", ""), str(action.get("position", "")))
            else:
                vkey = (vtype, "", "")
            if vkey == _last_violation_key.get(pid):
                _violation_streak[pid] += 1
            else:
                _violation_streak[pid] = 1
                _last_violation_key[pid] = vkey
            if _violation_streak[pid] >= STUCK_LOOP_LIMIT:
                event.award_forfeit_wins(pid)

        def _handle_forfeit_turn(
            pid: str, vkind: ViolationKind
        ) -> bool:
            """Record turn forfeit via escalation. Returns True if match forfeited."""
            nonlocal match_forfeit_ruling
            escalation_ruling = referee.record_turn_forfeit(pid, vkind)
            if escalation_ruling == Ruling.FORFEIT_MATCH:
                event.award_forfeit_wins(pid)
                match_forfeit_ruling = "match_forfeit"
                print(
                    f"[FORFEIT] {player_models[pid]} forfeits match "
                    f"({referee.get_strikes(pid)} strikes)"
                )
                return True
            return False

        def _telemetry_extras(pid: str, time_limit: int | None, time_exceeded: bool):
            """Build shot clock / escalation telemetry kwargs."""
            return {
                "time_limit_ms": time_limit,
                "time_exceeded": time_exceeded,
                "cumulative_strikes": referee.get_strikes(pid),
                "strike_limit": referee.match_forfeit_threshold,
            }

        while not event.is_terminal():
            referee.new_turn()
            player_id = event.current_player()
            model_name = player_models[player_id]
            adapter = self.adapters[model_name]
            time_limit_ms = self._get_time_limit_ms(model_name)
            prompt = event.get_prompt(player_id)

            # Inject shot clock notice into prompt
            if time_limit_ms is not None:
                strikes = referee.get_strikes(player_id)
                threshold = referee.match_forfeit_threshold or "N/A"
                clock_notice = (
                    f"\n[TIME LIMIT: {time_limit_ms}ms per turn. "
                    f"Exceeding this forfeits your turn. "
                    f"Strikes: {strikes}/{threshold}. "
                    f"Reaching {threshold} forfeits the match.]"
                )
                prompt = prompt + clock_notice

            # Query model
            response, query_ok = self._safe_query(
                adapter, [{"role": "user", "content": prompt}], model_name, seed
            )
            if not query_ok:
                referee.record_violation(
                    player_id, ViolationKind.TIMEOUT, severity=2,
                    details="adapter error",
                )
                event.forfeit_turn(player_id)
                if _handle_forfeit_turn(player_id, ViolationKind.TIMEOUT):
                    snapshot = event.get_state_snapshot()
                    turn_number += 1
                    self._log_turn(
                        logger,
                        turn_number=turn_number,
                        snapshot=snapshot,
                        player_id=player_id,
                        response=response,
                        prompt=prompt,
                        raw_text="",
                        parsed=parser.parse("", event.action_schema),
                        validation_result="forfeit",
                        violation=ViolationKind.TIMEOUT.value,
                        ruling=Ruling.FORFEIT_MATCH.value,
                        **_telemetry_extras(player_id, time_limit_ms, False),
                    )
                    break
                snapshot = event.get_state_snapshot()
                turn_number += 1
                self._log_turn(
                    logger,
                    turn_number=turn_number,
                    snapshot=snapshot,
                    player_id=player_id,
                    response=response,
                    prompt=prompt,
                    raw_text="",
                    parsed=parser.parse("", event.action_schema),
                    validation_result="forfeit",
                    violation=ViolationKind.TIMEOUT.value,
                    ruling=Ruling.FORFEIT_TURN.value,
                    **_telemetry_extras(player_id, time_limit_ms, False),
                )
                _check_stuck_loop(player_id, "timeout")
                continue

            raw_text = response.raw_text or ""
            time_exceeded = False

            # Shot clock check (post-hoc): discard response if over time
            if time_limit_ms is not None and response.latency_ms > time_limit_ms:
                time_exceeded = True
                referee.record_violation(
                    player_id, ViolationKind.TIMEOUT, severity=2,
                    details=f"shot clock exceeded: {response.latency_ms:.0f}ms > {time_limit_ms}ms",
                )
                event.forfeit_turn(player_id)
                if _handle_forfeit_turn(player_id, ViolationKind.TIMEOUT):
                    snapshot = event.get_state_snapshot()
                    turn_number += 1
                    self._log_turn(
                        logger,
                        turn_number=turn_number,
                        snapshot=snapshot,
                        player_id=player_id,
                        response=response,
                        prompt=prompt,
                        raw_text=raw_text,
                        parsed=parser.parse("", event.action_schema),
                        validation_result="forfeit",
                        violation=ViolationKind.TIMEOUT.value,
                        ruling=Ruling.FORFEIT_MATCH.value,
                        **_telemetry_extras(player_id, time_limit_ms, True),
                    )
                    break
                snapshot = event.get_state_snapshot()
                turn_number += 1
                self._log_turn(
                    logger,
                    turn_number=turn_number,
                    snapshot=snapshot,
                    player_id=player_id,
                    response=response,
                    prompt=prompt,
                    raw_text=raw_text,
                    parsed=parser.parse("", event.action_schema),
                    validation_result="forfeit",
                    violation=ViolationKind.TIMEOUT.value,
                    ruling=Ruling.FORFEIT_TURN.value,
                    **_telemetry_extras(player_id, time_limit_ms, True),
                )
                _check_stuck_loop(player_id, "timeout")
                continue

            # Empty response check (before parsing)
            if not raw_text.strip():
                referee.record_violation(
                    player_id, ViolationKind.EMPTY_RESPONSE, severity=2,
                    details="empty or whitespace-only response",
                )
                event.forfeit_turn(player_id)
                if _handle_forfeit_turn(player_id, ViolationKind.EMPTY_RESPONSE):
                    snapshot = event.get_state_snapshot()
                    turn_number += 1
                    self._log_turn(
                        logger,
                        turn_number=turn_number,
                        snapshot=snapshot,
                        player_id=player_id,
                        response=response,
                        prompt=prompt,
                        raw_text=raw_text,
                        parsed=parser.parse("", event.action_schema),
                        validation_result="forfeit",
                        violation=ViolationKind.EMPTY_RESPONSE.value,
                        ruling=Ruling.FORFEIT_MATCH.value,
                        **_telemetry_extras(player_id, time_limit_ms, False),
                    )
                    break
                snapshot = event.get_state_snapshot()
                turn_number += 1
                self._log_turn(
                    logger,
                    turn_number=turn_number,
                    snapshot=snapshot,
                    player_id=player_id,
                    response=response,
                    prompt=prompt,
                    raw_text=raw_text,
                    parsed=parser.parse("", event.action_schema),
                    validation_result="forfeit",
                    violation=ViolationKind.EMPTY_RESPONSE.value,
                    ruling=Ruling.FORFEIT_TURN.value,
                    **_telemetry_extras(player_id, time_limit_ms, False),
                )
                _check_stuck_loop(player_id, "empty_response")
                continue

            raw_text = sanitize_text(raw_text)
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
                    response, retry_ok = self._safe_query(
                        adapter,
                        [{"role": "user", "content": retry_prompt}],
                        model_name, seed,
                    )
                    if retry_ok:
                        raw_text = sanitize_text(response.raw_text)
                        parsed = parser.parse(raw_text, event.action_schema)
                    else:
                        raw_text = ""
                        parsed = parser.parse("", event.action_schema)

                if not parsed.success:
                    event.forfeit_turn(player_id)
                    if _handle_forfeit_turn(player_id, ViolationKind.MALFORMED_JSON):
                        snapshot = event.get_state_snapshot()
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
                            ruling=Ruling.FORFEIT_MATCH.value,
                            **_telemetry_extras(player_id, time_limit_ms, False),
                        )
                        break
                    snapshot = event.get_state_snapshot()
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
                        **_telemetry_extras(player_id, time_limit_ms, False),
                    )
                    _check_stuck_loop(player_id, "malformed_json")
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
                    response, retry_ok = self._safe_query(
                        adapter,
                        [{"role": "user", "content": retry_prompt}],
                        model_name, seed,
                    )
                    if retry_ok:
                        raw_text = sanitize_text(response.raw_text)
                        parsed = parser.parse(raw_text, event.action_schema)
                    else:
                        raw_text = ""
                        parsed = parser.parse("", event.action_schema)
                    if parsed.success:
                        validation = event.validate_action(
                            player_id, parsed.action
                        )

                if not parsed.success or not validation.legal:
                    event.forfeit_turn(player_id)
                    if _handle_forfeit_turn(player_id, ViolationKind.ILLEGAL_MOVE):
                        snapshot = event.get_state_snapshot()
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
                            ruling=Ruling.FORFEIT_MATCH.value,
                            **_telemetry_extras(player_id, time_limit_ms, False),
                        )
                        break
                    snapshot = event.get_state_snapshot()
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
                        **_telemetry_extras(player_id, time_limit_ms, False),
                    )
                    _check_stuck_loop(
                        player_id, "illegal_move",
                        parsed.action if parsed.success else None,
                    )
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

            # Apply the valid action — reset stuck-loop tracking
            _violation_streak[player_id] = 0
            _last_violation_key.pop(player_id, None)
            event.apply_action(player_id, parsed.action)
            snapshot = event.get_state_snapshot()

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
                **_telemetry_extras(player_id, time_limit_ms, False),
            )

        # Finalize
        scores = event.get_scores()
        fidelity = referee.get_fidelity_report()

        # Ensure fidelity report has entries for all players even if clean
        for pid in player_ids:
            if pid not in fidelity:
                fidelity[pid] = {
                    "total_violations": 0,
                    "malformed_json": 0,
                    "illegal_move": 0,
                    "timeout": 0,
                    "empty_response": 0,
                    "injection_attempts": 0,
                    "total_severity": 0,
                    "retries_used": 0,
                    "turn_forfeits": 0,
                }

        # Build match summary extras
        match_extra: dict = {
            "event": event_name,
            "player_models": player_models,
            "highlight_hands": event.get_highlight_hands(),
            "ruling": match_forfeit_ruling or "completed",
        }
        forfeit_player = referee.get_match_forfeit_player()
        if forfeit_player:
            match_extra["forfeit_details"] = {
                "forfeiting_player": forfeit_player,
                "forfeiting_model": player_models[forfeit_player],
                "turn_forfeits": referee.get_strikes(forfeit_player),
            }

        logger.finalize_match(
            scores=scores,
            fidelity=fidelity,
            extra=match_extra,
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
        time_limit_ms: int | None = None,
        time_exceeded: bool = False,
        cumulative_strikes: int = 0,
        strike_limit: int | None = None,
    ) -> None:
        """Write a single turn entry to the telemetry log."""
        # Prefer native adapter reasoning (thinking blocks, o1); fall back
        # to in-JSON "reasoning" field if the model included one.
        reasoning = response.reasoning_text
        if not reasoning and parsed.action:
            reasoning = parsed.action.get("reasoning")

        entry = TelemetryEntry(
            turn_number=turn_number,
            hand_number=snapshot.get("hand_number", 0),
            street=snapshot.get("street", "unknown"),
            player_id=player_id,
            model_id=response.model_id,
            model_version=response.model_version,
            prompt=prompt,
            raw_output=raw_text,
            reasoning_output=reasoning,
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
            time_limit_ms=time_limit_ms,
            time_exceeded=time_exceeded,
            cumulative_strikes=cumulative_strikes,
            strike_limit=strike_limit,
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
