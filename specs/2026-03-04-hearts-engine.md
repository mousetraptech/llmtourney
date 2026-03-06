# Hearts Engine Spec -- LLM Tourney Season 3

## Why

Hearts is the trick-avoidance counterpart to Spades. Where Spades tests partnership coordination, Hearts tests individual survival in a 4-player free-for-all. You're trying to NOT take tricks -- or more precisely, not take tricks containing penalty cards. The strategic inversion (winning = bad) tests whether models can override the default "play to win" instinct.

The card-passing phase is unique in the tournament -- a pre-play decision layer where you modify your own hand AND weaponize cards against opponents. No other game has this.

Research question: can models play defensively? Can they detect and disrupt a Shoot the Moon attempt? Do they dump dangerous cards intelligently in the pass phase?

## Architecture

New event at src/llmtourney/events/hearts/. Subclass MultiplayerSeriesEvent from events/base.py with num_players=4. Create engine.py, schema.json, __init__.py.

Hearts shares roughly 80% of its infrastructure with Spades -- trick resolution, follow-suit validation, card formatting, turn rotation, dealer rotation. Reference spades/engine.py heavily.

Key differences from Spades: no bidding, no teams, add passing phase, inverted scoring, Shoot the Moon detection, no trump suit.

Follow the same patterns as Spades for trick play mechanics, state snapshots with hidden hands, prompt structure, JSON-first response format, dealer rotation, card string format.

## Game Rules

### Setup
- Standard 52-card deck, 13 cards each, 4 players
- No teams -- free-for-all
- No trump suit (unlike Spades)
- Play order: a, b, c, d (clockwise), rotating dealer each hand

### Phase 1: Card Passing
- Before play, each player selects 3 cards to pass
- Pass direction rotates each hand in a 4-hand cycle:
  - Hand 1: pass left (a to b, b to c, c to d, d to a)
  - Hand 2: pass right (a to d, b to a, c to b, d to c)
  - Hand 3: pass across (a to c, b to d, c to a, d to b)
  - Hand 4: no pass (hold hand as dealt)
  - Hand 5: cycle repeats
- All players select simultaneously (no info about what others pass)
- After passing, players receive 3 cards and see their new hand before play

Pass action schema:
  reasoning: string (strategic thinking about which cards to pass)
  cards: array of 3 card strings

Validation: exactly 3 cards, all in hand, no duplicates.

Implementation: cycle through a, b, c, d collecting pass selections, then execute all swaps at once. Prompt during collection does NOT reveal what others are passing.

### Phase 2: Trick Play (13 tricks)
- Player holding 2 of clubs leads the first trick (mandatory)
- Must follow suit if able
- First trick restriction: cannot play hearts or Q of spades even if void in led suit. Exception: if void in clubs AND hand is only hearts and Q of spades, may play a heart (but not Q of spades).
- Cannot lead hearts until hearts broken (a heart played because void in led suit)
- If only hearts remain, may lead hearts
- Highest card of the led suit wins (NO trump in Hearts)
- Trick winner leads next trick

Card rank: A > K > Q > J > 10 > 9 > 8 > 7 > 6 > 5 > 4 > 3 > 2

Play action schema:
  reasoning: string
  card: string (e.g. "A of spades", "10 of hearts" -- use same format as Spades engine)

Validation: card in hand, must follow suit, first trick restrictions, hearts leading restrictions.

### Scoring (per hand)
- Each heart taken = 1 point (13 hearts = 13 points max)
- Queen of spades = 13 points
- Total penalty per hand = 26
- Lower is better -- you want 0

### Shooting the Moon
- If one player takes ALL 26 penalty points (all 13 hearts + queen of spades):
  - Shooter scores 0 for the hand
  - Every other player scores 26
- Missing even one heart = you eat whatever you took. No partial credit.
- Engine must detect at hand end: if any player penalty == 26, apply inversion.

### Game End
- Play until one player reaches 100 cumulative points
- Player with LOWEST cumulative score wins
- If tied for lowest, they share the win
- Safety valve: 20-hand cap, lowest score wins

### Match Structure
- games_per_match parameter (default 1)
- get_scores() returns individual penalty points (lower = better)
- For tournament integration: INVERT for standings. Lowest penalty = highest tournament score. Use placement-based scoring (1st/2nd/3rd/4th).

## Prompt Design

### Pass Phase
Include: player hand (sorted by suit), pass direction, who you're passing to, current game scores, hand number. Reminder: select 3 cards to pass. RESPOND WITH JSON ONLY, reasoning field first.

### Play Phase
Include: current hand (post-pass), current trick cards, trick number, penalty points taken this hand by each player, hearts broken status, cumulative scores, led suit, first trick reminder if applicable. RESPOND WITH JSON ONLY, reasoning field first.

Key principle: surface enough info for strategic play without coaching. Show who has penalty points this hand so models can reason about Shoot the Moon threats.

## Forfeit Handling

Pass phase: pass the 3 highest hearts. If fewer than 3 hearts, fill with highest cards from longest suit.

Play phase:
- Following suit: play LOWEST card of led suit (avoid winning tricks)
- Void and have Q of spades: play it (dump it)
- Void and have hearts: play highest heart (dump penalty cards)
- Void otherwise: play highest card of any suit
- Leading: play lowest non-heart. If only hearts, play lowest heart.

## State Snapshot

phase: pass or play
game_number, hand_number, pass_direction
trick_number (1-13 during play)
hands: hidden, telemetry only
passed_cards: hidden, what each player passed
received_cards: hidden, what each player received
current_trick: array of player+card
penalty_points_this_hand: per player
cumulative_scores: per player
hearts_broken: bool
trick_history: per trick (leader, cards, winner, points)
shoot_the_moon: player_id or null
terminal: bool

## Highlight Detection

- Queen of spades played (always dramatic)
- Queen of spades dumped on someone (void in led suit, plays Q spades)
- Shoot the Moon in progress (player has 20+ penalty points with tricks remaining)
- Shoot the Moon succeeded (26 points, scoring inverted)
- Shoot the Moon broken (had 20+, then another player took a heart)
- Hearts broken (first time per hand)
- Zero-point hand (player takes 0 penalty)
- Score milestone (player crosses 50 or 75, approaching 100)

## Differences from Spades

Teams: Spades 2v2, Hearts free-for-all
Objective: Spades win tricks, Hearts avoid penalty cards
Trump: Spades has trump, Hearts no trump
Pre-play: Spades bids, Hearts passes cards
Scoring: Spades higher is better, Hearts lower is better (inverted for tournament)
Special: Spades has nil/bags, Hearts has Shoot the Moon and queen of spades = 13
First lead: Spades rotates dealer, Hearts player with 2 clubs leads trick 1
First trick: Spades no restriction, Hearts no hearts or queen of spades

## Design Decisions

1. No teams. Hearts is free-for-all. Individual scoring.
2. Standard passing rotation: left, right, across, no-pass, repeat.
3. 100-point threshold, 20-hand cap.
4. Simultaneous passing via sequential collection then batch swap.
5. Shoot the Moon = 0 for shooter, +26 for everyone else (standard rule).
6. No Jack of Diamonds variant. Skip for simplicity.
7. 8-model roster same as Spades. Two tables of 4 per round.

## Testing Priority

1. Card passing: direction rotation, swap execution, hand state after pass, 3-card validation
2. Trick play: follow suit, first trick restrictions, hearts breaking, no-trump resolution
3. Scoring: penalty counting, queen of spades = 13, Shoot the Moon detection and inversion
4. Game end: 100 threshold, lowest wins, 20-hand cap
5. Phase transitions: pass then play then scoring then next hand with new direction then game end
6. Forfeit: always legal, strategically sane (dump hearts and queen of spades)
7. Player with 2 clubs leads trick 1 regardless of dealer
8. Integration: tournament runner compatibility
