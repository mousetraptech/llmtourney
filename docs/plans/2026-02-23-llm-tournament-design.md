# LLM Tournament of Champions — Design Document

**Date:** 2026-02-23
**Status:** Approved
**Scope:** Phase 1 (Foundation) + Phase 2 (Hold'em only)

## Overview

A reproducible, auditable, multi-event competitive framework where LLMs compete head-to-head. Phase 1 builds the foundation infrastructure. Phase 2 delivers the first event (Pot-Limit Hold'em) as a vertical slice proving the architecture.

## Repo Layout

```
llmtourney/
├── pyproject.toml
├── tournament.yaml.example
├── docs/plans/
├── lexicon/                          # Scrabble lexicon (future)
├── src/llmtourney/
│   ├── core/
│   │   ├── seed.py                   # SeedManager
│   │   ├── adapter.py                # ModelAdapter ABC + Mock/OpenAI/Anthropic
│   │   ├── parser.py                 # ActionParser
│   │   ├── telemetry.py              # TelemetryLogger
│   │   ├── sanitizer.py              # Text sanitization + injection detection
│   │   ├── referee.py                # Violation tracking + penalties
│   │   └── schemas.py                # Schema loading utility
│   ├── events/
│   │   ├── base.py                   # Event ABC
│   │   └── holdem/
│   │       ├── engine.py             # Pot-limit Hold'em game logic
│   │       ├── evaluator.py          # Hand evaluation (stdlib only)
│   │       └── schema.json           # Action JSON Schema
│   ├── scoring/                      # Phase 3 (future)
│   ├── judges/                       # Phase 4 (future)
│   ├── reporting/                    # Phase 5 (future)
│   └── tournament.py                 # TournamentEngine
├── schemas/
│   ├── holdem_action.json
│   ├── match_log_entry.json
│   └── tournament_config.json
├── tests/
│   ├── conftest.py
│   ├── test_seed.py
│   ├── test_adapter.py
│   ├── test_parser.py
│   ├── test_telemetry.py
│   ├── test_sanitizer.py
│   ├── test_holdem_engine.py
│   ├── test_holdem_evaluator.py
│   ├── test_referee.py
│   ├── test_tournament_holdem.py
│   └── test_determinism.py
└── output/                           # .gitignored
```

## Key Interfaces

### SeedManager

HMAC-derived seeds from tournament_seed + event/round/match identifiers. Returns isolated `random.Random` instances. Adding matches never shifts existing seeds.

### ModelAdapter (ABC)

```python
class ModelAdapter(ABC):
    def query(self, messages: list[dict], max_tokens: int,
              timeout_s: float) -> AdapterResponse: ...

@dataclass(frozen=True)
class AdapterResponse:
    raw_text: str
    reasoning_text: str | None   # logged only, never enters game engine
    input_tokens: int
    output_tokens: int
    latency_ms: float
    model_id: str
    model_version: str
```

Implementations: MockAdapter (strategy callable), OpenAIAdapter, AnthropicAdapter.

### ActionParser

Extracts first valid JSON object from raw text. Validates against per-event JSON Schema. Returns ParseResult with success/failure, parsed action, and injection detection flag.

### Event (ABC)

```python
class Event(ABC):
    def reset(self, seed: int) -> None: ...
    def get_prompt(self, player_id: str) -> str: ...
    def validate_action(self, player_id: str, action: dict) -> ValidationResult: ...
    def apply_action(self, player_id: str, action: dict) -> None: ...
    def is_terminal(self) -> bool: ...
    def get_scores(self) -> dict[str, float]: ...
    def get_state_snapshot(self) -> dict: ...
    def action_schema(self) -> dict: ...  # property
```

### Referee

Standalone per match. Tracks violations by player, kind, severity. Ruling: RETRY (once per turn), FORFEIT_TURN, FORFEIT_MATCH. Produces fidelity report.

### TelemetryLogger

JSONL writer. One line per turn, match summary as final line. All entries versioned (engine, prompt, model, schema).

### TournamentEngine

Orchestrates: config parsing, adapter construction, event construction, match scheduling (round-robin for heads-up events), match execution loop, scoring.

## Hold'em Engine Design

- **Format:** Pot-limit, heads-up, 100 hands per match, seat rotation every hand
- **Stacks:** 200 chips each (100 BB)
- **Blinds:** 1/2
- **Betting:** Min raise = last raise size or BB. Max raise = current pot.
- **Hand evaluator:** Stdlib-only. Enumerate C(7,5)=21 combos, score as category<<20|kickers.
- **State machine:** DEAL_HOLE -> PRE_FLOP_BET -> DEAL_FLOP -> FLOP_BET -> DEAL_TURN -> TURN_BET -> DEAL_RIVER -> RIVER_BET -> SHOWDOWN
- **Forfeit turn:** Check if free, fold otherwise.
- **Highlights:** Big pot (>3x avg), all-in, comeback (>20% chips), bluff success (river raise win without showdown).

### Action Schema

```json
{
  "type": "object",
  "properties": {
    "action": {"type": "string", "enum": ["fold", "call", "raise"]},
    "amount": {"type": "integer", "minimum": 0}
  },
  "required": ["action"],
  "if": {"properties": {"action": {"const": "raise"}}},
  "then": {"required": ["action", "amount"]},
  "additionalProperties": false
}
```

### Mock Strategies

- **AlwaysCall:** Calls every bet, never raises, never folds.
- **SimpleHeuristic:** Raises top hands, calls medium, folds trash. Deterministic given seed.

## Telemetry Schema

Each JSONL line contains: schema_version, match_id, event, turn_number, hand_number, street, player_id, model_id, model_version, prompt, raw_output, reasoning_output, parsed_action, parse_success, validation_result, violation, ruling, state_snapshot, input_tokens, output_tokens, latency_ms, timestamp, engine_version, prompt_version.

Match summary final line adds: seed, players, hands_played, final_scores, winner, fidelity_report, total_tokens, total_latency_ms, highlight_hands, duration_s.

## Dependencies

| Package | Purpose |
|---------|---------|
| pyyaml | Tournament config parsing |
| jsonschema | Action + telemetry schema validation |
| pytest | Testing |

All other imports are stdlib.

## Retry & Forfeit Flow

One retry per turn. Malformed JSON (sev=2) or illegal move (sev=1) triggers retry. Second failure same turn forfeits the turn. Injection attempts (sev=3) are logged but action still processed if otherwise legal. Violations accumulate in fidelity report.

## Testing Plan

1. **Determinism:** Same seed + same mocks = identical telemetry
2. **Hand evaluator:** All 10 categories, tiebreakers, edge cases
3. **Engine state:** Blinds, pot-limit bounds, all-in, fold, street transitions, bust-out
4. **ActionParser:** Clean JSON, embedded JSON, malformed, schema failures, empty input
5. **Injection detection:** Known patterns flagged, legitimate text not flagged
6. **Referee:** Retry logic, forfeit logic, escalation, fidelity report accuracy
7. **Telemetry:** JSONL validity, required fields, version stamps
8. **Integration:** Full 100-hand match with mocks, chip conservation, no violations from clean mocks, violations from adversarial mock

## Expansion Strategy

- **New event:** Implement Event ABC, add schema, add config section, register. Zero core changes.
- **New model:** Add config entry. New provider = one ModelAdapter subclass.
- **Seasons:** Each run is self-contained. Season = a config YAML.

## Locked Decisions (Reference)

- Poker: heads-up, pot-limit, fixed hand count, seat rotation
- Compute: equal caps per move (max tokens + timeout), logged
- Debate scoring: 70% factuality / 30% structure
- Diplomacy: max 3 messages/turn, 150 tokens each, sanitized
- Scoring: TrueSkill per event, weights (H=3, M=2, B=1), bootstrap CI
- Judges: min 3 models, temp=0, blinded, median aggregation, anchor cases
