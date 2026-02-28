---
name: llmtourney
description: >
  Analyze LLM Tourney data — a tournament system where AI models compete in classic games
  (holdem, connect four, reversi, tic-tac-toe, checkers, scrabble, bullshit, liar's dice, roller derby). Use this skill
  whenever the user asks about tournament results, model performance, win rates, head-to-head
  matchups, violations, fidelity, leaderboards, game-specific stats, or anything related to
  LLM Tourney. Also trigger when the user mentions model matchups, AI game competitions,
  "which model is best at X", forfeit rates, or wants dashboards/visualizations of tournament
  data. The data lives in a local MongoDB instance. Source code is at ~/projects/play-games/llmtourney.
---

# LLM Tourney Skill

LLM Tourney is Dave's tournament system where AI language models compete head-to-head (and multiplayer) in classic board and card games. Each model receives game state as a structured prompt and must respond with valid JSON moves. A referee system tracks violations, enforces rules, and escalates penalties up to match forfeit. All results flow into MongoDB for analysis.

This skill helps Claude query, analyze, and visualize tournament data.

## Quick Reference

- **MongoDB**: `mongodb://localhost:27017`, database: `llmtourney`
- **Collections**: `models`, `matches`, `turns`
- **Source code**: `~/projects/play-games/llmtourney`
- **Spectator UI**: `http://localhost:8080` (when running)
- **Config files**: `~/projects/play-games/llmtourney/configs/*.yaml`

## Games

| Game | Type | Players | Scoring | Key Mechanic |
|------|------|---------|---------|--------------|
| **holdem** | Card | 2-9 | Chip count (continuous) | Blind schedule escalation, position play, pot odds |
| **connectfour** | Board | 2 | Binary win/loss/draw | Column drops, 4-in-a-row |
| **reversi** | Board | 2 | Piece count (continuous) | Flipping mechanics, corner control |
| **tictactoe** | Board | 2 | Best-of-N series (games_per_match) | Simple but reveals JSON compliance |
| **checkers** | Board | 2 | Binary win/loss/draw | Multi-jump captures, king promotion |
| **scrabble** | Word | 2 | Point total (continuous) | Tile placement, word validation — hardest for LLMs |
| **bullshit** | Card | 2-6 | Elimination scoring | Deception, bluff-calling, card counting |
| **liarsdice** | Dice | 2-9 | Elimination scoring | Bluffing, probability, bid escalation |
| **rollerderby** | Dice | 2-9 | Rank-based (N-1 for 1st) | Yahtzee-style scoring, category selection, rerolls |

### Scoring Nuance

Holdem uses chip-based scoring — a model can win by accumulating chips over many hands, so the final score is a chip count, not binary. Tic-tac-toe uses best-of-N series (typically 9 games per match) where the match winner has the most game wins. Roller Derby (internally "yahtzee") uses rank-based scoring: N-1 points for 1st, N-2 for 2nd, etc., with ties sharing averaged positions. Other games use their natural scoring (piece count for reversi, points for scrabble, elimination order for bullshit/liarsdice).

## Tournament Structure

### Tiers

Models are grouped into weight classes reflecting their compute budgets:

| Tier | Token Limit | Shot Clock | Typical Models |
|------|-------------|------------|----------------|
| **Heavyweight** | 2048 tokens | 120s | claude-opus-4.6, gpt-5, gemini-2.5-pro |
| **Midtier** | 512 tokens | 45s | claude-sonnet-4.5, grok-3-mini, deepseek-v3.2 |
| **Flyweight** | 512 tokens | 45s | haiku-3.5, gpt-4o-mini, llama-4-scout |

Cross-tier matches happen in mixed events (like 9-player holdem) where all tiers sit at the same table.

### Formats

- **round_robin**: Every model plays every other model. Standard for 2-player games.
- **bracket**: Elimination-style. Used for larger fields and championships.
- **single match**: One-off matchups configured in YAML. Used for testing or specific head-to-heads.

### Configuration

Tournaments are defined in YAML config files (`configs/*.yaml`). Each config specifies models (with provider, token limits, timeouts), events (game type, rounds, hands per match), shot clock settings, and forfeit escalation rules. The `tournament_name` field in MongoDB links matches back to their config.

## Fidelity System (Violations & Forfeits)

The referee tracks five violation types per turn:

| Violation | Trigger | Severity |
|-----------|---------|----------|
| `malformed_json` | Response isn't valid JSON or missing required fields | Model can't follow schema |
| `illegal_move` | Valid JSON but the move breaks game rules | Model understands format but not game state |
| `timeout` | Response exceeds shot clock | Model too slow or hung |
| `empty_response` | No content returned | API failure or refusal |
| `injection_attempt` | Prompt injection detected in output | Model trying to manipulate game |

### Escalation Flow

```
First violation in a turn → RETRY (one chance to fix it)
Second violation in same turn → FORFEIT_TURN (lose this turn/hand)
Cumulative turn forfeits hit threshold → FORFEIT_MATCH (2-player) or ELIMINATE_PLAYER (3+ player)
```

The `match_forfeit_threshold` is configurable (default: 3 turn forfeits → match forfeit). For tables with 7+ players, the threshold scales up (+1 at 7, +2 at 8, +3 at 9 players) so larger tables are more forgiving.

Only certain violation types count as "strikes" toward match forfeit — by default `timeout` and `empty_response`. This means a model that gets illegal_move violations repeatedly will forfeit individual turns but won't be ejected from the match unless it also accumulates timeout/empty_response strikes.

### Fidelity Report

Each match produces a fidelity report stored in `matches.fidelity`, keyed by player_id:

```json
{
  "player_a": {
    "total_violations": 3,
    "malformed_json": 1,
    "illegal_move": 2,
    "timeout": 0,
    "empty_response": 0,
    "injection_attempts": 0,
    "total_severity": 5,
    "retries_used": 1,
    "turn_forfeits": 1
  }
}
```

If a match was forfeited, additional fields appear: `_match_forfeited: true`, `_match_forfeited_by: "player_a"`.

## MongoDB Schema

### `models` collection

Pre-aggregated stats per model. The `_id` is the canonical model name (normalized).

```
_id: string           — canonical model name (e.g., "claude-opus-4.6")
total_matches: number
wins: number
losses: number
draws: number
total_violations: number
last_played: Date
games: {              — per-game breakdown
  holdem: { matches, wins, losses, draws }
  connectfour: { ... }
  reversi: { ... }
  ...
}
```

### `matches` collection

One document per completed match.

```
match_id: string      — unique match identifier
event_type: string    — game name ("holdem", "connectfour", "rollerderby", etc.)
tournament_name: string
tier: string          — "heavyweight", "midtier", "flyweight", or null for mixed
round: number
models: [string]      — array of canonical model names (for querying)
player_models: {      — maps player_id → model_id
  player_a: "claude-opus-4.6",
  player_b: "gpt-5"
}
scores: {             — maps player_id → final score
  player_a: 350,
  player_b: 50
}
winner: string|null   — canonical model name, or null for draw
fidelity: { ... }     — per-player violation report (see above)
timestamp: string     — ISO datetime
_ingested_at: Date
schema_version: string
```

### `turns` collection

One document per model decision point. This is the largest collection.

```
match_id: string
turn_number: number
hand_number: number       — relevant for holdem (which hand in the match)
street: string            — game phase ("preflop", "flop", "turn", "river" for holdem; game-specific otherwise)
player_id: string
model_id: string          — canonical model name
model_version: string
parse_success: boolean
validation_result: string — "valid" or description of failure
violation: string|null    — violation type if any
ruling: string|null       — "retry", "forfeit_turn", etc.
parsed_action: object     — the model's parsed move (game-specific structure)
state_snapshot: object    — full game state at decision point
input_tokens: number
output_tokens: number
latency_ms: number
event_type: string
tournament_name: string
tier: string
round: number
timestamp: string
cumulative_strikes: number
strike_limit: number|null
time_limit_ms: number|null
time_exceeded: boolean
```

**Note on prompts**: By default, `store_prompts: false` in MongoSink, so turns contain `prompt_hash`, `prompt_chars`, and `prompt_tokens` instead of the full prompt text.

### Indexes

The turns collection has a compound unique index on `(match_id, turn_number, hand_number, player_id)`. Additional indexes exist on `match_id`, `model_id`, `event_type`, and `timestamp`. The matches collection is indexed on `match_id` (unique), `event_type`, `models`, and `(models, event_type)`.

## Model Name Normalization

Models go by many names across configs, APIs, and telemetry. The `model_names.py` module normalizes everything to canonical short names. When querying MongoDB, always use the canonical form.

Key mappings:

| Canonical | Common Aliases |
|-----------|---------------|
| claude-opus-4.6 | anthropic/claude-opus-4.6, opus-4.6, opus |
| claude-sonnet-4.5 | anthropic/claude-sonnet-4.5, sonnet-4.5, sonnet |
| gpt-5 | openai/gpt-5 |
| gemini-2.5-pro | google/gemini-2.5-pro |
| deepseek-r1 | deepseek/deepseek-r1 |
| grok-3 | x-ai/grok-3 |
| llama-4-maverick | meta-llama/llama-4-maverick |

Full mapping is in `src/llmtourney/core/model_names.py`. When the user mentions a model casually ("how did opus do?"), resolve to the canonical name before querying.

## Common Query Patterns

Use the MongoDB MCP tool to query the `llmtourney` database directly. Here are proven aggregation patterns:

### Overall Leaderboard

```javascript
// From models collection — quick leaderboard
db.models.find({}, { _id: 1, total_matches: 1, wins: 1, losses: 1, draws: 1, total_violations: 1 })
  .sort({ wins: -1 })
```

### Win Rate by Model and Game

```javascript
// Unwind models array, group by model+event, compute win rate
db.matches.aggregate([
  { $unwind: "$models" },
  { $group: {
      _id: { model: "$models", event_type: "$event_type" },
      wins: { $sum: { $cond: [{ $eq: ["$winner", "$models"] }, 1, 0] } },
      losses: { $sum: { $cond: [{ $and: [{ $ne: ["$winner", null] }, { $ne: ["$winner", "$models"] }] }, 1, 0] } },
      draws: { $sum: { $cond: [{ $eq: ["$winner", null] }, 1, 0] } },
      total: { $sum: 1 }
  }},
  { $addFields: { win_rate: { $cond: [{ $gt: ["$total", 0] }, { $divide: ["$wins", "$total"] }, 0] } } },
  { $sort: { win_rate: -1 } }
])
```

### Head-to-Head Between Two Models

```javascript
db.matches.find({
  models: { $all: ["claude-opus-4.6", "gpt-5"] }
})
```

### Violation Breakdown from Turns

```javascript
db.turns.aggregate([
  { $match: { violation: { $ne: null } } },
  { $group: {
      _id: { model_id: "$model_id", violation: "$violation" },
      count: { $sum: 1 }
  }},
  { $sort: { count: -1 } }
])
```

### Forfeit Rate

```javascript
db.matches.aggregate([
  { $unwind: "$models" },
  { $group: {
      _id: "$models",
      total: { $sum: 1 },
      forfeits: { $sum: { $cond: [{ $eq: ["$fidelity._match_forfeited", true] }, 1, 0] } }
  }},
  { $addFields: { forfeit_rate: { $divide: ["$forfeits", "$total"] } } },
  { $sort: { forfeit_rate: -1 } }
])
```

### Average Latency by Model

```javascript
db.turns.aggregate([
  { $group: {
      _id: { model_id: "$model_id", event_type: "$event_type" },
      avg_ms: { $avg: "$latency_ms" },
      min_ms: { $min: "$latency_ms" },
      max_ms: { $max: "$latency_ms" }
  }},
  { $sort: { avg_ms: 1 } }
])
```

### Token Usage by Model

```javascript
db.turns.aggregate([
  { $group: {
      _id: "$model_id",
      avg_input: { $avg: "$input_tokens" },
      avg_output: { $avg: "$output_tokens" },
      total_turns: { $sum: 1 }
  }},
  { $sort: { avg_input: -1 } }
])
```

## Visualization Guidelines

When building React dashboards or artifacts from tourney data:

- Use a consistent color palette for models across charts (assign colors deterministically by model name)
- Holdem scores are chip-based (continuous) — use bar charts or line charts, not binary win/loss
- For game-specific comparisons, normalize differently: win rate for binary games, average score for continuous games
- Violation data works well as stacked bar charts (violation type breakdown per model)
- Head-to-head records work well as matrix/heatmap visualizations
- The spectator UI at localhost:8080 shows live matches — reference it for real-time viewing

## Source Code Reference

The full source is at `~/projects/play-games/llmtourney`. Key modules for understanding the system:

| Path | Purpose |
|------|---------|
| `src/llmtourney/core/referee.py` | Violation tracking, penalty escalation, fidelity reports |
| `src/llmtourney/core/mongo_sink.py` | Background MongoDB writer with batch queue |
| `src/llmtourney/core/mongo_queries.py` | Pre-built aggregation pipelines (win_rates, head_to_head, etc.) |
| `src/llmtourney/core/telemetry.py` | JSONL + MongoDB telemetry logging per match |
| `src/llmtourney/core/model_names.py` | Canonical name normalization with alias mapping |
| `src/llmtourney/config.py` | YAML config loading, tier/event/escalation dataclasses |
| `src/llmtourney/events/*/engine.py` | Game engines (one per game type) |
| `src/llmtourney/events/*/schema.json` | JSON schemas for model move validation |
| `configs/*.yaml` | Tournament configuration files |
| `output/telemetry/*.jsonl` | Raw telemetry files (one per match) |

When the user asks about game mechanics, rules, or engine behavior, read the relevant `engine.py`. When they ask about move format, check the `schema.json` for that game.
