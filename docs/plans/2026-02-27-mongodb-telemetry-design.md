# MongoDB Telemetry Backend — Design

**Date:** 2026-02-27
**Status:** Approved

## Goal

Add MongoDB Atlas as an optional second telemetry sink alongside existing JSONL.
Never stall a match. Capture wide, query narrow.

## Architecture: Wrapper Sink (Approach A)

A standalone `MongoSink` class that TelemetryLogger delegates to. MongoSink owns
the connection, background writer thread, and all Mongo-specific logic.

### Why not subclass or observer pattern?

- **Subclass** (`MongoTelemetryLogger(TelemetryLogger)`) — tight coupling, hard
  to compose multiple sinks, tournament.py needs conditional instantiation.
- **Observer/event** — over-engineered for one additional sink.
- **Wrapper** — minimal touch to existing code (3 lines in TelemetryLogger),
  MongoSink is independently testable, pattern extends naturally.

## MongoSink (`core/mongo_sink.py`)

```python
class MongoSink:
    def __init__(self, uri: str, db_name: str = "llmtourney", store_prompts: bool = False)
    def log_turn(self, match_id: str, entry: TelemetryEntry, tournament_context: dict)
    def finalize_match(self, match_id: str, scores: dict, fidelity: dict, extra: dict, tournament_context: dict)
    def close(self)
    def __enter__(self) / __exit__()  # context manager
```

### Background Writer

- Daemon thread drains a `queue.Queue`
- Each item: `(collection_name, document | list[document])`
- **Batch writes:** drains up to 50 items per loop iteration, groups by
  collection, uses `insert_many` to reduce Atlas round-trips
- All pymongo errors caught and logged as warnings — never raises
- `close()` sends sentinel, drains remaining items, joins thread

### Prompt Handling

`store_prompts=False` (default): prompts stored as a stub:
```json
{"prompt_hash": "sha256hex", "prompt_chars": 2847, "prompt_tokens": 226}
```

`store_prompts=True`: full prompt text stored. JSONL always gets full prompt.

### Connection Resilience

- `serverSelectionTimeoutMS=5000` on client construction
- If initial connection fails, constructor logs warning and sets `self._disabled = True`
- All public methods check `_disabled` and return immediately (no-op)
- Reconnection not attempted — if Atlas is down, JSONL captures everything

## Collections & Schema

### `turns`

One document per turn. Mirrors TelemetryEntry fields exactly, plus denormalized context.

```
Fields (from TelemetryEntry):
  turn_number, hand_number, street, player_id, model_id, model_version,
  prompt (or prompt stub), raw_output, reasoning_output, parsed_action,
  parse_success, validation_result, violation, ruling, state_snapshot,
  input_tokens, output_tokens, latency_ms, engine_version, prompt_version,
  time_limit_ms, time_exceeded, cumulative_strikes, strike_limit

Added fields:
  match_id, event_type, tournament_name, tier, round, timestamp, schema_version
```

**Indexes:**
- `match_id` (single)
- `model_id` (single)
- `event_type` (single)
- `timestamp` (single)
- `(match_id, turn_number)` compound — for ordered game replay
- Unique compound: `(match_id, turn_number, hand_number, player_id)` — dedup key

### `matches`

One document per match. Mirrors JSONL match summary.

```
Fields (from match summary):
  match_id (unique), final_scores, fidelity_report, engine_version,
  event, player_models, highlight_hands, ruling, forfeit_details

Added fields:
  event_type, tournament_name, tier, round, timestamp, schema_version,
  models (list of model_id strings),
  winner (derived from scores, null if draw),
  total_turns (int),
  total_tokens (int, sum of all players' input + output),
  duration_ms (last turn timestamp - first turn timestamp)
```

**Indexes:**
- `match_id` (unique)
- `event_type` (single)
- `(model_id, event_type)` compound — "how does model X do at Reversi"
- `tournament_name` (single)

### `models`

Aggregate stats per model. Updated via `$inc` / `$set` / `$push` on match finalize.

```
_id: model_id (string)
matches_played, wins, losses, draws
total_violations: {malformed_json, illegal_move, timeout, empty_response, injection_attempts}
total_input_tokens, total_output_tokens
total_latency_ms
last_played: datetime
elo_history: [{timestamp, elo, event_type, opponent}]  # $push on each match
games: {
  "reversi": {matches_played, wins, losses, draws, ...},
  "holdem": {...},
  ...
}
```

**Indexes:** None beyond `_id` — small collection, full scans are fine.

### `tournaments`

One document per tournament run.

```
_id: auto
name, tier, config (YAML snapshot as dict), started_at, completed_at
models: [list of model_ids that participated]
match_ids: [list of match_id strings]
```

**Indexes:** `name` (single).

## Integration Surface

### TelemetryLogger changes (3 touch points)

```python
def __init__(self, output_dir, match_id, mongo_sink=None, tournament_context=None):
    self._sink = mongo_sink
    self._tournament_context = tournament_context or {}
    # ... existing init unchanged

def log_turn(self, entry):
    # ... existing JSONL write unchanged
    if self._sink:
        self._sink.log_turn(self._match_id, entry, self._tournament_context)

def finalize_match(self, scores, fidelity, extra):
    # ... existing JSONL write unchanged
    if self._sink:
        self._sink.finalize_match(self._match_id, scores, fidelity, extra, self._tournament_context)
```

### TournamentEngine changes

**Init:** Create MongoSink if `TOURNEY_MONGO_URI` is set:
```python
uri = os.environ.get("TOURNEY_MONGO_URI")
if uri:
    try:
        self._mongo_sink = MongoSink(uri, store_prompts=...)
    except Exception:
        logger.warning("MongoDB unavailable, continuing JSONL-only")
        self._mongo_sink = None
```

**Match setup:** Pass sink + context to TelemetryLogger constructor.

**Cleanup/finally:** Call `self._mongo_sink.close()` to drain queue on shutdown/crash.

## Query Helpers (`core/mongo_queries.py`)

Standalone functions taking a `pymongo.database.Database`. Return plain dicts.

```python
def get_db(uri=None, db_name="llmtourney") -> Database

def win_rates(db, model_id=None, event_type=None, tier=None) -> list[dict]
    # Pipeline on `matches`. Group by (model_id, event_type), count W/L/D.

def avg_latency(db, model_id=None, event_type=None, tournament_name=None) -> list[dict]
    # Pipeline on `turns`. Group by (model_id, event_type), $avg latency_ms.

def violation_frequency(db, model_id=None, violation=None) -> list[dict]
    # Pipeline on `turns` where violation != null. Group by (model_id, violation).

def head_to_head(db, model_a, model_b, event_type=None) -> dict
    # Query `matches` where both models participated. Return W/L/D counts.

def latency_by_phase(db, model_id, event_type) -> list[dict]
    # Pipeline on `turns`. Percentile-based thirds per match (early/mid/late).
    # Each match's turns divided into 3 equal buckets by turn_number.
    # Meaningful across all game types (9-turn TTT vs 60-turn Reversi).

def token_efficiency(db, model_id=None, event_type=None) -> list[dict]
    # Pipeline on `matches` using denormalized total_tokens.
    # Avg tokens per match grouped by model, correlated with win/loss.
    # No $lookup needed — all data on match doc.

def fidelity_scores(db, event_type=None, tier=None) -> list[dict]
    # Pipeline on `matches`. Sum violations from fidelity_report by model.
    # Compute clean play % (turns without violations / total_turns).
```

## Backfill Script (`scripts/backfill_mongo.py`)

```
python -m scripts.backfill_mongo [--uri URI] [--dir output/telemetry] [--dry-run]
```

- Globs `*.jsonl` from telemetry directory
- Turn entries: bulk `insert_many(..., ordered=False)`, dupes silently dropped
  via compound unique key `(match_id, turn_number, hand_number, player_id)`
- Match summaries: upsert to `matches` on `match_id`
- Model stats: derived from match summaries, upserted to `models`
- Missing tournament context fields default to `"unknown"`
- Progress output: `Processing file 14/87: heavyweight_r2_m3.jsonl...`
- `--dry-run`: parse all files, print counts, write nothing

## Report Script (`scripts/telemetry_report.py`)

```
python -m scripts.telemetry_report [--uri URI] [--event EVENT] [--model MODEL] [--json]
```

Console output: model leaderboard, head-to-head, latency by game, top violators.
Uses formatted f-strings (no new dependency).

`--json` flag: dumps same data as structured JSON to stdout for piping to `jq`,
saving snapshots, or feeding a future dashboard.

## Dependencies

Only addition: `pymongo` as an optional dependency.

```toml
[project.optional-dependencies]
mongo = ["pymongo >= 4.6"]
```

## Constraints

- Python 3.11+
- Non-blocking writes via background thread + queue
- If Mongo is unreachable, silent fallback to JSONL-only
- Telemetry schema version remains 1.1.0 (Mongo mirrors, doesn't extend)
- No ODM — raw pymongo only
