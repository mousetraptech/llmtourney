#!/usr/bin/env python3
"""Generate a publishable HTML page of all tournament results."""

import json
import sys
from pathlib import Path

TELEMETRY_DIR = Path(__file__).parent / "output" / "telemetry"
OUTPUT_FILE = Path(__file__).parent / "tournament-results.html"

GAME_LABELS = {
    "tictactoe": "Tic-Tac-Toe",
    "connectfour": "Connect Four",
    "holdem": "Hold'em",
    "reversi": "Reversi",
}

GAME_ORDER = ["tictactoe", "connectfour", "reversi", "holdem"]

TIER_ORDER = ["budget", "midtier", "heavyweight"]
TIER_LABELS = {"budget": "Budget", "midtier": "Midtier", "heavyweight": "Heavyweight"}


def classify_tier(name: str) -> str:
    for tier in TIER_ORDER:
        if tier in name:
            return tier
    return "unknown"


def load_manifests():
    manifests = []
    for p in sorted(TELEMETRY_DIR.glob("bracket-*.json")):
        data = json.loads(p.read_text())
        data["_tier"] = classify_tier(data["tournament_name"])
        manifests.append(data)
    return manifests


def build_bracket_svg(m: dict) -> str:
    """Build an SVG bracket tree for a tournament."""
    rounds = m.get("rounds", [])
    if not rounds:
        return ""

    num_rounds = len(rounds)
    # Layout constants
    match_w = 180
    match_h = 48
    gap_x = 60
    gap_y_base = 16
    name_max = 18

    def trunc(name, mx=name_max):
        return name[:mx-1] + "\u2026" if len(name) > mx else name

    # Calculate positions
    total_w = num_rounds * match_w + (num_rounds - 1) * gap_x + 40
    qf_matches = len(rounds[0]["matches"])
    total_h = qf_matches * (match_h + gap_y_base) + 40

    lines = []
    lines.append(f'<svg viewBox="0 0 {total_w} {total_h}" xmlns="http://www.w3.org/2000/svg" '
                 f'style="width:100%;max-width:{total_w}px;height:auto">')
    lines.append('<style>')
    lines.append('text { font-family: "SF Mono","Cascadia Code","Fira Code",monospace; font-size: 11px; fill: #e6edf3; }')
    lines.append('text.dim { fill: #7d8590; font-size: 10px; }')
    lines.append('text.winner { fill: #3fb950; font-weight: bold; }')
    lines.append('text.score { fill: #7d8590; font-size: 10px; text-anchor: end; }')
    lines.append('rect.match-bg { fill: #161b22; stroke: #30363d; stroke-width: 1; rx: 4; }')
    lines.append('rect.winner-bg { fill: #161b22; stroke: #3fb950; stroke-width: 1.5; rx: 4; }')
    lines.append('line.connector { stroke: #30363d; stroke-width: 1; }')
    lines.append('</style>')

    match_positions = {}  # (round_idx, match_idx) -> (x, y_center)

    for ri, rnd in enumerate(rounds):
        matches = rnd["matches"]
        n = len(matches)
        x = 20 + ri * (match_w + gap_x)

        if ri == 0:
            spacing = (match_h + gap_y_base)
            y_start = 20
        else:
            # Center between the two parent matches
            positions = []
            for mi in range(n):
                parent_a = match_positions.get((ri - 1, mi * 2))
                parent_b = match_positions.get((ri - 1, mi * 2 + 1))
                if parent_a and parent_b:
                    cy = (parent_a[1] + parent_b[1]) / 2
                else:
                    cy = 20 + mi * (match_h + gap_y_base * (2 ** ri)) + match_h / 2
                positions.append(cy)
            y_start = None  # use positions

        for mi, match in enumerate(matches):
            if ri == 0:
                cy = y_start + mi * spacing + match_h / 2
            else:
                cy = positions[mi]

            my = cy - match_h / 2
            match_positions[(ri, mi)] = (x + match_w, cy)

            is_winner_a = match.get("winner") == match.get("model_a")
            is_winner_b = match.get("winner") == match.get("model_b")
            has_winner = match.get("winner") is not None

            bg_class = "match-bg"
            lines.append(f'<rect class="{bg_class}" x="{x}" y="{my}" width="{match_w}" height="{match_h}"/>')

            # Divider line
            mid_y = my + match_h / 2
            lines.append(f'<line x1="{x}" y1="{mid_y}" x2="{x + match_w}" y2="{mid_y}" class="connector" stroke-dasharray="2,2"/>')

            # Player A (top half)
            name_a = trunc(match.get("model_a", "TBD"))
            score_a = match.get("scores", {}).get("player_a", "")
            cls_a = "winner" if is_winner_a else "dim" if (has_winner and not is_winner_a) else ""
            seed_a = match.get("seed_a", "")
            lines.append(f'<text x="{x + 6}" y="{my + 16}" class="{cls_a}">{seed_a}. {name_a}</text>')
            if score_a != "":
                score_str = str(int(score_a)) if float(score_a) == int(score_a) else str(score_a)
                lines.append(f'<text x="{x + match_w - 6}" y="{my + 16}" class="score">{score_str}</text>')

            # Player B (bottom half)
            name_b = trunc(match.get("model_b", "TBD"))
            score_b = match.get("scores", {}).get("player_b", "")
            cls_b = "winner" if is_winner_b else "dim" if (has_winner and not is_winner_b) else ""
            seed_b = match.get("seed_b", "")
            lines.append(f'<text x="{x + 6}" y="{my + match_h - 8}" class="{cls_b}">{seed_b}. {name_b}</text>')
            if score_b != "":
                score_str = str(int(score_b)) if float(score_b) == int(score_b) else str(score_b)
                lines.append(f'<text x="{x + match_w - 6}" y="{my + match_h - 8}" class="score">{score_str}</text>')

            # Connectors to next round
            if ri < num_rounds - 1:
                cx = x + match_w
                nx = cx + gap_x
                lines.append(f'<line x1="{cx}" y1="{cy}" x2="{nx}" y2="{cy}" class="connector"/>')

        # Draw vertical connectors between paired matches going into next round
        if ri < num_rounds - 1:
            next_matches = rounds[ri + 1]["matches"]
            for nmi in range(len(next_matches)):
                top = match_positions.get((ri, nmi * 2))
                bot = match_positions.get((ri, nmi * 2 + 1))
                if top and bot:
                    mid_x = top[0] + gap_x / 2
                    lines.append(f'<line x1="{top[0]}" y1="{top[1]}" x2="{mid_x}" y2="{top[1]}" class="connector"/>')
                    lines.append(f'<line x1="{bot[0]}" y1="{bot[1]}" x2="{mid_x}" y2="{bot[1]}" class="connector"/>')
                    lines.append(f'<line x1="{mid_x}" y1="{top[1]}" x2="{mid_x}" y2="{bot[1]}" class="connector"/>')
                    next_cy = (top[1] + bot[1]) / 2
                    next_x = top[0] + gap_x
                    lines.append(f'<line x1="{mid_x}" y1="{next_cy}" x2="{next_x}" y2="{next_cy}" class="connector"/>')

    lines.append('</svg>')
    return "\n".join(lines)


def format_score(scores: dict, winner: str | None, model_a: str, model_b: str) -> str:
    sa = scores.get("player_a", "")
    sb = scores.get("player_b", "")
    if sa == "" or sb == "":
        return ""
    # Format nicely
    def fmt(v):
        v = float(v)
        return str(int(v)) if v == int(v) else f"{v:.1f}"
    return f"{fmt(sa)}\u2013{fmt(sb)}"


def generate_html(manifests: list[dict]) -> str:
    # Group by game then tier
    grid = {}  # game -> tier -> manifest
    for m in manifests:
        game = m["event"]
        tier = m["_tier"]
        grid.setdefault(game, {})[tier] = m

    # Collect all unique models per tier for the model tracker
    model_results = {}  # model -> list of (game, tier, best_round, is_champion)
    for m in manifests:
        if m["status"] != "complete":
            continue
        champion = m.get("champion")
        # Track how far each model got
        seeds = {s["model"]: s["seed"] for s in m["seeds"]}
        model_best = {}
        for rnd in m["rounds"]:
            for match in rnd["matches"]:
                w = match.get("winner")
                if w:
                    model_best[w] = rnd["label"]
        for s in m["seeds"]:
            model = s["model"]
            best = model_best.get(model, "QF Loss")
            is_champ = model == champion
            model_results.setdefault(model, []).append({
                "game": m["event"],
                "tier": m["_tier"],
                "best": best,
                "champion": is_champ,
            })

    # Count championships per model
    champ_counts = {}
    for model, results in model_results.items():
        champ_counts[model] = sum(1 for r in results if r["champion"])

    # Build HTML
    parts = []
    parts.append("""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>LLM Tournament of Champions &mdash; Results</title>
<style>
:root {
  --bg: #0d1117;
  --surface: #161b22;
  --border: #30363d;
  --text: #e6edf3;
  --dim: #7d8590;
  --cyan: #58a6ff;
  --green: #3fb950;
  --red: #f85149;
  --yellow: #d29922;
  --gold: #f0c040;
  --magenta: #d2a8ff;
}
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
  background: var(--bg);
  color: var(--text);
  font-family: 'SF Mono', 'Cascadia Code', 'Fira Code', 'Consolas', monospace;
  font-size: 13px;
  line-height: 1.5;
  padding: 20px;
  max-width: 1100px;
  margin: 0 auto;
}
h1 {
  font-size: 22px;
  text-align: center;
  margin-bottom: 4px;
}
.subtitle {
  text-align: center;
  color: var(--dim);
  font-size: 12px;
  margin-bottom: 24px;
}

/* Summary grid */
.summary-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: 10px;
  margin-bottom: 28px;
}
.champ-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 12px 14px;
  text-align: center;
}
.champ-card.in-progress {
  border-style: dashed;
  opacity: 0.7;
}
.champ-card .game-label {
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 1px;
  color: var(--dim);
}
.champ-card .tier-label {
  font-size: 10px;
  color: var(--dim);
}
.champ-card .champion-name {
  font-size: 15px;
  font-weight: bold;
  color: var(--gold);
  margin: 4px 0;
}
.champ-card .final-score {
  font-size: 11px;
  color: var(--dim);
}
.champ-card .runner-up {
  font-size: 10px;
  color: var(--dim);
}

/* Section headers */
.section-header {
  font-size: 15px;
  font-weight: bold;
  margin: 28px 0 12px 0;
  padding-bottom: 6px;
  border-bottom: 1px solid var(--border);
}

/* Bracket container */
.bracket-section {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 14px;
  margin-bottom: 14px;
  overflow-x: auto;
}
.bracket-title {
  font-size: 13px;
  font-weight: bold;
  margin-bottom: 10px;
  display: flex;
  align-items: center;
  gap: 8px;
}
.bracket-title .status-badge {
  font-size: 10px;
  padding: 1px 8px;
  border-radius: 4px;
  font-weight: bold;
}
.status-complete { background: var(--green); color: #000; }
.status-live { background: var(--yellow); color: #000; animation: pulse 2s infinite; }
@keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.6; } }

/* Leaderboard table */
.leaderboard {
  width: 100%;
  border-collapse: collapse;
  margin-bottom: 20px;
}
.leaderboard th {
  text-align: left;
  font-size: 10px;
  text-transform: uppercase;
  color: var(--dim);
  padding: 6px 10px;
  border-bottom: 1px solid var(--border);
}
.leaderboard td {
  padding: 5px 10px;
  border-bottom: 1px solid #1c2129;
  font-size: 12px;
}
.leaderboard tr:hover td { background: #1c2129; }
.leaderboard .rank { color: var(--dim); width: 30px; }
.leaderboard .model-name { font-weight: bold; }
.leaderboard .champ-count { color: var(--gold); font-weight: bold; }
.leaderboard .result-chip {
  display: inline-block;
  padding: 1px 6px;
  border-radius: 3px;
  font-size: 10px;
  margin: 1px 2px;
}
.chip-champ { background: rgba(240,192,64,0.2); color: var(--gold); }
.chip-final { background: rgba(210,168,255,0.15); color: var(--magenta); }
.chip-sf { background: rgba(88,166,255,0.15); color: var(--cyan); }
.chip-qf { background: rgba(125,133,144,0.15); color: var(--dim); }

footer {
  text-align: center;
  color: var(--dim);
  font-size: 11px;
  margin-top: 30px;
  padding-top: 12px;
  border-top: 1px solid var(--border);
}
</style>
</head>
<body>
""")

    # Header
    complete = sum(1 for m in manifests if m["status"] == "complete")
    total = len(manifests)
    parts.append(f'<h1>\U0001F3C6 LLM Tournament of Champions</h1>')
    parts.append(f'<div class="subtitle">{complete} of {total} tournaments complete</div>')

    # Summary cards
    parts.append('<div class="summary-grid">')
    for game in GAME_ORDER:
        for tier in TIER_ORDER:
            m = grid.get(game, {}).get(tier)
            if not m:
                continue
            game_label = GAME_LABELS.get(game, game)
            tier_label = TIER_LABELS.get(tier, tier)
            champion = m.get("champion")
            in_progress = m["status"] != "complete"
            cls = "champ-card in-progress" if in_progress else "champ-card"

            # Get final match info
            final_score = ""
            runner_up = ""
            if not in_progress and m["rounds"]:
                final_round = m["rounds"][-1]
                if final_round["matches"]:
                    fm = final_round["matches"][0]
                    final_score = format_score(fm["scores"], fm["winner"], fm["model_a"], fm["model_b"])
                    runner_up = fm["model_b"] if fm["winner"] == fm["model_a"] else fm["model_a"]

            parts.append(f'<div class="{cls}">')
            parts.append(f'  <div class="game-label">{game_label}</div>')
            parts.append(f'  <div class="tier-label">{tier_label}</div>')
            if in_progress:
                status_round = "QFs"
                for rnd in m["rounds"]:
                    if rnd["status"] == "in_progress":
                        status_round = rnd["label"][:2]
                        break
                parts.append(f'  <div class="champion-name" style="color:var(--yellow)">\u23F3 In Progress ({status_round})</div>')
            else:
                parts.append(f'  <div class="champion-name">\U0001F451 {champion}</div>')
                if final_score:
                    parts.append(f'  <div class="final-score">Final: {final_score}</div>')
                if runner_up:
                    parts.append(f'  <div class="runner-up">vs {runner_up}</div>')
            parts.append('</div>')
    parts.append('</div>')

    # Model leaderboard
    parts.append('<div class="section-header">\U0001F4CA Model Leaderboard</div>')
    # Sort by championship count, then by finals appearances
    model_stats = []
    for model, results in model_results.items():
        champs = sum(1 for r in results if r["champion"])
        finals = sum(1 for r in results if r["best"] == "FINAL")
        semis = sum(1 for r in results if r["best"] == "SEMIFINALS")
        appearances = len(results)
        model_stats.append((model, champs, finals, semis, appearances, results))
    model_stats.sort(key=lambda x: (x[1], x[2], x[3]), reverse=True)

    parts.append('<table class="leaderboard">')
    parts.append('<tr><th>#</th><th>Model</th><th>\U0001F3C6</th><th>Results</th></tr>')
    for rank, (model, champs, finals, semis, appearances, results) in enumerate(model_stats, 1):
        chips = []
        for r in sorted(results, key=lambda x: (GAME_ORDER.index(x["game"]) if x["game"] in GAME_ORDER else 99, TIER_ORDER.index(x["tier"]) if x["tier"] in TIER_ORDER else 99)):
            gl = GAME_LABELS.get(r["game"], r["game"])[:3]
            tl = TIER_LABELS.get(r["tier"], r["tier"])[:1]
            label = f'{gl} {tl}'
            if r["champion"]:
                chips.append(f'<span class="result-chip chip-champ">\U0001F451 {label}</span>')
            elif r["best"] == "FINAL":
                chips.append(f'<span class="result-chip chip-final">2nd {label}</span>')
            elif r["best"] == "SEMIFINALS":
                chips.append(f'<span class="result-chip chip-sf">SF {label}</span>')
            else:
                chips.append(f'<span class="result-chip chip-qf">QF {label}</span>')
        champ_str = f'<span class="champ-count">{champs}</span>' if champs > 0 else '<span style="color:var(--dim)">0</span>'
        parts.append(f'<tr><td class="rank">{rank}</td><td class="model-name">{model}</td><td>{champ_str}</td><td>{"".join(chips)}</td></tr>')
    parts.append('</table>')

    # Full bracket trees by game
    parts.append('<div class="section-header">\U0001F333 Bracket Details</div>')
    for game in GAME_ORDER:
        for tier in TIER_ORDER:
            m = grid.get(game, {}).get(tier)
            if not m:
                continue
            game_label = GAME_LABELS.get(game, game)
            tier_label = TIER_LABELS.get(tier, tier)
            status = m["status"]
            badge_cls = "status-complete" if status == "complete" else "status-live"
            badge_text = "COMPLETE" if status == "complete" else "LIVE"

            parts.append('<div class="bracket-section">')
            parts.append(f'<div class="bracket-title">{game_label} \u2014 {tier_label} <span class="status-badge {badge_cls}">{badge_text}</span></div>')
            parts.append(build_bracket_svg(m))
            parts.append('</div>')

    # Footer
    parts.append('<footer>Generated from llmtourney bracket manifests</footer>')
    parts.append('</body></html>')

    return "\n".join(parts)


def main():
    manifests = load_manifests()
    if not manifests:
        print("No bracket manifests found in", TELEMETRY_DIR)
        sys.exit(1)

    html = generate_html(manifests)
    OUTPUT_FILE.write_text(html)
    print(f"Generated {OUTPUT_FILE} ({len(manifests)} tournaments, {len(html)} bytes)")


if __name__ == "__main__":
    main()
