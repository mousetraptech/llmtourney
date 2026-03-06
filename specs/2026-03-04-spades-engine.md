# Spades Engine Spec — LLM Tourney Season 3

## Why

Spades is the first **partnership game** in the tournament. Two teams of two LLMs must cooperate *implicitly* through card play — no side channel, no communication except the cards themselves and the bids they make. This tests a fundamentally different capability than anything in S1 or S2: can models develop conventions with a partner they can't talk to?

The research question: does partnership play reveal cooperative intelligence, or do models treat partners as just another opponent they happen to share a score with?

## Architecture

New event at `src/llmtourney/events/spades/`. Subclass `MultiplayerSeriesEvent` from `events/base.py` with `num_players=4`. Create `engine.py`, `schema.json`, `__init__.py`.

Follow the patterns in:
- `bullshit/engine.py` — multi-phase turns (play phase + challenge phase → bid phase + trick phase)
- `liarsdice/engine.py` — elimination/round tracking, prompt structure
- `holdem/engine.py` — hidden information handling, state snapshots with hidden data for telemetry

## Game Rules

### Setup
- Standard 52-card deck, 13 cards dealt to each of 4 players
- Fixed partnerships: Team 1 = `player_a` + `player_c`, Team 2 = `player_b` + `player_d` (partners sit across, standard Spades seating)
- Spades are always trump
- Play order: a → b → c → d (clockwise)

### Phase 1: Bidding
- Each player bids in turn order (a, b, c, d)
- Bid = number of tricks (0–13) the player expects to take individually
- Bid of 0 = **nil bid** (special scoring, see below)
- All bids are public — each player sees all previous bids before making theirs
- Partners' bids are summed to form the **team contract**
- No communication between partners about strategy

### Phase 2: Trick Play (13 tricks)
- Player `a` leads the first trick
- **Leading rules:** Cannot lead spades until spades have been "broken" (played as trump on a previous trick) OR the player has only spades remaining
- **Following rules:** Must follow the led suit if able. If void in the led suit, may play any card (including spades to trump)
- **Winning:** Highest card of the led suit wins, unless trumped — highest spade wins if any spades played
- Trick winner leads the next trick
- Card rank order: A > K > Q > J > 10 > 9 > 8 > 7 > 6 > 5 > 4 > 3 > 2

### Scoring (per hand)
- **Made contract:** If team takes >= their contract, they score `contract × 10` plus 1 point per overtrick ("bag"). Example: bid 5, took 7 = 50 + 2 = 52 points.
- **Set (broken contract):** If team takes < their contract, they score `-(contract × 10)`. Example: bid 5, took 4 = -50.
- **Nil bid:** If a player bids nil and takes 0 tricks: +100 bonus for the team. If they take any tricks: -100 penalty. Partner's bid and tricks are scored normally regardless.
- **Bag penalty:** Every 10 cumulative overtricks (bags) costs -100 points. Track bags across hands within a game.

### Game End
- Play to **500 points** (first team to reach 500 at end of a hand wins)
- If both teams cross 500 on the same hand, higher score wins
- Safety valve: if neither team reaches 500 after **25 hands**, the team with more points wins (prevents infinite games with conservative bidding)
- If a team reaches **-200** at any point, they lose immediately (prevents sandbagging/griefing spirals)

### Match Structure
- `games_per_match` parameter (default 1 for league play)
- Team-based scoring for `get_scores()`: return individual player scores equal to their team's total. Both `player_a` and `player_c` get Team 1's score; both `player_b` and `player_d` get Team 2's score.

## Turn Structure / Phases

Use an enum `Phase` with values `BID` and `PLAY` (same pattern as Bullshit's `PLAY`/`CHALLENGE`).

### Bid Phase
- `current_player()` cycles a → b → c → d during bidding
- After all 4 bids collected, transition to `Phase.PLAY`

**Bid action schema:**
```json
{
  "reasoning": "string — the model's strategic thinking about their hand and bid",
  "bid": "integer 0-13"
}
```

Validation: bid must be integer 0–13. That's it — there's no restriction on total bids exceeding 13 (that's a strategic consideration, not a rule violation).

### Play Phase
- `current_player()` returns the trick leader for the first card, then cycles clockwise for remaining 3 cards per trick
- After all 4 cards played, resolve trick winner, update state, check for game end

**Play action schema:**
```json
{
  "reasoning": "string — the model's thinking about which card to play",
  "card": "string — card to play, e.g. 'A♠', '10♥', '3♦'"
}
```

Validation:
1. Card must be in the player's hand
2. Must follow suit if able (player has cards of the led suit)
3. Cannot lead spades unless broken or only spades in hand
4. Card string format must match deck format (rank + suit symbol)

## Prompt Design

### Bid Phase Prompt
Include:
- Player's 13-card hand (sorted by suit, then rank within suit)
- Which team they're on and who their partner is
- Any bids already made this round (and by which player/team)
- Current game score for both teams
- Current bag count for both teams
- Brief rules reminder: "Bid the number of tricks you expect to take. Your bid will be combined with your partner's."

### Play Phase Prompt
Include:
- Player's current hand
- Current trick (cards already played this trick, who played them)
- Trick number (1-13)
- Tricks taken so far by each team
- Team contracts (bid totals)
- Whether spades are broken
- Current game score
- Which suit was led (if not the leader)
- Brief rules reminder about following suit and spades-breaking

### Key Prompt Design Principle
The prompt should subtly encourage partnership awareness without explicitly coaching strategy. Include the partner's bid, the partner's trick count, the team contract — let the model decide what to do with that information. The research value is in seeing whether models *use* partner information, not in telling them to.

## Forfeit Handling

**Bid phase forfeit:** Bid 2 (safe conservative default — not nil, not aggressive)

**Play phase forfeit:**
1. If must follow suit: play lowest card of the led suit
2. If void and spades not broken and leading: play lowest non-spade
3. Otherwise: play lowest card in hand
(Same "play safe, play low" philosophy as other engines)

## State Snapshot (`get_state_snapshot()`)

Include all public info PLUS hidden hands (for telemetry/spectator, not shown to players):
```python
{
    "phase": "bid" | "play",
    "game_number": int,
    "hand_number": int,  # within the game (1-25)
    "trick_number": int,  # within the hand (1-13)
    "hands": {player_id: [cards]},  # HIDDEN — for telemetry only
    "bids": {player_id: int | None},
    "team_contracts": {"team_1": int, "team_2": int},
    "tricks_taken": {"team_1": int, "team_2": int},
    "current_trick": [{"player": str, "card": str}, ...],
    "scores": {"team_1": int, "team_2": int},
    "bags": {"team_1": int, "team_2": int},
    "spades_broken": bool,
    "trick_history": [{"leader": str, "cards": [...], "winner": str}, ...],
    "terminal": bool,
}
```

## Highlight Detection

Flag these as highlights:
- **Nil bid made** (any player bids 0)
- **Nil succeeded** (player who bid nil takes 0 tricks in the hand)
- **Nil busted** (player who bid nil takes a trick — drama!)
- **Set** (team fails to make their contract)
- **Bag penalty triggered** (team hits 10 cumulative bags, -100)
- **Lead change** (team takes the lead after being behind)
- **Game point** (a team reaches 400+ and is within striking distance)
- **Spades broken** on first occurrence per hand

## Team Mechanics — Implementation Notes

The partnership mechanic is what makes this engine unique. Key implementation details:

1. **Team mapping:** Use a dict or method `_get_team(player_id) -> str` returning `"team_1"` or `"team_2"`. Team 1 = a+c, Team 2 = b+d.

2. **Contract calculation:** After all 4 bids, compute `team_contracts = {"team_1": bids[a] + bids[c], "team_2": bids[b] + bids[d]}`. Handle nil bids specially — a nil bid contributes 0 to the team contract but the nil player's tricks are tracked individually for nil scoring.

3. **Trick attribution:** When a team member wins a trick, it counts toward the *team's* trick total, not the individual's (except for nil tracking where individual tricks matter).

4. **Score reporting:** `get_scores()` returns per-player scores, but both members of a team get the same score (their team's cumulative game score). This integrates cleanly with the league standings system which tracks per-player points.

## Config Integration

Example YAML for a league fixture:
```yaml
event: spades
games_per_match: 1
num_players: 4
target_score: 500
hand_limit: 25
```

For 8-model league play, you'll need to rotate partnerships — each model should partner with every other model across fixtures. That's a **fixture scheduling** concern for the league runner, not the engine. The engine just takes 4 player IDs and assigns a+c vs b+d.

For 9-model league play (existing bantam/midtier rosters): either drop to 8 for Spades fixtures, or run multiple 4-player tables per round. Design decision for later — engine doesn't care, it just plays 4 players.

## Testing Priority

1. **Card mechanics first:** Deal, follow-suit validation, trick resolution, spades-breaking logic. These are deterministic — easy to unit test.
2. **Scoring:** Contract made/set, nil success/failure, bag accumulation, bag penalty, game-end conditions (500 target, -200 floor, 25-hand cap).
3. **Phase transitions:** Bid → play → next hand → game end. Make sure `current_player()` always returns the right player in the right phase.
4. **Forfeit handling:** Verify forfeit plays are always legal moves.
5. **Integration:** Verify it works with the tournament runner — `reset()`, turn loop, `get_scores()`, `get_state_snapshot()`.

## What This Engine Does NOT Need

- No spectator (yet) — build the engine, spectator comes later
- No AI strategy coaching — the prompt gives information, not advice
- No team chat or signaling mechanism — the whole point is implicit coordination
- No duplicate detection or anti-collusion — models can't collude because they can't communicate

## Design Decisions (Resolved)

1. **Partnerships: Rotating for league, fixed for playoffs.** During league play, every model partners with every other model across fixtures (round-robin partnerships). This isolates individual contribution. If there's a Champions playoff, partnerships are fixed — testing whether specific duos develop chemistry under pressure.

2. **Blind nil: Skip for S3.** Too chaotic for LLM play. Revisit if models handle regular nil competently.

3. **Roster: Drop to 8 models, rotate partnerships.** Spades needs exactly 4 players. Use 8-model rosters (not 9) and rotate partnerships across fixtures. This gives clean combinatorics — 8 models = 28 possible partnerships, each pair can face every other pair.

4. **Jokers: Skip.** Adds complexity without clear analytical value.
