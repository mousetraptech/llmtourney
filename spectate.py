#!/usr/bin/env python3
"""Live spectator UI for llmtourney matches.

Usage:
    python spectate.py <match-id>          # Watch a specific match
    python spectate.py                      # Auto-discover latest match

Tails the JSONL telemetry file and renders a live sportscast-style display.
"""

import json
import re
import sys
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

from rich.align import Align
from rich.columns import Columns
from rich.console import Console, Group
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

TELEMETRY_DIR = Path("output/telemetry")
REFRESH_RATE = 0.5
TOTAL_STARTING_CHIPS = 400
BAR_WIDTH = 30

# Player color scheme
PLAYER_COLORS = {
    "player_a": "cyan",
    "player_b": "magenta",
}

# Fun emoji pool — deterministically assigned per match via hash of model names
_EMOJI_POOL = [
    "\U0001F525", "\U0001F9E0", "\U0001F47E", "\U0001F916", "\U0001F3AF",
    "\U0001F680", "\U0001F40D", "\U0001F98A", "\U0001F43B", "\U0001F985",
    "\U0001F409", "\U0001F3B2", "\U0001F9CA", "\U0001F30B", "\U0001F308",
    "\U0001F52E", "\U0001F9F2", "\U0001F41D", "\U0001F95D", "\U0001F344",
]


def pick_player_emoji(model_a: str, model_b: str) -> dict[str, str]:
    """Deterministically assign emojis to players based on model names."""
    idx_a = hash(model_a) % len(_EMOJI_POOL)
    idx_b = hash(model_b) % len(_EMOJI_POOL)
    if idx_b == idx_a:
        idx_b = (idx_a + 1) % len(_EMOJI_POOL)
    return {"player_a": _EMOJI_POOL[idx_a], "player_b": _EMOJI_POOL[idx_b]}


@dataclass
class HandRecord:
    """Completed hand summary."""

    hand_number: int
    winner_model: str
    margin: int
    ending_action: str  # "fold", "showdown"
    pot: int


@dataclass
class CommentaryLine:
    """A single line in the play-by-play feed."""

    hand_number: int
    street: str
    model: str
    player_id: str
    action: str
    amount: int | None
    reasoning_snippet: str | None
    latency_ms: float
    is_violation: bool = False


@dataclass
class MatchState:
    """Accumulated match state built from JSONL lines."""

    match_id: str = ""
    model_a: str = ""
    model_b: str = ""
    hand_number: int = 0
    street: str = "preflop"
    pot: int = 0
    blinds: tuple[int, int] = (1, 2)
    stacks: dict = field(default_factory=lambda: {"player_a": 200, "player_b": 200})
    community_cards: list = field(default_factory=list)
    dealer: str = "player_a"
    total_hands: int = 100

    # Hole cards per player for the current hand
    hole_cards: dict = field(default_factory=lambda: {"player_a": [], "player_b": []})

    # Last action
    last_player_id: str = ""
    last_model: str = ""
    last_action: str = ""
    last_amount: int | None = None

    # Tracking
    hand_history: deque = field(default_factory=lambda: deque(maxlen=5))
    commentary: deque = field(default_factory=lambda: deque(maxlen=12))
    turn_count: int = 0
    hand_start_stacks: dict = field(default_factory=dict)
    current_hand_last_pot: int = 0
    current_hand_last_action: str = ""
    finished: bool = False
    final_scores: dict = field(default_factory=dict)
    highlight_hands: list = field(default_factory=list)
    violations: dict = field(
        default_factory=lambda: {"player_a": 0, "player_b": 0}
    )
    total_tokens_used: dict = field(
        default_factory=lambda: {"player_a": 0, "player_b": 0}
    )
    emojis: dict = field(default_factory=lambda: {"player_a": "", "player_b": ""})

    # Shot clock
    time_limit_ms: int | None = None
    strikes: dict = field(default_factory=lambda: {"player_a": 0, "player_b": 0})
    strike_limit: int | None = None
    waiting_on: str = ""
    last_turn_time: float = 0.0


def _assign_emojis(state) -> None:
    """Assign emojis once both model names are known."""
    if state.model_a and state.model_b and not state.emojis.get("player_a"):
        state.emojis = pick_player_emoji(state.model_a, state.model_b)


def truncate_reasoning(text: str | None, max_len: int = 70) -> str | None:
    """Extract a short snippet from reasoning output."""
    if not text:
        return None
    # Take first meaningful line
    for line in text.strip().split("\n"):
        line = line.strip()
        if len(line) > 10:
            if len(line) > max_len:
                return line[: max_len - 3] + "..."
            return line
    return text[:max_len] if len(text) > max_len else text


def process_turn(state: MatchState, data: dict) -> None:
    """Update match state from a single telemetry turn line."""
    # Detect match summary
    if data.get("record_type") == "match_summary":
        state.finished = True
        state.final_scores = data.get("final_scores", {})
        state.highlight_hands = data.get("highlight_hands", [])
        pm = data.get("player_models", {})
        if pm:
            state.model_a = pm.get("player_a", state.model_a)
            state.model_b = pm.get("player_b", state.model_b)
        _assign_emojis(state)
        return

    state.turn_count += 1
    snap = data.get("state_snapshot", {})
    hand_num = data.get("hand_number", snap.get("hand_number", 0))
    player_id = data.get("player_id", "")
    model_id = data.get("model_id", "")

    # Set match info on first turn
    if not state.match_id:
        state.match_id = data.get("match_id", "")
    if player_id == "player_a" and not state.model_a:
        state.model_a = model_id
    elif player_id == "player_b" and not state.model_b:
        state.model_b = model_id
    _assign_emojis(state)

    # Detect hand transition -> record previous hand result
    if hand_num > state.hand_number and state.hand_number > 0:
        _record_hand_result(state, snap)

    # Track hand start stacks + reset hole cards on new hand
    if hand_num > state.hand_number or not state.hand_start_stacks:
        state.hand_start_stacks = dict(snap.get("stacks", {}))
        state.hole_cards = {"player_a": [], "player_b": []}

    # Extract hole cards from prompt text
    prompt = data.get("prompt", "")
    if player_id and prompt:
        m = re.search(r"Your hole cards:\s*(.+)", prompt)
        if m:
            cards = m.group(1).strip().split()
            state.hole_cards[player_id] = cards

    # Update current state
    state.hand_number = hand_num
    state.street = data.get("street", snap.get("street", "preflop"))
    state.pot = snap.get("pot", state.pot)
    state.stacks = dict(snap.get("stacks", state.stacks))
    state.community_cards = snap.get("community_cards", state.community_cards)
    state.dealer = snap.get("dealer", state.dealer)
    if snap.get("blinds"):
        state.blinds = tuple(snap["blinds"])

    # Parse action
    parsed = data.get("parsed_action") or {}
    action = parsed.get("action", "???")
    amount = parsed.get("amount")
    violation = data.get("violation")

    if data.get("validation_result") == "forfeit":
        action = "forfeit"

    state.last_player_id = player_id
    state.last_model = model_id
    state.last_action = action
    state.last_amount = amount
    state.current_hand_last_pot = snap.get("pot", 0)
    state.current_hand_last_action = action

    # Track violations
    if violation:
        state.violations[player_id] = state.violations.get(player_id, 0) + 1

    # Shot clock
    if data.get("time_limit_ms"):
        state.time_limit_ms = data["time_limit_ms"]
    if data.get("strike_limit"):
        state.strike_limit = data["strike_limit"]
    if data.get("cumulative_strikes") is not None:
        state.strikes[player_id] = data["cumulative_strikes"]
    state.waiting_on = "player_b" if player_id == "player_a" else "player_a"
    state.last_turn_time = time.time()

    # Track tokens
    tokens = data.get("input_tokens", 0) + data.get("output_tokens", 0)
    state.total_tokens_used[player_id] = (
        state.total_tokens_used.get(player_id, 0) + tokens
    )

    # Commentary
    reasoning = truncate_reasoning(data.get("reasoning_output"))
    state.commentary.append(
        CommentaryLine(
            hand_number=hand_num,
            street=state.street,
            model=model_id,
            player_id=player_id,
            action=action,
            amount=amount,
            reasoning_snippet=reasoning,
            latency_ms=data.get("latency_ms", 0),
            is_violation=violation is not None,
        )
    )


def _record_hand_result(state: MatchState, new_snap: dict) -> None:
    """Record the result of a completed hand based on stack changes."""
    new_stacks = new_snap.get("stacks", {})
    old_stacks = state.hand_start_stacks

    if not old_stacks or not new_stacks:
        return

    delta_a = new_stacks.get("player_a", 0) - old_stacks.get("player_a", 0)
    delta_b = new_stacks.get("player_b", 0) - old_stacks.get("player_b", 0)

    if delta_a > 0:
        winner_pid = "player_a"
        margin = delta_a
    elif delta_b > 0:
        winner_pid = "player_b"
        margin = delta_b
    else:
        return  # Split pot or no change

    winner_model = state.model_a if winner_pid == "player_a" else state.model_b

    # Determine ending: if last action was fold, it's a fold win
    ending = "fold" if state.current_hand_last_action == "fold" else "showdown"

    state.hand_history.append(
        HandRecord(
            hand_number=state.hand_number,
            winner_model=winner_model,
            margin=margin,
            ending_action=ending,
            pot=state.current_hand_last_pot,
        )
    )


# ── Rich Rendering ──────────────────────────────────────────────────


def make_chip_bar(chips: int, total: int, color: str) -> Text:
    """Render a proportional chip bar."""
    fraction = max(0, min(1, chips / total)) if total > 0 else 0
    filled = int(fraction * BAR_WIDTH)
    empty = BAR_WIDTH - filled

    bar = Text()
    bar.append("\u2588" * filled, style=f"bold {color}")
    bar.append("\u2591" * empty, style="dim")
    bar.append(f" {chips}", style=f"bold {color}")
    return bar


def make_street_label(street: str) -> Text:
    """Colorized street label."""
    colors = {
        "preflop": "yellow",
        "flop": "green",
        "turn": "blue",
        "river": "red",
        "showdown": "bold white",
    }
    return Text(street.upper(), style=colors.get(street, "white"))


def format_cards(cards: list) -> Text:
    """Format community cards with suit colors."""
    if not cards:
        return Text("-- no cards --", style="dim italic")
    result = Text()
    suit_colors = {"h": "red", "d": "blue", "c": "green", "s": "white"}
    for i, card in enumerate(cards):
        if i > 0:
            result.append("  ")
        rank = card[:-1].upper()
        suit = card[-1].lower()
        suit_symbol = {"h": "\u2665", "d": "\u2666", "c": "\u2663", "s": "\u2660"}.get(
            suit, suit
        )
        color = suit_colors.get(suit, "white")
        result.append(f"{rank}{suit_symbol}", style=f"bold {color}")
    return result


def build_header(state: MatchState) -> Panel:
    """Match header panel."""
    emoji_a = state.emojis.get("player_a", "")
    emoji_b = state.emojis.get("player_b", "")
    if state.finished:
        title_text = Text()
        title_text.append("FINAL  ", style="bold red blink")
        title_text.append("HOLD'EM  ", style="bold white")
        title_text.append(f"{emoji_a} {state.model_a}", style=f"bold {PLAYER_COLORS['player_a']}")
        title_text.append("  vs  ", style="dim")
        title_text.append(f"{emoji_b} {state.model_b}", style=f"bold {PLAYER_COLORS['player_b']}")
    else:
        title_text = Text()
        title_text.append("LIVE  ", style="bold green")
        title_text.append("HOLD'EM  ", style="bold white")
        title_text.append(f"{emoji_a} {state.model_a or '???'}", style=f"bold {PLAYER_COLORS['player_a']}")
        title_text.append("  vs  ", style="dim")
        title_text.append(f"{emoji_b} {state.model_b or '???'}", style=f"bold {PLAYER_COLORS['player_b']}")

    sub = Text()
    sub.append(f"Hand {state.hand_number}", style="bold")
    sub.append("  |  ", style="dim")
    sub.append_text(make_street_label(state.street))
    sub.append("  |  ", style="dim")
    sub.append(f"Pot: {state.pot}", style="bold yellow")
    sub.append("  |  ", style="dim")
    sub.append(f"Blinds: {state.blinds[0]}/{state.blinds[1]}", style="bold white")
    sub.append("  |  ", style="dim")
    sub.append(f"Turn #{state.turn_count}", style="dim")

    content = Group(Align.center(title_text), Align.center(sub))
    return Panel(
        content,
        border_style="bright_white" if not state.finished else "red",
        padding=(0, 1),
    )


def build_table_panel(state: MatchState) -> Panel:
    """Chip stacks + hole cards + board + last action."""
    table = Table(show_header=False, show_edge=False, pad_edge=False, expand=True)
    table.add_column("label", width=18, no_wrap=True)
    table.add_column("cards", width=12, no_wrap=True)
    table.add_column("bar", ratio=1)

    # Player A
    a_label = Text()
    if state.dealer == "player_a":
        a_label.append("D ", style="bold yellow")
    a_label.append(
        (state.model_a or "Player A")[:16],
        style=f"bold {PLAYER_COLORS['player_a']}",
    )
    a_cards = format_cards(state.hole_cards.get("player_a", []))
    if not state.hole_cards.get("player_a"):
        a_cards = Text("--  --", style="dim")
    table.add_row(a_label, a_cards, make_chip_bar(state.stacks.get("player_a", 0), TOTAL_STARTING_CHIPS, PLAYER_COLORS["player_a"]))

    # Player B
    b_label = Text()
    if state.dealer == "player_b":
        b_label.append("D ", style="bold yellow")
    b_label.append(
        (state.model_b or "Player B")[:16],
        style=f"bold {PLAYER_COLORS['player_b']}",
    )
    b_cards = format_cards(state.hole_cards.get("player_b", []))
    if not state.hole_cards.get("player_b"):
        b_cards = Text("--  --", style="dim")
    table.add_row(b_label, b_cards, make_chip_bar(state.stacks.get("player_b", 0), TOTAL_STARTING_CHIPS, PLAYER_COLORS["player_b"]))

    # Board cards
    board_text = Text("\n  Board: ", style="dim")
    board_text.append_text(format_cards(state.community_cards))

    # Last action
    action_text = Text("\n")
    if state.last_model:
        color = PLAYER_COLORS.get(state.last_player_id, "white")
        action_text.append("  >> ", style="bold white")
        action_text.append(state.last_model, style=f"bold {color}")

        if state.last_action == "raise" and state.last_amount:
            action_text.append(f" raises to {state.last_amount}", style="bold yellow")
        elif state.last_action == "call":
            action_text.append(" calls", style="bold green")
        elif state.last_action == "fold":
            action_text.append(" folds", style="bold red")
        elif state.last_action == "forfeit":
            action_text.append(" FORFEITS TURN", style="bold red")
        else:
            action_text.append(f" {state.last_action}", style="bold")
    else:
        action_text.append("  Waiting for first action...", style="dim italic")

    content = Group(table, board_text, action_text)
    return Panel(content, title="[bold]Table[/bold]", border_style="green", padding=(0, 1))


def build_hand_history(state: MatchState) -> Panel:
    """Recent hand results."""
    lines: list[Text] = []

    if not state.hand_history:
        lines.append(Text("  No completed hands yet", style="dim italic"))
    else:
        for hand in reversed(state.hand_history):
            line = Text()
            is_highlight = hand.hand_number in state.highlight_hands
            prefix = " * " if is_highlight else "   "
            line.append(prefix, style="bold yellow" if is_highlight else "")
            line.append(f"Hand {hand.hand_number:>3d}", style="bold")
            line.append("  ", style="dim")

            # Winner name with color
            pid = (
                "player_a"
                if hand.winner_model == state.model_a
                else "player_b"
            )
            color = PLAYER_COLORS.get(pid, "white")
            line.append(f"{hand.winner_model}", style=f"bold {color}")
            line.append(f" wins +{hand.margin}", style="bold green")
            line.append(f"  ({hand.ending_action})", style="dim")
            lines.append(line)

    content = Group(*lines)
    return Panel(
        content,
        title="[bold]Recent Hands[/bold]",
        border_style="yellow",
        padding=(0, 1),
    )


def build_commentary(state: MatchState) -> Panel:
    """Play-by-play scrolling feed."""
    lines: list[Text] = []

    if not state.commentary:
        lines.append(Text("  Waiting for action...", style="dim italic"))
    else:
        for entry in reversed(state.commentary):
            line = Text()
            # Timestamp tag
            street_short = {
                "preflop": "PRE",
                "flop": "FLP",
                "turn": "TRN",
                "river": "RVR",
                "showdown": "SHO",
            }.get(entry.street, entry.street[:3].upper())
            line.append(f"  H{entry.hand_number:<3d}", style="dim")
            line.append(f"{street_short}  ", style="dim cyan")

            # Model + action
            color = PLAYER_COLORS.get(entry.player_id, "white")
            line.append(f"{entry.model}", style=f"bold {color}")

            if entry.is_violation:
                line.append(f" {entry.action}", style="bold red")
                line.append(" !", style="bold red")
            elif entry.action == "raise" and entry.amount:
                line.append(f" raises {entry.amount}", style="bold yellow")
            elif entry.action == "call":
                line.append(" calls", style="green")
            elif entry.action == "fold":
                line.append(" folds", style="red")
            elif entry.action == "forfeit":
                line.append(" FORFEITS", style="bold red")
            else:
                line.append(f" {entry.action}", style="")

            # Latency for live models
            if entry.latency_ms > 100:
                line.append(f"  ({entry.latency_ms / 1000:.1f}s)", style="dim")

            lines.append(line)

            # Reasoning snippet on next line
            if entry.reasoning_snippet:
                reason_line = Text()
                reason_line.append("        ", style="")
                reason_line.append(
                    f'"{entry.reasoning_snippet}"',
                    style="dim italic",
                )
                lines.append(reason_line)

    content = Group(*lines)
    return Panel(
        content,
        title="[bold]Play-by-Play[/bold]",
        border_style="blue",
        padding=(0, 1),
    )


def build_shot_clock(state: MatchState) -> Panel | None:
    """Shot clock panel — returns None if no shot clock configured."""
    if not state.time_limit_ms or state.finished:
        return None

    # Countdown
    if state.last_turn_time > 0:
        elapsed_ms = (time.time() - state.last_turn_time) * 1000
        remaining_ms = max(0, state.time_limit_ms - elapsed_ms)
        remaining_s = remaining_ms / 1000
        pct = remaining_ms / state.time_limit_ms
        if pct <= 0.2:
            time_style = "bold red"
        elif pct <= 0.5:
            time_style = "bold yellow"
        else:
            time_style = "bold green"
    else:
        remaining_s = state.time_limit_ms / 1000
        time_style = "bold green"

    clock_text = Text()
    clock_text.append("SHOT CLOCK  ", style="dim")
    clock_text.append(f"{remaining_s:.1f}s", style=time_style)

    # Waiting on
    if state.waiting_on and not state.finished:
        waiting_model = state.model_a if state.waiting_on == "player_a" else state.model_b
        if waiting_model:
            clock_text.append(f"  {waiting_model}", style="dim")

    # Strikes
    if state.strike_limit:
        clock_text.append("  |  ", style="dim")
        for pid, label in [("player_a", state.model_a or "A"), ("player_b", state.model_b or "B")]:
            s = state.strikes.get(pid, 0)
            color = PLAYER_COLORS[pid]
            strike_style = f"bold {color}" if s < state.strike_limit else f"bold red"
            clock_text.append(f"{label}: ", style=f"bold {color}")
            clock_text.append(f"{s}/{state.strike_limit}", style=strike_style)
            if pid == "player_a":
                clock_text.append("  ", style="dim")

    return Panel(
        Align.center(clock_text),
        border_style="bright_white",
        padding=(0, 1),
    )


def build_footer(state: MatchState) -> Text:
    """Status bar."""
    footer = Text()
    if state.finished:
        footer.append(" MATCH COMPLETE ", style="bold white on red")
        footer.append("  ", style="")
        scores = state.final_scores
        for pid, label in [("player_a", state.model_a), ("player_b", state.model_b)]:
            score = scores.get(pid, 0)
            color = PLAYER_COLORS[pid]
            footer.append(f"  {label}: {score:.0f}", style=f"bold {color}")
    else:
        footer.append(" LIVE ", style="bold white on green")
        footer.append(f"  Refreshing every {REFRESH_RATE}s", style="dim")
        footer.append("  |  Ctrl+C to exit", style="dim")
    return footer


def build_final_panel(state: MatchState) -> Panel:
    """Final results panel shown when match is complete."""
    score_a = state.final_scores.get("player_a", 0)
    score_b = state.final_scores.get("player_b", 0)

    if score_a > score_b:
        winner, loser = state.model_a, state.model_b
        w_score, l_score = score_a, score_b
        w_color = PLAYER_COLORS["player_a"]
    elif score_b > score_a:
        winner, loser = state.model_b, state.model_a
        w_score, l_score = score_b, score_a
        w_color = PLAYER_COLORS["player_b"]
    else:
        winner = "TIE"
        w_score = score_a
        w_color = "yellow"

    result = Text()
    result.append("\n")
    if winner == "TIE":
        result.append("    DRAW", style="bold yellow")
        result.append(f" - {w_score:.0f} chips each\n", style="bold")
    else:
        result.append(f"    {winner}", style=f"bold {w_color}")
        result.append(" WINS", style="bold green")
        result.append(f"  {w_score:.0f} - {l_score:.0f}", style="bold")
        result.append(f"  (+{w_score - l_score:.0f} margin)\n", style="bold yellow")

    if state.highlight_hands:
        result.append(
            f"\n    Highlight hands: {', '.join(str(h) for h in state.highlight_hands)}\n",
            style="dim",
        )

    result.append("\n")
    return Panel(
        Align.center(result),
        title="[bold white on red] FINAL RESULT [/bold white on red]",
        border_style="red",
    )


def render(state: MatchState) -> Group:
    """Build the full display."""
    parts = [
        build_header(state),
    ]

    shot_clock = build_shot_clock(state)
    if shot_clock:
        parts.append(shot_clock)

    parts.append(build_table_panel(state))

    if state.finished:
        parts.append(build_final_panel(state))

    parts.append(build_hand_history(state))
    parts.append(build_commentary(state))
    parts.append(build_footer(state))

    return Group(*parts)


# ── Scrabble Spectator ─────────────────────────────────────────────

# Premium square positions (inline for standalone script)
_SCRABBLE_PREMIUM: dict[tuple[int, int], str] = {}
for _r, _c in [(0, 0), (0, 7), (0, 14), (7, 0), (7, 14), (14, 0), (14, 7), (14, 14)]:
    _SCRABBLE_PREMIUM[(_r, _c)] = "TW"
for _r, _c in [
    (1, 1), (2, 2), (3, 3), (4, 4), (1, 13), (2, 12), (3, 11), (4, 10),
    (10, 4), (11, 3), (12, 2), (13, 1), (10, 10), (11, 11), (12, 12), (13, 13), (7, 7),
]:
    _SCRABBLE_PREMIUM[(_r, _c)] = "DW"
for _r, _c in [
    (1, 5), (1, 9), (5, 1), (5, 5), (5, 9), (5, 13),
    (9, 1), (9, 5), (9, 9), (9, 13), (13, 5), (13, 9),
]:
    _SCRABBLE_PREMIUM[(_r, _c)] = "TL"
for _r, _c in [
    (0, 3), (0, 11), (2, 6), (2, 8), (3, 0), (3, 7), (3, 14),
    (6, 2), (6, 6), (6, 8), (6, 12), (7, 3), (7, 11),
    (8, 2), (8, 6), (8, 8), (8, 12), (11, 0), (11, 7), (11, 14),
    (12, 6), (12, 8), (14, 3), (14, 11),
]:
    _SCRABBLE_PREMIUM[(_r, _c)] = "DL"


@dataclass
class ScrabbleWordRecord:
    """Record of a single Scrabble action."""

    turn_number: int
    model: str
    player_id: str
    action_type: str  # "play", "exchange", "pass", "forfeit"
    word: str | None = None
    position: tuple | None = None
    direction: str | None = None
    points: int = 0
    cross_words: list = field(default_factory=list)
    bingo: bool = False
    tiles_exchanged: int = 0
    is_violation: bool = False


@dataclass
class ScrabbleMatchState:
    """Accumulated state for a Scrabble match spectator."""

    match_id: str = ""
    model_a: str = ""
    model_b: str = ""
    board: list = field(default_factory=lambda: [[None] * 15 for _ in range(15)])
    scores: dict = field(default_factory=lambda: {"player_a": 0, "player_b": 0})
    racks: dict = field(default_factory=lambda: {"player_a": [], "player_b": []})
    tiles_remaining: int = 86  # 100 - 14
    consecutive_passes: int = 0
    turn_count: int = 0
    active_player: str = "player_a"
    last_player_id: str = ""
    last_model: str = ""
    word_history: deque = field(default_factory=lambda: deque(maxlen=8))
    commentary: deque = field(default_factory=lambda: deque(maxlen=10))
    finished: bool = False
    final_scores: dict = field(default_factory=dict)
    highlight_turns: list = field(default_factory=list)
    violations: dict = field(default_factory=lambda: {"player_a": 0, "player_b": 0})
    total_bingos: dict = field(default_factory=lambda: {"player_a": 0, "player_b": 0})
    total_tokens_used: dict = field(default_factory=lambda: {"player_a": 0, "player_b": 0})
    emojis: dict = field(default_factory=lambda: {"player_a": "", "player_b": ""})


def process_scrabble_turn(state: ScrabbleMatchState, data: dict) -> None:
    """Update Scrabble match state from a single telemetry line."""
    # Match summary
    if data.get("record_type") == "match_summary":
        state.finished = True
        state.final_scores = data.get("final_scores", {})
        state.highlight_turns = data.get("highlight_hands", [])
        pm = data.get("player_models", {})
        if pm:
            state.model_a = pm.get("player_a", state.model_a)
            state.model_b = pm.get("player_b", state.model_b)
        _assign_emojis(state)
        # Try to score the last unscored word from final score delta
        if state.word_history:
            last = state.word_history[-1]
            if last.action_type == "play" and last.points == 0:
                delta = int(state.final_scores.get(last.player_id, 0)) - state.scores.get(
                    last.player_id, 0
                )
                if delta > 0:
                    last.points = delta
        return

    state.turn_count += 1
    snap = data.get("state_snapshot", {})
    player_id = data.get("player_id", "")
    model_id = data.get("model_id", "")

    # Match info from first turns
    if not state.match_id:
        state.match_id = data.get("match_id", "")
    if player_id == "player_a" and not state.model_a:
        state.model_a = model_id
    elif player_id == "player_b" and not state.model_b:
        state.model_b = model_id
    _assign_emojis(state)

    # Update game state fields
    state.tiles_remaining = snap.get("tiles_remaining", state.tiles_remaining)
    state.consecutive_passes = snap.get("consecutive_passes", state.consecutive_passes)
    state.active_player = snap.get("active_player", state.active_player)

    # Extract rack from prompt text
    prompt = data.get("prompt", "")
    if player_id and prompt:
        m = re.search(r"Your rack:\s*(.+)", prompt)
        if m:
            state.racks[player_id] = m.group(1).strip().split()

    # Parse current action
    parsed = data.get("parsed_action") or {}
    action_type = parsed.get("action", "???")
    violation = data.get("violation")
    is_forfeit = data.get("validation_result") == "forfeit"
    if is_forfeit:
        action_type = "forfeit"

    state.last_player_id = player_id
    state.last_model = model_id

    if violation:
        state.violations[player_id] = state.violations.get(player_id, 0) + 1

    tokens = data.get("input_tokens", 0) + data.get("output_tokens", 0)
    state.total_tokens_used[player_id] = state.total_tokens_used.get(player_id, 0) + tokens

    # Build word record for this action
    word = None
    position = None
    direction = None
    tiles_exchanged = 0

    if action_type == "play" and not is_forfeit:
        word = parsed.get("word", "").upper() or None
        pos = parsed.get("position", [])
        direction = parsed.get("direction")
        if isinstance(pos, list) and len(pos) == 2:
            position = (int(pos[0]), int(pos[1]))

        # Apply to local board if the action was legal
        if data.get("validation_result") == "legal" and word and position and direction:
            blanks = {int(k) for k in (parsed.get("blank_assignments") or {}).keys()}
            row, col = position
            for i, ch in enumerate(word):
                r = row + (i if direction == "down" else 0)
                c = col + (i if direction == "across" else 0)
                if 0 <= r < 15 and 0 <= c < 15 and state.board[r][c] is None:
                    state.board[r][c] = (ch.upper(), i in blanks)

    elif action_type == "exchange" and not is_forfeit:
        tiles_exchanged = len(parsed.get("tiles_to_exchange", []))

    state.word_history.append(
        ScrabbleWordRecord(
            turn_number=state.turn_count,
            model=model_id,
            player_id=player_id,
            action_type=action_type,
            word=word,
            position=position,
            direction=direction,
            tiles_exchanged=tiles_exchanged,
            is_violation=violation is not None or is_forfeit,
        )
    )

    # Score deltas — fill in the word record that scored points
    new_scores = snap.get("scores", {})
    if new_scores:
        for pid in ("player_a", "player_b"):
            delta = new_scores.get(pid, 0) - state.scores.get(pid, 0)
            if delta > 0:
                for rec in reversed(state.word_history):
                    if rec.player_id == pid and rec.action_type == "play" and rec.points == 0:
                        rec.points = delta
                        break
        state.scores = dict(new_scores)

    # Bingo / cross-words from snapshot telemetry
    snap_word = snap.get("word_played")
    snap_bingo = snap.get("bingo", False)
    snap_cross = snap.get("cross_words_formed", [])
    if snap_word:
        for rec in reversed(state.word_history):
            if rec.word and rec.word.upper() == snap_word.upper():
                if snap_cross and not rec.cross_words:
                    rec.cross_words = list(snap_cross)
                if snap_bingo and not rec.bingo:
                    rec.bingo = True
                    state.total_bingos[rec.player_id] = (
                        state.total_bingos.get(rec.player_id, 0) + 1
                    )
                break

    reasoning = truncate_reasoning(data.get("reasoning_output"))
    state.commentary.append(
        CommentaryLine(
            hand_number=state.turn_count,
            street="",
            model=model_id,
            player_id=player_id,
            action=action_type,
            amount=None,
            reasoning_snippet=reasoning,
            latency_ms=data.get("latency_ms", 0),
            is_violation=violation is not None or is_forfeit,
        )
    )


# ── Scrabble Rendering ────────────────────────────────────────────


def _scrabble_board_text(state: ScrabbleMatchState) -> Text:
    """Render 15×15 board with colored premium squares."""
    board = Text()
    board.append("      ", style="dim")
    for c in range(15):
        board.append(f"{c:>3d}", style="dim")
    board.append("\n")

    for r in range(15):
        board.append(f"  {r:>2d}  ", style="dim")
        for c in range(15):
            cell = state.board[r][c]
            if cell is not None:
                letter, is_blank = cell
                if is_blank:
                    board.append(f" {letter.lower()} ", style="bold yellow")
                else:
                    board.append(f" {letter} ", style="bold white")
            else:
                prem = _SCRABBLE_PREMIUM.get((r, c))
                if prem == "TW":
                    board.append(" 3W", style="bold red")
                elif prem == "DW":
                    if (r, c) == (7, 7):
                        board.append("  \u2605", style="bold yellow")
                    else:
                        board.append(" 2W", style="bold magenta")
                elif prem == "TL":
                    board.append(" 3L", style="bold blue")
                elif prem == "DL":
                    board.append(" 2L", style="bold cyan")
                else:
                    board.append("  .", style="dim")
        board.append("\n")

    return board


def _format_rack(tiles: list) -> Text:
    """Render a player's rack with tile styling."""
    rack = Text()
    for i, tile in enumerate(sorted(tiles)):
        if i > 0:
            rack.append(" ")
        if tile == "?":
            rack.append("[?]", style="bold yellow")
        elif tile in "JQXZ":
            rack.append(f"[{tile}]", style="bold red")
        elif tile in "KFHVWY":
            rack.append(f"[{tile}]", style="bold")
        else:
            rack.append(f"[{tile}]", style="")
    return rack


def _make_score_bar(score: int, max_score: int, color: str) -> Text:
    """Score bar proportional to the leading score."""
    total = max(max_score, 1)
    filled = int(min(1, score / total) * BAR_WIDTH)
    empty = BAR_WIDTH - filled
    bar = Text()
    bar.append("\u2588" * filled, style=f"bold {color}")
    bar.append("\u2591" * empty, style="dim")
    bar.append(f" {score}", style=f"bold {color}")
    return bar


def build_scrabble_header(state: ScrabbleMatchState) -> Panel:
    """Match header with scores and turn info."""
    title = Text()
    if state.finished:
        title.append("FINAL  ", style="bold red blink")
    else:
        title.append("LIVE  ", style="bold green")
    title.append("SCRABBLE  ", style="bold white")
    emoji_a = state.emojis.get("player_a", "")
    emoji_b = state.emojis.get("player_b", "")
    title.append(f"{emoji_a} {state.model_a or '???'}", style=f"bold {PLAYER_COLORS['player_a']}")
    title.append("  vs  ", style="dim")
    title.append(f"{emoji_b} {state.model_b or '???'}", style=f"bold {PLAYER_COLORS['player_b']}")

    sub = Text()
    sub.append(f"Turn {state.turn_count}", style="bold")
    sub.append("  |  ", style="dim")
    score_a = state.scores.get("player_a", 0)
    score_b = state.scores.get("player_b", 0)
    sub.append(f"{score_a}", style=f"bold {PLAYER_COLORS['player_a']}")
    sub.append(" – ", style="dim")
    sub.append(f"{score_b}", style=f"bold {PLAYER_COLORS['player_b']}")
    sub.append("  |  ", style="dim")
    sub.append(f"Bag: {state.tiles_remaining}", style="bold yellow")
    sub.append("  |  ", style="dim")
    pass_style = "bold red" if state.consecutive_passes >= 4 else "dim"
    sub.append(f"Passes: {state.consecutive_passes}/6", style=pass_style)

    return Panel(
        Group(Align.center(title), Align.center(sub)),
        border_style="bright_white" if not state.finished else "red",
        padding=(0, 1),
    )


def build_scrabble_board_panel(state: ScrabbleMatchState) -> Panel:
    """Board on left, scoreboard + racks on right."""
    board_text = _scrabble_board_text(state)

    # Sidebar
    side = Text()
    side.append("SCORES\n", style="bold underline")
    max_score = max(state.scores.get("player_a", 0), state.scores.get("player_b", 0), 1)

    emoji_a = state.emojis.get("player_a", "")
    emoji_b = state.emojis.get("player_b", "")
    a_name = f"{emoji_a} {(state.model_a or 'Player A')[:14]}"
    b_name = f"{emoji_b} {(state.model_b or 'Player B')[:14]}"

    side.append(f"  {a_name}\n", style=f"bold {PLAYER_COLORS['player_a']}")
    side.append("  ")
    side.append_text(
        _make_score_bar(state.scores.get("player_a", 0), max_score, PLAYER_COLORS["player_a"])
    )
    side.append("\n")
    side.append(f"  {b_name}\n", style=f"bold {PLAYER_COLORS['player_b']}")
    side.append("  ")
    side.append_text(
        _make_score_bar(state.scores.get("player_b", 0), max_score, PLAYER_COLORS["player_b"])
    )
    side.append("\n\n")

    side.append("RACKS\n", style="bold underline")
    side.append("  A: ", style=f"bold {PLAYER_COLORS['player_a']}")
    side.append_text(_format_rack(state.racks.get("player_a", [])))
    side.append("\n")
    side.append("  B: ", style=f"bold {PLAYER_COLORS['player_b']}")
    side.append_text(_format_rack(state.racks.get("player_b", [])))
    side.append("\n\n")

    side.append(f"  Bag: {state.tiles_remaining} tiles\n", style="bold yellow")

    violations_a = state.violations.get("player_a", 0)
    violations_b = state.violations.get("player_b", 0)
    if violations_a or violations_b:
        side.append(f"  Violations: A:{violations_a} B:{violations_b}\n", style="bold red")

    bingos_a = state.total_bingos.get("player_a", 0)
    bingos_b = state.total_bingos.get("player_b", 0)
    if bingos_a + bingos_b > 0:
        side.append(f"  Bingos: A:{bingos_a} B:{bingos_b}\n", style="bold yellow")

    # Side-by-side layout
    layout = Table(show_header=False, show_edge=False, padding=0, expand=True)
    layout.add_column("board", ratio=3)
    layout.add_column("side", ratio=1, min_width=35)
    layout.add_row(board_text, side)

    return Panel(layout, title="[bold]Board[/bold]", border_style="green", padding=(0, 1))


def build_scrabble_word_history(state: ScrabbleMatchState) -> Panel:
    """Recent word plays with scores, cross-words, bingo alerts."""
    lines: list[Text] = []
    if not state.word_history:
        lines.append(Text("  No plays yet", style="dim italic"))
    else:
        for rec in reversed(state.word_history):
            line = Text()
            is_hl = rec.turn_number in state.highlight_turns or rec.bingo
            line.append(" \u2605 " if is_hl else "   ", style="bold yellow" if is_hl else "")
            line.append(f"T{rec.turn_number:<3d} ", style="dim")

            color = PLAYER_COLORS.get(rec.player_id, "white")
            emoji = state.emojis.get(rec.player_id, "")
            name = rec.model[:16] if rec.model else "???"
            line.append(f"{emoji}{name:<16s} ", style=f"bold {color}")

            if rec.action_type == "play" and rec.word:
                arrow = "\u2192" if rec.direction == "across" else "\u2193"
                line.append(f"{rec.word}", style="bold white")
                if rec.position:
                    line.append(f" ({rec.position[0]},{rec.position[1]}){arrow}", style="dim")
                if rec.points > 0:
                    line.append(f"  {rec.points}pts", style="bold green")
                if rec.bingo:
                    line.append("  BINGO!", style="bold yellow on red")
                if rec.cross_words:
                    cw_str = " ".join(f"+{w}" for w in rec.cross_words[:3])
                    line.append(f"  {cw_str}", style="dim cyan")
            elif rec.action_type == "exchange":
                line.append(f"exchanged {rec.tiles_exchanged} tiles", style="dim")
            elif rec.action_type == "pass":
                line.append("PASS", style="dim yellow")
            elif rec.action_type == "forfeit":
                line.append("FORFEIT", style="bold red")
            else:
                line.append(f"{rec.action_type}", style="dim")

            lines.append(line)

    return Panel(
        Group(*lines),
        title="[bold]Word History[/bold]",
        border_style="yellow",
        padding=(0, 1),
    )


def build_scrabble_commentary(state: ScrabbleMatchState) -> Panel:
    """Play-by-play reasoning feed."""
    lines: list[Text] = []
    if not state.commentary:
        lines.append(Text("  Waiting for action...", style="dim italic"))
    else:
        for entry in reversed(state.commentary):
            line = Text()
            line.append(f"  T{entry.hand_number:<3d} ", style="dim")

            color = PLAYER_COLORS.get(entry.player_id, "white")
            line.append(f"{entry.model}", style=f"bold {color}")

            if entry.is_violation:
                line.append(f" {entry.action}", style="bold red")
                line.append(" !", style="bold red")
            elif entry.action == "play":
                line.append(" plays", style="bold green")
            elif entry.action == "exchange":
                line.append(" exchanges", style="bold")
            elif entry.action == "pass":
                line.append(" passes", style="yellow")
            elif entry.action == "forfeit":
                line.append(" FORFEITS", style="bold red")
            else:
                line.append(f" {entry.action}", style="")

            if entry.latency_ms > 100:
                line.append(f"  ({entry.latency_ms / 1000:.1f}s)", style="dim")

            lines.append(line)

            if entry.reasoning_snippet:
                rl = Text()
                rl.append("        ", style="")
                rl.append(f'"{entry.reasoning_snippet}"', style="dim italic")
                lines.append(rl)

    return Panel(
        Group(*lines),
        title="[bold]Play-by-Play[/bold]",
        border_style="blue",
        padding=(0, 1),
    )


def build_scrabble_footer(state: ScrabbleMatchState) -> Text:
    """Status bar for Scrabble."""
    footer = Text()
    if state.finished:
        footer.append(" MATCH COMPLETE ", style="bold white on red")
        for pid, label in [("player_a", state.model_a), ("player_b", state.model_b)]:
            score = state.final_scores.get(pid, 0)
            color = PLAYER_COLORS[pid]
            footer.append(f"  {label}: {score:.0f}", style=f"bold {color}")
    else:
        footer.append(" LIVE ", style="bold white on green")
        footer.append(f"  Refreshing every {REFRESH_RATE}s", style="dim")
        footer.append("  |  Ctrl+C to exit", style="dim")
    return footer


def build_scrabble_final_panel(state: ScrabbleMatchState) -> Panel:
    """Final results panel."""
    score_a = state.final_scores.get("player_a", 0)
    score_b = state.final_scores.get("player_b", 0)

    if score_a > score_b:
        w_emoji = state.emojis.get("player_a", "")
        winner = f"{w_emoji} {state.model_a}"
        w_score, l_score = score_a, score_b
        w_color = PLAYER_COLORS["player_a"]
    elif score_b > score_a:
        w_emoji = state.emojis.get("player_b", "")
        winner = f"{w_emoji} {state.model_b}"
        w_score, l_score = score_b, score_a
        w_color = PLAYER_COLORS["player_b"]
    else:
        winner = "TIE"
        w_score = score_a
        w_color = "yellow"

    result = Text()
    result.append("\n")
    if winner == "TIE":
        result.append("    DRAW", style="bold yellow")
        result.append(f" \u2014 {w_score:.0f} each\n", style="bold")
    else:
        result.append(f"    {winner}", style=f"bold {w_color}")
        result.append(" WINS", style="bold green")
        result.append(f"  {w_score:.0f} \u2013 {l_score:.0f}", style="bold")
        result.append(f"  (+{w_score - l_score:.0f})\n", style="bold yellow")

    bingos_a = state.total_bingos.get("player_a", 0)
    bingos_b = state.total_bingos.get("player_b", 0)
    if bingos_a + bingos_b > 0:
        result.append(f"\n    Bingos: A:{bingos_a}  B:{bingos_b}\n", style="dim")

    viol_a = state.violations.get("player_a", 0)
    viol_b = state.violations.get("player_b", 0)
    if viol_a + viol_b > 0:
        result.append(f"    Violations: A:{viol_a}  B:{viol_b}\n", style="dim red")

    if state.highlight_turns:
        result.append(
            f"    Highlights: {', '.join(f'T{h}' for h in state.highlight_turns)}\n",
            style="dim",
        )

    result.append("\n")
    return Panel(
        Align.center(result),
        title="[bold white on red] FINAL RESULT [/bold white on red]",
        border_style="red",
    )


def render_scrabble(state: ScrabbleMatchState) -> Group:
    """Build the full Scrabble display."""
    parts = [
        build_scrabble_header(state),
        build_scrabble_board_panel(state),
    ]
    if state.finished:
        parts.append(build_scrabble_final_panel(state))
    parts.append(build_scrabble_word_history(state))
    parts.append(build_scrabble_commentary(state))
    parts.append(build_scrabble_footer(state))
    return Group(*parts)


# ── Tic-Tac-Toe Spectator ─────────────────────────────────────────


@dataclass
class TicTacToeGameRecord:
    """Result of a single game in a series."""

    game_number: int
    result: str  # "x_wins", "o_wins", "draw"
    x_player_model: str
    o_player_model: str


@dataclass
class TicTacToeMatchState:
    """Accumulated state for a Tic-Tac-Toe match spectator."""

    match_id: str = ""
    model_a: str = ""
    model_b: str = ""
    board: list = field(default_factory=lambda: [[""] * 3 for _ in range(3)])
    series_scores: dict = field(
        default_factory=lambda: {"player_a": 0.0, "player_b": 0.0}
    )
    game_number: int = 1
    game_turn: int = 0
    turn_count: int = 0
    active_player: str = "player_a"
    last_player_id: str = ""
    last_model: str = ""
    last_position: list | None = None
    game_history: deque = field(default_factory=lambda: deque(maxlen=12))
    commentary: deque = field(default_factory=lambda: deque(maxlen=10))
    finished: bool = False
    final_scores: dict = field(default_factory=dict)
    highlight_games: list = field(default_factory=list)
    violations: dict = field(
        default_factory=lambda: {"player_a": 0, "player_b": 0}
    )
    total_tokens_used: dict = field(
        default_factory=lambda: {"player_a": 0, "player_b": 0}
    )
    emojis: dict = field(default_factory=lambda: {"player_a": "", "player_b": ""})
    first_player: str = "player_a"
    prev_game_number: int = 1


def process_tictactoe_turn(state: TicTacToeMatchState, data: dict) -> None:
    """Update Tic-Tac-Toe match state from a single telemetry line."""
    if data.get("record_type") == "match_summary":
        state.finished = True
        state.final_scores = data.get("final_scores", {})
        state.highlight_games = data.get("highlight_hands", [])
        pm = data.get("player_models", {})
        if pm:
            old_a, old_b = state.model_a, state.model_b
            state.model_a = pm.get("player_a", state.model_a)
            state.model_b = pm.get("player_b", state.model_b)
            # Sync game history records to new short names
            for rec in state.game_history:
                if rec.x_player_model == old_a:
                    rec.x_player_model = state.model_a
                elif rec.x_player_model == old_b:
                    rec.x_player_model = state.model_b
                if rec.o_player_model == old_a:
                    rec.o_player_model = state.model_a
                elif rec.o_player_model == old_b:
                    rec.o_player_model = state.model_b
        _assign_emojis(state)
        return

    state.turn_count += 1
    snap = data.get("state_snapshot", {})
    player_id = data.get("player_id", "")
    model_id = data.get("model_id", "")

    if not state.match_id:
        state.match_id = data.get("match_id", "")
    if player_id == "player_a" and not state.model_a:
        state.model_a = model_id
    elif player_id == "player_b" and not state.model_b:
        state.model_b = model_id
    _assign_emojis(state)

    # Update board from snapshot
    snap_board = snap.get("board")
    if snap_board and isinstance(snap_board, list):
        state.board = [row[:] for row in snap_board]

    game_num = snap.get("hand_number", state.game_number)
    state.game_turn = snap.get("game_turn", state.game_turn)
    state.active_player = snap.get("active_player", state.active_player)

    # Detect game transition — record completed game
    if game_num > state.prev_game_number:
        result = snap.get("result")
        if result:
            # Figure out who was X last game (first_player alternates)
            x_model = (
                state.model_a
                if state.first_player == "player_a"
                else state.model_b
            )
            o_model = (
                state.model_b
                if state.first_player == "player_a"
                else state.model_a
            )
            state.game_history.append(
                TicTacToeGameRecord(
                    game_number=state.prev_game_number,
                    result=result,
                    x_player_model=x_model,
                    o_player_model=o_model,
                )
            )
            # First player alternates each game
            state.first_player = (
                "player_b"
                if state.first_player == "player_a"
                else "player_a"
            )
        state.prev_game_number = game_num

    state.game_number = game_num

    # Series scores
    snap_scores = snap.get("series_scores", snap.get("scores"))
    if snap_scores:
        state.series_scores = dict(snap_scores)

    # Parse action
    parsed = data.get("parsed_action") or {}
    action_type = parsed.get("action", "???")
    violation = data.get("violation")
    is_forfeit = data.get("validation_result") == "forfeit"
    if is_forfeit:
        action_type = "forfeit"

    position = parsed.get("position")
    state.last_player_id = player_id
    state.last_model = model_id
    state.last_position = position

    if violation:
        state.violations[player_id] = state.violations.get(player_id, 0) + 1

    tokens = data.get("input_tokens", 0) + data.get("output_tokens", 0)
    state.total_tokens_used[player_id] = (
        state.total_tokens_used.get(player_id, 0) + tokens
    )

    # Commentary
    pos_str = ""
    if position and isinstance(position, list) and len(position) == 2:
        pos_str = f"[{position[0]},{position[1]}]"

    reasoning = truncate_reasoning(data.get("reasoning_output"))
    state.commentary.append(
        CommentaryLine(
            hand_number=state.turn_count,
            street=pos_str,
            model=model_id,
            player_id=player_id,
            action=action_type,
            amount=None,
            reasoning_snippet=reasoning,
            latency_ms=data.get("latency_ms", 0),
            is_violation=violation is not None or is_forfeit,
        )
    )


# ── Tic-Tac-Toe Rendering ───────────────────────────────────────────


_TTT_MARK_STYLES = {"X": "bold cyan", "O": "bold magenta", "": "dim"}


def _tictactoe_board_text(state: TicTacToeMatchState) -> Text:
    """Render 3x3 board with box-drawing characters."""
    board = Text()
    board.append("        0     1     2\n", style="dim")
    board.append("      \u250c\u2500\u2500\u2500\u2500\u2500\u252c\u2500\u2500\u2500\u2500\u2500\u252c\u2500\u2500\u2500\u2500\u2500\u2510\n", style="dim")

    for r in range(3):
        board.append(f"  {r}   ", style="dim")
        for c in range(3):
            board.append("\u2502", style="dim")
            cell = state.board[r][c] if state.board else ""
            if cell:
                # Color X as player_a color, O as player_b color
                # (depends on who is first_player this game)
                style = _TTT_MARK_STYLES.get(cell, "bold white")
                board.append(f"  {cell}  ", style=style)
            else:
                board.append("  \u00b7  ", style="dim")
        board.append("\u2502\n", style="dim")
        if r < 2:
            board.append("      \u251c\u2500\u2500\u2500\u2500\u2500\u253c\u2500\u2500\u2500\u2500\u2500\u253c\u2500\u2500\u2500\u2500\u2500\u2524\n", style="dim")

    board.append("      \u2514\u2500\u2500\u2500\u2500\u2500\u2534\u2500\u2500\u2500\u2500\u2500\u2534\u2500\u2500\u2500\u2500\u2500\u2518\n", style="dim")

    # Last move indicator
    if state.last_position and isinstance(state.last_position, list):
        board.append(
            f"\n  Last: [{state.last_position[0]}, {state.last_position[1]}]",
            style="bold yellow",
        )
        board.append(f" by {state.last_model}", style="dim")

    return board


def _make_series_bar(score: float, max_score: float, color: str) -> Text:
    """Series score bar."""
    total = max(max_score, 0.5)
    filled = int(min(1, score / total) * BAR_WIDTH)
    empty = BAR_WIDTH - filled
    bar = Text()
    bar.append("\u2588" * filled, style=f"bold {color}")
    bar.append("\u2591" * empty, style="dim")
    bar.append(f" {score:.1f}", style=f"bold {color}")
    return bar


def build_tictactoe_header(state: TicTacToeMatchState) -> Panel:
    """Match header with series score and game info."""
    title = Text()
    if state.finished:
        title.append("FINAL  ", style="bold red blink")
    else:
        title.append("LIVE  ", style="bold green")
    title.append("TIC-TAC-TOE  ", style="bold white")
    emoji_a = state.emojis.get("player_a", "")
    emoji_b = state.emojis.get("player_b", "")
    title.append(
        f"{emoji_a} {state.model_a or '???'}",
        style=f"bold {PLAYER_COLORS['player_a']}",
    )
    title.append("  vs  ", style="dim")
    title.append(
        f"{emoji_b} {state.model_b or '???'}",
        style=f"bold {PLAYER_COLORS['player_b']}",
    )

    sub = Text()
    score_a = state.series_scores.get("player_a", 0)
    score_b = state.series_scores.get("player_b", 0)
    # When finished, show last real game number (not phantom incremented one)
    display_game = (
        state.game_history[-1].game_number
        if state.finished and state.game_history
        else state.game_number
    )
    sub.append(f"Game {display_game}", style="bold")
    sub.append("  |  ", style="dim")
    sub.append(f"{score_a:.1f}", style=f"bold {PLAYER_COLORS['player_a']}")
    sub.append(" \u2013 ", style="dim")
    sub.append(f"{score_b:.1f}", style=f"bold {PLAYER_COLORS['player_b']}")
    sub.append("  |  ", style="dim")
    sub.append(f"Turn #{state.turn_count}", style="dim")

    return Panel(
        Group(Align.center(title), Align.center(sub)),
        border_style="bright_white" if not state.finished else "red",
        padding=(0, 1),
    )


def build_tictactoe_board_panel(state: TicTacToeMatchState) -> Panel:
    """Board on left, series scoreboard on right."""
    board_text = _tictactoe_board_text(state)

    side = Text()
    side.append("SERIES SCORE\n", style="bold underline")
    max_score = max(
        state.series_scores.get("player_a", 0),
        state.series_scores.get("player_b", 0),
        0.5,
    )

    emoji_a = state.emojis.get("player_a", "")
    emoji_b = state.emojis.get("player_b", "")
    a_name = f"{emoji_a} {(state.model_a or 'Player A')[:14]}"
    b_name = f"{emoji_b} {(state.model_b or 'Player B')[:14]}"

    side.append(f"  {a_name}\n", style=f"bold {PLAYER_COLORS['player_a']}")
    side.append("  ")
    side.append_text(
        _make_series_bar(
            state.series_scores.get("player_a", 0),
            max_score,
            PLAYER_COLORS["player_a"],
        )
    )
    side.append("\n")
    side.append(f"  {b_name}\n", style=f"bold {PLAYER_COLORS['player_b']}")
    side.append("  ")
    side.append_text(
        _make_series_bar(
            state.series_scores.get("player_b", 0),
            max_score,
            PLAYER_COLORS["player_b"],
        )
    )
    side.append("\n\n")

    # Current game info — use last game record when finished
    if state.finished and state.game_history:
        last_game = state.game_history[-1]
        a_is_x = last_game.x_player_model == state.model_a
    else:
        a_is_x = state.first_player == "player_a"
    x_model = (state.model_a or "A") if a_is_x else (state.model_b or "B")
    o_model = (state.model_b or "B") if a_is_x else (state.model_a or "A")
    side.append("CURRENT GAME\n", style="bold underline")
    side.append(f"  X: {x_model[:16]}\n", style="bold cyan")
    side.append(f"  O: {o_model[:16]}\n", style="bold magenta")
    side.append(f"  Move {state.game_turn}/9\n", style="dim")

    violations_a = state.violations.get("player_a", 0)
    violations_b = state.violations.get("player_b", 0)
    if violations_a or violations_b:
        side.append(
            f"\n  Violations: A:{violations_a} B:{violations_b}\n",
            style="bold red",
        )

    layout = Table(show_header=False, show_edge=False, padding=0, expand=True)
    layout.add_column("board", ratio=1)
    layout.add_column("side", ratio=1, min_width=35)
    layout.add_row(board_text, side)

    return Panel(
        layout, title="[bold]Board[/bold]", border_style="green", padding=(0, 1)
    )


def build_tictactoe_game_history(state: TicTacToeMatchState) -> Panel:
    """Recent game results in the series."""
    lines: list[Text] = []
    if not state.game_history:
        lines.append(Text("  No completed games yet", style="dim italic"))
    else:
        for rec in reversed(state.game_history):
            line = Text()
            is_hl = rec.game_number in state.highlight_games
            line.append(
                " \u2605 " if is_hl else "   ",
                style="bold yellow" if is_hl else "",
            )
            line.append(f"Game {rec.game_number:<3d}", style="bold")

            if rec.result == "x_wins":
                line.append(f"  X wins ", style="bold cyan")
                line.append(f"({rec.x_player_model})", style="dim")
            elif rec.result == "o_wins":
                line.append(f"  O wins ", style="bold magenta")
                line.append(f"({rec.o_player_model})", style="dim")
            else:
                line.append("  Draw", style="bold yellow")

            lines.append(line)

    return Panel(
        Group(*lines),
        title="[bold]Game History[/bold]",
        border_style="yellow",
        padding=(0, 1),
    )


def build_tictactoe_commentary(state: TicTacToeMatchState) -> Panel:
    """Play-by-play reasoning feed."""
    lines: list[Text] = []
    if not state.commentary:
        lines.append(Text("  Waiting for action...", style="dim italic"))
    else:
        for entry in reversed(state.commentary):
            line = Text()
            line.append(f"  #{entry.hand_number:<3d}", style="dim")
            if entry.street:  # position string
                line.append(f"{entry.street}  ", style="dim cyan")

            color = PLAYER_COLORS.get(entry.player_id, "white")
            line.append(f"{entry.model}", style=f"bold {color}")

            if entry.is_violation:
                line.append(f" {entry.action}", style="bold red")
                line.append(" !", style="bold red")
            elif entry.action == "play":
                line.append(" plays", style="bold green")
            elif entry.action == "forfeit":
                line.append(" FORFEITS", style="bold red")
            else:
                line.append(f" {entry.action}", style="")

            if entry.latency_ms > 100:
                line.append(f"  ({entry.latency_ms / 1000:.1f}s)", style="dim")

            lines.append(line)

            if entry.reasoning_snippet:
                rl = Text()
                rl.append("        ", style="")
                rl.append(
                    f'"{entry.reasoning_snippet}"', style="dim italic"
                )
                lines.append(rl)

    return Panel(
        Group(*lines),
        title="[bold]Play-by-Play[/bold]",
        border_style="blue",
        padding=(0, 1),
    )


def build_tictactoe_footer(state: TicTacToeMatchState) -> Text:
    """Status bar."""
    footer = Text()
    if state.finished:
        footer.append(" MATCH COMPLETE ", style="bold white on red")
        for pid, label in [
            ("player_a", state.model_a),
            ("player_b", state.model_b),
        ]:
            score = state.final_scores.get(pid, 0)
            color = PLAYER_COLORS[pid]
            footer.append(f"  {label}: {score:.1f}", style=f"bold {color}")
    else:
        footer.append(" LIVE ", style="bold white on green")
        footer.append(f"  Refreshing every {REFRESH_RATE}s", style="dim")
        footer.append("  |  Ctrl+C to exit", style="dim")
    return footer


def build_tictactoe_final_panel(state: TicTacToeMatchState) -> Panel:
    """Final series results panel."""
    score_a = state.final_scores.get("player_a", 0)
    score_b = state.final_scores.get("player_b", 0)

    if score_a > score_b:
        w_emoji = state.emojis.get("player_a", "")
        winner = f"{w_emoji} {state.model_a}"
        w_score, l_score = score_a, score_b
        w_color = PLAYER_COLORS["player_a"]
    elif score_b > score_a:
        w_emoji = state.emojis.get("player_b", "")
        winner = f"{w_emoji} {state.model_b}"
        w_score, l_score = score_b, score_a
        w_color = PLAYER_COLORS["player_b"]
    else:
        winner = "TIE"
        w_score = score_a
        w_color = "yellow"

    result = Text()
    result.append("\n")
    if winner == "TIE":
        result.append("    DRAW", style="bold yellow")
        result.append(f" \u2014 {w_score:.1f} each\n", style="bold")
    else:
        result.append(f"    {winner}", style=f"bold {w_color}")
        result.append(" WINS", style="bold green")
        result.append(
            f"  {w_score:.1f} \u2013 {l_score:.1f}", style="bold"
        )
        result.append(
            f"  (+{w_score - l_score:.1f})\n", style="bold yellow"
        )

    # Game breakdown
    wins_a = sum(
        1
        for rec in state.game_history
        if rec.result in ("x_wins", "o_wins")
        and (
            (rec.result == "x_wins" and rec.x_player_model == state.model_a)
            or (rec.result == "o_wins" and rec.o_player_model == state.model_a)
        )
    )
    wins_b = sum(
        1
        for rec in state.game_history
        if rec.result in ("x_wins", "o_wins")
        and (
            (rec.result == "x_wins" and rec.x_player_model == state.model_b)
            or (rec.result == "o_wins" and rec.o_player_model == state.model_b)
        )
    )
    draws = sum(1 for rec in state.game_history if rec.result == "draw")
    result.append(
        f"\n    W-D-L: {state.model_a[:12]} {wins_a}-{draws}-{wins_b}"
        f"  |  {state.model_b[:12]} {wins_b}-{draws}-{wins_a}\n",
        style="dim",
    )

    viol_a = state.violations.get("player_a", 0)
    viol_b = state.violations.get("player_b", 0)
    if viol_a + viol_b > 0:
        result.append(
            f"    Violations: A:{viol_a}  B:{viol_b}\n", style="dim red"
        )

    result.append("\n")
    return Panel(
        Align.center(result),
        title="[bold white on red] FINAL RESULT [/bold white on red]",
        border_style="red",
    )


def render_tictactoe(state: TicTacToeMatchState) -> Group:
    """Build the full Tic-Tac-Toe display."""
    parts = [
        build_tictactoe_header(state),
        build_tictactoe_board_panel(state),
    ]
    if state.finished:
        parts.append(build_tictactoe_final_panel(state))
    parts.append(build_tictactoe_game_history(state))
    parts.append(build_tictactoe_commentary(state))
    parts.append(build_tictactoe_footer(state))
    return Group(*parts)


# ── Connect Four Spectator ─────────────────────────────────────────


@dataclass
class ConnectFourMatchState:
    """Accumulated state for a Connect Four match spectator."""

    match_id: str = ""
    model_a: str = ""
    model_b: str = ""
    board: list = field(default_factory=lambda: [[""] * 7 for _ in range(6)])
    series_scores: dict = field(
        default_factory=lambda: {"player_a": 0.0, "player_b": 0.0}
    )
    game_number: int = 1
    game_turn: int = 0
    turn_count: int = 0
    active_player: str = "player_a"
    last_player_id: str = ""
    last_model: str = ""
    last_column: int | None = None
    last_row: int | None = None
    game_history: deque = field(default_factory=lambda: deque(maxlen=12))
    commentary: deque = field(default_factory=lambda: deque(maxlen=10))
    finished: bool = False
    final_scores: dict = field(default_factory=dict)
    highlight_games: list = field(default_factory=list)
    violations: dict = field(
        default_factory=lambda: {"player_a": 0, "player_b": 0}
    )
    total_tokens_used: dict = field(
        default_factory=lambda: {"player_a": 0, "player_b": 0}
    )
    emojis: dict = field(default_factory=lambda: {"player_a": "", "player_b": ""})
    first_player: str = "player_a"
    prev_game_number: int = 1


def process_connectfour_turn(state: ConnectFourMatchState, data: dict) -> None:
    """Update Connect Four match state from a single telemetry line."""
    if data.get("record_type") == "match_summary":
        state.finished = True
        state.final_scores = data.get("final_scores", {})
        state.highlight_games = data.get("highlight_hands", [])
        pm = data.get("player_models", {})
        if pm:
            old_a, old_b = state.model_a, state.model_b
            state.model_a = pm.get("player_a", state.model_a)
            state.model_b = pm.get("player_b", state.model_b)
            # Sync game history records to new short names
            for rec in state.game_history:
                if rec.x_player_model == old_a:
                    rec.x_player_model = state.model_a
                elif rec.x_player_model == old_b:
                    rec.x_player_model = state.model_b
                if rec.o_player_model == old_a:
                    rec.o_player_model = state.model_a
                elif rec.o_player_model == old_b:
                    rec.o_player_model = state.model_b
        _assign_emojis(state)
        return

    state.turn_count += 1
    snap = data.get("state_snapshot", {})
    player_id = data.get("player_id", "")
    model_id = data.get("model_id", "")

    if not state.match_id:
        state.match_id = data.get("match_id", "")
    if player_id == "player_a" and not state.model_a:
        state.model_a = model_id
    elif player_id == "player_b" and not state.model_b:
        state.model_b = model_id
    _assign_emojis(state)

    # Update board from snapshot
    snap_board = snap.get("board")
    if snap_board and isinstance(snap_board, list):
        state.board = [row[:] for row in snap_board]

    game_num = snap.get("hand_number", state.game_number)
    state.game_turn = snap.get("game_turn", state.game_turn)
    state.active_player = snap.get("active_player", state.active_player)

    # Detect game transition — record completed game
    if game_num > state.prev_game_number:
        result = snap.get("result")
        if result:
            x_model = (
                state.model_a
                if state.first_player == "player_a"
                else state.model_b
            )
            o_model = (
                state.model_b
                if state.first_player == "player_a"
                else state.model_a
            )
            state.game_history.append(
                TicTacToeGameRecord(
                    game_number=state.prev_game_number,
                    result=result,
                    x_player_model=x_model,
                    o_player_model=o_model,
                )
            )
            state.first_player = (
                "player_b"
                if state.first_player == "player_a"
                else "player_a"
            )
        state.prev_game_number = game_num

    state.game_number = game_num

    # Series scores
    snap_scores = snap.get("series_scores", snap.get("scores"))
    if snap_scores:
        state.series_scores = dict(snap_scores)

    # Parse action
    parsed = data.get("parsed_action") or {}
    action_type = parsed.get("action", "???")
    violation = data.get("violation")
    is_forfeit = data.get("validation_result") == "forfeit"
    if is_forfeit:
        action_type = "forfeit"

    column = snap.get("last_column")
    state.last_player_id = player_id
    state.last_model = model_id
    state.last_column = column
    state.last_row = snap.get("last_row")

    if violation:
        state.violations[player_id] = state.violations.get(player_id, 0) + 1

    tokens = data.get("input_tokens", 0) + data.get("output_tokens", 0)
    state.total_tokens_used[player_id] = (
        state.total_tokens_used.get(player_id, 0) + tokens
    )

    # Commentary
    col_str = f"col {column}" if column is not None else ""

    reasoning = truncate_reasoning(data.get("reasoning_output"))
    state.commentary.append(
        CommentaryLine(
            hand_number=state.turn_count,
            street=col_str,
            model=model_id,
            player_id=player_id,
            action=action_type,
            amount=None,
            reasoning_snippet=reasoning,
            latency_ms=data.get("latency_ms", 0),
            is_violation=violation is not None or is_forfeit,
        )
    )


# ── Connect Four Rendering ─────────────────────────────────────────


def _connectfour_board_text(state: ConnectFourMatchState) -> Text:
    """Render 6x7 board with box-drawing characters."""
    board = Text()

    # Determine mark->player mapping for the displayed board.
    # When finished, first_player has been toggled past the last game,
    # so use the last game record to determine who was actually X.
    if state.finished and state.game_history:
        last_game = state.game_history[-1]
        a_is_x = last_game.x_player_model == state.model_a
    else:
        a_is_x = state.first_player == "player_a"

    # Column headers
    board.append("      ", style="dim")
    for c in range(7):
        board.append(f"  {c}  ", style="dim")
    board.append("\n")
    board.append("      \u250c" + "\u252c".join(["\u2500\u2500\u2500\u2500"] * 7) + "\u2510\n", style="dim")

    for r in range(6):
        board.append(f"  {r}   ", style="dim")
        for c in range(7):
            board.append("\u2502", style="dim")
            cell = state.board[r][c] if state.board else ""
            if cell == "X":
                color = PLAYER_COLORS["player_a"] if a_is_x else PLAYER_COLORS["player_b"]
                board.append(f" \u25cf  ", style=f"bold {color}")
            elif cell == "O":
                color = PLAYER_COLORS["player_b"] if a_is_x else PLAYER_COLORS["player_a"]
                board.append(f" \u25cf  ", style=f"bold {color}")
            else:
                board.append(" \u00b7  ", style="dim")
        board.append("\u2502\n", style="dim")
        if r < 5:
            board.append("      \u251c" + "\u253c".join(["\u2500\u2500\u2500\u2500"] * 7) + "\u2524\n", style="dim")

    board.append("      \u2514" + "\u2534".join(["\u2500\u2500\u2500\u2500"] * 7) + "\u2518\n", style="dim")

    # Last move indicator
    if state.last_column is not None:
        board.append(
            f"\n  Last: col {state.last_column}",
            style="bold yellow",
        )
        board.append(f" by {state.last_model}", style="dim")

    return board


def build_connectfour_header(state: ConnectFourMatchState) -> Panel:
    """Match header with series score and game info."""
    title = Text()
    if state.finished:
        title.append("FINAL  ", style="bold red blink")
    else:
        title.append("LIVE  ", style="bold green")
    title.append("CONNECT FOUR  ", style="bold white")
    emoji_a = state.emojis.get("player_a", "")
    emoji_b = state.emojis.get("player_b", "")
    title.append(
        f"{emoji_a} {state.model_a or '???'}",
        style=f"bold {PLAYER_COLORS['player_a']}",
    )
    title.append("  vs  ", style="dim")
    title.append(
        f"{emoji_b} {state.model_b or '???'}",
        style=f"bold {PLAYER_COLORS['player_b']}",
    )

    sub = Text()
    score_a = state.series_scores.get("player_a", 0)
    score_b = state.series_scores.get("player_b", 0)
    # When finished, show last real game number (not phantom incremented one)
    display_game = (
        state.game_history[-1].game_number
        if state.finished and state.game_history
        else state.game_number
    )
    sub.append(f"Game {display_game}", style="bold")
    sub.append("  |  ", style="dim")
    sub.append(f"{score_a:.1f}", style=f"bold {PLAYER_COLORS['player_a']}")
    sub.append(" \u2013 ", style="dim")
    sub.append(f"{score_b:.1f}", style=f"bold {PLAYER_COLORS['player_b']}")
    sub.append("  |  ", style="dim")
    sub.append(f"Move {state.game_turn}", style="dim")

    return Panel(
        Group(Align.center(title), Align.center(sub)),
        border_style="bright_white" if not state.finished else "red",
        padding=(0, 1),
    )


def build_connectfour_board_panel(state: ConnectFourMatchState) -> Panel:
    """Board on left, series scoreboard on right."""
    board_text = _connectfour_board_text(state)

    side = Text()
    side.append("SERIES SCORE\n", style="bold underline")
    max_score = max(
        state.series_scores.get("player_a", 0),
        state.series_scores.get("player_b", 0),
        0.5,
    )

    emoji_a = state.emojis.get("player_a", "")
    emoji_b = state.emojis.get("player_b", "")
    a_name = f"{emoji_a} {(state.model_a or 'Player A')[:14]}"
    b_name = f"{emoji_b} {(state.model_b or 'Player B')[:14]}"

    side.append(f"  {a_name}\n", style=f"bold {PLAYER_COLORS['player_a']}")
    side.append("  ")
    side.append_text(
        _make_series_bar(
            state.series_scores.get("player_a", 0),
            max_score,
            PLAYER_COLORS["player_a"],
        )
    )
    side.append("\n")
    side.append(f"  {b_name}\n", style=f"bold {PLAYER_COLORS['player_b']}")
    side.append("  ")
    side.append_text(
        _make_series_bar(
            state.series_scores.get("player_b", 0),
            max_score,
            PLAYER_COLORS["player_b"],
        )
    )
    side.append("\n\n")

    # Current game info — use last game record when finished to avoid
    # first_player being toggled past the last game
    if state.finished and state.game_history:
        last_game = state.game_history[-1]
        a_is_x = last_game.x_player_model == state.model_a
    else:
        a_is_x = state.first_player == "player_a"
    x_model = (state.model_a or "A") if a_is_x else (state.model_b or "B")
    o_model = (state.model_b or "B") if a_is_x else (state.model_a or "A")
    x_color = PLAYER_COLORS["player_a"] if a_is_x else PLAYER_COLORS["player_b"]
    o_color = PLAYER_COLORS["player_b"] if a_is_x else PLAYER_COLORS["player_a"]

    side.append("CURRENT GAME\n", style="bold underline")
    side.append(f"  \u25cf {x_model[:16]}\n", style=f"bold {x_color}")
    side.append(f"  \u25cf {o_model[:16]}\n", style=f"bold {o_color}")
    side.append(f"  Move {state.game_turn}\n", style="dim")

    violations_a = state.violations.get("player_a", 0)
    violations_b = state.violations.get("player_b", 0)
    if violations_a or violations_b:
        side.append(
            f"\n  Violations: A:{violations_a} B:{violations_b}\n",
            style="bold red",
        )

    layout = Table(show_header=False, show_edge=False, padding=0, expand=True)
    layout.add_column("board", ratio=2)
    layout.add_column("side", ratio=1, min_width=35)
    layout.add_row(board_text, side)

    return Panel(
        layout, title="[bold]Board[/bold]", border_style="green", padding=(0, 1)
    )


def build_connectfour_game_history(state: ConnectFourMatchState) -> Panel:
    return build_tictactoe_game_history(state)


def build_connectfour_commentary(state: ConnectFourMatchState) -> Panel:
    return build_tictactoe_commentary(state)


def build_connectfour_footer(state: ConnectFourMatchState) -> Text:
    """Status bar."""
    footer = Text()
    if state.finished:
        footer.append(" MATCH COMPLETE ", style="bold white on red")
        for pid, label in [
            ("player_a", state.model_a),
            ("player_b", state.model_b),
        ]:
            score = state.final_scores.get(pid, 0)
            color = PLAYER_COLORS[pid]
            footer.append(f"  {label}: {score:.1f}", style=f"bold {color}")
    else:
        footer.append(" LIVE ", style="bold white on green")
        footer.append(f"  Refreshing every {REFRESH_RATE}s", style="dim")
        footer.append("  |  Ctrl+C to exit", style="dim")
    return footer


def build_connectfour_final_panel(state: ConnectFourMatchState) -> Panel:
    return build_tictactoe_final_panel(state)


def render_connectfour(state: ConnectFourMatchState) -> Group:
    """Build the full Connect Four display."""
    parts = [
        build_connectfour_header(state),
        build_connectfour_board_panel(state),
    ]
    if state.finished:
        parts.append(build_connectfour_final_panel(state))
    parts.append(build_connectfour_game_history(state))
    parts.append(build_connectfour_commentary(state))
    parts.append(build_connectfour_footer(state))
    return Group(*parts)


# ── Reversi Spectator ──────────────────────────────────────────────


@dataclass
class ReversiMatchState:
    """Accumulated state for a Reversi match spectator."""

    match_id: str = ""
    model_a: str = ""
    model_b: str = ""
    board: list = field(default_factory=lambda: [[""] * 8 for _ in range(8)])
    series_scores: dict = field(
        default_factory=lambda: {"player_a": 0.0, "player_b": 0.0}
    )
    game_number: int = 1
    game_turn: int = 0
    turn_count: int = 0
    active_player: str = "player_a"
    last_player_id: str = ""
    last_model: str = ""
    last_position: list | None = None
    last_flipped: list = field(default_factory=list)
    color_map: dict = field(
        default_factory=lambda: {"player_a": "B", "player_b": "W"}
    )
    piece_counts: dict = field(default_factory=lambda: {"B": 2, "W": 2})
    game_history: deque = field(default_factory=lambda: deque(maxlen=12))
    commentary: deque = field(default_factory=lambda: deque(maxlen=10))
    finished: bool = False
    final_scores: dict = field(default_factory=dict)
    highlight_games: list = field(default_factory=list)
    violations: dict = field(
        default_factory=lambda: {"player_a": 0, "player_b": 0}
    )
    total_tokens_used: dict = field(
        default_factory=lambda: {"player_a": 0, "player_b": 0}
    )
    emojis: dict = field(default_factory=lambda: {"player_a": "", "player_b": ""})
    first_player: str = "player_a"
    prev_game_number: int = 1


def process_reversi_turn(state: ReversiMatchState, data: dict) -> None:
    """Update Reversi match state from a single telemetry line."""
    if data.get("record_type") == "match_summary":
        state.finished = True
        state.final_scores = data.get("final_scores", {})
        state.highlight_games = data.get("highlight_hands", [])
        pm = data.get("player_models", {})
        if pm:
            old_a, old_b = state.model_a, state.model_b
            state.model_a = pm.get("player_a", state.model_a)
            state.model_b = pm.get("player_b", state.model_b)
            for rec in state.game_history:
                if rec.x_player_model == old_a:
                    rec.x_player_model = state.model_a
                elif rec.x_player_model == old_b:
                    rec.x_player_model = state.model_b
                if rec.o_player_model == old_a:
                    rec.o_player_model = state.model_a
                elif rec.o_player_model == old_b:
                    rec.o_player_model = state.model_b
        _assign_emojis(state)
        return

    state.turn_count += 1
    snap = data.get("state_snapshot", {})
    player_id = data.get("player_id", "")
    model_id = data.get("model_id", "")

    if not state.match_id:
        state.match_id = data.get("match_id", "")
    if player_id == "player_a" and not state.model_a:
        state.model_a = model_id
    elif player_id == "player_b" and not state.model_b:
        state.model_b = model_id
    _assign_emojis(state)

    # Update board from snapshot
    snap_board = snap.get("board")
    if snap_board and isinstance(snap_board, list):
        state.board = [row[:] for row in snap_board]

    game_num = snap.get("hand_number", state.game_number)
    state.game_turn = snap.get("game_turn", state.game_turn)
    state.active_player = snap.get("active_player", state.active_player)

    # Reversi-specific state
    pc = snap.get("piece_counts")
    if pc:
        state.piece_counts = dict(pc)
    cm = snap.get("color_map")
    if cm:
        state.color_map = dict(cm)

    # Detect game transition — record completed game
    if game_num > state.prev_game_number:
        result = snap.get("result")
        if result:
            b_model = (
                state.model_a
                if state.first_player == "player_a"
                else state.model_b
            )
            w_model = (
                state.model_b
                if state.first_player == "player_a"
                else state.model_a
            )
            state.game_history.append(
                TicTacToeGameRecord(
                    game_number=state.prev_game_number,
                    result=result,
                    x_player_model=b_model,  # B maps to x_player_model slot
                    o_player_model=w_model,
                )
            )
            state.first_player = (
                "player_b"
                if state.first_player == "player_a"
                else "player_a"
            )
        state.prev_game_number = game_num

    state.game_number = game_num

    # Series scores
    snap_scores = snap.get("series_scores", snap.get("scores"))
    if snap_scores:
        state.series_scores = dict(snap_scores)

    # Parse action
    parsed = data.get("parsed_action") or {}
    action_type = parsed.get("action", "???")
    violation = data.get("violation")
    is_forfeit = data.get("validation_result") == "forfeit"
    if is_forfeit:
        action_type = "forfeit"

    pos = snap.get("last_position")
    state.last_player_id = player_id
    state.last_model = model_id
    state.last_position = pos
    state.last_flipped = snap.get("last_flipped", [])

    if violation:
        state.violations[player_id] = state.violations.get(player_id, 0) + 1

    tokens = data.get("input_tokens", 0) + data.get("output_tokens", 0)
    state.total_tokens_used[player_id] = (
        state.total_tokens_used.get(player_id, 0) + tokens
    )

    # Commentary
    pos_str = f"({pos[0]},{pos[1]})" if pos else ""
    reasoning = truncate_reasoning(data.get("reasoning_output"))
    state.commentary.append(
        CommentaryLine(
            hand_number=state.turn_count,
            street=pos_str,
            model=model_id,
            player_id=player_id,
            action=action_type,
            amount=None,
            reasoning_snippet=reasoning,
            latency_ms=data.get("latency_ms", 0),
            is_violation=violation is not None or is_forfeit,
        )
    )


# ── Reversi Rendering ─────────────────────────────────────────────


def _reversi_board_text(state: ReversiMatchState) -> Text:
    """Render 8×8 board with box-drawing characters."""
    board = Text()

    # Determine mark->player mapping
    a_is_b = state.color_map.get("player_a") == "B"

    flipped_set = set()
    for pos in state.last_flipped:
        if isinstance(pos, (list, tuple)) and len(pos) == 2:
            flipped_set.add((pos[0], pos[1]))

    last_pos = None
    if state.last_position and isinstance(state.last_position, (list, tuple)):
        last_pos = (state.last_position[0], state.last_position[1])

    # Column headers
    board.append("      ", style="dim")
    for c in range(8):
        board.append(f"  {c}  ", style="dim")
    board.append("\n")
    board.append("      \u250c" + "\u252c".join(["\u2500\u2500\u2500\u2500"] * 8) + "\u2510\n", style="dim")

    for r in range(8):
        board.append(f"  {r}   ", style="dim")
        for c in range(8):
            board.append("\u2502", style="dim")
            cell = state.board[r][c] if state.board else ""
            is_last = last_pos == (r, c)
            is_flipped = (r, c) in flipped_set

            if cell == "B":
                color = PLAYER_COLORS["player_a"] if a_is_b else PLAYER_COLORS["player_b"]
                style = f"bold {color}"
                if is_last:
                    board.append(f" \u25cf  ", style=f"{style} underline")
                elif is_flipped:
                    board.append(f" \u25d9  ", style=style)
                else:
                    board.append(f" \u25cf  ", style=style)
            elif cell == "W":
                color = PLAYER_COLORS["player_b"] if a_is_b else PLAYER_COLORS["player_a"]
                style = f"bold {color}"
                if is_last:
                    board.append(f" \u25cf  ", style=f"{style} underline")
                elif is_flipped:
                    board.append(f" \u25d9  ", style=style)
                else:
                    board.append(f" \u25cf  ", style=style)
            else:
                board.append(" \u00b7  ", style="dim")
        board.append("\u2502\n", style="dim")
        if r < 7:
            board.append("      \u251c" + "\u253c".join(["\u2500\u2500\u2500\u2500"] * 8) + "\u2524\n", style="dim")

    board.append("      \u2514" + "\u2534".join(["\u2500\u2500\u2500\u2500"] * 8) + "\u2518\n", style="dim")

    # Last move indicator
    if state.last_position:
        board.append(
            f"\n  Last: ({state.last_position[0]},{state.last_position[1]})",
            style="bold yellow",
        )
        board.append(f" by {state.last_model}", style="dim")
        if state.last_flipped:
            board.append(f"  flipped {len(state.last_flipped)} pieces", style="dim")

    return board


def build_reversi_header(state: ReversiMatchState) -> Panel:
    """Match header with series score and game info."""
    title = Text()
    if state.finished:
        title.append("FINAL  ", style="bold red blink")
    else:
        title.append("LIVE  ", style="bold green")
    title.append("REVERSI  ", style="bold white")
    emoji_a = state.emojis.get("player_a", "")
    emoji_b = state.emojis.get("player_b", "")
    title.append(
        f"{emoji_a} {state.model_a or '???'}",
        style=f"bold {PLAYER_COLORS['player_a']}",
    )
    title.append("  vs  ", style="dim")
    title.append(
        f"{emoji_b} {state.model_b or '???'}",
        style=f"bold {PLAYER_COLORS['player_b']}",
    )

    sub = Text()
    score_a = state.series_scores.get("player_a", 0)
    score_b = state.series_scores.get("player_b", 0)
    display_game = (
        state.game_history[-1].game_number
        if state.finished and state.game_history
        else state.game_number
    )
    sub.append(f"Game {display_game}", style="bold")
    sub.append("  |  ", style="dim")
    sub.append(f"{score_a:.1f}", style=f"bold {PLAYER_COLORS['player_a']}")
    sub.append(" \u2013 ", style="dim")
    sub.append(f"{score_b:.1f}", style=f"bold {PLAYER_COLORS['player_b']}")
    sub.append("  |  ", style="dim")
    sub.append(f"Move {state.game_turn}", style="dim")
    sub.append("  |  ", style="dim")
    sub.append(
        f"B:{state.piece_counts.get('B', 0)} W:{state.piece_counts.get('W', 0)}",
        style="dim",
    )

    return Panel(
        Group(Align.center(title), Align.center(sub)),
        border_style="bright_white" if not state.finished else "red",
        padding=(0, 1),
    )


def build_reversi_board_panel(state: ReversiMatchState) -> Panel:
    """Board on left, series scoreboard on right."""
    board_text = _reversi_board_text(state)

    side = Text()
    side.append("SERIES SCORE\n", style="bold underline")
    max_score = max(
        state.series_scores.get("player_a", 0),
        state.series_scores.get("player_b", 0),
        0.5,
    )

    emoji_a = state.emojis.get("player_a", "")
    emoji_b = state.emojis.get("player_b", "")
    a_name = f"{emoji_a} {(state.model_a or 'Player A')[:14]}"
    b_name = f"{emoji_b} {(state.model_b or 'Player B')[:14]}"

    side.append(f"  {a_name}\n", style=f"bold {PLAYER_COLORS['player_a']}")
    side.append("  ")
    side.append_text(
        _make_series_bar(
            state.series_scores.get("player_a", 0),
            max_score,
            PLAYER_COLORS["player_a"],
        )
    )
    side.append("\n")
    side.append(f"  {b_name}\n", style=f"bold {PLAYER_COLORS['player_b']}")
    side.append("  ")
    side.append_text(
        _make_series_bar(
            state.series_scores.get("player_b", 0),
            max_score,
            PLAYER_COLORS["player_b"],
        )
    )
    side.append("\n\n")

    # Current game info
    a_is_b = state.color_map.get("player_a") == "B"
    b_model = (state.model_a or "A") if a_is_b else (state.model_b or "B")
    w_model = (state.model_b or "B") if a_is_b else (state.model_a or "A")
    b_color = PLAYER_COLORS["player_a"] if a_is_b else PLAYER_COLORS["player_b"]
    w_color = PLAYER_COLORS["player_b"] if a_is_b else PLAYER_COLORS["player_a"]

    side.append("CURRENT GAME\n", style="bold underline")
    side.append(f"  \u25cf {b_model[:16]} (B)\n", style=f"bold {b_color}")
    side.append(f"  \u25cf {w_model[:16]} (W)\n", style=f"bold {w_color}")
    side.append(f"  Move {state.game_turn}\n", style="dim")
    side.append(
        f"  B:{state.piece_counts.get('B', 0)}  "
        f"W:{state.piece_counts.get('W', 0)}\n",
        style="dim",
    )

    violations_a = state.violations.get("player_a", 0)
    violations_b = state.violations.get("player_b", 0)
    if violations_a or violations_b:
        side.append(
            f"\n  Violations: A:{violations_a} B:{violations_b}\n",
            style="bold red",
        )

    layout = Table(show_header=False, show_edge=False, padding=0, expand=True)
    layout.add_column("board", ratio=2)
    layout.add_column("side", ratio=1, min_width=35)
    layout.add_row(board_text, side)

    return Panel(
        layout, title="[bold]Board[/bold]", border_style="green", padding=(0, 1)
    )


def build_reversi_game_history(state: ReversiMatchState) -> Panel:
    return build_tictactoe_game_history(state)


def build_reversi_commentary(state: ReversiMatchState) -> Panel:
    return build_tictactoe_commentary(state)


def build_reversi_footer(state: ReversiMatchState) -> Text:
    """Status bar."""
    footer = Text()
    if state.finished:
        footer.append(" MATCH COMPLETE ", style="bold white on red")
        for pid, label in [
            ("player_a", state.model_a),
            ("player_b", state.model_b),
        ]:
            score = state.final_scores.get(pid, 0)
            color = PLAYER_COLORS[pid]
            footer.append(f"  {label}: {score:.1f}", style=f"bold {color}")
    else:
        footer.append(" LIVE ", style="bold white on green")
        footer.append(f"  Refreshing every {REFRESH_RATE}s", style="dim")
        footer.append("  |  Ctrl+C to exit", style="dim")
    return footer


def build_reversi_final_panel(state: ReversiMatchState) -> Panel:
    return build_tictactoe_final_panel(state)


def render_reversi(state: ReversiMatchState) -> Group:
    """Build the full Reversi display."""
    parts = [
        build_reversi_header(state),
        build_reversi_board_panel(state),
    ]
    if state.finished:
        parts.append(build_reversi_final_panel(state))
    parts.append(build_reversi_game_history(state))
    parts.append(build_reversi_commentary(state))
    parts.append(build_reversi_footer(state))
    return Group(*parts)


# ── File Tailing ────────────────────────────────────────────────────


def discover_latest_match() -> Path | None:
    """Find the most recently modified JSONL file in telemetry dir."""
    if not TELEMETRY_DIR.exists():
        return None
    jsonl_files = list(TELEMETRY_DIR.glob("*.jsonl"))
    if not jsonl_files:
        return None
    return max(jsonl_files, key=lambda f: f.stat().st_mtime)


def tail_jsonl(path: Path, position: int) -> tuple[list[dict], int]:
    """Read new lines from a JSONL file starting at byte position."""
    lines = []
    try:
        size = path.stat().st_size
        if size <= position:
            return [], position

        with open(path, "r") as f:
            f.seek(position)
            for raw_line in f:
                raw_line = raw_line.strip()
                if raw_line:
                    try:
                        lines.append(json.loads(raw_line))
                    except json.JSONDecodeError:
                        pass  # Partial write, will catch next refresh
            new_position = f.tell()
    except FileNotFoundError:
        return [], position

    return lines, new_position


# ── Main ────────────────────────────────────────────────────────────


def main() -> None:
    console = Console()

    # Resolve match file
    if len(sys.argv) > 1:
        match_id = sys.argv[1]
        jsonl_path = TELEMETRY_DIR / f"{match_id}.jsonl"
    else:
        jsonl_path = discover_latest_match()
        if jsonl_path is None:
            console.print(
                "[bold red]No telemetry files found.[/bold red]\n"
                f"Looking in: {TELEMETRY_DIR.resolve()}\n\n"
                "Usage: python spectate.py [match-id]\n"
                "   or: start a tournament and run this with no args to auto-discover.",
            )
            sys.exit(1)
        match_id = jsonl_path.stem

    # Detect event type from match_id prefix
    is_scrabble = match_id.startswith("scrabble")
    is_tictactoe = match_id.startswith("tictactoe")
    is_connectfour = match_id.startswith("connectfour")
    is_reversi = match_id.startswith("reversi")

    console.print(f"[bold]Spectating:[/bold] {match_id}")
    console.print(f"[dim]File: {jsonl_path}[/dim]")
    if is_reversi:
        event_label = "Reversi"
    elif is_connectfour:
        event_label = "Connect Four"
    elif is_tictactoe:
        event_label = "Tic-Tac-Toe"
    elif is_scrabble:
        event_label = "Scrabble"
    else:
        event_label = "Hold'em"
    console.print(f"[dim]Event: {event_label}[/dim]")

    if not jsonl_path.exists():
        console.print(f"\n[yellow]Waiting for match to start...[/yellow]")

    if is_reversi:
        state = ReversiMatchState(match_id=match_id)
        process_fn = process_reversi_turn
        render_fn = render_reversi
        footer_fn = build_reversi_footer
    elif is_connectfour:
        state = ConnectFourMatchState(match_id=match_id)
        process_fn = process_connectfour_turn
        render_fn = render_connectfour
        footer_fn = build_connectfour_footer
    elif is_tictactoe:
        state = TicTacToeMatchState(match_id=match_id)
        process_fn = process_tictactoe_turn
        render_fn = render_tictactoe
        footer_fn = build_tictactoe_footer
    elif is_scrabble:
        state = ScrabbleMatchState(match_id=match_id)
        process_fn = process_scrabble_turn
        render_fn = render_scrabble
        footer_fn = build_scrabble_footer
    else:
        state = MatchState(match_id=match_id)
        process_fn = process_turn
        render_fn = render
        footer_fn = build_footer

    file_pos = 0

    with Live(render_fn(state), console=console, refresh_per_second=4, screen=True) as live:
        try:
            while True:
                new_lines, file_pos = tail_jsonl(jsonl_path, file_pos)
                for line in new_lines:
                    process_fn(state, line)

                live.update(render_fn(state))

                if state.finished:
                    # Show final state for a moment, then keep displaying
                    time.sleep(2)
                    live.update(render_fn(state))
                    # Keep alive so user can read the result
                    while True:
                        time.sleep(1)

                time.sleep(REFRESH_RATE)
        except KeyboardInterrupt:
            pass

    # Print final summary to regular terminal
    if state.finished:
        console.print()
        console.print(footer_fn(state))
        console.print()


if __name__ == "__main__":
    main()
