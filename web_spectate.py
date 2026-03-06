#!/usr/bin/env python3
"""Web-based spectator UI for LLM tournament matches.

Usage:
    python web_spectate.py <jsonl_file_or_match_id>
    python web_spectate.py                              # Auto-discover latest

Opens http://127.0.0.1:8800 with a live-updating board.
Zero external dependencies — stdlib only.
"""

import json
import sys
import time
import threading
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path

TELEMETRY_DIR = Path("output/telemetry")
PORT = 8800


def discover_latest_match(event_filter: str | None = None) -> Path | None:
    if not TELEMETRY_DIR.exists():
        return None
    jsonl_files = list(TELEMETRY_DIR.glob("*.jsonl"))
    if event_filter:
        jsonl_files = [f for f in jsonl_files if f.stem.startswith(event_filter)]
    if not jsonl_files:
        return None
    return max(jsonl_files, key=lambda f: f.stat().st_mtime)


def resolve_jsonl_path(arg: str | None) -> Path:
    if arg is None:
        p = discover_latest_match()
        if p is None:
            print(f"No telemetry files found in {TELEMETRY_DIR.resolve()}")
            sys.exit(1)
        return p
    p = Path(arg)
    if p.exists():
        return p
    # Try as match_id
    p = TELEMETRY_DIR / f"{arg}.jsonl"
    if p.exists():
        return p
    # Try with event prefixes
    for prefix in ("scrabble-", "tictactoe-", "checkers-", "connectfour-", "holdem-", "reversi-", "bullshit-", "liarsdice-", "gauntlet-", "rollerderby-", "yahtzee-"):
        p = TELEMETRY_DIR / f"{prefix}{arg}.jsonl"
        if p.exists():
            return p
    print(f"Cannot find: {arg}")
    sys.exit(1)


def detect_event_type(jsonl_path: Path) -> str:
    stem = jsonl_path.stem
    if stem.startswith("tictactoe"):
        return "tictactoe"
    if stem.startswith("checkers"):
        return "checkers"
    if stem.startswith("scrabble"):
        return "scrabble"
    if stem.startswith("connectfour"):
        return "connectfour"
    if stem.startswith("holdem"):
        return "holdem"
    if stem.startswith("reversi"):
        return "reversi"
    if stem.startswith("bullshit"):
        return "bullshit"
    if stem.startswith("liarsdice"):
        return "liarsdice"
    if stem.startswith("gauntlet"):
        return "gauntlet"
    if stem.startswith("rollerderby"):
        return "rollerderby"
    if stem.startswith("yahtzee"):
        return "yahtzee"
    if stem.startswith("storyteller"):
        return "storyteller"
    if stem.startswith("spades"):
        return "spades"
    if stem.startswith("hearts"):
        return "hearts"
    if stem.startswith("ginrummy") or stem.startswith("gin"):
        return "ginrummy"
    if stem.startswith("avalon"):
        return "avalon"
    # Fallback: peek at first line
    try:
        with open(jsonl_path) as f:
            first = f.readline()
            if '"tictactoe"' in first:
                return "tictactoe"
            if '"checkers"' in first:
                return "checkers"
            if '"connectfour"' in first:
                return "connectfour"
            if '"holdem"' in first:
                return "holdem"
            if '"reversi"' in first:
                return "reversi"
            if '"storyteller"' in first:
                return "storyteller"
    except Exception:
        pass
    return "scrabble"


# ── TicTacToe HTML/CSS/JS ─────────────────────────────────────────

TTT_HTML_PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Tic-Tac-Toe Spectator</title>
<style>
:root {
  --bg: #0d1117;
  --surface: #161b22;
  --border: #30363d;
  --text: #e6edf3;
  --dim: #7d8590;
  --cyan: #58a6ff;
  --magenta: #d2a8ff;
  --green: #3fb950;
  --red: #f85149;
  --yellow: #d29922;
}
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
  background: var(--bg);
  color: var(--text);
  font-family: 'SF Mono', 'Cascadia Code', 'Fira Code', 'Consolas', monospace;
  font-size: 13px;
  line-height: 1.4;
  padding: 12px;
  max-width: 900px;
  margin: 0 auto;
}

/* Header */
#header {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 12px 16px;
  margin-bottom: 10px;
  text-align: center;
}
#header .badge {
  display: inline-block;
  padding: 2px 10px;
  border-radius: 4px;
  font-weight: bold;
  font-size: 12px;
  margin-right: 8px;
  vertical-align: middle;
}
.badge-live { background: var(--green); color: #000; animation: pulse 2s infinite; }
.badge-final { background: var(--red); color: #fff; }
@keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.6; } }
#header .title { font-size: 16px; font-weight: bold; }
.player-a { color: var(--cyan); }
.player-b { color: var(--magenta); }
#header .sub { margin-top: 4px; color: var(--dim); }

/* Board + Sidebar layout */
#board-area {
  display: flex;
  gap: 12px;
  margin-bottom: 10px;
}
#board-panel {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 16px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
}
#board {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 4px;
  width: 240px;
  height: 240px;
}
#board .cell {
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 48px;
  font-weight: 900;
  border-radius: 6px;
  background: #1c2333;
  color: var(--dim);
  transition: background 0.2s;
}
.cell.x-mark { color: var(--cyan); }
.cell.o-mark { color: var(--magenta); }
.cell.last-move { box-shadow: inset 0 0 0 3px var(--yellow); }
.cell.win-cell { background: #1a2e1a; }
.cell.fresh { animation: pop 0.3s ease-out; }
@keyframes pop {
  0% { transform: scale(0.3); opacity: 0; }
  70% { transform: scale(1.1); }
  100% { transform: scale(1); opacity: 1; }
}

/* Sidebar */
#sidebar {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 12px;
  flex: 1;
  min-width: 220px;
}
#sidebar h3 {
  font-size: 11px;
  text-transform: uppercase;
  color: var(--dim);
  border-bottom: 1px solid var(--border);
  padding-bottom: 4px;
  margin-bottom: 8px;
}
.score-row { margin-bottom: 8px; }
.score-row .name { font-weight: bold; font-size: 12px; }
.score-bar {
  height: 10px;
  border-radius: 3px;
  margin-top: 2px;
  transition: width 0.5s ease;
}
.stat-line { color: var(--dim); font-size: 11px; margin: 3px 0; }
.stat-line.violations { color: var(--red); }
.game-assignment {
  font-size: 11px;
  margin: 2px 0;
}

/* Panels */
.panel {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px 14px;
  margin-bottom: 10px;
}
.panel h3 {
  font-size: 11px;
  text-transform: uppercase;
  color: var(--dim);
  border-bottom: 1px solid var(--border);
  padding-bottom: 4px;
  margin-bottom: 6px;
}

/* Game history */
.game-entry {
  padding: 3px 0;
  font-size: 12px;
  display: flex;
  align-items: baseline;
  gap: 6px;
}
.game-entry .gnum { color: var(--dim); min-width: 50px; }
.game-entry .result-win { font-weight: bold; }
.game-entry .result-draw { color: var(--yellow); font-weight: bold; }

/* Commentary */
.comment-entry { padding: 2px 0; font-size: 11px; }
.comment-entry .reasoning { color: var(--dim); font-style: italic; margin-left: 24px; display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

/* Footer */
#footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 0;
}
#footer .status { font-size: 12px; }
#copy-btn {
  background: var(--surface);
  border: 1px solid var(--border);
  color: var(--text);
  padding: 6px 14px;
  border-radius: 6px;
  cursor: pointer;
  font-family: inherit;
  font-size: 12px;
  transition: background 0.2s;
}
#copy-btn:hover { background: #1f2937; }
#copy-btn .count { background: var(--border); padding: 1px 6px; border-radius: 8px; margin-left: 6px; font-size: 10px; }
#copy-btn.copied { background: var(--green); color: #000; border-color: var(--green); }

/* Final panel */
#final-panel {
  display: none;
  text-align: center;
  padding: 20px;
  border-color: var(--red);
}
#final-panel.show { display: block; }
#final-panel .winner { font-size: 20px; font-weight: bold; }
#final-panel .breakdown { font-size: 14px; margin-top: 6px; }
#final-panel .stats { color: var(--dim); margin-top: 8px; font-size: 12px; }

/* Shot clock */
#shot-clock {
  display: none;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 8px 16px;
  margin-bottom: 10px;
  text-align: center;
}
#shot-clock .clock-label { font-size: 11px; color: var(--dim); text-transform: uppercase; letter-spacing: 1px; }
#shot-clock .clock-display { font-size: 24px; font-weight: bold; font-variant-numeric: tabular-nums; letter-spacing: 1px; margin: 2px 0; }
#shot-clock .clock-display.clock-ok { color: var(--cyan); }
#shot-clock .clock-display.clock-warn { color: var(--yellow); }
#shot-clock .clock-display.clock-danger { color: var(--red); animation: pulse 0.5s infinite; }
#shot-clock .strike-info { font-size: 11px; color: var(--dim); }
</style>
</head>
<body>

<div id="header">
  <span class="badge badge-live" id="badge">LIVE</span>
  <span class="title">TIC-TAC-TOE</span>
  <span id="matchup"></span>
  <div class="sub" id="sub-info"></div>
</div>

<div id="shot-clock">
  <div class="clock-label" id="clock-label">SHOT CLOCK</div>
  <div class="clock-display clock-ok" id="clock-display">--.-s</div>
  <div class="strike-info" id="strike-info"></div>
</div>

<div id="board-area">
  <div id="board-panel">
    <div id="board"></div>
  </div>
  <div id="sidebar">
    <h3>Series Score</h3>
    <div id="scores"></div>
    <h3 style="margin-top:12px">Current Game</h3>
    <div id="game-info"></div>
    <div id="sidebar-stats"></div>
  </div>
</div>

<div class="panel" id="final-panel">
  <h3>Final Result</h3>
  <div id="final-content"></div>
</div>

<div class="panel">
  <h3>Game History</h3>
  <div id="game-history"><span style="color:var(--dim);font-style:italic">No completed games</span></div>
</div>

<div class="panel">
  <h3>Play-by-Play</h3>
  <div id="commentary"><span style="color:var(--dim);font-style:italic">Waiting for action...</span></div>
</div>

<div id="footer">
  <div class="status" id="status-text">
    <span class="badge badge-live" style="font-size:10px">LIVE</span>
    Waiting for data...
  </div>
  <button id="copy-btn" onclick="copyRunlog()">
    Copy Runlog Path <span class="count" id="line-count">0</span>
  </button>
</div>

<script>
// ── Emoji system ─────────────────────────────────────────────────
const EMOJI_POOL = [
  '\u{1F525}','\u{1F9E0}','\u{1F47E}','\u{1F916}','\u{1F3AF}',
  '\u{1F680}','\u{1F40D}','\u{1F98A}','\u{1F43B}','\u{1F985}',
  '\u{1F409}','\u{1F3B2}','\u{1F9CA}','\u{1F30B}','\u{1F308}',
  '\u{1F52E}','\u{1F9F2}','\u{1F41D}','\u{1F95D}','\u{1F344}'
];
function djb2(s) {
  let h = 5381;
  for (let i = 0; i < s.length; i++) h = ((h << 5) + h + s.charCodeAt(i)) >>> 0;
  return h;
}
function pickEmojis(a, b) {
  let ia = djb2(a) % EMOJI_POOL.length;
  let ib = djb2(b) % EMOJI_POOL.length;
  if (ib === ia) ib = (ia + 1) % EMOJI_POOL.length;
  return { player_a: EMOJI_POOL[ia], player_b: EMOJI_POOL[ib] };
}

// ── Match state ──────────────────────────────────────────────────
const S = {
  matchId: '', modelA: '', modelB: '',
  board: [['','',''],['','',''],['','','']],
  seriesScores: { player_a: 0, player_b: 0 },
  gameNumber: 0,
  gameTurn: 0,
  turnCount: 0,
  // Who is X this game? player_a or player_b
  xPlayer: 'player_a',
  firstPlayer: '',  // who moves first this game
  lastMove: null,   // [r,c] of last position played
  previousBoard: [['','',''],['','',''],['','','']],
  gameHistory: [],  // {gameNum, result, xPlayer}
  commentary: [],   // last 12
  violations: { player_a: 0, player_b: 0 },
  finished: false,
  finalScores: {},
  highlightHands: [],
  emojis: { player_a: '', player_b: '' },
  // Shot clock
  shotClock: { timeLimitMs: null, lastTurnTime: null, strikes: { player_a: 0, player_b: 0 }, strikeLimit: null, waitingOn: '', lastTimeExceeded: false }
};

const rawLines = [];
let turnQueue = [];
let isReplaying = false;

function shortModel(name) {
  if (!name) return name;
  return name.replace(/^anthropic\/claude-/, '').replace(/^anthropic\//, '').replace(/^openai\//, '');
}

function assignEmojis() {
  if (S.modelA && S.modelB && !S.emojis.player_a) {
    S.emojis = pickEmojis(S.modelA, S.modelB);
  }
}

function truncateReasoning(text, max) {
  max = max || 100;
  if (!text) return null;
  const lines = text.trim().split('\n');
  for (const line of lines) {
    const t = line.trim();
    if (t.length > 10) return t.length > max ? t.slice(0, max-3) + '...' : t;
  }
  return null;
}

// ── State machine ────────────────────────────────────────────────
function processTurn(data) {
  if (data.record_type === 'match_summary') {
    S.finished = true;
    S.finalScores = data.final_scores || {};
    S.highlightHands = data.highlight_hands || [];
    const pm = data.player_models || {};
    if (pm.player_a) S.modelA = shortModel(pm.player_a);
    if (pm.player_b) S.modelB = shortModel(pm.player_b);
    assignEmojis();
    // Record final game if not already recorded
    const snap = data.final_snapshot || {};
    return;
  }

  S.turnCount++;
  const snap = data.state_snapshot || {};
  const playerId = data.player_id || '';
  const modelId = data.model_id || '';

  if (!S.matchId) S.matchId = data.match_id || '';
  if (playerId === 'player_a' && !S.modelA) S.modelA = shortModel(modelId);
  else if (playerId === 'player_b' && !S.modelB) S.modelB = shortModel(modelId);
  assignEmojis();
  // Shot clock
  if (data.time_limit_ms) S.shotClock.timeLimitMs = data.time_limit_ms;
  if (data.strike_limit) S.shotClock.strikeLimit = data.strike_limit;
  if (data.cumulative_strikes !== undefined) S.shotClock.strikes[playerId] = data.cumulative_strikes;
  S.shotClock.lastTimeExceeded = !!data.time_exceeded;
  S.shotClock.lastTurnTime = Date.now();
  S.shotClock.waitingOn = playerId === 'player_a' ? 'player_b' : 'player_a';

  const handNum = snap.hand_number || 1;
  const gameTurn = snap.game_turn || 0;

  // Detect new game
  if (handNum !== S.gameNumber) {
    // Record completed game if we had one
    if (S.gameNumber > 0 && snap.result) {
      // Check if we already recorded this game
      const already = S.gameHistory.find(g => g.gameNum === S.gameNumber);
      if (!already) {
        S.gameHistory.push({
          gameNum: S.gameNumber,
          result: snap.result,
          xPlayer: S.xPlayer
        });
      }
    }
    S.gameNumber = handNum;
    S.lastMove = null;
    S.previousBoard = [['','',''],['','',''],['','','']];
  }

  // Detect X/O assignment from prompt
  const prompt = data.prompt || '';
  if (gameTurn <= 1 && prompt) {
    const xMatch = prompt.match(/You are (X|O)/);
    if (xMatch) {
      if (xMatch[1] === 'X') S.xPlayer = playerId;
      else S.xPlayer = (playerId === 'player_a') ? 'player_b' : 'player_a';
    }
  }

  // Track first player each game
  if (gameTurn === 1) {
    S.firstPlayer = playerId;
  }

  S.gameTurn = gameTurn;

  // Update board from snapshot
  if (snap.board) {
    S.previousBoard = S.board.map(r => [...r]);
    S.board = snap.board.map(r => [...r]);
  }

  // Update series scores
  if (snap.series_scores) {
    S.seriesScores = { ...snap.series_scores };
  }

  // Last move
  S.lastMove = snap.position_played || null;

  // Violations
  const violation = data.violation;
  if (violation) S.violations[playerId] = (S.violations[playerId] || 0) + 1;

  // Terminal — record final game result
  if (snap.terminal && snap.result) {
    const already = S.gameHistory.find(g => g.gameNum === S.gameNumber);
    if (!already) {
      S.gameHistory.push({
        gameNum: S.gameNumber,
        result: snap.result,
        xPlayer: S.xPlayer
      });
    }
  }

  // Commentary
  const reasoning = truncateReasoning(data.reasoning_output);
  const parsed = data.parsed_action || {};
  const actionType = parsed.action || '???';
  const pos = snap.position_played;
  if (gameTurn > 0) {
    S.commentary.push({
      turnNumber: S.turnCount,
      gameNumber: S.gameNumber,
      model: modelId,
      playerId,
      position: pos,
      reasoning,
      latencyMs: data.latency_ms || 0,
      isViolation: !!violation
    });
    if (S.commentary.length > 12) S.commentary.shift();
  }
}

// ── Win detection (for highlighting) ─────────────────────────────
function findWinLine(board) {
  const lines = [
    [[0,0],[0,1],[0,2]], [[1,0],[1,1],[1,2]], [[2,0],[2,1],[2,2]],
    [[0,0],[1,0],[2,0]], [[0,1],[1,1],[2,1]], [[0,2],[1,2],[2,2]],
    [[0,0],[1,1],[2,2]], [[0,2],[1,1],[2,0]]
  ];
  for (const line of lines) {
    const [a,b,c] = line;
    const v = board[a[0]][a[1]];
    if (v && v === board[b[0]][b[1]] && v === board[c[0]][c[1]]) {
      return line;
    }
  }
  return null;
}

// ── Rendering ────────────────────────────────────────────────────
function renderBoard() {
  const el = document.getElementById('board');
  el.innerHTML = '';
  const winLine = findWinLine(S.board);
  const winSet = new Set();
  if (winLine) winLine.forEach(([r,c]) => winSet.add(r+','+c));

  for (let r = 0; r < 3; r++) {
    for (let c = 0; c < 3; c++) {
      const div = document.createElement('div');
      div.className = 'cell';
      const v = S.board[r][c];
      if (v === 'X') {
        div.className += ' x-mark';
        div.textContent = 'X';
      } else if (v === 'O') {
        div.className += ' o-mark';
        div.textContent = 'O';
      } else {
        div.textContent = '\u00B7';
      }
      // Last move highlight
      if (S.lastMove && S.lastMove[0] === r && S.lastMove[1] === c) {
        div.className += ' last-move';
      }
      // Win line highlight
      if (winSet.has(r+','+c)) {
        div.className += ' win-cell';
      }
      // Fresh animation
      if (v && S.previousBoard[r][c] !== v) {
        div.className += ' fresh';
      }
      el.appendChild(div);
    }
  }
}

function renderHeader() {
  const badge = document.getElementById('badge');
  badge.textContent = S.finished ? 'FINAL' : 'LIVE';
  badge.className = 'badge ' + (S.finished ? 'badge-final' : 'badge-live');

  const ea = S.emojis.player_a || '';
  const eb = S.emojis.player_b || '';
  document.getElementById('matchup').innerHTML =
    `<span class="player-a">${ea} ${S.modelA || '???'}</span>` +
    ` <span style="color:var(--dim)">vs</span> ` +
    `<span class="player-b">${eb} ${S.modelB || '???'}</span>`;

  const sa = S.finished ? (S.finalScores.player_a ?? S.seriesScores.player_a) : S.seriesScores.player_a;
  const sb = S.finished ? (S.finalScores.player_b ?? S.seriesScores.player_b) : S.seriesScores.player_b;
  document.getElementById('sub-info').innerHTML =
    `<strong>Game ${S.gameNumber}</strong>` +
    ` <span style="color:var(--dim)">|</span> ` +
    `<span class="player-a" style="font-weight:bold">${sa}</span>` +
    ` <span style="color:var(--dim)">\u2013</span> ` +
    `<span class="player-b" style="font-weight:bold">${sb}</span>` +
    ` <span style="color:var(--dim)">|</span> ` +
    `<span style="color:var(--dim)">Move ${S.gameTurn}</span>`;
}

function renderSidebar() {
  const sa = S.finished ? (S.finalScores.player_a ?? S.seriesScores.player_a) : S.seriesScores.player_a;
  const sb = S.finished ? (S.finalScores.player_b ?? S.seriesScores.player_b) : S.seriesScores.player_b;
  const maxScore = Math.max(sa, sb, 1);

  const ea = S.emojis.player_a || '';
  const eb = S.emojis.player_b || '';
  const nameA = (S.modelA || 'Player A').slice(0, 18);
  const nameB = (S.modelB || 'Player B').slice(0, 18);

  const pctA = Math.max(0, Math.min(100, (sa / maxScore) * 100));
  const pctB = Math.max(0, Math.min(100, (sb / maxScore) * 100));

  document.getElementById('scores').innerHTML =
    `<div class="score-row">
      <div class="name player-a">${ea} ${nameA}</div>
      <div class="score-bar" style="width:${pctA}%;background:var(--cyan)">&nbsp;</div>
      <div style="color:var(--cyan);font-weight:bold">${sa}</div>
    </div>
    <div class="score-row">
      <div class="name player-b">${eb} ${nameB}</div>
      <div class="score-bar" style="width:${pctB}%;background:var(--magenta)">&nbsp;</div>
      <div style="color:var(--magenta);font-weight:bold">${sb}</div>
    </div>`;

  // Current game info
  const xName = S.xPlayer === 'player_a' ? nameA : nameB;
  const oName = S.xPlayer === 'player_a' ? nameB : nameA;
  const xColor = S.xPlayer === 'player_a' ? 'var(--cyan)' : 'var(--magenta)';
  const oColor = S.xPlayer === 'player_a' ? 'var(--magenta)' : 'var(--cyan)';

  let gameInfo = '';
  if (S.gameNumber > 0) {
    gameInfo = `<div class="game-assignment"><span style="color:${xColor};font-weight:bold">X</span> = ${xName}</div>` +
               `<div class="game-assignment"><span style="color:${oColor};font-weight:bold">O</span> = ${oName}</div>` +
               `<div class="stat-line" style="margin-top:6px">Move ${S.gameTurn} of game ${S.gameNumber}</div>`;
  }
  document.getElementById('game-info').innerHTML = gameInfo;

  // Stats
  let stats = '';
  const va = S.violations.player_a || 0;
  const vb = S.violations.player_b || 0;
  if (va + vb > 0) stats += `<div class="stat-line violations" style="margin-top:8px">Violations: A:${va} B:${vb}</div>`;
  document.getElementById('sidebar-stats').innerHTML = stats;
}

function renderGameHistory() {
  const el = document.getElementById('game-history');
  if (!S.gameHistory.length) {
    el.innerHTML = '<span style="color:var(--dim);font-style:italic">No completed games</span>';
    return;
  }
  const nameA = S.modelA || 'Player A';
  const nameB = S.modelB || 'Player B';
  el.innerHTML = S.gameHistory.map(g => {
    let resultHTML;
    if (g.result === 'x_wins') {
      const winPid = g.xPlayer;
      const winName = winPid === 'player_a' ? nameA : nameB;
      const color = winPid === 'player_a' ? 'var(--cyan)' : 'var(--magenta)';
      resultHTML = `<span class="result-win" style="color:${color}">X wins</span> <span style="color:var(--dim)">(${winName})</span>`;
    } else if (g.result === 'o_wins') {
      const winPid = g.xPlayer === 'player_a' ? 'player_b' : 'player_a';
      const winName = winPid === 'player_a' ? nameA : nameB;
      const color = winPid === 'player_a' ? 'var(--cyan)' : 'var(--magenta)';
      resultHTML = `<span class="result-win" style="color:${color}">O wins</span> <span style="color:var(--dim)">(${winName})</span>`;
    } else {
      resultHTML = `<span class="result-draw">Draw</span>`;
    }
    const hl = S.highlightHands.includes(g.gameNum) ? '<span style="color:var(--yellow)">\u2605 </span>' : '  ';
    return `<div class="game-entry">${hl}<span class="gnum">Game ${g.gameNum}</span>${resultHTML}</div>`;
  }).join('');
}

function renderCommentary() {
  const el = document.getElementById('commentary');
  if (!S.commentary.length) {
    el.innerHTML = '<span style="color:var(--dim);font-style:italic">Waiting for action...</span>';
    return;
  }
  el.innerHTML = [...S.commentary].reverse().map(e => {
    const color = e.playerId === 'player_a' ? 'var(--cyan)' : 'var(--magenta)';
    const posStr = e.position ? `[${e.position[0]},${e.position[1]}]` : '';
    const mark = e.playerId === S.xPlayer ? 'X' : 'O';
    let actionHTML;
    if (e.isViolation) {
      actionHTML = `<span style="color:var(--red);font-weight:bold">violation!</span>`;
    } else if (posStr) {
      actionHTML = `<span style="color:var(--green)">${mark}</span> \u2192 <span style="font-weight:bold">${posStr}</span>`;
    } else {
      actionHTML = `<span style="color:var(--dim)">...</span>`;
    }
    const latency = e.latencyMs > 100 ? ` <span style="color:var(--dim)">(${(e.latencyMs/1000).toFixed(1)}s)</span>` : '';
    const reason = e.reasoning ? `<span class="reasoning">"${e.reasoning}"</span>` : '';
    return `<div class="comment-entry"><span style="color:var(--dim)">G${e.gameNumber} T${e.turnNumber}</span> <span style="color:${color};font-weight:bold">${e.model}</span> ${actionHTML}${latency}${reason}</div>`;
  }).join('');
}

function renderFinal() {
  if (!S.finished) { document.getElementById('final-panel').className = 'panel'; return; }
  document.getElementById('final-panel').className = 'panel show';
  const sa = S.finalScores.player_a || 0;
  const sb = S.finalScores.player_b || 0;

  // Count W/D/L for each player
  let wA = 0, wB = 0, draws = 0;
  S.gameHistory.forEach(g => {
    if (g.result === 'draw') { draws++; return; }
    const xWins = g.result === 'x_wins';
    const winPid = xWins ? g.xPlayer : (g.xPlayer === 'player_a' ? 'player_b' : 'player_a');
    if (winPid === 'player_a') wA++;
    else wB++;
  });

  let html;
  if (sa === sb) {
    html = `<div class="winner" style="color:var(--yellow)">DRAW</div><div class="breakdown">${sa} each</div>`;
  } else {
    const wPid = sa > sb ? 'player_a' : 'player_b';
    const emoji = S.emojis[wPid] || '';
    const wName = wPid === 'player_a' ? S.modelA : S.modelB;
    const wColor = wPid === 'player_a' ? 'var(--cyan)' : 'var(--magenta)';
    html = `<div class="winner" style="color:${wColor}">${emoji} ${wName} WINS</div>` +
           `<div class="breakdown">${sa} \u2013 ${sb}</div>`;
  }
  const nameA = S.modelA || 'A';
  const nameB = S.modelB || 'B';
  html += `<div class="stats">${nameA}: ${wA}W ${draws}D ${wB}L &nbsp;\u00B7&nbsp; ${nameB}: ${wB}W ${draws}D ${wA}L</div>`;
  const va = S.violations.player_a || 0, vb = S.violations.player_b || 0;
  if (va + vb > 0) html += `<div class="stats" style="color:var(--red)">Violations: A:${va} B:${vb}</div>`;
  document.getElementById('final-content').innerHTML = html;
}

function renderFooter() {
  const st = document.getElementById('status-text');
  if (S.finished) {
    st.innerHTML = '<span class="badge badge-final" style="font-size:10px">FINAL</span> Series Complete';
  } else {
    st.innerHTML = '<span class="badge badge-live" style="font-size:10px">LIVE</span> Watching...';
  }
  document.getElementById('line-count').textContent = rawLines.length;
}

function renderShotClock() {
  var el = document.getElementById('shot-clock');
  if (!S.shotClock.timeLimitMs || S.finished) { el.style.display = 'none'; return; }
  el.style.display = 'block';
  var display = document.getElementById('clock-display');
  var label = document.getElementById('clock-label');
  var strikeEl = document.getElementById('strike-info');
  if (!S.finished && !isReplaying && S.shotClock.lastTurnTime) {
    var elapsed = Date.now() - S.shotClock.lastTurnTime;
    var remaining = Math.max(0, S.shotClock.timeLimitMs - elapsed);
    var secs = remaining / 1000;
    display.textContent = secs.toFixed(1) + 's';
    var pct = remaining / S.shotClock.timeLimitMs;
    display.className = 'clock-display ' + (pct <= 0 ? 'clock-danger' : pct < 0.2 ? 'clock-danger' : pct < 0.5 ? 'clock-warn' : 'clock-ok');
  } else {
    display.textContent = (S.shotClock.timeLimitMs / 1000).toFixed(1) + 's';
    display.className = 'clock-display clock-ok';
  }
  var wModel = S.shotClock.waitingOn === 'player_a' ? (S.modelA || 'A') : (S.modelB || 'B');
  label.textContent = S.finished ? 'SHOT CLOCK' : 'SHOT CLOCK \u00b7 ' + wModel;
  if (S.shotClock.strikeLimit) {
    var sA = S.shotClock.strikes.player_a || 0;
    var sB = S.shotClock.strikes.player_b || 0;
    var nA = S.modelA || 'A', nB = S.modelB || 'B';
    strikeEl.innerHTML = '<span class="player-a">' + nA + ': ' + sA + '/' + S.shotClock.strikeLimit + '</span> \u00b7 <span class="player-b">' + nB + ': ' + sB + '/' + S.shotClock.strikeLimit + '</span>';
  } else { strikeEl.innerHTML = ''; }
}

function renderAll() {
  renderHeader();
  renderShotClock();
  renderBoard();
  renderSidebar();
  renderGameHistory();
  renderCommentary();
  renderFinal();
  renderFooter();
}

// ── Copy runlog ──────────────────────────────────────────────────
function copyRunlog() {
  const btn = document.getElementById('copy-btn');
  fetch('/filepath').then(r => r.text()).then(function(fp) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(fp).then(function() {
        btn.classList.add('copied');
        btn.textContent = 'Copied path!';
        setTimeout(function() {
          btn.classList.remove('copied');
          btn.innerHTML = 'Copy Runlog Path <span class="count">' + rawLines.length + '</span>';
        }, 2000);
      });
    } else {
      const ta = document.createElement('textarea');
      ta.value = fp;
      ta.style.position = 'fixed';
      ta.style.left = '-9999px';
      document.body.appendChild(ta);
      ta.select();
      document.execCommand('copy');
      document.body.removeChild(ta);
      btn.classList.add('copied');
      btn.textContent = 'Copied path!';
      setTimeout(function() {
        btn.classList.remove('copied');
        btn.innerHTML = 'Copy Runlog Path <span class="count">' + rawLines.length + '</span>';
      }, 2000);
    }
  });
}

// ── SSE client ───────────────────────────────────────────────────
function startSSE() {
  const es = new EventSource('/events');
  es.onmessage = function(e) {
    const line = e.data;
    rawLines.push(line);
    try {
      const data = JSON.parse(line);
      if (isReplaying) {
        turnQueue.push(data);
      } else {
        processTurn(data);
        renderAll();
      }
    } catch(err) {}
    document.getElementById('line-count').textContent = rawLines.length;
  };
  es.addEventListener('done', function() {
    es.close();
  });
  es.onerror = function() {};
}

function drainQueue() {
  if (!turnQueue.length) {
    isReplaying = false;
    renderAll();
    return;
  }
  const data = turnQueue.shift();
  processTurn(data);
  renderAll();
  const delay = data.record_type === 'match_summary' ? 200 : 50;
  setTimeout(drainQueue, delay);
}

// Init
renderBoard();
renderAll();

isReplaying = true;
turnQueue = [];
startSSE();

setTimeout(() => {
  if (turnQueue.length > 0) {
    drainQueue();
  } else {
    isReplaying = false;
  }
}, 300);
// Shot clock countdown
setInterval(function() {
  if (S.shotClock.timeLimitMs && !S.finished && !isReplaying) renderShotClock();
}, 100);

</script>
</body>
</html>"""


# ── Checkers HTML/CSS/JS ──────────────────────────────────────────

CHECKERS_HTML_PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Checkers Spectator</title>
<style>
:root {
  --bg: #0d1117;
  --surface: #161b22;
  --border: #30363d;
  --text: #e6edf3;
  --dim: #7d8590;
  --cyan: #58a6ff;
  --magenta: #d2a8ff;
  --green: #3fb950;
  --red: #f85149;
  --yellow: #d29922;
  --light-sq: #b58863;
  --dark-sq: #6d4c2a;
  --black-piece: #1a1a2e;
  --red-piece: #c0392b;
}
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
  background: var(--bg);
  color: var(--text);
  font-family: 'SF Mono', 'Cascadia Code', 'Fira Code', 'Consolas', monospace;
  font-size: 13px;
  line-height: 1.4;
  padding: 12px;
  max-width: 1000px;
  margin: 0 auto;
}

/* Header */
#header {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 12px 16px;
  margin-bottom: 10px;
  text-align: center;
}
#header .badge {
  display: inline-block;
  padding: 2px 10px;
  border-radius: 4px;
  font-weight: bold;
  font-size: 12px;
  margin-right: 8px;
  vertical-align: middle;
}
.badge-live { background: var(--green); color: #000; animation: pulse 2s infinite; }
.badge-final { background: var(--red); color: #fff; }
@keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.6; } }
#header .title { font-size: 16px; font-weight: bold; }
.player-a { color: var(--cyan); }
.player-b { color: var(--magenta); }
#header .sub { margin-top: 4px; color: var(--dim); }

/* Board + Sidebar layout */
#board-area {
  display: flex;
  gap: 12px;
  margin-bottom: 10px;
}
#board-panel {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 16px;
  flex-shrink: 0;
}
#board-wrap {
  display: flex;
  flex-direction: column;
  align-items: center;
}
#col-labels {
  display: grid;
  grid-template-columns: repeat(8, 1fr);
  width: 400px;
  margin-bottom: 2px;
  margin-left: 20px;
}
#col-labels span {
  text-align: center;
  font-size: 10px;
  color: var(--dim);
}
#board-with-rows {
  display: flex;
}
#row-labels {
  display: flex;
  flex-direction: column;
  justify-content: space-around;
  margin-right: 2px;
  width: 18px;
}
#row-labels span {
  font-size: 10px;
  color: var(--dim);
  text-align: center;
  height: 50px;
  line-height: 50px;
}
#board {
  display: grid;
  grid-template-columns: repeat(8, 50px);
  grid-template-rows: repeat(8, 50px);
  border: 2px solid var(--border);
  border-radius: 4px;
}
.sq {
  display: flex;
  align-items: center;
  justify-content: center;
  position: relative;
}
.sq-light { background: var(--light-sq); }
.sq-dark { background: var(--dark-sq); }
.sq.last-from, .sq.last-to { box-shadow: inset 0 0 0 3px var(--yellow); }
.sq.captured-sq { animation: captureFade 0.5s ease-out; }

/* Pieces */
.piece {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 16px;
  font-weight: 900;
  border: 3px solid rgba(255,255,255,0.3);
  box-shadow: 0 2px 4px rgba(0,0,0,0.5);
}
.piece-b, .piece-B { background: var(--black-piece); color: #aaa; border-color: #555; }
.piece-r, .piece-R { background: var(--red-piece); color: #fdd; border-color: #e88; }
.piece-B::after, .piece-R::after {
  content: '\u265A';
  font-size: 18px;
}
.piece.fresh { animation: pop 0.3s ease-out; }
@keyframes pop {
  0% { transform: scale(0.3); opacity: 0; }
  70% { transform: scale(1.1); }
  100% { transform: scale(1); opacity: 1; }
}
@keyframes captureFade {
  0% { background: var(--red); }
  100% { background: var(--dark-sq); }
}

/* Sidebar */
#sidebar {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 12px;
  flex: 1;
  min-width: 220px;
}
#sidebar h3 {
  font-size: 11px;
  text-transform: uppercase;
  color: var(--dim);
  border-bottom: 1px solid var(--border);
  padding-bottom: 4px;
  margin-bottom: 8px;
}
.score-row { margin-bottom: 8px; }
.score-row .name { font-weight: bold; font-size: 12px; }
.score-bar {
  height: 10px;
  border-radius: 3px;
  margin-top: 2px;
  transition: width 0.5s ease;
}
.stat-line { color: var(--dim); font-size: 11px; margin: 3px 0; }
.stat-line.violations { color: var(--red); }
.game-assignment { font-size: 11px; margin: 2px 0; }

/* Panels */
.panel {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px 14px;
  margin-bottom: 10px;
}
.panel h3 {
  font-size: 11px;
  text-transform: uppercase;
  color: var(--dim);
  border-bottom: 1px solid var(--border);
  padding-bottom: 4px;
  margin-bottom: 6px;
}

/* Game history */
.game-entry {
  padding: 3px 0;
  font-size: 12px;
  display: flex;
  align-items: baseline;
  gap: 6px;
}
.game-entry .gnum { color: var(--dim); min-width: 50px; }
.game-entry .result-win { font-weight: bold; }
.game-entry .result-draw { color: var(--yellow); font-weight: bold; }

/* Commentary */
.comment-entry { padding: 2px 0; font-size: 11px; }
.comment-entry .reasoning { color: var(--dim); font-style: italic; margin-left: 24px; display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

/* Footer */
#footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 0;
}
#footer .status { font-size: 12px; }
#copy-btn {
  background: var(--surface);
  border: 1px solid var(--border);
  color: var(--text);
  padding: 6px 14px;
  border-radius: 6px;
  cursor: pointer;
  font-family: inherit;
  font-size: 12px;
  transition: background 0.2s;
}
#copy-btn:hover { background: #1f2937; }
#copy-btn .count { background: var(--border); padding: 1px 6px; border-radius: 8px; margin-left: 6px; font-size: 10px; }
#copy-btn.copied { background: var(--green); color: #000; border-color: var(--green); }

/* Final panel */
#final-panel {
  display: none;
  text-align: center;
  padding: 20px;
  border-color: var(--red);
}
#final-panel.show { display: block; }
#final-panel .winner { font-size: 20px; font-weight: bold; }
#final-panel .breakdown { font-size: 14px; margin-top: 6px; }
#final-panel .stats { color: var(--dim); margin-top: 8px; font-size: 12px; }

/* Shot clock */
#shot-clock {
  display: none;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 8px 16px;
  margin-bottom: 10px;
  text-align: center;
}
#shot-clock .clock-label { font-size: 11px; color: var(--dim); text-transform: uppercase; letter-spacing: 1px; }
#shot-clock .clock-display { font-size: 24px; font-weight: bold; font-variant-numeric: tabular-nums; letter-spacing: 1px; margin: 2px 0; }
#shot-clock .clock-display.clock-ok { color: var(--cyan); }
#shot-clock .clock-display.clock-warn { color: var(--yellow); }
#shot-clock .clock-display.clock-danger { color: var(--red); animation: pulse 0.5s infinite; }
#shot-clock .strike-info { font-size: 11px; color: var(--dim); }
</style>
</head>
<body>

<div id="header">
  <span class="badge badge-live" id="badge">LIVE</span>
  <span class="title">CHECKERS</span>
  <span id="matchup"></span>
  <div class="sub" id="sub-info"></div>
</div>

<div id="shot-clock">
  <div class="clock-label" id="clock-label">SHOT CLOCK</div>
  <div class="clock-display clock-ok" id="clock-display">--.-s</div>
  <div class="strike-info" id="strike-info"></div>
</div>

<div id="board-area">
  <div id="board-panel">
    <div id="board-wrap">
      <div id="col-labels"></div>
      <div id="board-with-rows">
        <div id="row-labels"></div>
        <div id="board"></div>
      </div>
    </div>
  </div>
  <div id="sidebar">
    <h3>Series Score</h3>
    <div id="scores"></div>
    <h3 style="margin-top:12px">Current Game</h3>
    <div id="game-info"></div>
    <div id="sidebar-stats"></div>
  </div>
</div>

<div class="panel" id="final-panel">
  <h3>Final Result</h3>
  <div id="final-content"></div>
</div>

<div class="panel">
  <h3>Game History</h3>
  <div id="game-history"><span style="color:var(--dim);font-style:italic">No completed games</span></div>
</div>

<div class="panel">
  <h3>Play-by-Play</h3>
  <div id="commentary"><span style="color:var(--dim);font-style:italic">Waiting for action...</span></div>
</div>

<div id="footer">
  <div class="status" id="status-text">
    <span class="badge badge-live" style="font-size:10px">LIVE</span>
    Waiting for data...
  </div>
  <button id="copy-btn" onclick="copyRunlog()">
    Copy Runlog Path <span class="count" id="line-count">0</span>
  </button>
</div>

<script>
// ── Emoji system ─────────────────────────────────────────────────
const EMOJI_POOL = [
  '\u{1F525}','\u{1F9E0}','\u{1F47E}','\u{1F916}','\u{1F3AF}',
  '\u{1F680}','\u{1F40D}','\u{1F98A}','\u{1F43B}','\u{1F985}',
  '\u{1F409}','\u{1F3B2}','\u{1F9CA}','\u{1F30B}','\u{1F308}',
  '\u{1F52E}','\u{1F9F2}','\u{1F41D}','\u{1F95D}','\u{1F344}'
];
function djb2(s) {
  let h = 5381;
  for (let i = 0; i < s.length; i++) h = ((h << 5) + h + s.charCodeAt(i)) >>> 0;
  return h;
}
function pickEmojis(a, b) {
  let ia = djb2(a) % EMOJI_POOL.length;
  let ib = djb2(b) % EMOJI_POOL.length;
  if (ib === ia) ib = (ia + 1) % EMOJI_POOL.length;
  return { player_a: EMOJI_POOL[ia], player_b: EMOJI_POOL[ib] };
}

// ── Match state ──────────────────────────────────────────────────
const S = {
  matchId: '', modelA: '', modelB: '',
  board: null,
  previousBoard: null,
  seriesScores: { player_a: 0, player_b: 0 },
  gameNumber: 0,
  gameTurn: 0,
  turnCount: 0,
  colorMap: {},
  lastMove: null,
  gameHistory: [],
  commentary: [],
  violations: { player_a: 0, player_b: 0 },
  piecesRemaining: { black: 12, red: 12 },
  movesWithoutCapture: 0,
  finished: false,
  finalScores: {},
  highlightHands: [],
  emojis: { player_a: '', player_b: '' },
  // Shot clock
  shotClock: { timeLimitMs: null, lastTurnTime: null, strikes: { player_a: 0, player_b: 0 }, strikeLimit: null, waitingOn: '', lastTimeExceeded: false }
};

function emptyBoard() {
  return Array.from({length:8}, () => Array(8).fill(''));
}
S.board = emptyBoard();
S.previousBoard = emptyBoard();

const rawLines = [];
let turnQueue = [];
let isReplaying = false;

function shortModel(name) {
  if (!name) return name;
  return name.replace(/^anthropic\/claude-/, '').replace(/^anthropic\//, '').replace(/^openai\//, '');
}

function assignEmojis() {
  if (S.modelA && S.modelB && !S.emojis.player_a) {
    S.emojis = pickEmojis(S.modelA, S.modelB);
  }
}

function truncateReasoning(text, max) {
  max = max || 120;
  if (!text) return null;
  const lines = text.trim().split('\n');
  for (const line of lines) {
    const t = line.trim();
    if (t.length > 10) return t.length > max ? t.slice(0, max-3) + '...' : t;
  }
  return null;
}

// ── State machine ────────────────────────────────────────────────
function processTurn(data) {
  if (data.record_type === 'match_summary') {
    S.finished = true;
    S.finalScores = data.final_scores || {};
    S.highlightHands = data.highlight_hands || [];
    const pm = data.player_models || {};
    if (pm.player_a) S.modelA = shortModel(pm.player_a);
    if (pm.player_b) S.modelB = shortModel(pm.player_b);
    assignEmojis();
    return;
  }

  S.turnCount++;
  const snap = data.state_snapshot || {};
  const playerId = data.player_id || '';
  const modelId = data.model_id || '';

  if (!S.matchId) S.matchId = data.match_id || '';
  if (playerId === 'player_a' && !S.modelA) S.modelA = shortModel(modelId);
  else if (playerId === 'player_b' && !S.modelB) S.modelB = shortModel(modelId);
  assignEmojis();
  // Shot clock
  if (data.time_limit_ms) S.shotClock.timeLimitMs = data.time_limit_ms;
  if (data.strike_limit) S.shotClock.strikeLimit = data.strike_limit;
  if (data.cumulative_strikes !== undefined) S.shotClock.strikes[playerId] = data.cumulative_strikes;
  S.shotClock.lastTimeExceeded = !!data.time_exceeded;
  S.shotClock.lastTurnTime = Date.now();
  S.shotClock.waitingOn = playerId === 'player_a' ? 'player_b' : 'player_a';

  const handNum = snap.hand_number || 1;
  const gameTurn = snap.game_turn || 0;

  // Detect new game
  if (handNum !== S.gameNumber) {
    if (S.gameNumber > 0 && snap.result) {
      const already = S.gameHistory.find(g => g.gameNum === S.gameNumber);
      if (!already) {
        S.gameHistory.push({
          gameNum: S.gameNumber,
          result: snap.result,
          colorMap: {...S.colorMap}
        });
      }
    }
    S.gameNumber = handNum;
    S.lastMove = null;
    S.previousBoard = emptyBoard();
  }

  S.gameTurn = gameTurn;

  // Update color map
  if (snap.color_map) S.colorMap = {...snap.color_map};

  // Update board
  if (snap.board) {
    S.previousBoard = S.board.map(r => [...r]);
    S.board = snap.board.map(r => [...r]);
  }

  // Series scores
  if (snap.series_scores) S.seriesScores = {...snap.series_scores};

  // Last move
  S.lastMove = snap.last_move || null;

  // Pieces remaining
  if (snap.pieces_remaining) S.piecesRemaining = {...snap.pieces_remaining};

  // Draw counter
  if (snap.moves_without_capture !== undefined) S.movesWithoutCapture = snap.moves_without_capture;

  // Violations
  const violation = data.violation;
  if (violation) S.violations[playerId] = (S.violations[playerId] || 0) + 1;

  // Terminal — record final game result
  if (snap.terminal && snap.result) {
    const already = S.gameHistory.find(g => g.gameNum === S.gameNumber);
    if (!already) {
      S.gameHistory.push({
        gameNum: S.gameNumber,
        result: snap.result,
        colorMap: {...S.colorMap}
      });
    }
  }

  // Commentary
  const reasoning = truncateReasoning(data.reasoning_output);
  const lm = snap.last_move;
  if (gameTurn > 0) {
    let moveStr = '';
    if (lm) {
      moveStr = '[' + lm.from[0] + ',' + lm.from[1] + ']\u2192[' + lm.to[0] + ',' + lm.to[1] + ']';
      if (lm.captures && lm.captures.length) moveStr += ' (x' + lm.captures.length + ')';
    }
    S.commentary.push({
      turnNumber: S.turnCount,
      gameNumber: S.gameNumber,
      model: modelId,
      playerId,
      moveStr,
      reasoning,
      latencyMs: data.latency_ms || 0,
      isViolation: !!violation
    });
    if (S.commentary.length > 16) S.commentary.shift();
  }
}

// ── Rendering ────────────────────────────────────────────────────
function renderBoard() {
  const el = document.getElementById('board');
  el.innerHTML = '';

  const lastFrom = S.lastMove ? S.lastMove.from : null;
  const lastTo = S.lastMove ? S.lastMove.to : null;
  const capturedSet = new Set();
  if (S.lastMove && S.lastMove.captures) {
    S.lastMove.captures.forEach(c => capturedSet.add(c[0]+','+c[1]));
  }

  for (let r = 0; r < 8; r++) {
    for (let c = 0; c < 8; c++) {
      const div = document.createElement('div');
      const isDark = (r + c) % 2 === 1;
      div.className = 'sq ' + (isDark ? 'sq-dark' : 'sq-light');

      // Last move highlights
      if (lastFrom && lastFrom[0] === r && lastFrom[1] === c) div.className += ' last-from';
      if (lastTo && lastTo[0] === r && lastTo[1] === c) div.className += ' last-to';
      if (capturedSet.has(r+','+c)) div.className += ' captured-sq';

      const piece = S.board[r][c];
      if (piece) {
        const pieceEl = document.createElement('div');
        pieceEl.className = 'piece piece-' + piece;
        // Fresh animation
        if (S.previousBoard[r][c] !== piece) pieceEl.className += ' fresh';
        div.appendChild(pieceEl);
      }

      el.appendChild(div);
    }
  }

  // Col labels
  const colEl = document.getElementById('col-labels');
  colEl.innerHTML = '';
  for (let c = 0; c < 8; c++) {
    const s = document.createElement('span');
    s.textContent = c;
    colEl.appendChild(s);
  }

  // Row labels
  const rowEl = document.getElementById('row-labels');
  rowEl.innerHTML = '';
  for (let r = 0; r < 8; r++) {
    const s = document.createElement('span');
    s.textContent = r;
    rowEl.appendChild(s);
  }
}

function renderHeader() {
  const badge = document.getElementById('badge');
  badge.textContent = S.finished ? 'FINAL' : 'LIVE';
  badge.className = 'badge ' + (S.finished ? 'badge-final' : 'badge-live');

  const ea = S.emojis.player_a || '';
  const eb = S.emojis.player_b || '';
  document.getElementById('matchup').innerHTML =
    '<span class="player-a">' + ea + ' ' + (S.modelA || '???') + '</span>' +
    ' <span style="color:var(--dim)">vs</span> ' +
    '<span class="player-b">' + eb + ' ' + (S.modelB || '???') + '</span>';

  const sa = S.finished ? (S.finalScores.player_a ?? S.seriesScores.player_a) : S.seriesScores.player_a;
  const sb = S.finished ? (S.finalScores.player_b ?? S.seriesScores.player_b) : S.seriesScores.player_b;
  document.getElementById('sub-info').innerHTML =
    '<strong>Game ' + S.gameNumber + '</strong>' +
    ' <span style="color:var(--dim)">|</span> ' +
    '<span class="player-a" style="font-weight:bold">' + sa + '</span>' +
    ' <span style="color:var(--dim)">\u2013</span> ' +
    '<span class="player-b" style="font-weight:bold">' + sb + '</span>' +
    ' <span style="color:var(--dim)">|</span> ' +
    '<span style="color:var(--dim)">Move ' + S.gameTurn + '</span>';
}

function renderSidebar() {
  const sa = S.finished ? (S.finalScores.player_a ?? S.seriesScores.player_a) : S.seriesScores.player_a;
  const sb = S.finished ? (S.finalScores.player_b ?? S.seriesScores.player_b) : S.seriesScores.player_b;
  const maxScore = Math.max(sa, sb, 1);

  const ea = S.emojis.player_a || '';
  const eb = S.emojis.player_b || '';
  const nameA = (S.modelA || 'Player A').slice(0, 18);
  const nameB = (S.modelB || 'Player B').slice(0, 18);
  const pctA = Math.max(0, Math.min(100, (sa / maxScore) * 100));
  const pctB = Math.max(0, Math.min(100, (sb / maxScore) * 100));

  document.getElementById('scores').innerHTML =
    '<div class="score-row">' +
    '  <div class="name player-a">' + ea + ' ' + nameA + '</div>' +
    '  <div class="score-bar" style="width:' + pctA + '%;background:var(--cyan)">&nbsp;</div>' +
    '  <div style="color:var(--cyan);font-weight:bold">' + sa + '</div>' +
    '</div>' +
    '<div class="score-row">' +
    '  <div class="name player-b">' + eb + ' ' + nameB + '</div>' +
    '  <div class="score-bar" style="width:' + pctB + '%;background:var(--magenta)">&nbsp;</div>' +
    '  <div style="color:var(--magenta);font-weight:bold">' + sb + '</div>' +
    '</div>';

  // Color assignments
  let gameInfo = '';
  if (S.gameNumber > 0) {
    const blackPid = Object.entries(S.colorMap).find(([k,v]) => v === 'black');
    const redPid = Object.entries(S.colorMap).find(([k,v]) => v === 'red');
    const blackName = blackPid ? (blackPid[0] === 'player_a' ? nameA : nameB) : '?';
    const redName = redPid ? (redPid[0] === 'player_a' ? nameA : nameB) : '?';
    const blackColor = blackPid && blackPid[0] === 'player_a' ? 'var(--cyan)' : 'var(--magenta)';
    const redColor = redPid && redPid[0] === 'player_a' ? 'var(--cyan)' : 'var(--magenta)';

    gameInfo =
      '<div class="game-assignment">' +
      '<span style="color:#555;font-weight:bold">\u25CF Black</span> = <span style="color:' + blackColor + '">' + blackName + '</span></div>' +
      '<div class="game-assignment">' +
      '<span style="color:var(--red);font-weight:bold">\u25CF Red</span> = <span style="color:' + redColor + '">' + redName + '</span></div>' +
      '<div class="stat-line" style="margin-top:8px">Pieces: Black ' + S.piecesRemaining.black + ' / Red ' + S.piecesRemaining.red + '</div>' +
      '<div class="stat-line">Moves w/o capture: ' + S.movesWithoutCapture + ' / 40</div>' +
      '<div class="stat-line">Game ' + S.gameNumber + ', move ' + S.gameTurn + '</div>';
  }
  document.getElementById('game-info').innerHTML = gameInfo;

  // Violations
  let stats = '';
  const va = S.violations.player_a || 0;
  const vb = S.violations.player_b || 0;
  if (va + vb > 0) stats += '<div class="stat-line violations" style="margin-top:8px">Violations: A:' + va + ' B:' + vb + '</div>';
  document.getElementById('sidebar-stats').innerHTML = stats;
}

function renderGameHistory() {
  const el = document.getElementById('game-history');
  if (!S.gameHistory.length) {
    el.innerHTML = '<span style="color:var(--dim);font-style:italic">No completed games</span>';
    return;
  }
  const nameA = S.modelA || 'Player A';
  const nameB = S.modelB || 'Player B';
  el.innerHTML = S.gameHistory.map(function(g) {
    let resultHTML;
    if (g.result === 'black_wins') {
      const cm = g.colorMap || {};
      const winPid = Object.entries(cm).find(([k,v]) => v === 'black');
      const pid = winPid ? winPid[0] : 'player_a';
      const winName = pid === 'player_a' ? nameA : nameB;
      const color = pid === 'player_a' ? 'var(--cyan)' : 'var(--magenta)';
      resultHTML = '<span class="result-win" style="color:' + color + '">Black wins</span> <span style="color:var(--dim)">(' + winName + ')</span>';
    } else if (g.result === 'red_wins') {
      const cm = g.colorMap || {};
      const winPid = Object.entries(cm).find(([k,v]) => v === 'red');
      const pid = winPid ? winPid[0] : 'player_b';
      const winName = pid === 'player_a' ? nameA : nameB;
      const color = pid === 'player_a' ? 'var(--cyan)' : 'var(--magenta)';
      resultHTML = '<span class="result-win" style="color:' + color + '">Red wins</span> <span style="color:var(--dim)">(' + winName + ')</span>';
    } else {
      resultHTML = '<span class="result-draw">Draw</span>';
    }
    const hl = S.highlightHands.includes(g.gameNum) ? '<span style="color:var(--yellow)">\u2605 </span>' : '  ';
    return '<div class="game-entry">' + hl + '<span class="gnum">Game ' + g.gameNum + '</span>' + resultHTML + '</div>';
  }).join('');
}

function renderCommentary() {
  const el = document.getElementById('commentary');
  if (!S.commentary.length) {
    el.innerHTML = '<span style="color:var(--dim);font-style:italic">Waiting for action...</span>';
    return;
  }
  el.innerHTML = S.commentary.slice().reverse().map(function(e) {
    const color = e.playerId === 'player_a' ? 'var(--cyan)' : 'var(--magenta)';
    let actionHTML;
    if (e.isViolation) {
      actionHTML = '<span style="color:var(--red);font-weight:bold">violation!</span>';
    } else if (e.moveStr) {
      actionHTML = '<span style="color:var(--green)">' + e.moveStr + '</span>';
    } else {
      actionHTML = '<span style="color:var(--dim)">...</span>';
    }
    const latency = e.latencyMs > 100 ? ' <span style="color:var(--dim)">(' + (e.latencyMs/1000).toFixed(1) + 's)</span>' : '';
    const reason = e.reasoning ? '<span class="reasoning">"' + e.reasoning + '"</span>' : '';
    return '<div class="comment-entry"><span style="color:var(--dim)">G' + e.gameNumber + ' T' + e.turnNumber + '</span> <span style="color:' + color + ';font-weight:bold">' + e.model + '</span> ' + actionHTML + latency + reason + '</div>';
  }).join('');
}

function renderFinal() {
  if (!S.finished) { document.getElementById('final-panel').className = 'panel'; return; }
  document.getElementById('final-panel').className = 'panel show';
  const sa = S.finalScores.player_a || 0;
  const sb = S.finalScores.player_b || 0;

  let wA = 0, wB = 0, draws = 0;
  S.gameHistory.forEach(function(g) {
    if (g.result === 'draw') { draws++; return; }
    const cm = g.colorMap || {};
    const winColor = g.result === 'black_wins' ? 'black' : 'red';
    const winPid = Object.entries(cm).find(([k,v]) => v === winColor);
    const pid = winPid ? winPid[0] : 'player_a';
    if (pid === 'player_a') wA++;
    else wB++;
  });

  let html;
  if (sa === sb) {
    html = '<div class="winner" style="color:var(--yellow)">DRAW</div><div class="breakdown">' + sa + ' each</div>';
  } else {
    const wPid = sa > sb ? 'player_a' : 'player_b';
    const emoji = S.emojis[wPid] || '';
    const wName = wPid === 'player_a' ? S.modelA : S.modelB;
    const wColor = wPid === 'player_a' ? 'var(--cyan)' : 'var(--magenta)';
    html = '<div class="winner" style="color:' + wColor + '">' + emoji + ' ' + wName + ' WINS</div>' +
           '<div class="breakdown">' + sa + ' \u2013 ' + sb + '</div>';
  }
  const nameA = S.modelA || 'A';
  const nameB = S.modelB || 'B';
  html += '<div class="stats">' + nameA + ': ' + wA + 'W ' + draws + 'D ' + wB + 'L &nbsp;\u00B7&nbsp; ' + nameB + ': ' + wB + 'W ' + draws + 'D ' + wA + 'L</div>';
  const va = S.violations.player_a || 0, vb = S.violations.player_b || 0;
  if (va + vb > 0) html += '<div class="stats" style="color:var(--red)">Violations: A:' + va + ' B:' + vb + '</div>';
  document.getElementById('final-content').innerHTML = html;
}

function renderFooter() {
  const st = document.getElementById('status-text');
  if (S.finished) {
    st.innerHTML = '<span class="badge badge-final" style="font-size:10px">FINAL</span> Series Complete';
  } else {
    st.innerHTML = '<span class="badge badge-live" style="font-size:10px">LIVE</span> Watching...';
  }
  document.getElementById('line-count').textContent = rawLines.length;
}

function renderShotClock() {
  var el = document.getElementById('shot-clock');
  if (!S.shotClock.timeLimitMs || S.finished) { el.style.display = 'none'; return; }
  el.style.display = 'block';
  var display = document.getElementById('clock-display');
  var label = document.getElementById('clock-label');
  var strikeEl = document.getElementById('strike-info');
  if (!S.finished && !isReplaying && S.shotClock.lastTurnTime) {
    var elapsed = Date.now() - S.shotClock.lastTurnTime;
    var remaining = Math.max(0, S.shotClock.timeLimitMs - elapsed);
    var secs = remaining / 1000;
    display.textContent = secs.toFixed(1) + 's';
    var pct = remaining / S.shotClock.timeLimitMs;
    display.className = 'clock-display ' + (pct <= 0 ? 'clock-danger' : pct < 0.2 ? 'clock-danger' : pct < 0.5 ? 'clock-warn' : 'clock-ok');
  } else {
    display.textContent = (S.shotClock.timeLimitMs / 1000).toFixed(1) + 's';
    display.className = 'clock-display clock-ok';
  }
  var wModel = S.shotClock.waitingOn === 'player_a' ? (S.modelA || 'A') : (S.modelB || 'B');
  label.textContent = S.finished ? 'SHOT CLOCK' : 'SHOT CLOCK \u00b7 ' + wModel;
  if (S.shotClock.strikeLimit) {
    var sA = S.shotClock.strikes.player_a || 0;
    var sB = S.shotClock.strikes.player_b || 0;
    var nA = S.modelA || 'A', nB = S.modelB || 'B';
    strikeEl.innerHTML = '<span class="player-a">' + nA + ': ' + sA + '/' + S.shotClock.strikeLimit + '</span> \u00b7 <span class="player-b">' + nB + ': ' + sB + '/' + S.shotClock.strikeLimit + '</span>';
  } else { strikeEl.innerHTML = ''; }
}

function renderAll() {
  renderHeader();
  renderShotClock();
  renderBoard();
  renderSidebar();
  renderGameHistory();
  renderCommentary();
  renderFinal();
  renderFooter();
}

// ── Copy runlog ──────────────────────────────────────────────────
function copyRunlog() {
  const btn = document.getElementById('copy-btn');
  fetch('/filepath').then(function(r) { return r.text(); }).then(function(fp) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(fp).then(function() {
        btn.classList.add('copied');
        btn.textContent = 'Copied path!';
        setTimeout(function() {
          btn.classList.remove('copied');
          btn.innerHTML = 'Copy Runlog Path <span class="count">' + rawLines.length + '</span>';
        }, 2000);
      });
    } else {
      var ta = document.createElement('textarea');
      ta.value = fp;
      ta.style.position = 'fixed';
      ta.style.left = '-9999px';
      document.body.appendChild(ta);
      ta.select();
      document.execCommand('copy');
      document.body.removeChild(ta);
      btn.classList.add('copied');
      btn.textContent = 'Copied path!';
      setTimeout(function() {
        btn.classList.remove('copied');
        btn.innerHTML = 'Copy Runlog Path <span class="count">' + rawLines.length + '</span>';
      }, 2000);
    }
  });
}

// ── SSE client ───────────────────────────────────────────────────
function startSSE() {
  const es = new EventSource('/events');
  es.onmessage = function(e) {
    const line = e.data;
    rawLines.push(line);
    try {
      const data = JSON.parse(line);
      if (isReplaying) {
        turnQueue.push(data);
      } else {
        processTurn(data);
        renderAll();
      }
    } catch(err) {}
    document.getElementById('line-count').textContent = rawLines.length;
  };
  es.addEventListener('done', function() {
    es.close();
  });
  es.onerror = function() {};
}

function drainQueue() {
  if (!turnQueue.length) {
    isReplaying = false;
    renderAll();
    return;
  }
  const data = turnQueue.shift();
  processTurn(data);
  renderAll();
  const delay = data.record_type === 'match_summary' ? 200 : 80;
  setTimeout(drainQueue, delay);
}

// Init
renderBoard();
renderAll();

isReplaying = true;
turnQueue = [];
startSSE();

setTimeout(function() {
  if (turnQueue.length > 0) {
    drainQueue();
  } else {
    isReplaying = false;
  }
}, 300);
// Shot clock countdown
setInterval(function() {
  if (S.shotClock.timeLimitMs && !S.finished && !isReplaying) renderShotClock();
}, 100);

</script>
</body>
</html>"""


# ── Scrabble HTML/CSS/JS ─────────────────────────────────────────

HTML_PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Scrabble Spectator</title>
<style>
:root {
  --bg: #0d1117;
  --surface: #161b22;
  --border: #30363d;
  --text: #e6edf3;
  --dim: #7d8590;
  --cyan: #58a6ff;
  --magenta: #d2a8ff;
  --green: #3fb950;
  --red: #f85149;
  --yellow: #d29922;
  --blue: #58a6ff;
  --tile-bg: #d4a56a;
  --tile-text: #1a1209;
  --tile-blank: #c4944a;
  --tw: #c9362c;
  --dw: #c964cf;
  --tl: #2b7bd4;
  --dl: #3aafb9;
  --star: #d4a017;
}
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
  background: var(--bg);
  color: var(--text);
  font-family: 'SF Mono', 'Cascadia Code', 'Fira Code', 'Consolas', monospace;
  font-size: 13px;
  line-height: 1.4;
  padding: 12px;
  max-width: 1200px;
  margin: 0 auto;
}

/* Header */
#header {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 12px 16px;
  margin-bottom: 10px;
  text-align: center;
}
#header .badge {
  display: inline-block;
  padding: 2px 10px;
  border-radius: 4px;
  font-weight: bold;
  font-size: 12px;
  margin-right: 8px;
  vertical-align: middle;
}
.badge-live { background: var(--green); color: #000; animation: pulse 2s infinite; }
.badge-final { background: var(--red); color: #fff; }
@keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.6; } }
#header .title { font-size: 16px; font-weight: bold; }
.player-a { color: var(--cyan); }
.player-b { color: var(--magenta); }
#header .sub { margin-top: 4px; color: var(--dim); }
#header .sub .score { font-weight: bold; font-size: 14px; }

/* Board + Sidebar */
#board-area {
  display: flex;
  gap: 12px;
  margin-bottom: 10px;
}
#board-panel {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px;
  flex-shrink: 0;
}
#board {
  display: grid;
  grid-template-columns: repeat(15, 1fr);
  gap: 1px;
  width: 480px;
  height: 480px;
}
#board .cell {
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 11px;
  font-weight: bold;
  border-radius: 2px;
  position: relative;
}
.cell.empty { background: #1c2333; color: var(--dim); font-size: 9px; }
.cell.tw { background: var(--tw); color: #fff; font-size: 8px; }
.cell.dw { background: var(--dw); color: #fff; font-size: 8px; }
.cell.tl { background: var(--tl); color: #fff; font-size: 8px; }
.cell.dl { background: var(--dl); color: #fff; font-size: 8px; }
.cell.star { background: var(--star); color: #fff; font-size: 14px; }
.cell.tile {
  background: var(--tile-bg);
  color: var(--tile-text);
  font-size: 14px;
  font-weight: 900;
  text-shadow: 0 1px 0 rgba(255,255,255,0.3);
  box-shadow: inset 0 -2px 0 rgba(0,0,0,0.2), 0 1px 2px rgba(0,0,0,0.4);
  border-radius: 3px;
}
.cell.tile.blank { background: var(--tile-blank); font-style: italic; }
.cell.tile.fresh { animation: pop 0.3s ease-out; }
@keyframes pop {
  0% { transform: scale(0.3); opacity: 0; }
  70% { transform: scale(1.1); }
  100% { transform: scale(1); opacity: 1; }
}

/* Sidebar */
#sidebar {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 12px;
  flex: 1;
  min-width: 240px;
}
#sidebar h3 {
  font-size: 11px;
  text-transform: uppercase;
  color: var(--dim);
  border-bottom: 1px solid var(--border);
  padding-bottom: 4px;
  margin-bottom: 8px;
}
.score-row { margin-bottom: 8px; }
.score-row .name { font-weight: bold; font-size: 12px; }
.score-bar {
  height: 10px;
  border-radius: 3px;
  margin-top: 2px;
  transition: width 0.5s ease;
}
.rack { margin: 4px 0; }
.rack-tile {
  display: inline-block;
  background: var(--tile-bg);
  color: var(--tile-text);
  width: 24px; height: 24px;
  line-height: 24px;
  text-align: center;
  font-weight: 900;
  font-size: 12px;
  border-radius: 3px;
  margin: 1px;
  box-shadow: inset 0 -1px 0 rgba(0,0,0,0.2);
}
.rack-tile.high { color: var(--red); font-weight: 900; }
.rack-tile.blank-tile { background: var(--tile-blank); }
.stat-line { color: var(--dim); font-size: 11px; margin: 3px 0; }
.stat-line.violations { color: var(--red); }
.stat-line.bingos { color: var(--yellow); }

/* Panels */
.panel {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px 14px;
  margin-bottom: 10px;
}
.panel h3 {
  font-size: 11px;
  text-transform: uppercase;
  color: var(--dim);
  border-bottom: 1px solid var(--border);
  padding-bottom: 4px;
  margin-bottom: 6px;
}

/* Word History */
.word-entry {
  padding: 3px 0;
  font-size: 12px;
  display: flex;
  align-items: baseline;
  gap: 6px;
}
.word-entry .turn { color: var(--dim); min-width: 30px; }
.word-entry .who { font-weight: bold; min-width: 140px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.word-entry .word { font-weight: bold; color: #fff; }
.word-entry .pos { color: var(--dim); font-size: 11px; }
.word-entry .pts { color: var(--green); font-weight: bold; }
.word-entry .bingo { background: var(--red); color: #fff; padding: 0 4px; border-radius: 2px; font-size: 10px; font-weight: bold; }
.word-entry .cross { color: var(--cyan); font-size: 11px; }
.word-entry .action-dim { color: var(--dim); }
.word-entry .action-red { color: var(--red); font-weight: bold; }
.word-entry .highlight { color: var(--yellow); }

/* Commentary */
.comment-entry { padding: 2px 0; font-size: 11px; }
.comment-entry .reasoning { color: var(--dim); font-style: italic; margin-left: 24px; display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

/* Footer */
#footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 0;
}
#footer .status { font-size: 12px; }
#copy-btn {
  background: var(--surface);
  border: 1px solid var(--border);
  color: var(--text);
  padding: 6px 14px;
  border-radius: 6px;
  cursor: pointer;
  font-family: inherit;
  font-size: 12px;
  transition: background 0.2s;
}
#copy-btn:hover { background: #1f2937; }
#copy-btn .count { background: var(--border); padding: 1px 6px; border-radius: 8px; margin-left: 6px; font-size: 10px; }
#copy-btn.copied { background: var(--green); color: #000; border-color: var(--green); }

/* Final panel */
#final-panel {
  display: none;
  text-align: center;
  padding: 20px;
  border-color: var(--red);
}
#final-panel.show { display: block; }
#final-panel .winner { font-size: 20px; font-weight: bold; }
#final-panel .score-diff { font-size: 16px; margin-top: 4px; }
#final-panel .stats { color: var(--dim); margin-top: 8px; font-size: 12px; }

/* Shot clock */
#shot-clock {
  display: none;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 8px 16px;
  margin-bottom: 10px;
  text-align: center;
}
#shot-clock .clock-label { font-size: 11px; color: var(--dim); text-transform: uppercase; letter-spacing: 1px; }
#shot-clock .clock-display { font-size: 24px; font-weight: bold; font-variant-numeric: tabular-nums; letter-spacing: 1px; margin: 2px 0; }
#shot-clock .clock-display.clock-ok { color: var(--cyan); }
#shot-clock .clock-display.clock-warn { color: var(--yellow); }
#shot-clock .clock-display.clock-danger { color: var(--red); animation: pulse 0.5s infinite; }
#shot-clock .strike-info { font-size: 11px; color: var(--dim); }
</style>
</head>
<body>

<div id="header">
  <span class="badge badge-live" id="badge">LIVE</span>
  <span class="title">SCRABBLE</span>
  <span id="matchup"></span>
  <div class="sub" id="sub-info"></div>
</div>

<div id="shot-clock">
  <div class="clock-label" id="clock-label">SHOT CLOCK</div>
  <div class="clock-display clock-ok" id="clock-display">--.-s</div>
  <div class="strike-info" id="strike-info"></div>
</div>

<div id="board-area">
  <div id="board-panel">
    <div id="board"></div>
  </div>
  <div id="sidebar">
    <h3>Scores</h3>
    <div id="scores"></div>
    <h3 style="margin-top:12px">Racks</h3>
    <div id="racks"></div>
    <div id="sidebar-stats"></div>
  </div>
</div>

<div class="panel" id="final-panel">
  <h3>Final Result</h3>
  <div id="final-content"></div>
</div>

<div class="panel">
  <h3>Word History</h3>
  <div id="word-history"><span style="color:var(--dim);font-style:italic">No plays yet</span></div>
</div>

<div class="panel">
  <h3>Play-by-Play</h3>
  <div id="commentary"><span style="color:var(--dim);font-style:italic">Waiting for action...</span></div>
</div>

<div id="footer">
  <div class="status" id="status-text">
    <span class="badge badge-live" style="font-size:10px">LIVE</span>
    Waiting for data...
  </div>
  <button id="copy-btn" onclick="copyRunlog()">
    Copy Runlog Path <span class="count" id="line-count">0</span>
  </button>
</div>

<script>
// ── Premium squares ──────────────────────────────────────────────
const PREMIUM = {};
[[0,0],[0,7],[0,14],[7,0],[7,14],[14,0],[14,7],[14,14]].forEach(([r,c]) => PREMIUM[r+','+c]='TW');
[[1,1],[2,2],[3,3],[4,4],[1,13],[2,12],[3,11],[4,10],[10,4],[11,3],[12,2],[13,1],[10,10],[11,11],[12,12],[13,13],[7,7]].forEach(([r,c]) => PREMIUM[r+','+c]='DW');
[[1,5],[1,9],[5,1],[5,5],[5,9],[5,13],[9,1],[9,5],[9,9],[9,13],[13,5],[13,9]].forEach(([r,c]) => PREMIUM[r+','+c]='TL');
[[0,3],[0,11],[2,6],[2,8],[3,0],[3,7],[3,14],[6,2],[6,6],[6,8],[6,12],[7,3],[7,11],[8,2],[8,6],[8,8],[8,12],[11,0],[11,7],[11,14],[12,6],[12,8],[14,3],[14,11]].forEach(([r,c]) => PREMIUM[r+','+c]='DL');

// ── Emoji system ─────────────────────────────────────────────────
const EMOJI_POOL = [
  '\u{1F525}','\u{1F9E0}','\u{1F47E}','\u{1F916}','\u{1F3AF}',
  '\u{1F680}','\u{1F40D}','\u{1F98A}','\u{1F43B}','\u{1F985}',
  '\u{1F409}','\u{1F3B2}','\u{1F9CA}','\u{1F30B}','\u{1F308}',
  '\u{1F52E}','\u{1F9F2}','\u{1F41D}','\u{1F95D}','\u{1F344}'
];
function djb2(s) {
  let h = 5381;
  for (let i = 0; i < s.length; i++) h = ((h << 5) + h + s.charCodeAt(i)) >>> 0;
  return h;
}
function pickEmojis(a, b) {
  let ia = djb2(a) % EMOJI_POOL.length;
  let ib = djb2(b) % EMOJI_POOL.length;
  if (ib === ia) ib = (ia + 1) % EMOJI_POOL.length;
  return { player_a: EMOJI_POOL[ia], player_b: EMOJI_POOL[ib] };
}

// ── Match state ──────────────────────────────────────────────────
const S = {
  matchId: '', modelA: '', modelB: '',
  board: Array.from({length:15}, ()=> Array(15).fill(null)),
  scores: { player_a: 0, player_b: 0 },
  racks: { player_a: [], player_b: [] },
  tilesRemaining: 86,
  consecutivePasses: 0,
  turnCount: 0,
  activePlayer: 'player_a',
  wordHistory: [],  // last 8
  commentary: [],   // last 10
  finished: false,
  finalScores: {},
  highlightTurns: [],
  violations: { player_a: 0, player_b: 0 },
  totalBingos: { player_a: 0, player_b: 0 },
  emojis: { player_a: '', player_b: '' },
  // Shot clock
  shotClock: { timeLimitMs: null, lastTurnTime: null, strikes: { player_a: 0, player_b: 0 }, strikeLimit: null, waitingOn: '', lastTimeExceeded: false },
  previousCells: new Set()  // track which cells had tiles before this turn
};

const rawLines = [];
let turnQueue = [];
let isReplaying = false;

function shortModel(name) {
  if (!name) return name;
  // Strip provider prefixes like "anthropic/claude-" or "anthropic/"
  return name.replace(/^anthropic\/claude-/, '').replace(/^anthropic\//, '').replace(/^openai\//, '');
}

function assignEmojis() {
  if (S.modelA && S.modelB && !S.emojis.player_a) {
    S.emojis = pickEmojis(S.modelA, S.modelB);
  }
}

function truncateReasoning(text, max) {
  max = max || 80;
  if (!text) return null;
  const lines = text.trim().split('\n');
  for (const line of lines) {
    const t = line.trim();
    if (t.length > 10) return t.length > max ? t.slice(0, max-3) + '...' : t;
  }
  return null;
}

// ── State machine (port of process_scrabble_turn) ────────────────
function processTurn(data) {
  // Match summary
  if (data.record_type === 'match_summary') {
    S.finished = true;
    S.finalScores = data.final_scores || {};
    S.highlightTurns = data.highlight_hands || [];
    const pm = data.player_models || {};
    if (pm.player_a) S.modelA = shortModel(pm.player_a);
    if (pm.player_b) S.modelB = shortModel(pm.player_b);
    assignEmojis();
    // Score last unscored word
    if (S.wordHistory.length) {
      const last = S.wordHistory[S.wordHistory.length - 1];
      if (last.actionType === 'play' && last.points === 0) {
        const delta = (S.finalScores[last.playerId] || 0) - (S.scores[last.playerId] || 0);
        if (delta > 0) last.points = delta;
      }
    }
    return;
  }

  S.turnCount++;
  const snap = data.state_snapshot || {};
  const playerId = data.player_id || '';
  const modelId = data.model_id || '';

  if (!S.matchId) S.matchId = data.match_id || '';
  if (playerId === 'player_a' && !S.modelA) S.modelA = shortModel(modelId);
  else if (playerId === 'player_b' && !S.modelB) S.modelB = shortModel(modelId);
  assignEmojis();
  // Shot clock
  if (data.time_limit_ms) S.shotClock.timeLimitMs = data.time_limit_ms;
  if (data.strike_limit) S.shotClock.strikeLimit = data.strike_limit;
  if (data.cumulative_strikes !== undefined) S.shotClock.strikes[playerId] = data.cumulative_strikes;
  S.shotClock.lastTimeExceeded = !!data.time_exceeded;
  S.shotClock.lastTurnTime = Date.now();
  S.shotClock.waitingOn = playerId === 'player_a' ? 'player_b' : 'player_a';

  // Update game state
  if (snap.tiles_remaining !== undefined) S.tilesRemaining = snap.tiles_remaining;
  if (snap.consecutive_passes !== undefined) S.consecutivePasses = snap.consecutive_passes;
  if (snap.active_player) S.activePlayer = snap.active_player;

  // Extract rack
  const prompt = data.prompt || '';
  if (playerId && prompt) {
    const m = prompt.match(/Your rack:\s*(.+)/);
    if (m) S.racks[playerId] = m[1].trim().split(/\s+/);
  }

  // Parse action
  const parsed = data.parsed_action || {};
  let actionType = parsed.action || '???';
  const violation = data.violation;
  const isForfeit = data.validation_result === 'forfeit';
  if (isForfeit) actionType = 'forfeit';

  if (violation) S.violations[playerId] = (S.violations[playerId] || 0) + 1;

  // Build word record
  let word = null, position = null, direction = null, tilesExchanged = 0;
  // Snapshot previous board cells
  S.previousCells = new Set();
  for (let r = 0; r < 15; r++)
    for (let c = 0; c < 15; c++)
      if (S.board[r][c]) S.previousCells.add(r + ',' + c);

  if (actionType === 'play' && !isForfeit) {
    word = (parsed.word || '').toUpperCase() || null;
    const pos = parsed.position || [];
    direction = parsed.direction;
    if (Array.isArray(pos) && pos.length === 2) position = [+pos[0], +pos[1]];

    if (data.validation_result === 'legal' && word && position && direction) {
      const blanks = new Set(Object.keys(parsed.blank_assignments || {}).map(Number));
      let [row, col] = position;
      for (let i = 0; i < word.length; i++) {
        const r = row + (direction === 'down' ? i : 0);
        const c = col + (direction === 'across' ? i : 0);
        if (r >= 0 && r < 15 && c >= 0 && c < 15 && !S.board[r][c]) {
          S.board[r][c] = { letter: word[i].toUpperCase(), blank: blanks.has(i) };
        }
      }
    }
  } else if (actionType === 'exchange' && !isForfeit) {
    tilesExchanged = (parsed.tiles_to_exchange || []).length;
  }

  S.wordHistory.push({
    turnNumber: S.turnCount,
    model: modelId,
    playerId,
    actionType,
    word,
    position,
    direction,
    points: 0,
    crossWords: [],
    bingo: false,
    tilesExchanged,
    isViolation: !!violation || isForfeit
  });
  if (S.wordHistory.length > 8) S.wordHistory.shift();

  // Score deltas — fill in the word record that scored points
  const newScores = snap.scores || {};
  if (newScores.player_a !== undefined || newScores.player_b !== undefined) {
    for (const pid of ['player_a', 'player_b']) {
      const delta = (newScores[pid] || 0) - (S.scores[pid] || 0);
      if (delta > 0) {
        for (let i = S.wordHistory.length - 1; i >= 0; i--) {
          const rec = S.wordHistory[i];
          if (rec.playerId === pid && rec.actionType === 'play' && rec.points === 0) {
            rec.points = delta;
            break;
          }
        }
      }
    }
    S.scores = { player_a: newScores.player_a || 0, player_b: newScores.player_b || 0 };
  }

  // Bingo / cross-words from snapshot
  const snapWord = snap.word_played;
  const snapBingo = snap.bingo || false;
  const snapCross = snap.cross_words_formed || [];
  if (snapWord) {
    for (let i = S.wordHistory.length - 1; i >= 0; i--) {
      const rec = S.wordHistory[i];
      if (rec.word && rec.word.toUpperCase() === snapWord.toUpperCase()) {
        if (snapCross.length && !rec.crossWords.length) rec.crossWords = [...snapCross];
        if (snapBingo && !rec.bingo) {
          rec.bingo = true;
          S.totalBingos[rec.playerId] = (S.totalBingos[rec.playerId] || 0) + 1;
        }
        break;
      }
    }
  }

  const reasoning = truncateReasoning(data.reasoning_output);
  S.commentary.push({
    turnNumber: S.turnCount,
    model: modelId,
    playerId,
    action: actionType,
    reasoning,
    latencyMs: data.latency_ms || 0,
    isViolation: !!violation || isForfeit
  });
  if (S.commentary.length > 10) S.commentary.shift();
}

// ── Rendering ────────────────────────────────────────────────────
function renderBoard() {
  const el = document.getElementById('board');
  el.innerHTML = '';
  for (let r = 0; r < 15; r++) {
    for (let c = 0; c < 15; c++) {
      const div = document.createElement('div');
      div.className = 'cell';
      const cell = S.board[r][c];
      if (cell) {
        div.className = 'cell tile' + (cell.blank ? ' blank' : '');
        if (!S.previousCells.has(r + ',' + c)) div.className += ' fresh';
        div.textContent = cell.blank ? cell.letter.toLowerCase() : cell.letter;
      } else {
        const prem = PREMIUM[r + ',' + c];
        if (prem === 'TW') { div.className = 'cell tw'; div.textContent = '3W'; }
        else if (prem === 'DW') {
          if (r === 7 && c === 7) { div.className = 'cell star'; div.textContent = '\u2605'; }
          else { div.className = 'cell dw'; div.textContent = '2W'; }
        }
        else if (prem === 'TL') { div.className = 'cell tl'; div.textContent = '3L'; }
        else if (prem === 'DL') { div.className = 'cell dl'; div.textContent = '2L'; }
        else { div.className = 'cell empty'; div.textContent = '\u00B7'; }
      }
      el.appendChild(div);
    }
  }
}

function renderHeader() {
  const badge = document.getElementById('badge');
  badge.textContent = S.finished ? 'FINAL' : 'LIVE';
  badge.className = 'badge ' + (S.finished ? 'badge-final' : 'badge-live');

  const ea = S.emojis.player_a || '';
  const eb = S.emojis.player_b || '';
  document.getElementById('matchup').innerHTML =
    `<span class="player-a">${ea} ${S.modelA || '???'}</span>` +
    ` <span style="color:var(--dim)">vs</span> ` +
    `<span class="player-b">${eb} ${S.modelB || '???'}</span>`;

  const sa = S.finished ? (S.finalScores.player_a ?? S.scores.player_a ?? 0) : (S.scores.player_a || 0);
  const sb = S.finished ? (S.finalScores.player_b ?? S.scores.player_b ?? 0) : (S.scores.player_b || 0);
  const passStyle = S.consecutivePasses >= 4 ? 'color:var(--red);font-weight:bold' : 'color:var(--dim)';
  document.getElementById('sub-info').innerHTML =
    `<strong>Turn ${S.turnCount}</strong> ` +
    `<span style="color:var(--dim)">|</span> ` +
    `<span class="score player-a">${sa}</span>` +
    ` <span style="color:var(--dim)">\u2013</span> ` +
    `<span class="score player-b">${sb}</span>` +
    ` <span style="color:var(--dim)">|</span> ` +
    `<span style="color:var(--yellow);font-weight:bold">Bag: ${S.tilesRemaining}</span>` +
    ` <span style="color:var(--dim)">|</span> ` +
    `<span style="${passStyle}">Passes: ${S.consecutivePasses}/6</span>`;
}

function renderSidebar() {
  const sa = S.finished ? (S.finalScores.player_a ?? S.scores.player_a ?? 0) : (S.scores.player_a || 0);
  const sb = S.finished ? (S.finalScores.player_b ?? S.scores.player_b ?? 0) : (S.scores.player_b || 0);
  const maxScore = Math.max(sa, sb, 1);

  const ea = S.emojis.player_a || '';
  const eb = S.emojis.player_b || '';
  const nameA = (S.modelA || 'Player A').slice(0, 18);
  const nameB = (S.modelB || 'Player B').slice(0, 18);

  const pctA = Math.max(0, Math.min(100, (sa / maxScore) * 100));
  const pctB = Math.max(0, Math.min(100, (sb / maxScore) * 100));

  document.getElementById('scores').innerHTML =
    `<div class="score-row">
      <div class="name player-a">${ea} ${nameA}</div>
      <div class="score-bar" style="width:${pctA}%;background:var(--cyan)">&nbsp;</div>
      <div style="color:var(--cyan);font-weight:bold">${sa}</div>
    </div>
    <div class="score-row">
      <div class="name player-b">${eb} ${nameB}</div>
      <div class="score-bar" style="width:${pctB}%;background:var(--magenta)">&nbsp;</div>
      <div style="color:var(--magenta);font-weight:bold">${sb}</div>
    </div>`;

  const HIGH = new Set('JQXZ'.split(''));
  function rackHTML(tiles) {
    return tiles.sort().map(t => {
      if (t === '?') return `<span class="rack-tile blank-tile">?</span>`;
      const cls = HIGH.has(t) ? 'rack-tile high' : 'rack-tile';
      return `<span class="${cls}">${t}</span>`;
    }).join('');
  }
  document.getElementById('racks').innerHTML =
    `<div class="rack"><span class="player-a" style="font-weight:bold">A:</span> ${rackHTML(S.racks.player_a || [])}</div>` +
    `<div class="rack"><span class="player-b" style="font-weight:bold">B:</span> ${rackHTML(S.racks.player_b || [])}</div>`;

  let stats = `<div class="stat-line" style="margin-top:10px">Bag: ${S.tilesRemaining} tiles</div>`;
  const va = S.violations.player_a || 0;
  const vb = S.violations.player_b || 0;
  if (va + vb > 0) stats += `<div class="stat-line violations">Violations: A:${va} B:${vb}</div>`;
  const ba = S.totalBingos.player_a || 0;
  const bb = S.totalBingos.player_b || 0;
  if (ba + bb > 0) stats += `<div class="stat-line bingos">Bingos: A:${ba} B:${bb}</div>`;
  document.getElementById('sidebar-stats').innerHTML = stats;
}

function renderWordHistory() {
  const el = document.getElementById('word-history');
  if (!S.wordHistory.length) { el.innerHTML = '<span style="color:var(--dim);font-style:italic">No plays yet</span>'; return; }
  el.innerHTML = [...S.wordHistory].reverse().map(rec => {
    const isHL = S.highlightTurns.includes(rec.turnNumber) || rec.bingo;
    const color = rec.playerId === 'player_a' ? 'var(--cyan)' : 'var(--magenta)';
    const emoji = S.emojis[rec.playerId] || '';
    const name = (rec.model || '???').slice(0, 16);
    let detail = '';
    if (rec.actionType === 'play' && rec.word) {
      const arrow = rec.direction === 'across' ? '\u2192' : '\u2193';
      const posStr = rec.position ? `(${rec.position[0]},${rec.position[1]})${arrow}` : '';
      detail = `<span class="word">${rec.word}</span> <span class="pos">${posStr}</span>`;
      if (rec.points > 0) detail += ` <span class="pts">${rec.points}pts</span>`;
      if (rec.bingo) detail += ` <span class="bingo">BINGO!</span>`;
      if (rec.crossWords.length) detail += ` <span class="cross">${rec.crossWords.slice(0,3).map(w=>'+'+w).join(' ')}</span>`;
    } else if (rec.actionType === 'exchange') {
      detail = `<span class="action-dim">exchanged ${rec.tilesExchanged} tiles</span>`;
    } else if (rec.actionType === 'pass') {
      detail = `<span class="action-dim" style="color:var(--yellow)">PASS</span>`;
    } else if (rec.actionType === 'forfeit') {
      detail = `<span class="action-red">FORFEIT</span>`;
    } else {
      detail = `<span class="action-dim">${rec.actionType}</span>`;
    }
    const hlMark = isHL ? '<span class="highlight">\u2605 </span>' : '  ';
    return `<div class="word-entry">${hlMark}<span class="turn">T${rec.turnNumber}</span><span class="who" style="color:${color}">${emoji}${name}</span>${detail}</div>`;
  }).join('');
}

function renderCommentary() {
  const el = document.getElementById('commentary');
  if (!S.commentary.length) { el.innerHTML = '<span style="color:var(--dim);font-style:italic">Waiting for action...</span>'; return; }
  el.innerHTML = [...S.commentary].reverse().map(e => {
    const color = e.playerId === 'player_a' ? 'var(--cyan)' : 'var(--magenta)';
    let actionHTML;
    if (e.isViolation) actionHTML = `<span style="color:var(--red);font-weight:bold">${e.action} !</span>`;
    else if (e.action === 'play') actionHTML = `<span style="color:var(--green);font-weight:bold">plays</span>`;
    else if (e.action === 'exchange') actionHTML = `<span style="font-weight:bold">exchanges</span>`;
    else if (e.action === 'pass') actionHTML = `<span style="color:var(--yellow)">passes</span>`;
    else if (e.action === 'forfeit') actionHTML = `<span style="color:var(--red);font-weight:bold">FORFEITS</span>`;
    else actionHTML = `<span>${e.action}</span>`;
    const latency = e.latencyMs > 100 ? ` <span style="color:var(--dim)">(${(e.latencyMs/1000).toFixed(1)}s)</span>` : '';
    const reason = e.reasoning ? `<span class="reasoning">"${e.reasoning}"</span>` : '';
    return `<div class="comment-entry"><span style="color:var(--dim)">T${e.turnNumber}</span> <span style="color:${color};font-weight:bold">${e.model}</span> ${actionHTML}${latency}${reason}</div>`;
  }).join('');
}

function renderFinal() {
  if (!S.finished) { document.getElementById('final-panel').className = 'panel'; return; }
  document.getElementById('final-panel').className = 'panel show';
  const sa = S.finalScores.player_a || 0;
  const sb = S.finalScores.player_b || 0;
  let html;
  if (sa === sb) {
    html = `<div class="winner" style="color:var(--yellow)">DRAW</div><div class="score-diff">${sa} each</div>`;
  } else {
    const wPid = sa > sb ? 'player_a' : 'player_b';
    const emoji = S.emojis[wPid] || '';
    const wName = wPid === 'player_a' ? S.modelA : S.modelB;
    const wColor = wPid === 'player_a' ? 'var(--cyan)' : 'var(--magenta)';
    const ws = Math.max(sa,sb), ls = Math.min(sa,sb);
    html = `<div class="winner" style="color:${wColor}">${emoji} ${wName} WINS</div>` +
           `<div class="score-diff">${ws} \u2013 ${ls} <span style="color:var(--yellow)">(+${ws-ls})</span></div>`;
  }
  let stats = '';
  const ba = S.totalBingos.player_a || 0, bb = S.totalBingos.player_b || 0;
  if (ba + bb > 0) stats += `Bingos: A:${ba} B:${bb}  `;
  const va = S.violations.player_a || 0, vb = S.violations.player_b || 0;
  if (va + vb > 0) stats += `<span style="color:var(--red)">Violations: A:${va} B:${vb}</span>`;
  if (stats) html += `<div class="stats">${stats}</div>`;
  document.getElementById('final-content').innerHTML = html;
}

function renderFooter() {
  const st = document.getElementById('status-text');
  if (S.finished) {
    st.innerHTML = '<span class="badge badge-final" style="font-size:10px">FINAL</span> Match Complete';
  } else {
    st.innerHTML = '<span class="badge badge-live" style="font-size:10px">LIVE</span> Watching...';
  }
  document.getElementById('line-count').textContent = rawLines.length;
}

function renderShotClock() {
  var el = document.getElementById('shot-clock');
  if (!S.shotClock.timeLimitMs || S.finished) { el.style.display = 'none'; return; }
  el.style.display = 'block';
  var display = document.getElementById('clock-display');
  var label = document.getElementById('clock-label');
  var strikeEl = document.getElementById('strike-info');
  if (!S.finished && !isReplaying && S.shotClock.lastTurnTime) {
    var elapsed = Date.now() - S.shotClock.lastTurnTime;
    var remaining = Math.max(0, S.shotClock.timeLimitMs - elapsed);
    var secs = remaining / 1000;
    display.textContent = secs.toFixed(1) + 's';
    var pct = remaining / S.shotClock.timeLimitMs;
    display.className = 'clock-display ' + (pct <= 0 ? 'clock-danger' : pct < 0.2 ? 'clock-danger' : pct < 0.5 ? 'clock-warn' : 'clock-ok');
  } else {
    display.textContent = (S.shotClock.timeLimitMs / 1000).toFixed(1) + 's';
    display.className = 'clock-display clock-ok';
  }
  var wModel = S.shotClock.waitingOn === 'player_a' ? (S.modelA || 'A') : (S.modelB || 'B');
  label.textContent = S.finished ? 'SHOT CLOCK' : 'SHOT CLOCK \u00b7 ' + wModel;
  if (S.shotClock.strikeLimit) {
    var sA = S.shotClock.strikes.player_a || 0;
    var sB = S.shotClock.strikes.player_b || 0;
    var nA = S.modelA || 'A', nB = S.modelB || 'B';
    strikeEl.innerHTML = '<span class="player-a">' + nA + ': ' + sA + '/' + S.shotClock.strikeLimit + '</span> \u00b7 <span class="player-b">' + nB + ': ' + sB + '/' + S.shotClock.strikeLimit + '</span>';
  } else { strikeEl.innerHTML = ''; }
}

function renderAll() {
  renderHeader();
  renderShotClock();
  renderBoard();
  renderSidebar();
  renderWordHistory();
  renderCommentary();
  renderFinal();
  renderFooter();
}

// ── Copy runlog ──────────────────────────────────────────────────
function copyRunlog() {
  const btn = document.getElementById('copy-btn');
  fetch('/filepath').then(r => r.text()).then(function(fp) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(fp).then(() => {
        btn.classList.add('copied');
        btn.textContent = 'Copied path!';
        setTimeout(() => {
          btn.classList.remove('copied');
          btn.innerHTML = 'Copy Runlog Path <span class="count">' + rawLines.length + '</span>';
        }, 2000);
      });
    } else {
      const ta = document.createElement('textarea');
      ta.value = fp;
      ta.style.position = 'fixed';
      ta.style.left = '-9999px';
      document.body.appendChild(ta);
      ta.select();
      document.execCommand('copy');
      document.body.removeChild(ta);
      btn.classList.add('copied');
      btn.textContent = 'Copied path!';
      setTimeout(() => {
        btn.classList.remove('copied');
        btn.innerHTML = 'Copy Runlog Path <span class="count">' + rawLines.length + '</span>';
      }, 2000);
    }
  });
}

// ── SSE client ───────────────────────────────────────────────────
function startSSE() {
  const es = new EventSource('/events');
  es.onmessage = function(e) {
    const line = e.data;
    rawLines.push(line);
    try {
      const data = JSON.parse(line);
      if (isReplaying) {
        turnQueue.push(data);
      } else {
        processTurn(data);
        renderAll();
      }
    } catch(err) {}
    document.getElementById('line-count').textContent = rawLines.length;
  };
  es.addEventListener('done', function() {
    es.close();
  });
  es.onerror = function() {
    // Will auto-reconnect or close
  };
}

// Replay animation for completed matches
function drainQueue() {
  if (!turnQueue.length) {
    isReplaying = false;
    renderAll();
    return;
  }
  const data = turnQueue.shift();
  processTurn(data);
  renderAll();
  const delay = data.record_type === 'match_summary' ? 200 : 50;
  setTimeout(drainQueue, delay);
}

// Init
renderBoard();
renderAll();

// Start SSE — check if match is already complete by loading first batch
isReplaying = true;
turnQueue = [];
startSSE();

// After a short delay to accumulate initial batch, start replay
setTimeout(() => {
  if (turnQueue.length > 0) {
    drainQueue();
  } else {
    isReplaying = false;
  }
}, 300);
// Shot clock countdown
setInterval(function() {
  if (S.shotClock.timeLimitMs && !S.finished && !isReplaying) renderShotClock();
}, 100);

</script>
</body>
</html>"""


# ── Connect Four HTML/CSS/JS ──────────────────────────────────────

CONNECTFOUR_HTML_PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Connect Four Spectator</title>
<style>
:root {
  --bg: #0d1117;
  --surface: #161b22;
  --border: #30363d;
  --text: #e6edf3;
  --dim: #7d8590;
  --cyan: #58a6ff;
  --magenta: #d2a8ff;
  --green: #3fb950;
  --red: #f85149;
  --yellow: #d29922;
  --piece-x: #e8c840;
  --piece-o: #e84040;
}
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
  background: var(--bg);
  color: var(--text);
  font-family: 'SF Mono', 'Cascadia Code', 'Fira Code', 'Consolas', monospace;
  font-size: 13px;
  line-height: 1.4;
  padding: 12px;
  max-width: 960px;
  margin: 0 auto;
}

/* Header */
#header {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 12px 16px;
  margin-bottom: 10px;
  text-align: center;
}
#header .badge {
  display: inline-block;
  padding: 2px 10px;
  border-radius: 4px;
  font-weight: bold;
  font-size: 12px;
  margin-right: 8px;
  vertical-align: middle;
}
.badge-live { background: var(--green); color: #000; animation: pulse 2s infinite; }
.badge-final { background: var(--red); color: #fff; }
@keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.6; } }
#header .title { font-size: 16px; font-weight: bold; }
.player-a { color: var(--piece-x); }
.player-b { color: var(--piece-o); }
#header .sub { margin-top: 4px; color: var(--dim); }

/* Board + Sidebar layout */
#board-area {
  display: flex;
  gap: 12px;
  margin-bottom: 10px;
}
#board-panel {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 16px;
  flex-shrink: 0;
}

/* Column numbers */
#col-labels {
  display: grid;
  grid-template-columns: repeat(7, 48px);
  gap: 4px;
  margin-bottom: 4px;
  text-align: center;
  color: var(--dim);
  font-size: 12px;
  font-weight: bold;
}

/* Board grid */
#board {
  display: grid;
  grid-template-columns: repeat(7, 48px);
  grid-template-rows: repeat(6, 48px);
  gap: 4px;
  background: #1a3a8a;
  padding: 6px;
  border-radius: 8px;
}
#board .cell {
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  background: #0d1117;
  transition: background 0.2s, box-shadow 0.2s;
}
#board .cell.x-piece {
  background: var(--piece-x);
  box-shadow: inset 0 -3px 6px rgba(0,0,0,0.3);
}
#board .cell.o-piece {
  background: var(--piece-o);
  box-shadow: inset 0 -3px 6px rgba(0,0,0,0.3);
}
#board .cell.last-move {
  box-shadow: 0 0 0 3px var(--green), inset 0 -3px 6px rgba(0,0,0,0.3);
}
#board .cell.win-cell {
  box-shadow: 0 0 12px 4px var(--green), inset 0 -3px 6px rgba(0,0,0,0.3);
  animation: glow 1s ease-in-out infinite alternate;
}
@keyframes glow {
  0% { box-shadow: 0 0 8px 2px var(--green), inset 0 -3px 6px rgba(0,0,0,0.3); }
  100% { box-shadow: 0 0 16px 6px var(--green), inset 0 -3px 6px rgba(0,0,0,0.3); }
}
.cell.fresh { animation: drop 0.4s ease-in; }
@keyframes drop {
  0% { transform: translateY(-200px); opacity: 0; }
  60% { transform: translateY(10px); }
  80% { transform: translateY(-4px); }
  100% { transform: translateY(0); opacity: 1; }
}

/* Sidebar */
#sidebar {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 12px;
  flex: 1;
  min-width: 220px;
}
#sidebar h3 {
  font-size: 11px;
  text-transform: uppercase;
  color: var(--dim);
  border-bottom: 1px solid var(--border);
  padding-bottom: 4px;
  margin-bottom: 8px;
}
.score-row { margin-bottom: 8px; }
.score-row .name { font-weight: bold; font-size: 12px; }
.score-bar {
  height: 10px;
  border-radius: 3px;
  margin-top: 2px;
  transition: width 0.5s ease;
}
.stat-line { color: var(--dim); font-size: 11px; margin: 3px 0; }
.stat-line.violations { color: var(--red); }
.game-assignment { font-size: 11px; margin: 2px 0; }

/* Panels */
.panel {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px 14px;
  margin-bottom: 10px;
}
.panel h3 {
  font-size: 11px;
  text-transform: uppercase;
  color: var(--dim);
  border-bottom: 1px solid var(--border);
  padding-bottom: 4px;
  margin-bottom: 6px;
}

/* Game history */
.game-entry {
  padding: 3px 0;
  font-size: 12px;
  display: flex;
  align-items: baseline;
  gap: 6px;
}
.game-entry .gnum { color: var(--dim); min-width: 50px; }
.game-entry .result-win { font-weight: bold; }
.game-entry .result-draw { color: var(--yellow); font-weight: bold; }

/* Commentary */
.comment-entry { padding: 2px 0; font-size: 11px; }
.comment-entry .reasoning { color: var(--dim); font-style: italic; margin-left: 24px; display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

/* Footer */
#footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 0;
}
#footer .status { font-size: 12px; }
#copy-btn {
  background: var(--surface);
  border: 1px solid var(--border);
  color: var(--text);
  padding: 6px 14px;
  border-radius: 6px;
  cursor: pointer;
  font-family: inherit;
  font-size: 12px;
  transition: background 0.2s;
}
#copy-btn:hover { background: #1f2937; }
#copy-btn .count { background: var(--border); padding: 1px 6px; border-radius: 8px; margin-left: 6px; font-size: 10px; }
#copy-btn.copied { background: var(--green); color: #000; border-color: var(--green); }

/* Final panel */
#final-panel {
  display: none;
  text-align: center;
  padding: 20px;
  border-color: var(--red);
}
#final-panel.show { display: block; }
#final-panel .winner { font-size: 20px; font-weight: bold; }
#final-panel .breakdown { font-size: 14px; margin-top: 6px; }
#final-panel .stats { color: var(--dim); margin-top: 8px; font-size: 12px; }

/* Shot clock */
#shot-clock {
  display: none;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 8px 16px;
  margin-bottom: 10px;
  text-align: center;
}
#shot-clock .clock-label { font-size: 11px; color: var(--dim); text-transform: uppercase; letter-spacing: 1px; }
#shot-clock .clock-display { font-size: 24px; font-weight: bold; font-variant-numeric: tabular-nums; letter-spacing: 1px; margin: 2px 0; }
#shot-clock .clock-display.clock-ok { color: var(--cyan); }
#shot-clock .clock-display.clock-warn { color: var(--yellow); }
#shot-clock .clock-display.clock-danger { color: var(--red); animation: pulse 0.5s infinite; }
#shot-clock .strike-info { font-size: 11px; color: var(--dim); }
</style>
</head>
<body>

<div id="header">
  <span class="badge badge-live" id="badge">LIVE</span>
  <span class="title">CONNECT FOUR</span>
  <span id="matchup"></span>
  <div class="sub" id="sub-info"></div>
</div>

<div id="shot-clock">
  <div class="clock-label" id="clock-label">SHOT CLOCK</div>
  <div class="clock-display clock-ok" id="clock-display">--.-s</div>
  <div class="strike-info" id="strike-info"></div>
</div>

<div id="board-area">
  <div id="board-panel">
    <div id="col-labels"></div>
    <div id="board"></div>
  </div>
  <div id="sidebar">
    <h3>Series Score</h3>
    <div id="scores"></div>
    <h3 style="margin-top:12px">Current Game</h3>
    <div id="game-info"></div>
    <div id="sidebar-stats"></div>
  </div>
</div>

<div class="panel" id="final-panel">
  <h3>Final Result</h3>
  <div id="final-content"></div>
</div>

<div class="panel">
  <h3>Game History</h3>
  <div id="game-history"><span style="color:var(--dim);font-style:italic">No completed games</span></div>
</div>

<div class="panel">
  <h3>Play-by-Play</h3>
  <div id="commentary"><span style="color:var(--dim);font-style:italic">Waiting for action...</span></div>
</div>

<div id="footer">
  <div class="status" id="status-text">
    <span class="badge badge-live" style="font-size:10px">LIVE</span>
    Waiting for data...
  </div>
  <button id="copy-btn" onclick="copyRunlog()">
    Copy Runlog Path <span class="count" id="line-count">0</span>
  </button>
</div>

<script>
// ── Emoji system ─────────────────────────────────────────────────
const EMOJI_POOL = [
  '\u{1F525}','\u{1F9E0}','\u{1F47E}','\u{1F916}','\u{1F3AF}',
  '\u{1F680}','\u{1F40D}','\u{1F98A}','\u{1F43B}','\u{1F985}',
  '\u{1F409}','\u{1F3B2}','\u{1F9CA}','\u{1F30B}','\u{1F308}',
  '\u{1F52E}','\u{1F9F2}','\u{1F41D}','\u{1F95D}','\u{1F344}'
];
function djb2(s) {
  let h = 5381;
  for (let i = 0; i < s.length; i++) h = ((h << 5) + h + s.charCodeAt(i)) >>> 0;
  return h;
}
function pickEmojis(a, b) {
  let ia = djb2(a) % EMOJI_POOL.length;
  let ib = djb2(b) % EMOJI_POOL.length;
  if (ib === ia) ib = (ia + 1) % EMOJI_POOL.length;
  return { player_a: EMOJI_POOL[ia], player_b: EMOJI_POOL[ib] };
}

// ── Match state ──────────────────────────────────────────────────
const ROWS = 6, COLS = 7;
function emptyBoard() {
  return Array.from({length: ROWS}, () => Array(COLS).fill(''));
}

const S = {
  matchId: '', modelA: '', modelB: '',
  board: emptyBoard(),
  seriesScores: { player_a: 0, player_b: 0 },
  gameNumber: 0,
  gameTurn: 0,
  turnCount: 0,
  xPlayer: 'player_a',
  firstPlayer: '',
  lastCol: null,
  lastRow: null,
  previousBoard: emptyBoard(),
  gameHistory: [],
  commentary: [],
  violations: { player_a: 0, player_b: 0 },
  finished: false,
  finalScores: {},
  highlightHands: [],
  emojis: { player_a: '', player_b: '' },
  // Shot clock
  shotClock: { timeLimitMs: null, lastTurnTime: null, strikes: { player_a: 0, player_b: 0 }, strikeLimit: null, waitingOn: '', lastTimeExceeded: false }
};

const rawLines = [];
let turnQueue = [];
let isReplaying = false;

function shortModel(name) {
  if (!name) return name;
  return name.replace(/^anthropic\/claude-/, '').replace(/^anthropic\//, '').replace(/^openai\//, '');
}

function assignEmojis() {
  if (S.modelA && S.modelB && !S.emojis.player_a) {
    S.emojis = pickEmojis(S.modelA, S.modelB);
  }
}

function truncateReasoning(text, max) {
  max = max || 100;
  if (!text) return null;
  const lines = text.trim().split('\n');
  for (const line of lines) {
    const t = line.trim();
    if (t.length > 10) return t.length > max ? t.slice(0, max-3) + '...' : t;
  }
  return null;
}

// ── State machine ────────────────────────────────────────────────
function processTurn(data) {
  if (data.record_type === 'match_summary') {
    S.finished = true;
    S.finalScores = data.final_scores || {};
    S.highlightHands = data.highlight_hands || [];
    const pm = data.player_models || {};
    if (pm.player_a) S.modelA = shortModel(pm.player_a);
    if (pm.player_b) S.modelB = shortModel(pm.player_b);
    assignEmojis();
    return;
  }

  S.turnCount++;
  const snap = data.state_snapshot || {};
  const playerId = data.player_id || '';
  const modelId = data.model_id || '';

  if (!S.matchId) S.matchId = data.match_id || '';
  if (playerId === 'player_a' && !S.modelA) S.modelA = shortModel(modelId);
  else if (playerId === 'player_b' && !S.modelB) S.modelB = shortModel(modelId);
  assignEmojis();
  // Shot clock
  if (data.time_limit_ms) S.shotClock.timeLimitMs = data.time_limit_ms;
  if (data.strike_limit) S.shotClock.strikeLimit = data.strike_limit;
  if (data.cumulative_strikes !== undefined) S.shotClock.strikes[playerId] = data.cumulative_strikes;
  S.shotClock.lastTimeExceeded = !!data.time_exceeded;
  S.shotClock.lastTurnTime = Date.now();
  S.shotClock.waitingOn = playerId === 'player_a' ? 'player_b' : 'player_a';

  const handNum = snap.hand_number || 1;
  const gameTurn = snap.game_turn || 0;

  // Detect new game
  if (handNum !== S.gameNumber) {
    if (S.gameNumber > 0 && snap.result) {
      const already = S.gameHistory.find(g => g.gameNum === S.gameNumber);
      if (!already) {
        S.gameHistory.push({
          gameNum: S.gameNumber,
          result: snap.result,
          xPlayer: S.xPlayer
        });
      }
    }
    S.gameNumber = handNum;
    S.lastCol = null;
    S.lastRow = null;
    S.previousBoard = emptyBoard();
  }

  // Detect X/O assignment from prompt
  const prompt = data.prompt || '';
  if (gameTurn <= 1 && prompt) {
    const xMatch = prompt.match(/You are (X|O)/);
    if (xMatch) {
      if (xMatch[1] === 'X') S.xPlayer = playerId;
      else S.xPlayer = (playerId === 'player_a') ? 'player_b' : 'player_a';
    }
  }

  if (gameTurn === 1) S.firstPlayer = playerId;
  S.gameTurn = gameTurn;

  // Update board from snapshot
  if (snap.board) {
    S.previousBoard = S.board.map(r => [...r]);
    S.board = snap.board.map(r => [...r]);
  }

  // Update series scores
  if (snap.series_scores) {
    S.seriesScores = { ...snap.series_scores };
  }

  // Last move
  S.lastCol = snap.last_column != null ? snap.last_column : null;
  S.lastRow = snap.last_row != null ? snap.last_row : null;

  // Violations
  const violation = data.violation;
  if (violation) S.violations[playerId] = (S.violations[playerId] || 0) + 1;

  // Terminal — record final game result
  if (snap.terminal && snap.result) {
    const already = S.gameHistory.find(g => g.gameNum === S.gameNumber);
    if (!already) {
      S.gameHistory.push({
        gameNum: S.gameNumber,
        result: snap.result,
        xPlayer: S.xPlayer
      });
    }
  }

  // Commentary
  const reasoning = truncateReasoning(data.reasoning_output);
  const parsed = data.parsed_action || {};
  const col = snap.last_column;
  if (gameTurn > 0) {
    S.commentary.push({
      turnNumber: S.turnCount,
      gameNumber: S.gameNumber,
      model: modelId,
      playerId,
      column: col,
      reasoning,
      latencyMs: data.latency_ms || 0,
      isViolation: !!violation
    });
    if (S.commentary.length > 12) S.commentary.shift();
  }
}

// ── Win detection (for highlighting) ─────────────────────────────
function findWinCells(board) {
  const cells = [];
  // Horizontal
  for (let r = 0; r < ROWS; r++) {
    for (let c = 0; c <= COLS - 4; c++) {
      const v = board[r][c];
      if (v && v === board[r][c+1] && v === board[r][c+2] && v === board[r][c+3]) {
        cells.push([r,c],[r,c+1],[r,c+2],[r,c+3]);
      }
    }
  }
  // Vertical
  for (let r = 0; r <= ROWS - 4; r++) {
    for (let c = 0; c < COLS; c++) {
      const v = board[r][c];
      if (v && v === board[r+1][c] && v === board[r+2][c] && v === board[r+3][c]) {
        cells.push([r,c],[r+1,c],[r+2,c],[r+3,c]);
      }
    }
  }
  // Diagonal down-right
  for (let r = 0; r <= ROWS - 4; r++) {
    for (let c = 0; c <= COLS - 4; c++) {
      const v = board[r][c];
      if (v && v === board[r+1][c+1] && v === board[r+2][c+2] && v === board[r+3][c+3]) {
        cells.push([r,c],[r+1,c+1],[r+2,c+2],[r+3,c+3]);
      }
    }
  }
  // Diagonal up-right
  for (let r = 3; r < ROWS; r++) {
    for (let c = 0; c <= COLS - 4; c++) {
      const v = board[r][c];
      if (v && v === board[r-1][c+1] && v === board[r-2][c+2] && v === board[r-3][c+3]) {
        cells.push([r,c],[r-1,c+1],[r-2,c+2],[r-3,c+3]);
      }
    }
  }
  return cells;
}

// ── Rendering ────────────────────────────────────────────────────
function renderBoard() {
  // Column labels
  const labels = document.getElementById('col-labels');
  labels.innerHTML = '';
  for (let c = 0; c < COLS; c++) {
    const d = document.createElement('div');
    d.textContent = c;
    if (S.lastCol === c) d.style.color = 'var(--green)';
    labels.appendChild(d);
  }

  const el = document.getElementById('board');
  el.innerHTML = '';
  const winCells = findWinCells(S.board);
  const winSet = new Set(winCells.map(([r,c]) => r+','+c));

  for (let r = 0; r < ROWS; r++) {
    for (let c = 0; c < COLS; c++) {
      const div = document.createElement('div');
      div.className = 'cell';
      const v = S.board[r][c];
      if (v === 'X') {
        div.className += ' x-piece';
      } else if (v === 'O') {
        div.className += ' o-piece';
      }
      // Last move highlight
      if (S.lastRow === r && S.lastCol === c) {
        div.className += ' last-move';
      }
      // Win highlight
      if (winSet.has(r+','+c)) {
        div.className += ' win-cell';
      }
      // Drop animation for new pieces
      if (v && S.previousBoard[r][c] !== v) {
        div.className += ' fresh';
      }
      el.appendChild(div);
    }
  }
}

function renderHeader() {
  const badge = document.getElementById('badge');
  badge.textContent = S.finished ? 'FINAL' : 'LIVE';
  badge.className = 'badge ' + (S.finished ? 'badge-final' : 'badge-live');

  const ea = S.emojis.player_a || '';
  const eb = S.emojis.player_b || '';
  document.getElementById('matchup').innerHTML =
    `<span class="player-a">${ea} ${S.modelA || '???'}</span>` +
    ` <span style="color:var(--dim)">vs</span> ` +
    `<span class="player-b">${eb} ${S.modelB || '???'}</span>`;

  const sa = S.finished ? (S.finalScores.player_a ?? S.seriesScores.player_a) : S.seriesScores.player_a;
  const sb = S.finished ? (S.finalScores.player_b ?? S.seriesScores.player_b) : S.seriesScores.player_b;
  document.getElementById('sub-info').innerHTML =
    `<strong>Game ${S.gameNumber}</strong>` +
    ` <span style="color:var(--dim)">|</span> ` +
    `<span class="player-a" style="font-weight:bold">${sa}</span>` +
    ` <span style="color:var(--dim)">\u2013</span> ` +
    `<span class="player-b" style="font-weight:bold">${sb}</span>` +
    ` <span style="color:var(--dim)">|</span> ` +
    `<span style="color:var(--dim)">Move ${S.gameTurn}</span>`;
}

function renderSidebar() {
  const sa = S.finished ? (S.finalScores.player_a ?? S.seriesScores.player_a) : S.seriesScores.player_a;
  const sb = S.finished ? (S.finalScores.player_b ?? S.seriesScores.player_b) : S.seriesScores.player_b;
  const maxScore = Math.max(sa, sb, 1);

  const ea = S.emojis.player_a || '';
  const eb = S.emojis.player_b || '';
  const nameA = (S.modelA || 'Player A').slice(0, 18);
  const nameB = (S.modelB || 'Player B').slice(0, 18);

  const pctA = Math.max(0, Math.min(100, (sa / maxScore) * 100));
  const pctB = Math.max(0, Math.min(100, (sb / maxScore) * 100));

  document.getElementById('scores').innerHTML =
    `<div class="score-row">
      <div class="name player-a">${ea} ${nameA}</div>
      <div class="score-bar" style="width:${pctA}%;background:var(--piece-x)">&nbsp;</div>
      <div style="color:var(--piece-x);font-weight:bold">${sa}</div>
    </div>
    <div class="score-row">
      <div class="name player-b">${eb} ${nameB}</div>
      <div class="score-bar" style="width:${pctB}%;background:var(--piece-o)">&nbsp;</div>
      <div style="color:var(--piece-o);font-weight:bold">${sb}</div>
    </div>`;

  // Current game info
  const xName = S.xPlayer === 'player_a' ? nameA : nameB;
  const oName = S.xPlayer === 'player_a' ? nameB : nameA;

  let gameInfo = '';
  if (S.gameNumber > 0) {
    gameInfo = `<div class="game-assignment"><span style="color:var(--piece-x);font-weight:bold">\u25CF X</span> = ${xName} (Yellow)</div>` +
               `<div class="game-assignment"><span style="color:var(--piece-o);font-weight:bold">\u25CF O</span> = ${oName} (Red)</div>` +
               `<div class="stat-line" style="margin-top:6px">Move ${S.gameTurn} of game ${S.gameNumber}</div>`;
  }
  document.getElementById('game-info').innerHTML = gameInfo;

  // Stats
  let stats = '';
  const va = S.violations.player_a || 0;
  const vb = S.violations.player_b || 0;
  if (va + vb > 0) stats += `<div class="stat-line violations" style="margin-top:8px">Violations: A:${va} B:${vb}</div>`;
  document.getElementById('sidebar-stats').innerHTML = stats;
}

function renderGameHistory() {
  const el = document.getElementById('game-history');
  if (!S.gameHistory.length) {
    el.innerHTML = '<span style="color:var(--dim);font-style:italic">No completed games</span>';
    return;
  }
  const nameA = S.modelA || 'Player A';
  const nameB = S.modelB || 'Player B';
  el.innerHTML = S.gameHistory.map(g => {
    let resultHTML;
    if (g.result === 'x_wins') {
      const winPid = g.xPlayer;
      const winName = winPid === 'player_a' ? nameA : nameB;
      const color = winPid === 'player_a' ? 'var(--piece-x)' : 'var(--piece-o)';
      resultHTML = `<span class="result-win" style="color:${color}">X wins</span> <span style="color:var(--dim)">(${winName})</span>`;
    } else if (g.result === 'o_wins') {
      const winPid = g.xPlayer === 'player_a' ? 'player_b' : 'player_a';
      const winName = winPid === 'player_a' ? nameA : nameB;
      const color = winPid === 'player_a' ? 'var(--piece-x)' : 'var(--piece-o)';
      resultHTML = `<span class="result-win" style="color:${color}">O wins</span> <span style="color:var(--dim)">(${winName})</span>`;
    } else {
      resultHTML = `<span class="result-draw">Draw</span>`;
    }
    const hl = S.highlightHands.includes(g.gameNum) ? '<span style="color:var(--yellow)">\u2605 </span>' : '  ';
    return `<div class="game-entry">${hl}<span class="gnum">Game ${g.gameNum}</span>${resultHTML}</div>`;
  }).join('');
}

function renderCommentary() {
  const el = document.getElementById('commentary');
  if (!S.commentary.length) {
    el.innerHTML = '<span style="color:var(--dim);font-style:italic">Waiting for action...</span>';
    return;
  }
  el.innerHTML = [...S.commentary].reverse().map(e => {
    const color = e.playerId === 'player_a' ? 'var(--piece-x)' : 'var(--piece-o)';
    const mark = e.playerId === S.xPlayer ? 'X' : 'O';
    let actionHTML;
    if (e.isViolation) {
      actionHTML = `<span style="color:var(--red);font-weight:bold">violation!</span>`;
    } else if (e.column != null) {
      actionHTML = `<span style="color:var(--green)">${mark}</span> \u2192 col <span style="font-weight:bold">${e.column}</span>`;
    } else {
      actionHTML = `<span style="color:var(--dim)">...</span>`;
    }
    const latency = e.latencyMs > 100 ? ` <span style="color:var(--dim)">(${(e.latencyMs/1000).toFixed(1)}s)</span>` : '';
    const reason = e.reasoning ? `<span class="reasoning">"${e.reasoning}"</span>` : '';
    return `<div class="comment-entry"><span style="color:var(--dim)">G${e.gameNumber} T${e.turnNumber}</span> <span style="color:${color};font-weight:bold">${e.model}</span> ${actionHTML}${latency}${reason}</div>`;
  }).join('');
}

function renderFinal() {
  if (!S.finished) { document.getElementById('final-panel').className = 'panel'; return; }
  document.getElementById('final-panel').className = 'panel show';
  const sa = S.finalScores.player_a || 0;
  const sb = S.finalScores.player_b || 0;

  let wA = 0, wB = 0, draws = 0;
  S.gameHistory.forEach(g => {
    if (g.result === 'draw') { draws++; return; }
    const xWins = g.result === 'x_wins';
    const winPid = xWins ? g.xPlayer : (g.xPlayer === 'player_a' ? 'player_b' : 'player_a');
    if (winPid === 'player_a') wA++;
    else wB++;
  });

  let html;
  if (sa === sb) {
    html = `<div class="winner" style="color:var(--yellow)">DRAW</div><div class="breakdown">${sa} each</div>`;
  } else {
    const wPid = sa > sb ? 'player_a' : 'player_b';
    const emoji = S.emojis[wPid] || '';
    const wName = wPid === 'player_a' ? S.modelA : S.modelB;
    const wColor = wPid === 'player_a' ? 'var(--piece-x)' : 'var(--piece-o)';
    html = `<div class="winner" style="color:${wColor}">${emoji} ${wName} WINS</div>` +
           `<div class="breakdown">${sa} \u2013 ${sb}</div>`;
  }
  const nameA = S.modelA || 'A';
  const nameB = S.modelB || 'B';
  html += `<div class="stats">${nameA}: ${wA}W ${draws}D ${wB}L &nbsp;\u00B7&nbsp; ${nameB}: ${wB}W ${draws}D ${wA}L</div>`;
  const va = S.violations.player_a || 0, vb = S.violations.player_b || 0;
  if (va + vb > 0) html += `<div class="stats" style="color:var(--red)">Violations: A:${va} B:${vb}</div>`;
  document.getElementById('final-content').innerHTML = html;
}

function renderFooter() {
  const st = document.getElementById('status-text');
  if (S.finished) {
    st.innerHTML = '<span class="badge badge-final" style="font-size:10px">FINAL</span> Series Complete';
  } else {
    st.innerHTML = '<span class="badge badge-live" style="font-size:10px">LIVE</span> Watching...';
  }
  document.getElementById('line-count').textContent = rawLines.length;
}

function renderShotClock() {
  var el = document.getElementById('shot-clock');
  if (!S.shotClock.timeLimitMs || S.finished) { el.style.display = 'none'; return; }
  el.style.display = 'block';
  var display = document.getElementById('clock-display');
  var label = document.getElementById('clock-label');
  var strikeEl = document.getElementById('strike-info');
  if (!S.finished && !isReplaying && S.shotClock.lastTurnTime) {
    var elapsed = Date.now() - S.shotClock.lastTurnTime;
    var remaining = Math.max(0, S.shotClock.timeLimitMs - elapsed);
    var secs = remaining / 1000;
    display.textContent = secs.toFixed(1) + 's';
    var pct = remaining / S.shotClock.timeLimitMs;
    display.className = 'clock-display ' + (pct <= 0 ? 'clock-danger' : pct < 0.2 ? 'clock-danger' : pct < 0.5 ? 'clock-warn' : 'clock-ok');
  } else {
    display.textContent = (S.shotClock.timeLimitMs / 1000).toFixed(1) + 's';
    display.className = 'clock-display clock-ok';
  }
  var wModel = S.shotClock.waitingOn === 'player_a' ? (S.modelA || 'A') : (S.modelB || 'B');
  label.textContent = S.finished ? 'SHOT CLOCK' : 'SHOT CLOCK \u00b7 ' + wModel;
  if (S.shotClock.strikeLimit) {
    var sA = S.shotClock.strikes.player_a || 0;
    var sB = S.shotClock.strikes.player_b || 0;
    var nA = S.modelA || 'A', nB = S.modelB || 'B';
    strikeEl.innerHTML = '<span class="player-a">' + nA + ': ' + sA + '/' + S.shotClock.strikeLimit + '</span> \u00b7 <span class="player-b">' + nB + ': ' + sB + '/' + S.shotClock.strikeLimit + '</span>';
  } else { strikeEl.innerHTML = ''; }
}

function renderAll() {
  renderHeader();
  renderShotClock();
  renderBoard();
  renderSidebar();
  renderGameHistory();
  renderCommentary();
  renderFinal();
  renderFooter();
}

// ── Copy runlog ──────────────────────────────────────────────────
function copyRunlog() {
  const btn = document.getElementById('copy-btn');
  fetch('/filepath').then(r => r.text()).then(function(fp) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(fp).then(function() {
        btn.classList.add('copied');
        btn.textContent = 'Copied path!';
        setTimeout(function() {
          btn.classList.remove('copied');
          btn.innerHTML = 'Copy Runlog Path <span class="count">' + rawLines.length + '</span>';
        }, 2000);
      });
    } else {
      const ta = document.createElement('textarea');
      ta.value = fp;
      ta.style.position = 'fixed';
      ta.style.left = '-9999px';
      document.body.appendChild(ta);
      ta.select();
      document.execCommand('copy');
      document.body.removeChild(ta);
      btn.classList.add('copied');
      btn.textContent = 'Copied path!';
      setTimeout(function() {
        btn.classList.remove('copied');
        btn.innerHTML = 'Copy Runlog Path <span class="count">' + rawLines.length + '</span>';
      }, 2000);
    }
  });
}

// ── SSE client ───────────────────────────────────────────────────
function startSSE() {
  const es = new EventSource('/events');
  es.onmessage = function(e) {
    const line = e.data;
    rawLines.push(line);
    try {
      const data = JSON.parse(line);
      if (isReplaying) {
        turnQueue.push(data);
      } else {
        processTurn(data);
        renderAll();
      }
    } catch(err) {}
    document.getElementById('line-count').textContent = rawLines.length;
  };
  es.addEventListener('done', function() {
    es.close();
  });
  es.onerror = function() {};
}

function drainQueue() {
  if (!turnQueue.length) {
    isReplaying = false;
    renderAll();
    return;
  }
  const data = turnQueue.shift();
  processTurn(data);
  renderAll();
  const delay = data.record_type === 'match_summary' ? 200 : 50;
  setTimeout(drainQueue, delay);
}

// Init
renderBoard();
renderAll();

isReplaying = true;
turnQueue = [];
startSSE();

setTimeout(() => {
  if (turnQueue.length > 0) {
    drainQueue();
  } else {
    isReplaying = false;
  }
}, 300);
// Shot clock countdown
setInterval(function() {
  if (S.shotClock.timeLimitMs && !S.finished && !isReplaying) renderShotClock();
}, 100);

</script>
</body>
</html>"""


# ── Reversi HTML/CSS/JS ─────────────────────────────────────────

REVERSI_HTML_PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Reversi Spectator</title>
<style>
:root {
  --bg: #0d1117;
  --surface: #161b22;
  --border: #30363d;
  --text: #e6edf3;
  --dim: #7d8590;
  --cyan: #58a6ff;
  --magenta: #d2a8ff;
  --green: #3fb950;
  --red: #f85149;
  --yellow: #d29922;
  --piece-b: #222;
  --piece-w: #f0f0f0;
}
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
  background: var(--bg);
  color: var(--text);
  font-family: 'SF Mono', 'Cascadia Code', 'Fira Code', 'Consolas', monospace;
  font-size: 13px;
  line-height: 1.4;
  padding: 12px;
  max-width: 960px;
  margin: 0 auto;
}

/* Header */
#header {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 12px 16px;
  margin-bottom: 10px;
  text-align: center;
}
#header .badge {
  display: inline-block;
  padding: 2px 10px;
  border-radius: 4px;
  font-weight: bold;
  font-size: 12px;
  margin-right: 8px;
  vertical-align: middle;
}
.badge-live { background: var(--green); color: #000; animation: pulse 2s infinite; }
.badge-final { background: var(--red); color: #fff; }
@keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.6; } }
#header .title { font-size: 16px; font-weight: bold; }
.player-a { color: var(--cyan); }
.player-b { color: var(--magenta); }
#header .sub { margin-top: 4px; color: var(--dim); }

/* Board + Sidebar layout */
#board-area {
  display: flex;
  gap: 12px;
  margin-bottom: 10px;
}
#board-panel {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 16px;
  flex-shrink: 0;
}

/* Column labels (a-h) */
#col-labels {
  display: grid;
  grid-template-columns: 24px repeat(8, 44px);
  gap: 2px;
  margin-bottom: 2px;
  text-align: center;
  color: var(--dim);
  font-size: 12px;
  font-weight: bold;
}

/* Board grid */
#board-wrap {
  display: flex;
}
#row-labels {
  display: flex;
  flex-direction: column;
  gap: 2px;
  justify-content: center;
  width: 24px;
  text-align: center;
  color: var(--dim);
  font-size: 12px;
  font-weight: bold;
}
#row-labels div { height: 44px; line-height: 44px; }

#board {
  display: grid;
  grid-template-columns: repeat(8, 44px);
  grid-template-rows: repeat(8, 44px);
  gap: 2px;
  background: #2d6a2d;
  padding: 4px;
  border-radius: 6px;
}
#board .cell {
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 4px;
  background: #3a8a3a;
  transition: background 0.2s, box-shadow 0.2s;
}
#board .cell.b-piece {
  background: #3a8a3a;
}
#board .cell.b-piece::after {
  content: '';
  width: 36px;
  height: 36px;
  border-radius: 50%;
  background: var(--piece-b);
  box-shadow: inset 0 -3px 6px rgba(0,0,0,0.5), 0 1px 3px rgba(0,0,0,0.4);
}
#board .cell.w-piece {
  background: #3a8a3a;
}
#board .cell.w-piece::after {
  content: '';
  width: 36px;
  height: 36px;
  border-radius: 50%;
  background: var(--piece-w);
  box-shadow: inset 0 -3px 6px rgba(0,0,0,0.15), 0 1px 3px rgba(0,0,0,0.3);
}
#board .cell.last-move {
  box-shadow: inset 0 0 0 3px var(--green);
}
#board .cell.flipped::after {
  animation: flip 0.4s ease-in-out;
}
@keyframes flip {
  0% { transform: scale(1); }
  50% { transform: scale(0.1); }
  100% { transform: scale(1); }
}

/* Sidebar */
#sidebar {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 12px;
  flex: 1;
  min-width: 220px;
}
#sidebar h3 {
  font-size: 11px;
  text-transform: uppercase;
  color: var(--dim);
  border-bottom: 1px solid var(--border);
  padding-bottom: 4px;
  margin-bottom: 8px;
}
.score-row { margin-bottom: 8px; }
.score-row .name { font-weight: bold; font-size: 12px; }
.score-bar {
  height: 10px;
  border-radius: 3px;
  margin-top: 2px;
  transition: width 0.5s ease;
}
.stat-line { color: var(--dim); font-size: 11px; margin: 3px 0; }
.stat-line.violations { color: var(--red); }
.game-assignment { font-size: 11px; margin: 2px 0; }
.piece-counts { font-size: 12px; margin: 8px 0; padding: 6px 8px; background: var(--bg); border-radius: 4px; }

/* Panels */
.panel {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px 14px;
  margin-bottom: 10px;
}
.panel h3 {
  font-size: 11px;
  text-transform: uppercase;
  color: var(--dim);
  border-bottom: 1px solid var(--border);
  padding-bottom: 4px;
  margin-bottom: 6px;
}

/* Game history */
.game-entry {
  padding: 3px 0;
  font-size: 12px;
  display: flex;
  align-items: baseline;
  gap: 6px;
}
.game-entry .gnum { color: var(--dim); min-width: 50px; }
.game-entry .result-win { font-weight: bold; }
.game-entry .result-draw { color: var(--yellow); font-weight: bold; }

/* Commentary */
.comment-entry { padding: 2px 0; font-size: 11px; }
.comment-entry .reasoning { color: var(--dim); font-style: italic; margin-left: 24px; display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

/* Footer */
#footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 0;
}
#footer .status { font-size: 12px; }
#copy-btn {
  background: var(--surface);
  border: 1px solid var(--border);
  color: var(--text);
  padding: 6px 14px;
  border-radius: 6px;
  cursor: pointer;
  font-family: inherit;
  font-size: 12px;
  transition: background 0.2s;
}
#copy-btn:hover { background: #1f2937; }
#copy-btn .count { background: var(--border); padding: 1px 6px; border-radius: 8px; margin-left: 6px; font-size: 10px; }
#copy-btn.copied { background: var(--green); color: #000; border-color: var(--green); }

/* Final panel */
#final-panel {
  display: none;
  text-align: center;
  padding: 20px;
  border-color: var(--red);
}
#final-panel.show { display: block; }
#final-panel .winner { font-size: 20px; font-weight: bold; }
#final-panel .breakdown { font-size: 14px; margin-top: 6px; }
#final-panel .stats { color: var(--dim); margin-top: 8px; font-size: 12px; }

/* Shot clock */
#shot-clock {
  display: none;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 8px 16px;
  margin-bottom: 10px;
  text-align: center;
}
#shot-clock .clock-label { font-size: 11px; color: var(--dim); text-transform: uppercase; letter-spacing: 1px; }
#shot-clock .clock-display { font-size: 24px; font-weight: bold; font-variant-numeric: tabular-nums; letter-spacing: 1px; margin: 2px 0; }
#shot-clock .clock-display.clock-ok { color: var(--cyan); }
#shot-clock .clock-display.clock-warn { color: var(--yellow); }
#shot-clock .clock-display.clock-danger { color: var(--red); animation: pulse 0.5s infinite; }
#shot-clock .strike-info { font-size: 11px; color: var(--dim); }
</style>
</head>
<body>

<div id="header">
  <span class="badge badge-live" id="badge">LIVE</span>
  <span class="title">REVERSI</span>
  <span id="matchup"></span>
  <div class="sub" id="sub-info"></div>
</div>

<div id="shot-clock">
  <div class="clock-label" id="clock-label">SHOT CLOCK</div>
  <div class="clock-display clock-ok" id="clock-display">--.-s</div>
  <div class="strike-info" id="strike-info"></div>
</div>

<div id="board-area">
  <div id="board-panel">
    <div id="col-labels"></div>
    <div id="board-wrap">
      <div id="row-labels"></div>
      <div id="board"></div>
    </div>
  </div>
  <div id="sidebar">
    <h3>Series Score</h3>
    <div id="scores"></div>
    <h3 style="margin-top:12px">Current Game</h3>
    <div id="game-info"></div>
    <div id="sidebar-stats"></div>
  </div>
</div>

<div class="panel" id="final-panel">
  <h3>Final Result</h3>
  <div id="final-content"></div>
</div>

<div class="panel">
  <h3>Game History</h3>
  <div id="game-history"><span style="color:var(--dim);font-style:italic">No completed games</span></div>
</div>

<div class="panel">
  <h3>Play-by-Play</h3>
  <div id="commentary"><span style="color:var(--dim);font-style:italic">Waiting for action...</span></div>
</div>

<div id="footer">
  <div class="status" id="status-text">
    <span class="badge badge-live" style="font-size:10px">LIVE</span>
    Waiting for data...
  </div>
  <button id="copy-btn" onclick="copyRunlog()">
    Copy Runlog Path <span class="count" id="line-count">0</span>
  </button>
</div>

<script>
// ── Emoji system ─────────────────────────────────────────────────
var EMOJI_POOL = [
  '\u{1F525}','\u{1F9E0}','\u{1F47E}','\u{1F916}','\u{1F3AF}',
  '\u{1F680}','\u{1F40D}','\u{1F98A}','\u{1F43B}','\u{1F985}',
  '\u{1F409}','\u{1F3B2}','\u{1F9CA}','\u{1F30B}','\u{1F308}',
  '\u{1F52E}','\u{1F9F2}','\u{1F41D}','\u{1F95D}','\u{1F344}'
];
function djb2(s) {
  var h = 5381;
  for (var i = 0; i < s.length; i++) h = ((h << 5) + h + s.charCodeAt(i)) >>> 0;
  return h;
}
function pickEmojis(a, b) {
  var ia = djb2(a) % EMOJI_POOL.length;
  var ib = djb2(b) % EMOJI_POOL.length;
  if (ib === ia) ib = (ia + 1) % EMOJI_POOL.length;
  return { player_a: EMOJI_POOL[ia], player_b: EMOJI_POOL[ib] };
}

// ── Match state ──────────────────────────────────────────────────
var ROWS = 8, COLS = 8;
var COL_LETTERS = 'abcdefgh';
function emptyBoard() {
  return Array.from({length: ROWS}, function() { return Array(COLS).fill(''); });
}

var S = {
  matchId: '', modelA: '', modelB: '',
  board: emptyBoard(),
  seriesScores: { player_a: 0, player_b: 0 },
  gameNumber: 0,
  gameTurn: 0,
  turnCount: 0,
  colorMap: {},
  pieceCounts: { B: 0, W: 0 },
  lastPosition: null,
  lastFlipped: [],
  previousBoard: emptyBoard(),
  gameHistory: [],
  commentary: [],
  violations: { player_a: 0, player_b: 0 },
  finished: false,
  finalScores: {},
  highlightHands: [],
  emojis: { player_a: '', player_b: '' },
  shotClock: { timeLimitMs: null, lastTurnTime: null, strikes: { player_a: 0, player_b: 0 }, strikeLimit: null, waitingOn: '', lastTimeExceeded: false }
};

var rawLines = [];
var turnQueue = [];
var isReplaying = false;

function shortModel(name) {
  if (!name) return name;
  return name.replace(/^anthropic\/claude-/, '').replace(/^anthropic\//, '').replace(/^openai\//, '');
}

function assignEmojis() {
  if (S.modelA && S.modelB && !S.emojis.player_a) {
    S.emojis = pickEmojis(S.modelA, S.modelB);
  }
}

function truncateReasoning(text, max) {
  max = max || 100;
  if (!text) return null;
  var lines = text.trim().split('\n');
  for (var i = 0; i < lines.length; i++) {
    var t = lines[i].trim();
    if (t.length > 10) return t.length > max ? t.slice(0, max-3) + '...' : t;
  }
  return null;
}

// ── State machine ────────────────────────────────────────────────
function processTurn(data) {
  if (data.record_type === 'match_summary') {
    S.finished = true;
    S.finalScores = data.final_scores || {};
    S.highlightHands = data.highlight_hands || [];
    var pm = data.player_models || {};
    if (pm.player_a) S.modelA = shortModel(pm.player_a);
    if (pm.player_b) S.modelB = shortModel(pm.player_b);
    assignEmojis();
    return;
  }

  S.turnCount++;
  var snap = data.state_snapshot || {};
  var playerId = data.player_id || '';
  var modelId = data.model_id || '';

  if (!S.matchId) S.matchId = data.match_id || '';
  if (playerId === 'player_a' && !S.modelA) S.modelA = shortModel(modelId);
  else if (playerId === 'player_b' && !S.modelB) S.modelB = shortModel(modelId);
  assignEmojis();

  // Shot clock
  if (data.time_limit_ms) S.shotClock.timeLimitMs = data.time_limit_ms;
  if (data.strike_limit) S.shotClock.strikeLimit = data.strike_limit;
  if (data.cumulative_strikes !== undefined) S.shotClock.strikes[playerId] = data.cumulative_strikes;
  S.shotClock.lastTimeExceeded = !!data.time_exceeded;
  S.shotClock.lastTurnTime = Date.now();
  S.shotClock.waitingOn = playerId === 'player_a' ? 'player_b' : 'player_a';

  var handNum = snap.hand_number || 1;
  var gameTurn = snap.game_turn || 0;

  // Detect new game
  if (handNum !== S.gameNumber) {
    if (S.gameNumber > 0 && snap.result) {
      var already = S.gameHistory.find(function(g) { return g.gameNum === S.gameNumber; });
      if (!already) {
        S.gameHistory.push({
          gameNum: S.gameNumber,
          result: snap.result,
          colorMap: Object.assign({}, S.colorMap)
        });
      }
    }
    S.gameNumber = handNum;
    S.lastPosition = null;
    S.lastFlipped = [];
    S.previousBoard = emptyBoard();
  }

  // Color map from snapshot
  if (snap.color_map) {
    S.colorMap = Object.assign({}, snap.color_map);
  }

  // Piece counts
  if (snap.piece_counts) {
    S.pieceCounts = Object.assign({}, snap.piece_counts);
  }

  S.gameTurn = gameTurn;

  // Update board from snapshot
  if (snap.board) {
    S.previousBoard = S.board.map(function(r) { return r.slice(); });
    S.board = snap.board.map(function(r) { return r.slice(); });
  }

  // Update series scores
  if (snap.series_scores) {
    S.seriesScores = Object.assign({}, snap.series_scores);
  }

  // Last move position
  S.lastPosition = snap.last_position || null;
  S.lastFlipped = snap.last_flipped || [];

  // Violations
  var violation = data.violation;
  if (violation) S.violations[playerId] = (S.violations[playerId] || 0) + 1;

  // Terminal — record final game result
  if (snap.terminal && snap.result) {
    var already2 = S.gameHistory.find(function(g) { return g.gameNum === S.gameNumber; });
    if (!already2) {
      S.gameHistory.push({
        gameNum: S.gameNumber,
        result: snap.result,
        colorMap: Object.assign({}, S.colorMap)
      });
    }
  }

  // Commentary
  var reasoning = truncateReasoning(data.reasoning_output);
  if (gameTurn > 0) {
    var pos = S.lastPosition;
    var flippedCount = S.lastFlipped.length;
    S.commentary.push({
      turnNumber: S.turnCount,
      gameNumber: S.gameNumber,
      model: modelId,
      playerId: playerId,
      position: pos,
      flippedCount: flippedCount,
      reasoning: reasoning,
      latencyMs: data.latency_ms || 0,
      isViolation: !!violation
    });
    if (S.commentary.length > 12) S.commentary.shift();
  }
}

// ── Rendering ────────────────────────────────────────────────────
function renderBoard() {
  // Column labels (a-h)
  var labels = document.getElementById('col-labels');
  labels.innerHTML = '<div></div>';
  for (var c = 0; c < COLS; c++) {
    var d = document.createElement('div');
    d.textContent = COL_LETTERS[c];
    if (S.lastPosition && S.lastPosition[1] === c) d.style.color = 'var(--green)';
    labels.appendChild(d);
  }

  // Row labels (1-8)
  var rowLabels = document.getElementById('row-labels');
  rowLabels.innerHTML = '';
  for (var r = 0; r < ROWS; r++) {
    var d = document.createElement('div');
    d.textContent = r + 1;
    if (S.lastPosition && S.lastPosition[0] === r) d.style.color = 'var(--green)';
    rowLabels.appendChild(d);
  }

  var el = document.getElementById('board');
  el.innerHTML = '';
  var flippedSet = {};
  for (var i = 0; i < S.lastFlipped.length; i++) {
    flippedSet[S.lastFlipped[i][0] + ',' + S.lastFlipped[i][1]] = true;
  }

  for (var r = 0; r < ROWS; r++) {
    for (var c = 0; c < COLS; c++) {
      var div = document.createElement('div');
      div.className = 'cell';
      var v = S.board[r][c];
      if (v === 'B') {
        div.className += ' b-piece';
      } else if (v === 'W') {
        div.className += ' w-piece';
      }
      // Last move highlight
      if (S.lastPosition && S.lastPosition[0] === r && S.lastPosition[1] === c) {
        div.className += ' last-move';
      }
      // Flip animation for newly captured pieces
      if (v && flippedSet[r + ',' + c] && S.previousBoard[r][c] !== v) {
        div.className += ' flipped';
      }
      el.appendChild(div);
    }
  }
}

function renderHeader() {
  var badge = document.getElementById('badge');
  badge.textContent = S.finished ? 'FINAL' : 'LIVE';
  badge.className = 'badge ' + (S.finished ? 'badge-final' : 'badge-live');

  var ea = S.emojis.player_a || '';
  var eb = S.emojis.player_b || '';
  document.getElementById('matchup').innerHTML =
    '<span class="player-a">' + ea + ' ' + (S.modelA || '???') + '</span>' +
    ' <span style="color:var(--dim)">vs</span> ' +
    '<span class="player-b">' + eb + ' ' + (S.modelB || '???') + '</span>';

  var sa = S.finished ? (S.finalScores.player_a != null ? S.finalScores.player_a : S.seriesScores.player_a) : S.seriesScores.player_a;
  var sb = S.finished ? (S.finalScores.player_b != null ? S.finalScores.player_b : S.seriesScores.player_b) : S.seriesScores.player_b;
  document.getElementById('sub-info').innerHTML =
    '<strong>Game ' + S.gameNumber + '</strong>' +
    ' <span style="color:var(--dim)">|</span> ' +
    '<span class="player-a" style="font-weight:bold">' + sa + '</span>' +
    ' <span style="color:var(--dim)">\u2013</span> ' +
    '<span class="player-b" style="font-weight:bold">' + sb + '</span>' +
    ' <span style="color:var(--dim)">|</span> ' +
    '<span style="color:var(--dim)">Move ' + S.gameTurn + '</span>';
}

function renderSidebar() {
  var sa = S.finished ? (S.finalScores.player_a != null ? S.finalScores.player_a : S.seriesScores.player_a) : S.seriesScores.player_a;
  var sb = S.finished ? (S.finalScores.player_b != null ? S.finalScores.player_b : S.seriesScores.player_b) : S.seriesScores.player_b;
  var maxScore = Math.max(sa, sb, 1);

  var ea = S.emojis.player_a || '';
  var eb = S.emojis.player_b || '';
  var nameA = (S.modelA || 'Player A').slice(0, 18);
  var nameB = (S.modelB || 'Player B').slice(0, 18);

  var pctA = Math.max(0, Math.min(100, (sa / maxScore) * 100));
  var pctB = Math.max(0, Math.min(100, (sb / maxScore) * 100));

  document.getElementById('scores').innerHTML =
    '<div class="score-row">' +
      '<div class="name player-a">' + ea + ' ' + nameA + '</div>' +
      '<div class="score-bar" style="width:' + pctA + '%;background:var(--cyan)">&nbsp;</div>' +
      '<div style="color:var(--cyan);font-weight:bold">' + sa + '</div>' +
    '</div>' +
    '<div class="score-row">' +
      '<div class="name player-b">' + eb + ' ' + nameB + '</div>' +
      '<div class="score-bar" style="width:' + pctB + '%;background:var(--magenta)">&nbsp;</div>' +
      '<div style="color:var(--magenta);font-weight:bold">' + sb + '</div>' +
    '</div>';

  // Current game info + piece counts
  var gameInfo = '';
  if (S.gameNumber > 0) {
    var bPlayer = '', wPlayer = '';
    if (S.colorMap.player_a === 'B') { bPlayer = nameA; wPlayer = nameB; }
    else { bPlayer = nameB; wPlayer = nameA; }

    gameInfo = '<div class="game-assignment"><span style="font-weight:bold">\u26AB Black</span> = ' + bPlayer + '</div>' +
               '<div class="game-assignment"><span style="font-weight:bold">\u26AA White</span> = ' + wPlayer + '</div>' +
               '<div class="piece-counts">\u26AB Black: <strong>' + S.pieceCounts.B + '</strong> &nbsp;\u00B7&nbsp; \u26AA White: <strong>' + S.pieceCounts.W + '</strong></div>' +
               '<div class="stat-line" style="margin-top:6px">Move ' + S.gameTurn + ' of game ' + S.gameNumber + '</div>';
  }
  document.getElementById('game-info').innerHTML = gameInfo;

  // Stats
  var stats = '';
  var va = S.violations.player_a || 0;
  var vb = S.violations.player_b || 0;
  if (va + vb > 0) stats += '<div class="stat-line violations" style="margin-top:8px">Violations: A:' + va + ' B:' + vb + '</div>';
  document.getElementById('sidebar-stats').innerHTML = stats;
}

function renderGameHistory() {
  var el = document.getElementById('game-history');
  if (!S.gameHistory.length) {
    el.innerHTML = '<span style="color:var(--dim);font-style:italic">No completed games</span>';
    return;
  }
  var nameA = S.modelA || 'Player A';
  var nameB = S.modelB || 'Player B';
  el.innerHTML = S.gameHistory.map(function(g) {
    var resultHTML;
    if (g.result === 'b_wins') {
      var cm = g.colorMap || {};
      var winPid = cm.player_a === 'B' ? 'player_a' : 'player_b';
      var winName = winPid === 'player_a' ? nameA : nameB;
      var color = winPid === 'player_a' ? 'var(--cyan)' : 'var(--magenta)';
      resultHTML = '<span class="result-win" style="color:' + color + '">Black wins</span> <span style="color:var(--dim)">(' + winName + ')</span>';
    } else if (g.result === 'w_wins') {
      var cm = g.colorMap || {};
      var winPid = cm.player_a === 'W' ? 'player_a' : 'player_b';
      var winName = winPid === 'player_a' ? nameA : nameB;
      var color = winPid === 'player_a' ? 'var(--cyan)' : 'var(--magenta)';
      resultHTML = '<span class="result-win" style="color:' + color + '">White wins</span> <span style="color:var(--dim)">(' + winName + ')</span>';
    } else {
      resultHTML = '<span class="result-draw">Draw</span>';
    }
    var hl = S.highlightHands.includes(g.gameNum) ? '<span style="color:var(--yellow)">\u2605 </span>' : '  ';
    return '<div class="game-entry">' + hl + '<span class="gnum">Game ' + g.gameNum + '</span>' + resultHTML + '</div>';
  }).join('');
}

function renderCommentary() {
  var el = document.getElementById('commentary');
  if (!S.commentary.length) {
    el.innerHTML = '<span style="color:var(--dim);font-style:italic">Waiting for action...</span>';
    return;
  }
  el.innerHTML = S.commentary.slice().reverse().map(function(e) {
    var color = e.playerId === 'player_a' ? 'var(--cyan)' : 'var(--magenta)';
    var actionHTML;
    if (e.isViolation) {
      actionHTML = '<span style="color:var(--red);font-weight:bold">violation!</span>';
    } else if (e.position) {
      var posStr = COL_LETTERS[e.position[1]] + (e.position[0] + 1);
      actionHTML = '<span style="color:var(--green)">' + posStr + '</span>';
      if (e.flippedCount > 0) actionHTML += ' <span style="color:var(--dim)">(' + e.flippedCount + ' flipped)</span>';
    } else {
      actionHTML = '<span style="color:var(--dim)">pass</span>';
    }
    var latency = e.latencyMs > 100 ? ' <span style="color:var(--dim)">(' + (e.latencyMs/1000).toFixed(1) + 's)</span>' : '';
    var reason = e.reasoning ? '<span class="reasoning">"' + e.reasoning + '"</span>' : '';
    return '<div class="comment-entry"><span style="color:var(--dim)">G' + e.gameNumber + ' T' + e.turnNumber + '</span> <span style="color:' + color + ';font-weight:bold">' + e.model + '</span> ' + actionHTML + latency + reason + '</div>';
  }).join('');
}

function renderFinal() {
  if (!S.finished) { document.getElementById('final-panel').className = 'panel'; return; }
  document.getElementById('final-panel').className = 'panel show';
  var sa = S.finalScores.player_a || 0;
  var sb = S.finalScores.player_b || 0;

  var wA = 0, wB = 0, draws = 0;
  S.gameHistory.forEach(function(g) {
    if (g.result === 'draw') { draws++; return; }
    var cm = g.colorMap || {};
    var winPid;
    if (g.result === 'b_wins') winPid = cm.player_a === 'B' ? 'player_a' : 'player_b';
    else winPid = cm.player_a === 'W' ? 'player_a' : 'player_b';
    if (winPid === 'player_a') wA++;
    else wB++;
  });

  var html;
  if (sa === sb) {
    html = '<div class="winner" style="color:var(--yellow)">DRAW</div><div class="breakdown">' + sa + ' each</div>';
  } else {
    var wPid = sa > sb ? 'player_a' : 'player_b';
    var emoji = S.emojis[wPid] || '';
    var wName = wPid === 'player_a' ? S.modelA : S.modelB;
    var wColor = wPid === 'player_a' ? 'var(--cyan)' : 'var(--magenta)';
    html = '<div class="winner" style="color:' + wColor + '">' + emoji + ' ' + wName + ' WINS</div>' +
           '<div class="breakdown">' + sa + ' \u2013 ' + sb + '</div>';
  }
  var nameA = S.modelA || 'A';
  var nameB = S.modelB || 'B';
  html += '<div class="stats">' + nameA + ': ' + wA + 'W ' + draws + 'D ' + wB + 'L &nbsp;\u00B7&nbsp; ' + nameB + ': ' + wB + 'W ' + draws + 'D ' + wA + 'L</div>';
  var va = S.violations.player_a || 0, vb = S.violations.player_b || 0;
  if (va + vb > 0) html += '<div class="stats" style="color:var(--red)">Violations: A:' + va + ' B:' + vb + '</div>';
  document.getElementById('final-content').innerHTML = html;
}

function renderFooter() {
  var st = document.getElementById('status-text');
  if (S.finished) {
    st.innerHTML = '<span class="badge badge-final" style="font-size:10px">FINAL</span> Series Complete';
  } else {
    st.innerHTML = '<span class="badge badge-live" style="font-size:10px">LIVE</span> Watching...';
  }
  document.getElementById('line-count').textContent = rawLines.length;
}

function renderShotClock() {
  var el = document.getElementById('shot-clock');
  if (!S.shotClock.timeLimitMs || S.finished) { el.style.display = 'none'; return; }
  el.style.display = 'block';
  var display = document.getElementById('clock-display');
  var label = document.getElementById('clock-label');
  var strikeEl = document.getElementById('strike-info');
  if (!S.finished && !isReplaying && S.shotClock.lastTurnTime) {
    var elapsed = Date.now() - S.shotClock.lastTurnTime;
    var remaining = Math.max(0, S.shotClock.timeLimitMs - elapsed);
    var secs = remaining / 1000;
    display.textContent = secs.toFixed(1) + 's';
    var pct = remaining / S.shotClock.timeLimitMs;
    display.className = 'clock-display ' + (pct <= 0 ? 'clock-danger' : pct < 0.2 ? 'clock-danger' : pct < 0.5 ? 'clock-warn' : 'clock-ok');
  } else {
    display.textContent = (S.shotClock.timeLimitMs / 1000).toFixed(1) + 's';
    display.className = 'clock-display clock-ok';
  }
  var wModel = S.shotClock.waitingOn === 'player_a' ? (S.modelA || 'A') : (S.modelB || 'B');
  label.textContent = S.finished ? 'SHOT CLOCK' : 'SHOT CLOCK \u00b7 ' + wModel;
  if (S.shotClock.strikeLimit) {
    var sA = S.shotClock.strikes.player_a || 0;
    var sB = S.shotClock.strikes.player_b || 0;
    var nA = S.modelA || 'A', nB = S.modelB || 'B';
    strikeEl.innerHTML = '<span class="player-a">' + nA + ': ' + sA + '/' + S.shotClock.strikeLimit + '</span> \u00b7 <span class="player-b">' + nB + ': ' + sB + '/' + S.shotClock.strikeLimit + '</span>';
  } else { strikeEl.innerHTML = ''; }
}

function renderAll() {
  renderHeader();
  renderShotClock();
  renderBoard();
  renderSidebar();
  renderGameHistory();
  renderCommentary();
  renderFinal();
  renderFooter();
}

// ── Copy runlog ──────────────────────────────────────────────────
function copyRunlog() {
  var btn = document.getElementById('copy-btn');
  fetch('/filepath').then(function(r) { return r.text(); }).then(function(fp) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(fp).then(function() {
        btn.classList.add('copied');
        btn.textContent = 'Copied path!';
        setTimeout(function() {
          btn.classList.remove('copied');
          btn.innerHTML = 'Copy Runlog Path <span class="count">' + rawLines.length + '</span>';
        }, 2000);
      });
    } else {
      var ta = document.createElement('textarea');
      ta.value = fp;
      ta.style.position = 'fixed';
      ta.style.left = '-9999px';
      document.body.appendChild(ta);
      ta.select();
      document.execCommand('copy');
      document.body.removeChild(ta);
      btn.classList.add('copied');
      btn.textContent = 'Copied path!';
      setTimeout(function() {
        btn.classList.remove('copied');
        btn.innerHTML = 'Copy Runlog Path <span class="count">' + rawLines.length + '</span>';
      }, 2000);
    }
  });
}

// ── SSE client ───────────────────────────────────────────────────
function startSSE() {
  var es = new EventSource('/events');
  es.onmessage = function(e) {
    var line = e.data;
    rawLines.push(line);
    try {
      var data = JSON.parse(line);
      if (isReplaying) {
        turnQueue.push(data);
      } else {
        processTurn(data);
        renderAll();
      }
    } catch(err) {}
    document.getElementById('line-count').textContent = rawLines.length;
  };
  es.addEventListener('done', function() {
    es.close();
  });
  es.onerror = function() {};
}

function drainQueue() {
  if (!turnQueue.length) {
    isReplaying = false;
    renderAll();
    return;
  }
  var data = turnQueue.shift();
  processTurn(data);
  renderAll();
  var delay = data.record_type === 'match_summary' ? 200 : 50;
  setTimeout(drainQueue, delay);
}

// Init
renderBoard();
renderAll();

isReplaying = true;
turnQueue = [];
startSSE();

setTimeout(function() {
  if (turnQueue.length > 0) {
    drainQueue();
  } else {
    isReplaying = false;
  }
}, 300);
// Shot clock countdown
setInterval(function() {
  if (S.shotClock.timeLimitMs && !S.finished && !isReplaying) renderShotClock();
}, 100);

</script>
</body>
</html>"""


# ── Bullshit HTML/CSS/JS ──────────────────────────────────────────

BULLSHIT_HTML_PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Bullshit Spectator</title>
<style>
:root {
  --bg: #0d1117;
  --surface: #161b22;
  --border: #30363d;
  --text: #e6edf3;
  --dim: #7d8590;
  --cyan: #58a6ff;
  --magenta: #d2a8ff;
  --green: #3fb950;
  --red: #f85149;
  --yellow: #d29922;
  --pa: #58a6ff;
  --pb: #d2a8ff;
  --pc: #3fb950;
  --pd: #d29922;
  --pe: #f97583;
  --pf: #79c0ff;
  --pg: #ffa657;
  --ph: #b392f0;
  --pi: #56d4dd;
  --pj: #e3b341;
  --felt: #1a3a1a;
}
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
  background: var(--bg);
  color: var(--text);
  font-family: 'SF Mono', 'Cascadia Code', 'Fira Code', 'Consolas', monospace;
  font-size: 13px;
  line-height: 1.4;
  padding: 12px;
  max-width: 1200px;
  margin: 0 auto;
}

/* Header */
#header {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 12px 16px;
  margin-bottom: 10px;
  text-align: center;
}
#header .badge {
  display: inline-block;
  padding: 2px 10px;
  border-radius: 4px;
  font-weight: bold;
  font-size: 12px;
  margin-right: 8px;
  vertical-align: middle;
}
.badge-live { background: var(--green); color: #000; animation: pulse 2s infinite; }
.badge-final { background: var(--red); color: #fff; }
@keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.6; } }
#header .title { font-size: 16px; font-weight: bold; }
.player-a { color: var(--pa); }
.player-b { color: var(--pb); }
.player-c { color: var(--pc); }
.player-d { color: var(--pd); }
.player-e { color: var(--pe); }
.player-f { color: var(--pf); }
.player-g { color: var(--pg); }
.player-h { color: var(--ph); }
.player-i { color: var(--pi); }
.player-j { color: var(--pj); }
#header .sub { margin-top: 4px; color: var(--dim); }
#header .target-rank {
  display: inline-block;
  background: var(--yellow);
  color: #000;
  padding: 2px 12px;
  border-radius: 4px;
  font-weight: bold;
  font-size: 14px;
  margin-left: 8px;
}

/* Hero action panel */
#hero {
  background: var(--surface);
  border: 2px solid var(--yellow);
  border-radius: 8px;
  padding: 14px 18px;
  margin-bottom: 10px;
  text-align: center;
  min-height: 60px;
  transition: border-color 0.3s;
}
#hero.truth { border-color: var(--green); }
#hero.lie { border-color: var(--red); }
#hero .action-line { font-size: 15px; font-weight: bold; margin-bottom: 4px; }
#hero .detail-line { font-size: 12px; color: var(--dim); }
#hero .truth-tag { color: var(--green); font-weight: bold; }
#hero .lie-tag { color: var(--red); font-weight: bold; }
#hero .challenge-result { margin-top: 6px; font-size: 13px; }
@keyframes fadeIn { from { opacity: 0; transform: translateY(-6px); } to { opacity: 1; transform: translateY(0); } }
#hero .action-line { animation: fadeIn 0.3s ease-out; }

/* Player panels strip — columns set dynamically via JS */
#players {
  display: grid;
  gap: 8px;
  margin-bottom: 10px;
}
.player-panel {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px 12px;
  transition: border-color 0.3s;
}
.player-panel.active { border-color: var(--green); border-width: 2px; }
.player-panel.challenging { border-color: var(--yellow); border-width: 2px; border-style: dashed; }
.player-panel.challenging .model-name::after { content: '  DECIDING...'; font-size: 10px; color: var(--yellow); font-weight: normal; letter-spacing: 1px; }
.player-panel.eliminated { opacity: 0.5; }
.player-panel .model-name { font-weight: bold; font-size: 13px; margin-bottom: 4px; }
.player-panel .card-count { font-size: 18px; font-weight: bold; margin: 4px 0; }
.player-panel .hand {
  display: flex;
  flex-wrap: wrap;
  gap: 3px;
  margin: 6px 0;
  min-height: 24px;
}
.card-pill {
  display: inline-block;
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 3px;
  padding: 1px 4px;
  font-size: 10px;
  font-weight: bold;
  white-space: nowrap;
}
.card-pill.red { color: var(--red); }
.card-pill.black { color: var(--text); }
.card-pill.match-rank { outline: 2px solid var(--yellow); background: rgba(210,153,34,0.15); }
.player-panel .stats { font-size: 11px; color: var(--dim); margin-top: 4px; }
.player-panel .stats .caught { color: var(--red); }
.player-panel .out-overlay {
  font-size: 20px;
  font-weight: bold;
  color: var(--red);
  text-align: center;
  padding: 8px;
}

/* Panels */
.panel {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px 14px;
  margin-bottom: 10px;
}
.panel h3 {
  font-size: 11px;
  text-transform: uppercase;
  color: var(--dim);
  border-bottom: 1px solid var(--border);
  padding-bottom: 4px;
  margin-bottom: 6px;
}

/* History feed */
#history .entry { padding: 3px 0; font-size: 12px; border-bottom: 1px solid #21262d; }
#history .entry:last-child { border-bottom: none; }
.entry .truth { color: var(--green); font-weight: bold; }
.entry .lie { color: var(--red); font-weight: bold; }
.entry .unchallenged { color: var(--yellow); }
.entry .caught { color: var(--green); font-weight: bold; }
.entry .wrong-call { color: var(--red); font-weight: bold; }

/* Reasoning panel */
#reasoning-panel { cursor: pointer; }
#reasoning-panel .content { max-height: 60px; overflow: hidden; transition: max-height 0.3s; }
#reasoning-panel.expanded .content { max-height: 300px; }

/* Final panel */
#final-panel { display: none; text-align: center; border-color: var(--yellow); }
#final-panel.show { display: block; }
#final-panel .winner { font-size: 20px; font-weight: bold; margin: 8px 0; }
#final-panel .standings { font-size: 13px; margin: 6px 0; }

/* Shot clock */
#shot-clock {
  display: none;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 8px 16px;
  margin-bottom: 10px;
  text-align: center;
}
#shot-clock .clock-label { font-size: 11px; color: var(--dim); text-transform: uppercase; letter-spacing: 1px; }
#shot-clock .clock-display { font-size: 24px; font-weight: bold; font-variant-numeric: tabular-nums; letter-spacing: 1px; margin: 2px 0; }
#shot-clock .clock-display.clock-ok { color: var(--green); }
#shot-clock .clock-display.clock-warn { color: var(--yellow); }
#shot-clock .clock-display.clock-danger { color: var(--red); animation: pulse 0.5s infinite; }
#shot-clock .strike-info { font-size: 11px; color: var(--dim); }

/* Footer */
#footer {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 6px 14px;
  display: flex;
  justify-content: space-between;
  color: var(--dim);
  font-size: 11px;
}

/* Compact mode */
body.compact { padding: 4px; font-size: 11px; }
body.compact #header { padding: 6px 10px; margin-bottom: 6px; }
body.compact #header .title { font-size: 13px; }
body.compact #hero { padding: 8px 12px; margin-bottom: 6px; min-height: 40px; }
body.compact #hero .action-line { font-size: 12px; }
body.compact .player-panel { padding: 6px 8px; }
body.compact .player-panel .card-count { font-size: 14px; }
body.compact .card-pill { font-size: 9px; padding: 0 3px; }
body.compact #reasoning-panel { display: none; }
body.compact .panel { padding: 6px 10px; margin-bottom: 6px; }
</style>
</head>
<body>
<div id="header">
  <span id="badge" class="badge badge-live">LIVE</span>
  <span class="title" id="matchup">Loading...</span>
  <div class="sub" id="sub-info"></div>
</div>

<div id="hero">
  <div style="display:flex;align-items:center;justify-content:center;gap:18px">
    <div style="flex:1;text-align:center">
      <div class="action-line" id="hero-action">Waiting for first play...</div>
      <div class="detail-line" id="hero-detail"></div>
      <div class="challenge-result" id="hero-challenge"></div>
    </div>
    <div id="pile-indicator" style="text-align:center;min-width:70px">
      <div style="font-size:28px;font-weight:bold;color:var(--yellow)" id="pile-count">0</div>
      <div style="font-size:10px;color:var(--dim);text-transform:uppercase;letter-spacing:1px">pile</div>
    </div>
  </div>
</div>

<div id="shot-clock">
  <div class="clock-label" id="clock-label">SHOT CLOCK</div>
  <div class="clock-display clock-ok" id="clock-display">--.-s</div>
  <div class="strike-info" id="strike-info"></div>
</div>

<div id="players"></div>

<div class="panel" id="history-panel">
  <h3>Action History</h3>
  <div id="history"><span style="color:var(--dim);font-style:italic">No plays yet</span></div>
</div>

<div class="panel" id="reasoning-panel" onclick="this.classList.toggle('expanded')">
  <h3>Reasoning (click to expand)</h3>
  <div class="content" id="reasoning-content"><span style="color:var(--dim);font-style:italic">Waiting...</span></div>
</div>

<div class="panel" id="final-panel">
  <h3>Final Results</h3>
  <div id="final-content"></div>
</div>

<div id="footer">
  <span id="status-text"><span class="badge badge-live" style="font-size:10px">LIVE</span> Watching...</span>
  <span>Discard: <span id="discard-count">0</span> | Turns: <span id="turn-count">0</span></span>
</div>

<script>
var RANK_NAMES = {A:'Aces','2':'Twos','3':'Threes','4':'Fours','5':'Fives','6':'Sixes','7':'Sevens','8':'Eights','9':'Nines','10':'Tens',J:'Jacks',Q:'Queens',K:'Kings'};

// Dynamic player setup — initialized from first state snapshot
var PIDS = [];
var LABELS = {};
var SUFFIXES = {};
var COLORS = {};
var CLASS_NAMES = {};
var _playersInitialized = false;
var _ALL_SUFFIXES = 'abcdefghij'.split('');

function initPlayers(cardCounts) {
  if (_playersInitialized) return;
  PIDS = Object.keys(cardCounts).sort();
  PIDS.forEach(function(pid) {
    var suf = pid.replace('player_', '');
    SUFFIXES[pid] = suf;
    LABELS[pid] = suf.toUpperCase();
    CLASS_NAMES[pid] = 'player-' + suf;
    COLORS[pid] = 'var(--p' + suf + ')';
  });

  // Set grid columns
  var cols = PIDS.length <= 4 ? PIDS.length : Math.ceil(PIDS.length / 2);
  document.getElementById('players').style.gridTemplateColumns = 'repeat(' + cols + ', 1fr)';

  // Generate player panel HTML
  var html = '';
  PIDS.forEach(function(pid) {
    var suf = SUFFIXES[pid];
    var cls = CLASS_NAMES[pid];
    html += '<div class="player-panel" id="panel-' + suf + '">'
      + '<div class="model-name ' + cls + '" id="name-' + suf + '">Player ' + LABELS[pid] + '</div>'
      + '<div class="card-count" id="count-' + suf + '">0</div>'
      + '<div class="hand" id="hand-' + suf + '"></div>'
      + '<div class="stats" id="stats-' + suf + '"></div>'
      + '</div>';
  });
  document.getElementById('players').innerHTML = html;

  // Initialize S per-player maps
  var empty = {};
  PIDS.forEach(function(pid) {
    S.models[pid] = S.models[pid] || '';
    S.cardCounts[pid] = S.cardCounts[pid] || 0;
    S.hands[pid] = S.hands[pid] || [];
    S.matchScores[pid] = S.matchScores[pid] || 0;
    S.violations[pid] = S.violations[pid] || 0;
    S.shotClock.strikes[pid] = S.shotClock.strikes[pid] || 0;
  });

  _playersInitialized = true;
}

var S = {
  models: {},
  gameNumber: 1,
  gamesPerMatch: 1,
  turnNumber: 0,
  phase: 'play',
  targetRank: 'A',
  currentPlayer: '',
  cardCounts: {},
  hands: {},
  discardPileSize: 0,
  history: [],
  finishOrder: [],
  eliminated: [],
  matchScores: {},
  playerStats: {},
  lastPlay: null,
  lastPlayPlayer: '',
  finished: false,
  finalScores: {},
  violations: {},
  turnCount: 0,
  lastReasoning: '',
  lastModel: '',
  shotClock: { timeLimitMs: null, lastTurnTime: null, strikes: {}, strikeLimit: null, waitingOn: '' }
};

var rawLines = [];
var turnQueue = [];
var isReplaying = false;

// Compact mode
if (new URLSearchParams(window.location.search).get('compact') === '1') {
  document.body.classList.add('compact');
}

function processTurn(data) {
  rawLines.push(data);

  if (data.record_type === 'match_summary') {
    S.finished = true;
    S.finalScores = data.final_scores || {};
    var pm = data.player_models || {};
    PIDS.forEach(function(pid) { if (pm[pid]) S.models[pid] = pm[pid]; });
    return;
  }

  S.turnCount++;
  var snap = data.state_snapshot || {};
  var pid = data.player_id || '';
  var mid = data.model_id || '';

  // Initialize players from first snapshot
  if (snap.card_counts && !_playersInitialized) {
    initPlayers(snap.card_counts);
  }

  if (pid && mid) S.models[pid] = mid;

  // Populate all player models from snapshot (available from first turn)
  var pm = snap.player_models || {};
  Object.keys(pm).forEach(function(k) { if (!S.models[k]) S.models[k] = pm[k]; });

  // Shot clock tracking
  if (data.time_limit_ms) S.shotClock.timeLimitMs = data.time_limit_ms;
  if (data.strike_limit) S.shotClock.strikeLimit = data.strike_limit;
  if (data.cumulative_strikes !== undefined && pid) S.shotClock.strikes[pid] = data.cumulative_strikes;
  S.shotClock.lastTurnTime = Date.now();
  S.shotClock.waitingOn = (snap.current_player || S.currentPlayer);

  S.gameNumber = snap.game_number || S.gameNumber;
  S.gamesPerMatch = snap.games_per_match || S.gamesPerMatch;
  S.turnNumber = snap.turn_number || S.turnNumber;
  S.phase = snap.phase || S.phase;
  S.targetRank = snap.target_rank || S.targetRank;
  S.currentPlayer = snap.current_player || S.currentPlayer;
  S.cardCounts = snap.card_counts || S.cardCounts;
  S.hands = snap.hands || S.hands;
  S.discardPileSize = snap.discard_pile_size || 0;
  S.history = snap.history || S.history;
  S.finishOrder = snap.finish_order || S.finishOrder;
  S.eliminated = snap.eliminated || S.eliminated;
  S.matchScores = snap.match_scores || S.matchScores;
  S.playerStats = snap.player_stats || S.playerStats;
  S.lastPlay = snap.last_play || S.lastPlay;
  if (S.lastPlay && S.lastPlay.player) S.lastPlayPlayer = S.lastPlay.player;

  var reasoning = data.reasoning_output || '';
  if (reasoning) {
    S.lastReasoning = reasoning.length > 200 ? reasoning.substring(0, 197) + '...' : reasoning;
    S.lastModel = mid;
  }

  if (data.violation && pid) {
    S.violations[pid] = (S.violations[pid] || 0) + 1;
  }
}

function renderAll() {
  if (!_playersInitialized) return;
  renderHeader();
  renderHero();
  renderPlayers();
  renderShotClock();
  renderHistory();
  renderReasoning();
  renderFinal();
  renderFooter();
}

function renderShotClock() {
  var el = document.getElementById('shot-clock');
  if (!S.shotClock.timeLimitMs) { return; }
  el.style.display = 'block';
  var display = document.getElementById('clock-display');
  var label = document.getElementById('clock-label');
  var strikeEl = document.getElementById('strike-info');
  if (S.shotClock.lastTurnTime && !isReplaying) {
    var elapsed = Date.now() - S.shotClock.lastTurnTime;
    var remaining = Math.max(0, S.shotClock.timeLimitMs - elapsed);
    var secs = remaining / 1000;
    display.textContent = secs.toFixed(1) + 's';
    var cls = 'clock-display ';
    if (remaining <= 5000) cls += 'clock-danger';
    else if (remaining <= 10000) cls += 'clock-warn';
    else cls += 'clock-ok';
    display.className = cls;
  } else {
    display.textContent = (S.shotClock.timeLimitMs / 1000).toFixed(1) + 's';
    display.className = 'clock-display clock-ok';
  }
  var wModel = S.models[S.shotClock.waitingOn] || S.shotClock.waitingOn;
  label.innerHTML = 'SHOT CLOCK <span style="color:var(--dim)">\u00b7</span> ' + wModel;
  if (S.shotClock.strikeLimit) {
    var parts = [];
    PIDS.forEach(function(pid) {
      var s = S.shotClock.strikes[pid] || 0;
      var m = S.models[pid] || LABELS[pid];
      parts.push('<span class="' + CLASS_NAMES[pid] + '">' + m + ': ' + s + '/' + S.shotClock.strikeLimit + '</span>');
    });
    strikeEl.innerHTML = parts.join(' \u00b7 ');
  } else { strikeEl.innerHTML = ''; }
  if (S.finished) el.style.display = 'none';
}

function renderHeader() {
  var badge = document.getElementById('badge');
  badge.textContent = S.finished ? 'FINAL' : 'LIVE';
  badge.className = 'badge ' + (S.finished ? 'badge-final' : 'badge-live');

  var parts = [];
  PIDS.forEach(function(pid) {
    var name = S.models[pid] || ('Player ' + LABELS[pid]);
    parts.push('<span class="' + CLASS_NAMES[pid] + '">' + name + '</span>');
  });
  document.getElementById('matchup').innerHTML = parts.join(' <span style="color:var(--dim)">vs</span> ');

  var scores = S.finished ? S.finalScores : S.matchScores;
  var sub = '<strong>Game ' + S.gameNumber + '</strong>';
  if (S.gamesPerMatch > 1) sub += ' of ' + S.gamesPerMatch;
  sub += ' <span style="color:var(--dim)">|</span> ';
  PIDS.forEach(function(pid) {
    var sc = scores[pid] != null ? scores[pid] : (S.matchScores[pid] || 0);
    sub += '<span class="' + CLASS_NAMES[pid] + '" style="font-weight:bold">' + LABELS[pid] + ':' + Math.round(sc) + '</span> ';
  });
  sub += '<span style="color:var(--dim)">|</span> <span class="target-rank">' + (RANK_NAMES[S.targetRank] || S.targetRank) + '</span>';
  document.getElementById('sub-info').innerHTML = sub;
}

function cardPillHTML(card) {
  var suit = card.slice(-1);
  var isRed = (suit === '\u2665' || suit === '\u2666');
  return '<span class="card-pill ' + (isRed ? 'red' : 'black') + '">' + card + '</span>';
}

function cardPillWithHighlight(card, highlight) {
  var suit = card.slice(-1);
  var isRed = (suit === '\u2665' || suit === '\u2666');
  var cls = 'card-pill ' + (isRed ? 'red' : 'black');
  if (highlight) cls += ' match-rank';
  return '<span class="' + cls + '">' + card + '</span>';
}

function renderHero() {
  var hero = document.getElementById('hero');
  var actionEl = document.getElementById('hero-action');
  var detailEl = document.getElementById('hero-detail');
  var challengeEl = document.getElementById('hero-challenge');

  document.getElementById('pile-count').textContent = S.discardPileSize;

  if (!S.lastPlay || !S.history.length) {
    hero.className = '';
    actionEl.textContent = 'Waiting for first play...';
    detailEl.textContent = '';
    challengeEl.textContent = '';
    return;
  }

  var last = S.history[S.history.length - 1];
  var lp = S.lastPlay;
  var pid = lp.player;
  var model = S.models[pid] || LABELS[pid];
  var clr = CLASS_NAMES[pid];
  var rank = RANK_NAMES[lp.claim_rank] || lp.claim_rank;
  var count = lp.claim_count;

  actionEl.innerHTML = '<span class="' + clr + '">' + model + '</span> played ' + count + ' card(s) claiming <strong>' + rank + '</strong>';

  // Actual cards + truth/lie
  var cards = (lp.cards || []).map(cardPillHTML).join(' ');
  var tag = '';
  if (last.was_truthful) {
    tag = ' <span class="truth-tag">TRUTH</span>';
    hero.className = 'truth';
  } else {
    tag = ' <span class="lie-tag">LIE</span>';
    hero.className = 'lie';
  }
  detailEl.innerHTML = 'Actual: ' + cards + tag;

  // Challenge result
  if (last.challenge_by) {
    var cModel = S.models[last.challenge_by] || LABELS[last.challenge_by];
    var cClr = CLASS_NAMES[last.challenge_by];
    if (last.was_bluff) {
      challengeEl.innerHTML = '<span class="' + cClr + '">' + cModel + '</span> called BS \u2192 <span class="caught">CAUGHT! Liar picks up pile</span>';
    } else {
      challengeEl.innerHTML = '<span class="' + cClr + '">' + cModel + '</span> called BS \u2192 <span class="wrong-call">WRONG! Caller picks up pile</span>';
    }
    hero.className = last.was_bluff ? 'truth' : 'lie';
  } else {
    challengeEl.innerHTML = '<span class="unchallenged">Unchallenged</span>';
    hero.className = '';
  }
}

function renderPlayers() {
  PIDS.forEach(function(pid) {
    var suf = SUFFIXES[pid];
    var panel = document.getElementById('panel-' + suf);
    var nameEl = document.getElementById('name-' + suf);
    var countEl = document.getElementById('count-' + suf);
    var handEl = document.getElementById('hand-' + suf);
    var statsEl = document.getElementById('stats-' + suf);

    var model = S.models[pid] || ('Player ' + LABELS[pid]);
    nameEl.textContent = model;

    var isElim = S.eliminated.indexOf(pid) >= 0;
    var isPlayTurn = (pid === S.currentPlayer && !S.finished && S.phase === 'play');
    var isChallenging = (pid === S.currentPlayer && !S.finished && S.phase === 'challenge');
    var isLastPlayer = (S.phase === 'challenge' && pid === S.lastPlayPlayer && !S.finished);

    var cls = 'player-panel';
    if (isChallenging) cls += ' challenging';
    else if (isPlayTurn || isLastPlayer) cls += ' active';
    if (isElim) cls += ' eliminated';
    panel.className = cls;

    var cc = S.cardCounts[pid] || 0;
    if (isElim) {
      var finishIdx = S.finishOrder.indexOf(pid);
      if (finishIdx >= 0) {
        countEl.innerHTML = '<span style="color:var(--green)">' + ordinal(finishIdx + 1) + ' OUT</span>';
      } else {
        countEl.innerHTML = '<span style="color:var(--red)">DQ</span>';
      }
    } else {
      countEl.textContent = cc + ' cards';
    }

    // God mode hand — highlight cards matching target rank
    var hand = S.hands[pid] || [];
    if (hand.length > 0) {
      handEl.innerHTML = hand.map(function(card) {
        var rank = card.slice(0, -1);
        return cardPillWithHighlight(card, rank === S.targetRank);
      }).join('');
    } else {
      handEl.innerHTML = '<span style="color:var(--dim)">(empty)</span>';
    }

    // Stats
    var ps = (S.playerStats || {})[pid] || {};
    var lies = ps.lie_count || 0;
    var truths = ps.truth_count || 0;
    var caught = ps.times_caught || 0;
    var calls = ps.times_called_bs || 0;
    var correct = ps.correct_calls || 0;
    var total = lies + truths;

    var unnecessaryBluffs = ps.unnecessary_bluff_count || 0;

    var statParts = [];
    if (total > 0) {
      var liePct = Math.round(lies * 100 / total);
      statParts.push('Bluff: ' + liePct + '%');
    }
    if (unnecessaryBluffs > 0) {
      statParts.push('<span style="color:var(--yellow)">Needless: ' + unnecessaryBluffs + '</span>');
    }
    if (caught > 0) statParts.push('<span class="caught">Caught: ' + caught + '</span>');
    if (calls > 0) {
      var acc = Math.round(correct * 100 / calls);
      statParts.push('BS calls: ' + calls + ' (' + acc + '%)');
    }
    var v = S.violations[pid] || 0;
    if (v > 0) statParts.push('<span style="color:var(--red)">Violations: ' + v + '</span>');
    statsEl.innerHTML = statParts.join(' &middot; ');
  });
}

function renderHistory() {
  var el = document.getElementById('history');
  if (!S.history.length) {
    el.innerHTML = '<span style="color:var(--dim);font-style:italic">No plays yet</span>';
    return;
  }
  var recent = S.history.slice(-12).reverse();
  el.innerHTML = recent.map(function(h) {
    var pid = h.player;
    var clr = CLASS_NAMES[pid] || '';
    var model = S.models[pid] || LABELS[pid] || pid;

    var tag = '';
    if (h.challenge_by) {
      var cModel = S.models[h.challenge_by] || LABELS[h.challenge_by] || h.challenge_by;
      var cClr = CLASS_NAMES[h.challenge_by] || '';
      if (h.was_bluff) {
        tag = '<span class="lie">LIE</span> \u2192 <span class="' + cClr + '">' + cModel + '</span> <span class="caught">caught!</span>';
      } else {
        tag = '<span class="truth">TRUTH</span> \u2192 <span class="' + cClr + '">' + cModel + '</span> <span class="wrong-call">wrong!</span>';
      }
    } else {
      if (h.was_truthful) {
        tag = '<span class="truth">TRUTH</span> <span class="unchallenged">(unchallenged)</span>';
      } else {
        tag = '<span class="lie">LIE</span> <span class="unchallenged">(unchallenged)</span>';
      }
    }

    return '<div class="entry"><span style="color:var(--dim)">T' + h.turn + '</span> <span class="' + clr + '">' + model + '</span> played ' + h.claim_count + ' ' + (RANK_NAMES[h.claim_rank] || h.claim_rank) + ' ' + tag + '</div>';
  }).join('');
}

function renderReasoning() {
  var el = document.getElementById('reasoning-content');
  if (!S.lastReasoning) {
    el.innerHTML = '<span style="color:var(--dim);font-style:italic">Waiting...</span>';
    return;
  }
  el.innerHTML = '<span style="font-weight:bold">' + (S.lastModel || '?') + ':</span> <span style="font-style:italic;color:var(--dim)">' + S.lastReasoning.replace(/</g,'&lt;').replace(/>/g,'&gt;') + '</span>';
}

function ordinal(n) {
  var s = ['th','st','nd','rd'];
  var v = n % 100;
  return n + (s[(v-20)%10] || s[v] || s[0]);
}

function renderFinal() {
  var panel = document.getElementById('final-panel');
  if (!S.finished) { panel.className = 'panel'; return; }
  panel.className = 'panel show';

  var scores = S.finalScores || S.matchScores;
  var ranked = PIDS.slice().sort(function(a,b) { return (scores[b]||0) - (scores[a]||0); });

  var winner = ranked[0];
  var wModel = S.models[winner] || LABELS[winner];
  var wClr = CLASS_NAMES[winner];

  var html = '<div class="winner"><span class="' + wClr + '">' + wModel + ' WINS!</span></div>';
  html += '<div class="standings">';
  ranked.forEach(function(pid, i) {
    var m = S.models[pid] || LABELS[pid];
    var clr = CLASS_NAMES[pid];
    html += '<div>' + ordinal(i+1) + ': <span class="' + clr + '" style="font-weight:bold">' + m + '</span> (' + Math.round(scores[pid]||0) + ' pts)</div>';
  });
  html += '</div>';

  // Deception leaderboard
  html += '<div class="standings" style="margin-top:10px"><strong>Deception Stats</strong>';
  PIDS.forEach(function(pid) {
    var ps = (S.playerStats || {})[pid] || {};
    var m = S.models[pid] || LABELS[pid];
    var clr = CLASS_NAMES[pid];
    var lies = ps.lie_count || 0;
    var truths = ps.truth_count || 0;
    var total = lies + truths;
    var liePct = total > 0 ? Math.round(lies * 100 / total) : 0;
    var caught = ps.times_caught || 0;
    var calls = ps.times_called_bs || 0;
    var correct = ps.correct_calls || 0;
    var callAcc = calls > 0 ? Math.round(correct * 100 / calls) : 0;
    var needless = ps.unnecessary_bluff_count || 0;
    var needlessStr = needless > 0 ? ', needless ' + needless : '';
    html += '<div><span class="' + clr + '">' + m + '</span>: bluff ' + liePct + '%, caught ' + caught + 'x' + needlessStr + ', BS calls ' + calls + ' (' + callAcc + '% acc)</div>';
  });
  html += '</div>';

  document.getElementById('final-content').innerHTML = html;
}

function renderFooter() {
  var st = document.getElementById('status-text');
  if (S.finished) {
    st.innerHTML = '<span class="badge badge-final" style="font-size:10px">FINAL</span> Match Complete';
  } else {
    st.innerHTML = '<span class="badge badge-live" style="font-size:10px">LIVE</span> Watching...';
  }
  document.getElementById('discard-count').textContent = S.discardPileSize;
  document.getElementById('turn-count').textContent = S.turnCount;
}

function drainQueue() {
  if (turnQueue.length === 0) { isReplaying = false; return; }
  var batch = turnQueue.splice(0, 3);
  batch.forEach(function(d) { processTurn(d); });
  renderAll();
  if (turnQueue.length > 0) {
    setTimeout(drainQueue, 200);
  } else {
    isReplaying = false;
    renderShotClock();
  }
}

// SSE connection
var evtPath = '/events';
// Patch for compact/iframe mode
if (window.location.pathname.match(/^\/match\//)) {
  var matchId = window.location.pathname.split('/match/')[1];
  if (matchId) evtPath = '/events/' + matchId;
}
var es = new EventSource(evtPath);
es.onmessage = function(e) {
  var data = JSON.parse(e.data);
  if (isReplaying) {
    turnQueue.push(data);
  } else if (rawLines.length === 0) {
    // First batch — replay with animation
    turnQueue.push(data);
    isReplaying = true;
    drainQueue();
  } else {
    processTurn(data);
    renderAll();
  }
};
setInterval(function() {
  if (S.shotClock.timeLimitMs && !S.finished && !isReplaying) renderShotClock();
}, 100);
</script>
</body>
</html>"""


# ── Holdem HTML/CSS/JS ───────────────────────────────────────────

HOLDEM_HTML_PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Hold'em Spectator</title>
<style>
:root {
  --bg: #0d1117;
  --surface: #161b22;
  --border: #30363d;
  --text: #e6edf3;
  --dim: #7d8590;
  --green: #3fb950;
  --red: #f85149;
  --yellow: #d29922;
  --felt: #1a3a1a;
  --pa: #58a6ff;
  --pb: #d2a8ff;
  --pc: #3fb950;
  --pd: #f0883e;
  --pe: #f85149;
  --pf: #a5d6ff;
  --pg: #db61a2;
  --ph: #7ee787;
  --pi: #d29922;
  --pj: #79c0ff;
}
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
  background: var(--bg);
  color: var(--text);
  font-family: 'SF Mono', 'Cascadia Code', 'Fira Code', 'Consolas', monospace;
  font-size: 13px;
  line-height: 1.4;
  padding: 12px;
  max-width: 1100px;
  margin: 0 auto;
}

/* Header */
#header {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 12px 16px;
  margin-bottom: 10px;
  text-align: center;
}
#header .badge {
  display: inline-block;
  padding: 2px 10px;
  border-radius: 4px;
  font-weight: bold;
  font-size: 12px;
  margin-right: 8px;
  vertical-align: middle;
}
.badge-live { background: var(--green); color: #000; }
.badge-final { background: var(--yellow); color: #000; }
#matchup { font-size: 14px; font-weight: bold; }
#sub-info { font-size: 12px; color: var(--dim); margin-top: 4px; }

/* Main layout */
.main { display: flex; gap: 10px; margin-bottom: 10px; }
.table-area { flex: 1; min-width: 0; }
.sidebar { width: 280px; display: flex; flex-direction: column; gap: 10px; }

/* Panel base */
.panel {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px 14px;
}
.panel-title {
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 1px;
  color: var(--dim);
  margin-bottom: 8px;
  font-weight: bold;
}

/* Players grid */
#players {
  display: grid;
  gap: 6px;
  margin-bottom: 8px;
}
.player-section {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px 14px;
}
.player-section.active-turn {
  border-color: var(--green);
  box-shadow: 0 0 6px rgba(63,185,80,0.3);
}
.player-section.folded { opacity: 0.45; }
.player-section.busted { opacity: 0.25; }
.player-name {
  font-weight: bold;
  font-size: 13px;
  margin-bottom: 3px;
}
.chip-bar-container {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 3px 0;
}
.chip-bar {
  height: 12px;
  border-radius: 3px;
  transition: width 0.5s ease;
  min-width: 2px;
}
.chip-count {
  font-weight: bold;
  font-size: 13px;
  white-space: nowrap;
}
.hole-cards {
  display: flex;
  gap: 3px;
  margin-top: 4px;
  align-items: center;
}
.equity-badge {
  font-size: 13px;
  font-weight: bold;
  color: var(--dim);
  margin-left: 6px;
  padding: 2px 6px;
  border-radius: 4px;
  background: rgba(255,255,255,0.06);
  font-variant-numeric: tabular-nums;
}
.equity-badge.equity-hot { color: var(--green); background: rgba(63,185,80,0.12); }
.equity-badge.equity-cold { color: var(--red); background: rgba(248,81,73,0.12); }
.dealer-btn {
  display: inline-block;
  background: var(--yellow);
  color: #000;
  font-weight: bold;
  font-size: 10px;
  padding: 1px 5px;
  border-radius: 10px;
  margin-left: 6px;
}
.status-tag {
  display: inline-block;
  padding: 0 6px;
  border-radius: 3px;
  font-size: 10px;
  font-weight: bold;
  margin-left: 6px;
}
.tag-folded { background: var(--red); color: #fff; }
.tag-allin { background: var(--yellow); color: #000; }
.tag-busted { background: #30363d; color: var(--dim); }
.tag-eliminated { background: #6e40c9; color: #fff; }
.player-section.eliminated { opacity: 0.35; }
.action-badge {
  display: inline-block;
  padding: 1px 6px;
  border-radius: 4px;
  font-size: 10px;
  font-weight: bold;
  margin-left: 6px;
}
.action-fold { background: var(--red); color: #fff; }
.action-call { background: var(--green); color: #000; }
.action-raise { background: var(--yellow); color: #000; }
.action-check { background: var(--dim); color: #000; }

/* Card rendering */
.card {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 34px;
  height: 46px;
  border-radius: 4px;
  font-weight: bold;
  font-size: 13px;
  border: 2px solid #555;
}
.card-front {
  background: #f0f0f0;
  color: #000;
}
.card-back {
  background: linear-gradient(135deg, #1a4d8f 0%, #2a6dbf 50%, #1a4d8f 100%);
  border-color: #2a6dbf;
}
.card-back::after {
  content: '?';
  color: rgba(255,255,255,0.3);
  font-size: 16px;
}
.suit-h, .suit-d { color: #d32f2f; }
.suit-s, .suit-c { color: #222; }
.card-empty {
  background: var(--surface);
  border: 2px dashed var(--border);
  color: var(--dim);
}

/* Community area */
.community-area {
  background: var(--felt);
  border: 1px solid #2d5a2d;
  border-radius: 12px;
  padding: 14px;
  margin: 6px 0;
  text-align: center;
}
.community-cards {
  display: flex;
  gap: 6px;
  justify-content: center;
  margin: 8px 0;
}
.community-cards .card { width: 38px; height: 52px; font-size: 15px; }
.pot-display {
  font-size: 18px;
  font-weight: bold;
  color: var(--yellow);
  margin-top: 6px;
}
.street-badge {
  display: inline-block;
  padding: 2px 10px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: bold;
  text-transform: uppercase;
  margin-bottom: 4px;
}
.street-preflop { background: #30363d; color: var(--text); }
.street-flop { background: #1f4d1f; color: var(--green); }
.street-turn { background: #4d3d1f; color: var(--yellow); }
.street-river { background: #3d1f1f; color: var(--red); }
.street-showdown { background: #1f1f4d; color: var(--pa); }

/* Hand history */
.hand-entry {
  display: flex;
  justify-content: space-between;
  padding: 3px 0;
  border-bottom: 1px solid var(--border);
  font-size: 12px;
}
.hand-entry:last-child { border-bottom: none; }
.hand-winner { font-weight: bold; }
.hand-margin { color: var(--green); }
.hand-ending { color: var(--dim); }

/* Commentary */
.comment-entry {
  padding: 3px 0;
  border-bottom: 1px solid rgba(48,54,61,0.5);
  font-size: 11px;
  line-height: 1.4;
}
.comment-entry:last-child { border-bottom: none; }
.reasoning {
  display: block;
  color: var(--dim);
  font-style: italic;
  font-size: 10px;
  margin-top: 1px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 260px;
}

/* Final panel */
#final-panel { display: none; margin-bottom: 10px; text-align: center; }
#final-panel.show { display: block; }
.winner { font-size: 18px; font-weight: bold; margin-bottom: 4px; }
.breakdown { font-size: 13px; color: var(--dim); }
.stats { font-size: 11px; color: var(--dim); margin-top: 4px; }

/* Shot clock */
#shot-clock {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 8px 14px;
  margin-bottom: 10px;
  text-align: center;
  display: none;
}
#clock-label { font-size: 10px; color: var(--dim); text-transform: uppercase; letter-spacing: 1px; }
.clock-display { font-size: 24px; font-weight: bold; font-variant-numeric: tabular-nums; }
.clock-ok { color: var(--green); }
.clock-warn { color: var(--yellow); }
.clock-danger { color: var(--red); }
#strike-info { font-size: 11px; margin-top: 2px; }

/* Footer */
#footer {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 8px 14px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 11px;
}
#copy-btn {
  background: var(--border);
  color: var(--text);
  border: none;
  padding: 4px 12px;
  border-radius: 4px;
  cursor: pointer;
  font-size: 11px;
  font-family: inherit;
}
#copy-btn:hover { background: var(--dim); }
#copy-btn.copied { background: var(--green); color: #000; }
.count { color: var(--dim); }

@media (max-width: 700px) {
  .main { flex-direction: column; }
  .sidebar { width: 100%; }
}
</style>
</head>
<body>

<div id="header">
  <span id="badge" class="badge badge-live">LIVE</span>
  <span id="matchup">Connecting...</span>
  <div id="sub-info"></div>
</div>

<div id="shot-clock">
  <div id="clock-label">SHOT CLOCK</div>
  <div id="clock-display" class="clock-display clock-ok">--</div>
  <div id="strike-info"></div>
</div>

<div class="main">
  <div class="table-area">
    <div id="players"></div>
    <div class="community-area">
      <div id="street-label" class="street-badge street-preflop">PREFLOP</div>
      <div id="community-cards" class="community-cards"></div>
      <div id="pot-display" class="pot-display">Pot: 0</div>
    </div>
  </div>
  <div class="sidebar">
    <div class="panel" id="hand-history-panel">
      <div class="panel-title">Hand History</div>
      <div id="hand-history"><span style="color:var(--dim);font-style:italic">No completed hands</span></div>
    </div>
    <div class="panel" id="commentary-panel" style="flex:1;overflow-y:auto;max-height:340px">
      <div class="panel-title">Commentary</div>
      <div id="commentary"><span style="color:var(--dim);font-style:italic">Waiting for action...</span></div>
    </div>
  </div>
</div>

<div id="final-panel" class="panel">
  <div id="final-content"></div>
</div>

<div id="footer">
  <span id="status-text"><span class="badge badge-live" style="font-size:10px">LIVE</span> Connecting...</span>
  <button id="copy-btn" onclick="copyRunlog()">Copy Runlog Path <span class="count" id="line-count">0</span></button>
</div>

<script>
// ── Dynamic player system ────────────────────────────────────────
var PIDS = [];
var LABELS = {};
var COLORS = {};
var _playersInitialized = false;
var _COLOR_VARS = 'abcdefghij'.split('');

function initPlayers(stacks) {
  if (_playersInitialized) return;
  PIDS = Object.keys(stacks).sort();
  PIDS.forEach(function(pid) {
    var suf = pid.replace('player_', '');
    LABELS[pid] = suf.toUpperCase();
    COLORS[pid] = 'var(--p' + suf + ')';
  });

  // Dynamic grid: 2p stacked, 3-4 = 2 cols, 5+ = 3 cols
  var cols = PIDS.length <= 2 ? 1 : PIDS.length <= 4 ? 2 : 3;
  var grid = document.getElementById('players');
  grid.style.gridTemplateColumns = 'repeat(' + cols + ', 1fr)';

  // Generate player panels
  var html = '';
  PIDS.forEach(function(pid) {
    var suf = pid.replace('player_', '');
    html += '<div class="player-section" id="section-' + suf + '"></div>';
  });
  grid.innerHTML = html;

  // Init S per-player maps
  PIDS.forEach(function(pid) {
    S.models[pid] = S.models[pid] || '';
    S.stacks[pid] = S.stacks[pid] || 0;
    S.holeCards[pid] = S.holeCards[pid] || [];
    S.violations[pid] = S.violations[pid] || 0;
    S.emojis[pid] = S.emojis[pid] || '';
    S.shotClock.strikes[pid] = S.shotClock.strikes[pid] || 0;
  });
  _playersInitialized = true;
}

// ── Emoji system ─────────────────────────────────────────────────
var EMOJI_POOL = [
  '\u{1F525}','\u{1F9E0}','\u{1F47E}','\u{1F916}','\u{1F3AF}',
  '\u{1F680}','\u{1F40D}','\u{1F98A}','\u{1F43B}','\u{1F985}',
  '\u{1F409}','\u{1F3B2}','\u{1F9CA}','\u{1F30B}','\u{1F308}',
  '\u{1F52E}','\u{1F9F2}','\u{1F41D}','\u{1F95D}','\u{1F344}'
];
function djb2(s) {
  var h = 5381;
  for (var i = 0; i < s.length; i++) h = ((h << 5) + h + s.charCodeAt(i)) >>> 0;
  return h;
}
function assignEmojis() {
  var assigned = false;
  PIDS.forEach(function(pid) {
    if (S.models[pid] && !S.emojis[pid]) {
      S.emojis[pid] = EMOJI_POOL[djb2(S.models[pid]) % EMOJI_POOL.length];
      assigned = true;
    }
  });
}

// ── Card rendering ───────────────────────────────────────────────
var SUIT_SYMBOLS = { H: '\u2665', D: '\u2666', S: '\u2660', C: '\u2663' };
var SUIT_CLASSES = { H: 'suit-h', D: 'suit-d', S: 'suit-s', C: 'suit-c' };

function renderCard(cardStr) {
  if (!cardStr || cardStr === '??') return '<div class="card card-back"></div>';
  var rank = cardStr.slice(0, -1);
  var suit = cardStr.slice(-1).toUpperCase();
  var sym = SUIT_SYMBOLS[suit] || suit;
  var cls = SUIT_CLASSES[suit] || '';
  return '<div class="card card-front ' + cls + '">' + rank + sym + '</div>';
}
function renderEmptyCard() { return '<div class="card card-empty"></div>'; }

function shortModel(name) {
  if (!name) return name;
  return name.replace(/^anthropic\/claude-/, '').replace(/^anthropic\//, '').replace(/^openai\//, '');
}
function truncateReasoning(text, max) {
  max = max || 100;
  if (!text) return null;
  var lines = text.trim().split('\n');
  for (var i = 0; i < lines.length; i++) {
    var t = lines[i].trim();
    if (t.length > 10) return t.length > max ? t.slice(0, max-3) + '...' : t;
  }
  return null;
}

// ── Equity calculator (WSOP-style) ──────────────────────────────
var EQUITY_RANKS = '23456789TJQKA';
var EQUITY_RANK_VAL = {};
for (var ri = 0; ri < EQUITY_RANKS.length; ri++) EQUITY_RANK_VAL[EQUITY_RANKS[ri]] = ri;
var FULL_DECK = [];
(function() {
  var suits = ['h','d','c','s'];
  for (var si = 0; si < suits.length; si++)
    for (var ri = 0; ri < EQUITY_RANKS.length; ri++)
      FULL_DECK.push(EQUITY_RANKS[ri] + suits[si]);
})();

function eqParseCard(s) { return { rank: s.slice(0,-1), suit: s.slice(-1) }; }

function eqEvalHand(cards) {
  // Score a 5-card hand. Higher = better. Format: category<<20 | kickers
  var vals = cards.map(function(c) { return EQUITY_RANK_VAL[c.rank]; }).sort(function(a,b){return b-a;});
  var suitSet = {};
  cards.forEach(function(c) { suitSet[c.suit] = true; });
  var isFlush = Object.keys(suitSet).length === 1;

  // Straight check
  var unique = []; var seen = {};
  vals.forEach(function(v) { if (!seen[v]) { unique.push(v); seen[v] = true; } });
  unique.sort(function(a,b){return b-a;});
  var isStraight = false, straightHigh = 0;
  if (unique.length === 5) {
    if (unique[0] - unique[4] === 4) { isStraight = true; straightHigh = unique[0]; }
    else if (unique[0]===12 && unique[1]===3 && unique[2]===2 && unique[3]===1 && unique[4]===0) {
      isStraight = true; straightHigh = 3; // wheel
    }
  }

  // Group by rank count
  var counts = {};
  vals.forEach(function(v) { counts[v] = (counts[v]||0) + 1; });
  var groups = Object.keys(counts).map(function(v) { return [parseInt(v), counts[v]]; });
  groups.sort(function(a,b) { return b[1]-a[1] || b[0]-a[0]; });
  var gc = groups.map(function(g){return g[1];});
  var gv = groups.map(function(g){return g[0];});

  function encodeKickers(arr) {
    var r = 0;
    for (var i = 0; i < Math.min(arr.length, 5); i++) r |= arr[i] << (4*(4-i));
    return r;
  }

  if (isFlush && isStraight) return (8<<20) | encodeKickers([straightHigh]);
  if (gc[0]===4) return (7<<20) | encodeKickers([gv[0], gv[1]]);
  if (gc[0]===3 && gc[1]===2) return (6<<20) | encodeKickers([gv[0], gv[1]]);
  if (isFlush) return (5<<20) | encodeKickers(vals);
  if (isStraight) return (4<<20) | encodeKickers([straightHigh]);
  if (gc[0]===3) return (3<<20) | encodeKickers([gv[0]].concat(gv.slice(1).sort(function(a,b){return b-a;})));
  if (gc[0]===2 && gc[1]===2) {
    var hp = Math.max(gv[0],gv[1]), lp = Math.min(gv[0],gv[1]);
    return (2<<20) | encodeKickers([hp, lp, gv[2]]);
  }
  if (gc[0]===2) return (1<<20) | encodeKickers([gv[0]].concat(gv.slice(1).sort(function(a,b){return b-a;})));
  return (0<<20) | encodeKickers(vals);
}

function eqBestFive(cards) {
  // All C(n,5) combos, return best score
  var best = -1;
  var n = cards.length;
  for (var a=0;a<n-4;a++) for (var b=a+1;b<n-3;b++) for (var c=b+1;c<n-2;c++)
    for (var d=c+1;d<n-1;d++) for (var e=d+1;e<n;e++) {
      var s = eqEvalHand([cards[a],cards[b],cards[c],cards[d],cards[e]]);
      if (s > best) best = s;
    }
  return best;
}

function calcEquity(holeCardsMap, communityCards, activePids, numSims) {
  // Monte Carlo equity for each active player
  // holeCardsMap: {pid: ["Ah","Kd"], ...}, communityCards: ["2h","7s",...]
  // Returns {pid: 0.0-1.0, ...}
  numSims = numSims || 3000;
  if (!activePids.length) return {};

  // Check all active players have known hole cards
  var knownPids = [];
  activePids.forEach(function(pid) {
    if (holeCardsMap[pid] && holeCardsMap[pid].length === 2) knownPids.push(pid);
  });
  if (knownPids.length < 2) return {}; // need at least 2 known hands

  // Build set of known cards
  var usedSet = {};
  knownPids.forEach(function(pid) {
    holeCardsMap[pid].forEach(function(c) { usedSet[c] = true; });
  });
  communityCards.forEach(function(c) { usedSet[c] = true; });
  var remaining = FULL_DECK.filter(function(c) { return !usedSet[c]; });
  var comNeeded = 5 - communityCards.length;

  // Parse known hole cards
  var parsedHoles = {};
  knownPids.forEach(function(pid) {
    parsedHoles[pid] = holeCardsMap[pid].map(eqParseCard);
  });
  var parsedCom = communityCards.map(eqParseCard);

  var wins = {};
  knownPids.forEach(function(pid) { wins[pid] = 0; });

  // Fisher-Yates partial shuffle (only need comNeeded cards)
  var deck = remaining.slice();
  for (var sim = 0; sim < numSims; sim++) {
    // Partial shuffle: pick comNeeded cards from deck
    for (var i = 0; i < comNeeded; i++) {
      var j = i + Math.floor(Math.random() * (deck.length - i));
      var tmp = deck[i]; deck[i] = deck[j]; deck[j] = tmp;
    }
    var simCom = parsedCom.concat(deck.slice(0, comNeeded).map(eqParseCard));

    // Evaluate each player
    var bestScore = -1, bestPids = [];
    knownPids.forEach(function(pid) {
      var all7 = parsedHoles[pid].concat(simCom);
      var score = eqBestFive(all7);
      if (score > bestScore) { bestScore = score; bestPids = [pid]; }
      else if (score === bestScore) bestPids.push(pid);
    });
    // Split ties
    var share = 1.0 / bestPids.length;
    bestPids.forEach(function(pid) { wins[pid] += share; });
  }

  var result = {};
  knownPids.forEach(function(pid) { result[pid] = wins[pid] / numSims; });
  return result;
}

// Cached equity to avoid recalc on every render
var _equityCache = { key: '', equity: {} };

function getEquity() {
  // Build cache key from hole cards + community + folded
  var activePids = PIDS.filter(function(pid) {
    return S.folded.indexOf(pid) < 0 && S.busted.indexOf(pid) < 0 && S.deadSeats.indexOf(pid) < 0;
  });
  var keyParts = [];
  activePids.forEach(function(pid) {
    var h = S.holeCards[pid] || [];
    keyParts.push(pid + ':' + h.join(','));
  });
  keyParts.push('c:' + (S.communityCards || []).join(','));
  var key = keyParts.join('|');

  if (key === _equityCache.key) return _equityCache.equity;

  var eq = calcEquity(S.holeCards, S.communityCards || [], activePids);
  _equityCache = { key: key, equity: eq };
  return eq;
}

// ── Match state ──────────────────────────────────────────────────
var S = {
  matchId: '',
  models: {},
  handNumber: 0,
  totalHands: 50,
  street: 'preflop',
  pot: 0,
  blinds: [1, 2],
  stacks: {},
  communityCards: [],
  dealer: '',
  activePlayer: '',
  holeCards: {},
  folded: [],
  allIn: [],
  busted: [],
  deadSeats: [],
  lastAction: { playerId: '', action: '', amount: null },
  handStartStacks: {},
  currentHandLastPot: 0,
  currentHandLastAction: '',
  handHistory: [],
  commentary: [],
  turnCount: 0,
  violations: {},
  finished: false,
  finalScores: {},
  highlightHands: [],
  emojis: {},
  shotClock: { timeLimitMs: null, lastTurnTime: null, strikes: {}, strikeLimit: null, waitingOn: '' }
};

var rawLines = [];
var turnQueue = [];
var isReplaying = false;

// ── State machine ────────────────────────────────────────────────
function processTurn(data) {
  if (data.record_type === 'match_summary') {
    S.finished = true;
    S.finalScores = data.final_scores || {};
    S.highlightHands = data.highlight_hands || [];
    var pm = data.player_models || {};
    PIDS.forEach(function(pid) { if (pm[pid]) S.models[pid] = shortModel(pm[pid]); });
    assignEmojis();
    var snap = data.final_snapshot || {};
    if (snap.stacks && S.handStartStacks && Object.keys(S.handStartStacks).length) {
      recordHandResult(snap.stacks);
    }
    return;
  }

  S.turnCount++;
  var snap = data.state_snapshot || {};
  var playerId = data.player_id || '';
  var modelId = data.model_id || '';

  // Initialize players from first snapshot
  if (snap.stacks && !_playersInitialized) {
    initPlayers(snap.stacks);
  }

  if (!S.matchId) S.matchId = data.match_id || '';
  if (playerId && modelId) S.models[playerId] = shortModel(modelId);
  assignEmojis();

  // Shot clock
  if (data.time_limit_ms) S.shotClock.timeLimitMs = data.time_limit_ms;
  if (data.strike_limit) S.shotClock.strikeLimit = data.strike_limit;
  if (data.cumulative_strikes !== undefined && playerId) S.shotClock.strikes[playerId] = data.cumulative_strikes;
  S.shotClock.lastTurnTime = Date.now();
  S.shotClock.waitingOn = snap.active_player || S.activePlayer;

  var handNum = data.hand_number || snap.hand_number || 1;

  // Extract total hands from prompt
  var prompt = data.prompt || '';
  if (prompt) {
    var m = prompt.match(/Hand \d+ of (\d+)/);
    if (m) S.totalHands = parseInt(m[1]);
  }

  // Detect hand transition
  if (handNum > S.handNumber && S.handNumber > 0 && snap.stacks) {
    recordHandResult(snap.stacks);
  }

  // Track hand start stacks + reset hole cards on new hand
  if (handNum > S.handNumber || !Object.keys(S.handStartStacks).length) {
    S.handStartStacks = {};
    if (snap.stacks) { for (var k in snap.stacks) S.handStartStacks[k] = snap.stacks[k]; }
    PIDS.forEach(function(pid) { S.holeCards[pid] = []; });
  }

  // Hole cards from snapshot (all players at once) or fallback to prompt regex
  if (snap.hole_cards) {
    for (var hpid in snap.hole_cards) {
      if (snap.hole_cards[hpid] && snap.hole_cards[hpid].length === 2) {
        S.holeCards[hpid] = snap.hole_cards[hpid];
      }
    }
  } else if (playerId && prompt) {
    var hm = prompt.match(/Your hole cards:\s*(.+)/);
    if (hm) S.holeCards[playerId] = hm[1].trim().split(/\s+/);
  }

  // Update state
  S.handNumber = handNum;
  S.street = data.street || snap.street || 'preflop';
  S.pot = snap.pot !== undefined ? snap.pot : S.pot;
  if (snap.stacks) { S.stacks = {}; for (var sk in snap.stacks) S.stacks[sk] = snap.stacks[sk]; }
  S.communityCards = snap.community_cards || S.communityCards;
  S.dealer = snap.dealer || S.dealer;
  S.activePlayer = snap.active_player || S.activePlayer;
  if (snap.blinds) S.blinds = snap.blinds;
  S.folded = snap.folded || S.folded;
  S.allIn = snap.all_in || S.allIn;
  S.busted = snap.busted || S.busted;
  S.deadSeats = snap.dead_seats || S.deadSeats;

  // Parse action
  var parsed = data.parsed_action || {};
  var action = parsed.action || '???';
  var amount = parsed.amount;
  var violation = data.violation;

  if (data.validation_result === 'forfeit') {
    S.lastAction = { playerId: playerId, action: 'forfeit', amount: null };
  } else {
    S.lastAction = { playerId: playerId, action: action, amount: amount };
  }
  S.currentHandLastPot = snap.pot || 0;
  S.currentHandLastAction = action;

  if (violation) S.violations[playerId] = (S.violations[playerId] || 0) + 1;

  // Commentary
  var reasoning = truncateReasoning(data.reasoning_output);
  var commentAction = S.lastAction.action;
  if (data.ruling === 'eliminate_player') commentAction = 'ELIMINATED (dead seat)';
  S.commentary.push({
    turnNumber: S.turnCount, handNumber: handNum, street: S.street,
    model: modelId, playerId: playerId,
    action: commentAction, amount: S.lastAction.amount,
    reasoning: reasoning, latencyMs: data.latency_ms || 0,
    isViolation: !!violation
  });
  if (S.commentary.length > 16) S.commentary.shift();
}

function recordHandResult(newStacks) {
  if (!S.handStartStacks || !newStacks) return;
  // Find biggest winner
  var bestPid = null, bestDelta = 0;
  PIDS.forEach(function(pid) {
    var delta = (newStacks[pid] || 0) - (S.handStartStacks[pid] || 0);
    if (delta > bestDelta) { bestPid = pid; bestDelta = delta; }
  });
  if (!bestPid) return;
  var ending = S.currentHandLastAction === 'fold' ? 'fold' : 'showdown';
  S.handHistory.push({
    handNum: S.handNumber,
    winnerModel: S.models[bestPid] || LABELS[bestPid] || '?',
    winnerId: bestPid,
    margin: bestDelta,
    ending: ending,
    pot: S.currentHandLastPot
  });
  if (S.handHistory.length > 10) S.handHistory.shift();
}

// ── Rendering ────────────────────────────────────────────────────
function renderHeader() {
  var badge = document.getElementById('badge');
  badge.textContent = S.finished ? 'FINAL' : 'LIVE';
  badge.className = 'badge ' + (S.finished ? 'badge-final' : 'badge-live');

  // Build matchup string from all models
  var parts = [];
  PIDS.forEach(function(pid) {
    var emoji = S.emojis[pid] || '';
    var name = S.models[pid] || LABELS[pid] || '?';
    parts.push('<span style="color:' + COLORS[pid] + '">' + emoji + ' ' + name + '</span>');
  });
  document.getElementById('matchup').innerHTML = parts.join(' <span style="color:var(--dim)">\u00b7</span> ');

  var streetLabel = S.street.charAt(0).toUpperCase() + S.street.slice(1);
  document.getElementById('sub-info').innerHTML =
    '<strong>Hand ' + S.handNumber + ' of ' + S.totalHands + '</strong>' +
    ' <span style="color:var(--dim)">|</span> ' + streetLabel +
    ' <span style="color:var(--dim)">|</span> <span style="color:var(--yellow)">Pot: ' + S.pot + '</span>' +
    ' <span style="color:var(--dim)">|</span> Blinds: ' + S.blinds[0] + '/' + S.blinds[1];
}

function renderPlayers() {
  if (!PIDS.length) return;
  var totalChips = 0;
  PIDS.forEach(function(pid) { totalChips += (S.stacks[pid] || 0); });

  // Compute equity once for all players
  var equity = (S.street !== 'showdown' && !S.finished) ? getEquity() : {};

  PIDS.forEach(function(pid) {
    var suf = pid.replace('player_', '');
    var el = document.getElementById('section-' + suf);
    if (!el) return;
    var name = S.models[pid] || 'Player ' + LABELS[pid];
    var emoji = S.emojis[pid] || '';
    var color = COLORS[pid];
    var chips = S.stacks[pid] || 0;
    var pct = totalChips > 0 ? Math.max(1, (chips / totalChips) * 100) : 50;

    var isBusted = S.busted.indexOf(pid) >= 0;
    var isDead = S.deadSeats.indexOf(pid) >= 0;
    var isFolded = S.folded.indexOf(pid) >= 0;
    var isAllIn = S.allIn.indexOf(pid) >= 0;
    var isActive = S.activePlayer === pid;

    // Section classes
    var cls = 'player-section';
    if (isBusted) cls += ' busted';
    else if (isDead) cls += ' eliminated';
    else if (isFolded) cls += ' folded';
    if (isActive && !S.finished) cls += ' active-turn';
    el.className = cls;

    var dealerHTML = S.dealer === pid ? '<span class="dealer-btn">D</span>' : '';

    // Status tags
    var statusHTML = '';
    if (isBusted) statusHTML = '<span class="status-tag tag-busted">OUT</span>';
    else if (isDead) statusHTML = '<span class="status-tag tag-eliminated">ELIMINATED</span>';
    else if (isFolded) statusHTML = '<span class="status-tag tag-folded">FOLD</span>';
    else if (isAllIn) statusHTML = '<span class="status-tag tag-allin">ALL-IN</span>';

    // Last action badge
    var actionHTML = '';
    if (S.lastAction.playerId === pid && S.turnCount > 0 && !isBusted) {
      var a = S.lastAction.action;
      var amt = S.lastAction.amount;
      if (a === 'fold') actionHTML = '<span class="action-badge action-fold">FOLD</span>';
      else if (a === 'raise') actionHTML = '<span class="action-badge action-raise">RAISE ' + (amt || '') + '</span>';
      else if (a === 'call' && amt === 0) actionHTML = '<span class="action-badge action-check">CHECK</span>';
      else if (a === 'call') actionHTML = '<span class="action-badge action-call">CALL ' + (amt || '') + '</span>';
      else if (a === 'forfeit') actionHTML = '<span class="action-badge action-fold">FORFEIT</span>';
    }

    // Hole cards + equity (hide for busted/eliminated)
    var cards = S.holeCards[pid] || [];
    var cardsHTML = '';
    if (isBusted || isDead) {
      // No cards for eliminated players
    } else if (cards.length) {
      cardsHTML = '<div class="hole-cards">' + cards.map(function(c) { return renderCard(c); }).join('');
      // Equity badge
      if (equity[pid] !== undefined && !isFolded) {
        var eqPct = (equity[pid] * 100).toFixed(1);
        var eqCls = 'equity-badge';
        if (equity[pid] >= 0.5) eqCls += ' equity-hot';
        else if (equity[pid] < 0.15) eqCls += ' equity-cold';
        cardsHTML += '<span class="' + eqCls + '">' + eqPct + '%</span>';
      }
      cardsHTML += '</div>';
    } else if (S.handNumber > 0) {
      cardsHTML = '<div class="hole-cards">' + renderCard('??') + renderCard('??') + '</div>';
    }

    var v = S.violations[pid] || 0;
    var vHTML = v > 0 ? ' <span style="color:var(--red);font-size:10px">' + v + '\u26a0</span>' : '';

    el.innerHTML =
      '<div class="player-name" style="color:' + color + '">' + emoji + ' ' + name + dealerHTML + statusHTML + actionHTML + vHTML + '</div>' +
      '<div class="chip-bar-container">' +
        '<div class="chip-bar" style="width:' + pct + '%;background:' + color + '"></div>' +
        '<span class="chip-count" style="color:' + color + '">' + chips + '</span>' +
      '</div>' + cardsHTML;
  });
}

function renderCommunity() {
  var cc = document.getElementById('community-cards');
  var html = '';
  for (var i = 0; i < 5; i++) {
    if (i < S.communityCards.length) html += renderCard(S.communityCards[i]);
    else html += renderEmptyCard();
  }
  cc.innerHTML = html;

  var sl = document.getElementById('street-label');
  var street = S.street || 'preflop';
  sl.textContent = street.toUpperCase();
  sl.className = 'street-badge street-' + street;
  document.getElementById('pot-display').innerHTML = 'Pot: <strong>' + S.pot + '</strong>';
}

function renderHandHistory() {
  var el = document.getElementById('hand-history');
  if (!S.handHistory.length) {
    el.innerHTML = '<span style="color:var(--dim);font-style:italic">No completed hands</span>';
    return;
  }
  el.innerHTML = S.handHistory.slice().reverse().map(function(h) {
    var color = COLORS[h.winnerId] || 'var(--text)';
    var hl = S.highlightHands.indexOf(h.handNum) >= 0 ? '<span style="color:var(--yellow)">\u2605 </span>' : '';
    return '<div class="hand-entry">' +
      '<span>' + hl + 'H' + h.handNum + '</span>' +
      '<span class="hand-winner" style="color:' + color + '">' + (h.winnerModel || '?') + '</span>' +
      '<span class="hand-margin">+' + h.margin + '</span>' +
      '<span class="hand-ending">(' + h.ending + ')</span>' +
    '</div>';
  }).join('');
}

function renderCommentary() {
  var el = document.getElementById('commentary');
  if (!S.commentary.length) {
    el.innerHTML = '<span style="color:var(--dim);font-style:italic">Waiting for action...</span>';
    return;
  }
  el.innerHTML = S.commentary.slice().reverse().map(function(e) {
    var color = COLORS[e.playerId] || 'var(--dim)';
    var actionHTML;
    if (e.isViolation) actionHTML = '<span style="color:var(--red);font-weight:bold">violation!</span>';
    else if (e.action === 'fold') actionHTML = '<span style="color:var(--red)">fold</span>';
    else if (e.action === 'raise') actionHTML = '<span style="color:var(--yellow)">raise ' + (e.amount || '') + '</span>';
    else if (e.action === 'call') actionHTML = '<span style="color:var(--green)">' + (e.amount === 0 ? 'check' : 'call ' + (e.amount || '')) + '</span>';
    else actionHTML = '<span style="color:var(--dim)">' + e.action + '</span>';
    var latency = e.latencyMs > 100 ? ' <span style="color:var(--dim)">(' + (e.latencyMs/1000).toFixed(1) + 's)</span>' : '';
    var reason = e.reasoning ? '<span class="reasoning">"' + e.reasoning + '"</span>' : '';
    return '<div class="comment-entry">' +
      '<span style="color:var(--dim)">H' + e.handNumber + ' ' + e.street + '</span> ' +
      '<span style="color:' + color + ';font-weight:bold">' + e.model + '</span> ' +
      actionHTML + latency + reason + '</div>';
  }).join('');
}

function renderFinal() {
  var el = document.getElementById('final-panel');
  if (!S.finished) { el.className = 'panel'; return; }
  el.className = 'panel show';

  // Sort players by final score
  var sorted = PIDS.slice().sort(function(a, b) {
    return (S.finalScores[b] || 0) - (S.finalScores[a] || 0);
  });

  var topScore = S.finalScores[sorted[0]] || 0;
  var winners = sorted.filter(function(pid) { return (S.finalScores[pid] || 0) === topScore; });

  var html;
  if (winners.length > 1 && topScore > 0) {
    html = '<div class="winner" style="color:var(--yellow)">TIE</div>';
  } else {
    var wPid = sorted[0];
    var emoji = S.emojis[wPid] || '';
    var wName = S.models[wPid] || LABELS[wPid] || '?';
    html = '<div class="winner" style="color:' + COLORS[wPid] + '">' + emoji + ' ' + wName + ' WINS</div>';
  }

  // Standings
  html += '<div class="breakdown">';
  sorted.forEach(function(pid, i) {
    var name = S.models[pid] || LABELS[pid] || '?';
    var score = S.finalScores[pid] || 0;
    html += '<span style="color:' + COLORS[pid] + '">' + name + ': ' + score + '</span>';
    if (i < sorted.length - 1) html += ' \u00b7 ';
  });
  html += '</div>';

  var totalViolations = 0;
  PIDS.forEach(function(pid) { totalViolations += (S.violations[pid] || 0); });
  if (totalViolations > 0) {
    html += '<div class="stats" style="color:var(--red)">Violations: ';
    PIDS.forEach(function(pid) {
      var v = S.violations[pid] || 0;
      if (v > 0) html += LABELS[pid] + ':' + v + ' ';
    });
    html += '</div>';
  }
  html += '<div class="stats">' + S.handHistory.length + ' hands recorded over ' + S.turnCount + ' turns</div>';
  document.getElementById('final-content').innerHTML = html;
}

function renderShotClock() {
  var el = document.getElementById('shot-clock');
  if (!S.shotClock.timeLimitMs || S.finished) { el.style.display = 'none'; return; }
  el.style.display = 'block';
  var display = document.getElementById('clock-display');
  var label = document.getElementById('clock-label');
  var strikeEl = document.getElementById('strike-info');
  if (!S.finished && !isReplaying && S.shotClock.lastTurnTime) {
    var elapsed = Date.now() - S.shotClock.lastTurnTime;
    var remaining = Math.max(0, S.shotClock.timeLimitMs - elapsed);
    var secs = remaining / 1000;
    display.textContent = secs.toFixed(1) + 's';
    var pct = remaining / S.shotClock.timeLimitMs;
    display.className = 'clock-display ' + (pct <= 0 ? 'clock-danger' : pct < 0.17 ? 'clock-danger' : pct < 0.33 ? 'clock-warn' : 'clock-ok');
  } else {
    display.textContent = (S.shotClock.timeLimitMs / 1000).toFixed(1) + 's';
    display.className = 'clock-display clock-ok';
  }
  var waitPid = S.shotClock.waitingOn;
  var wModel = (waitPid && S.models[waitPid]) ? S.models[waitPid] : (waitPid ? LABELS[waitPid] || waitPid : '');
  label.textContent = S.finished ? 'SHOT CLOCK' : 'SHOT CLOCK \u00b7 ' + wModel;
  if (S.shotClock.strikeLimit && PIDS.length) {
    var parts = [];
    PIDS.forEach(function(pid) {
      var strikes = S.shotClock.strikes[pid] || 0;
      var name = S.models[pid] || LABELS[pid] || pid;
      parts.push('<span style="color:' + COLORS[pid] + '">' + name + ': ' + strikes + '/' + S.shotClock.strikeLimit + '</span>');
    });
    strikeEl.innerHTML = parts.join(' \u00b7 ');
  } else { strikeEl.innerHTML = ''; }
}

var _mongoStats = { connected: false, turns: 0, match_synced: false };
var _mongoLastPoll = 0;

function pollMongoStats() {
  var now = Date.now();
  if (now - _mongoLastPoll < 5000) return; // poll every 5s
  _mongoLastPoll = now;
  fetch('/mongo-stats').then(function(r) { return r.json(); }).then(function(d) {
    _mongoStats = d;
  }).catch(function() {});
}

function renderFooter() {
  pollMongoStats();
  var st = document.getElementById('status-text');
  if (S.finished) {
    st.innerHTML = '<span class="badge badge-final" style="font-size:10px">FINAL</span> Match Complete';
  } else {
    st.innerHTML = '<span class="badge badge-live" style="font-size:10px">LIVE</span> Watching...';
  }
  var lc = document.getElementById('line-count');
  var mongoHTML = '';
  if (_mongoStats.connected) {
    var syncIcon = _mongoStats.match_synced ? '\u2705' : '\u23f3';
    mongoHTML = ' <span style="color:var(--dim);margin-left:8px">Mongo: ' + _mongoStats.turns + ' turns ' + syncIcon + '</span>';
  } else {
    mongoHTML = ' <span style="color:var(--dim);margin-left:8px">Mongo: offline</span>';
  }
  lc.innerHTML = rawLines.length + ' turns' + mongoHTML;
}

function renderAll() {
  renderHeader();
  renderShotClock();
  renderPlayers();
  renderCommunity();
  renderHandHistory();
  renderCommentary();
  renderFinal();
  renderFooter();
}

// ── Copy runlog ──────────────────────────────────────────────────
function copyRunlog() {
  var btn = document.getElementById('copy-btn');
  fetch('/filepath').then(function(r) { return r.text(); }).then(function(fp) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(fp).then(function() {
        btn.classList.add('copied');
        btn.textContent = 'Copied path!';
        setTimeout(function() {
          btn.classList.remove('copied');
          btn.innerHTML = 'Copy Runlog Path <span class="count">' + rawLines.length + '</span>';
        }, 2000);
      });
    } else {
      var ta = document.createElement('textarea');
      ta.value = fp;
      ta.style.position = 'fixed';
      ta.style.left = '-9999px';
      document.body.appendChild(ta);
      ta.select();
      document.execCommand('copy');
      document.body.removeChild(ta);
      btn.classList.add('copied');
      btn.textContent = 'Copied path!';
      setTimeout(function() {
        btn.classList.remove('copied');
        btn.innerHTML = 'Copy Runlog Path <span class="count">' + rawLines.length + '</span>';
      }, 2000);
    }
  });
}

// ── SSE client ───────────────────────────────────────────────────
function startSSE() {
  var es = new EventSource('/events');
  es.onmessage = function(e) {
    var line = e.data;
    rawLines.push(line);
    try {
      var data = JSON.parse(line);
      if (isReplaying) { turnQueue.push(data); }
      else { processTurn(data); renderAll(); }
    } catch(err) {}
    document.getElementById('line-count').textContent = rawLines.length;
  };
  es.addEventListener('done', function() { es.close(); });
  es.onerror = function() {};
}

function drainQueue() {
  if (!turnQueue.length) {
    isReplaying = false;
    renderAll();
    return;
  }
  // Fast-forward: process all queued turns, render once at the end
  while (turnQueue.length) {
    processTurn(turnQueue.shift());
  }
  isReplaying = false;
  renderAll();
}

// Init
renderAll();
isReplaying = true;
turnQueue = [];
startSSE();

setTimeout(function() {
  if (turnQueue.length > 0) drainQueue();
  else isReplaying = false;
}, 300);

setInterval(function() {
  if (S.shotClock.timeLimitMs && !S.finished && !isReplaying) renderShotClock();
}, 100);

</script>
</body>
</html>"""


# ── Liar's Dice HTML/CSS/JS ───────────────────────────────────────

LIARSDICE_HTML_PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Liar's Dice Spectator</title>
<style>
:root {
  --bg: #0d1117;
  --surface: #161b22;
  --border: #30363d;
  --text: #e6edf3;
  --dim: #7d8590;
  --cyan: #58a6ff;
  --magenta: #d2a8ff;
  --green: #3fb950;
  --red: #f85149;
  --yellow: #d29922;
  --gold: #f0c040;
  --pa: #58a6ff;
  --pb: #d2a8ff;
  --pc: #3fb950;
  --pd: #d29922;
  --pe: #f97583;
  --pf: #79c0ff;
  --pg: #ffa657;
  --ph: #b392f0;
  --pi: #56d4dd;
  --pj: #e3b341;
}
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
  background: var(--bg);
  color: var(--text);
  font-family: 'SF Mono', 'Cascadia Code', 'Fira Code', 'Consolas', monospace;
  font-size: 13px;
  line-height: 1.4;
  padding: 12px;
  max-width: 1400px;
  margin: 0 auto;
}

/* Header */
#header {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 12px 16px;
  margin-bottom: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 16px;
  flex-wrap: wrap;
}
#header .badge {
  display: inline-block;
  padding: 2px 10px;
  border-radius: 4px;
  font-weight: bold;
  font-size: 12px;
}
.badge-live { background: var(--green); color: #000; animation: pulse 2s infinite; }
.badge-final { background: var(--red); color: #fff; }
@keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.6; } }
#header .title { font-size: 16px; font-weight: bold; }
#header .stats { color: var(--dim); font-size: 12px; }
.player-a { color: var(--pa); }
.player-b { color: var(--pb); }
.player-c { color: var(--pc); }
.player-d { color: var(--pd); }
.player-e { color: var(--pe); }
.player-f { color: var(--pf); }
.player-g { color: var(--pg); }
.player-h { color: var(--ph); }
.player-i { color: var(--pi); }
.player-j { color: var(--pj); }

/* Shot clock */
#shot-clock {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 8px 14px;
  margin-bottom: 10px;
  text-align: center;
  display: none;
}
#shot-clock .clock-display {
  font-size: 22px;
  font-weight: bold;
  font-variant-numeric: tabular-nums;
}
.clock-ok { color: var(--green); }
.clock-warn { color: var(--yellow); }
.clock-danger { color: var(--red); animation: pulse 1s infinite; }
#shot-clock .clock-label { color: var(--dim); font-size: 11px; margin-top: 2px; }
#shot-clock .strike-info { color: var(--dim); font-size: 11px; margin-top: 4px; }

/* Player cups grid */
#players {
  display: grid;
  gap: 8px;
  margin-bottom: 10px;
}
.cup-panel {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px 14px;
  transition: border-color 0.3s, opacity 0.3s;
  position: relative;
}
.cup-panel.active { border-color: var(--green); border-width: 2px; }
.cup-panel.eliminated { opacity: 0.35; }
.cup-panel .model-name { font-weight: bold; font-size: 13px; margin-bottom: 4px; }
.cup-panel .dice-row {
  display: flex;
  gap: 5px;
  margin: 6px 0;
  flex-wrap: wrap;
  min-height: 32px;
}
.die {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  background: var(--bg);
  border: 2px solid var(--border);
  border-radius: 5px;
  font-size: 16px;
  font-weight: bold;
}
.die.wild {
  color: var(--gold);
  border-color: var(--gold);
  background: rgba(240,192,64,0.1);
}
.die.match {
  border-color: var(--cyan);
  background: rgba(88,166,255,0.08);
}
.cup-panel .dice-tracker {
  display: flex;
  gap: 3px;
  margin-top: 6px;
}
.dice-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: var(--text);
  transition: opacity 0.3s;
}
.dice-dot.lost { opacity: 0.15; }
.cup-panel .bluff-rate { font-size: 11px; color: var(--dim); margin-top: 4px; }

/* Current bid panel */
#bid-panel {
  background: var(--surface);
  border: 2px solid var(--border);
  border-radius: 8px;
  padding: 14px 18px;
  margin-bottom: 10px;
  text-align: center;
  min-height: 70px;
  transition: border-color 0.3s;
}
#bid-panel.bid-true { border-color: var(--green); }
#bid-panel.bid-bluff { border-color: var(--red); }
#bid-panel .bid-text { font-size: 22px; font-weight: bold; margin-bottom: 4px; }
#bid-panel .bid-truth { font-size: 13px; margin-top: 4px; }
.truth-true { color: var(--green); }
.truth-bluff { color: var(--red); }

/* Probability bar */
#prob-bar {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px 14px;
  margin-bottom: 10px;
}
#prob-bar .prob-label { font-size: 12px; color: var(--dim); margin-bottom: 4px; }
#prob-bar .bar-track {
  height: 18px;
  background: var(--bg);
  border-radius: 4px;
  overflow: hidden;
  position: relative;
}
#prob-bar .bar-fill {
  height: 100%;
  border-radius: 4px;
  transition: width 0.3s, background 0.3s;
}
#prob-bar .bar-value {
  position: absolute;
  right: 8px;
  top: 0;
  line-height: 18px;
  font-size: 11px;
  font-weight: bold;
  color: var(--text);
}

/* Main content grid: bid ladder + elimination log */
#content-grid {
  display: grid;
  grid-template-columns: 1fr 240px;
  gap: 10px;
  margin-bottom: 10px;
}
@media (max-width: 800px) {
  #content-grid { grid-template-columns: 1fr; }
}

/* Bid ladder */
#bid-ladder {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px 14px;
  max-height: 300px;
  overflow-y: auto;
}
#bid-ladder .ladder-title { font-weight: bold; margin-bottom: 6px; color: var(--dim); font-size: 11px; text-transform: uppercase; letter-spacing: 1px; }
.bid-entry {
  padding: 3px 0;
  font-size: 12px;
  display: flex;
  align-items: center;
  gap: 6px;
}
.bid-entry.current { font-weight: bold; }
.bid-entry .arrow { color: var(--yellow); }
.bid-entry .truth-mark { font-size: 11px; margin-left: auto; }
.bid-entry .truth-mark.true { color: var(--green); }
.bid-entry .truth-mark.false { color: var(--red); }

/* Elimination log + dice lost */
#sidebar {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.sidebar-panel {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px 14px;
}
.sidebar-panel .panel-title { font-weight: bold; margin-bottom: 6px; color: var(--dim); font-size: 11px; text-transform: uppercase; letter-spacing: 1px; }
.sidebar-panel .entry { font-size: 12px; padding: 2px 0; }
.sidebar-panel .dice-summary { font-size: 12px; padding: 2px 0; display: flex; gap: 4px; align-items: center; }

/* Commentary */
#commentary {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px 14px;
  margin-bottom: 10px;
  max-height: 300px;
  overflow-y: auto;
}
#commentary .panel-title { font-weight: bold; margin-bottom: 6px; color: var(--dim); font-size: 11px; text-transform: uppercase; letter-spacing: 1px; }
.comment-entry {
  padding: 4px 0;
  font-size: 12px;
  border-bottom: 1px solid var(--border);
}
.comment-entry:last-child { border-bottom: none; }
.comment-entry .action-text { }
.comment-entry .reasoning { color: var(--dim); font-style: italic; margin-top: 2px; font-size: 11px; }
.comment-entry .bluff-tag { color: var(--red); font-weight: bold; font-size: 10px; }
.comment-entry .latency { color: var(--dim); font-size: 10px; }

/* Challenge reveal */
#challenge-reveal {
  background: var(--surface);
  border: 2px solid var(--yellow);
  border-radius: 8px;
  padding: 14px 18px;
  margin-bottom: 10px;
  display: none;
  text-align: center;
}
#challenge-reveal .reveal-title { font-size: 16px; font-weight: bold; margin-bottom: 8px; color: var(--yellow); }
#challenge-reveal .reveal-detail { font-size: 13px; margin: 4px 0; }
#challenge-reveal .reveal-result { font-size: 15px; font-weight: bold; margin-top: 8px; }
.reveal-correct { color: var(--green); }
.reveal-wrong { color: var(--red); }

/* Final results */
#final-results {
  background: var(--surface);
  border: 2px solid var(--green);
  border-radius: 8px;
  padding: 16px;
  margin-bottom: 10px;
  text-align: center;
  display: none;
}
#final-results .final-title { font-size: 18px; font-weight: bold; margin-bottom: 8px; }
#final-results .final-scores { font-size: 14px; }
#final-results .winner { color: var(--green); font-weight: bold; }

/* Footer */
#footer {
  text-align: center;
  color: var(--dim);
  font-size: 11px;
  padding: 8px 0;
}

/* Replay controls */
#replay-controls {
  position: fixed; bottom: 12px; right: 12px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 6px 10px;
  display: flex; gap: 6px; align-items: center;
  z-index: 100;
}
#replay-controls button {
  background: var(--bg); color: var(--text); border: 1px solid var(--border);
  border-radius: 4px; padding: 4px 10px; cursor: pointer; font-size: 12px;
  font-family: inherit;
}
#replay-controls button:hover { border-color: var(--cyan); }
#replay-controls button.active { background: var(--cyan); color: #000; }
#replay-controls .speed-label { color: var(--dim); font-size: 11px; }
</style>
</head>
<body>

<div id="header">
  <span id="badge" class="badge badge-live">LIVE</span>
  <span id="mode-badge" class="badge" style="background:var(--magenta);color:#000;display:none"></span>
  <span class="title">LIAR'S DICE</span>
  <span id="round-info" class="stats">Round 1 | 20 dice in play | 0 eliminated</span>
</div>

<div id="shot-clock">
  <div id="clock-display" class="clock-display clock-ok">30.0s</div>
  <div id="clock-label" class="clock-label">SHOT CLOCK</div>
  <div id="strike-info" class="strike-info"></div>
</div>

<div id="players"></div>

<div id="bid-panel">
  <div class="bid-text" id="bid-text">Waiting for first bid...</div>
  <div class="bid-truth" id="bid-truth"></div>
</div>

<div id="prob-bar">
  <div class="prob-label" id="prob-label">P(bid is true)</div>
  <div class="bar-track">
    <div class="bar-fill" id="bar-fill" style="width:0%"></div>
    <span class="bar-value" id="bar-value">—</span>
  </div>
</div>

<div id="challenge-reveal"></div>

<div id="content-grid">
  <div id="bid-ladder">
    <div class="ladder-title">Bid Ladder</div>
    <div id="ladder-entries"></div>
  </div>
  <div id="sidebar">
    <div class="sidebar-panel">
      <div class="panel-title">Elimination Log</div>
      <div id="elim-log"></div>
    </div>
    <div class="sidebar-panel">
      <div class="panel-title">Dice Remaining</div>
      <div id="dice-remaining"></div>
    </div>
  </div>
</div>

<div id="commentary">
  <div class="panel-title">Commentary</div>
  <div id="comment-entries"></div>
</div>

<div id="final-results">
  <div class="final-title" id="final-title"></div>
  <div class="final-scores" id="final-scores"></div>
</div>

<div id="footer">Liar's Dice Spectator &middot; God Mode</div>

<div id="replay-controls">
  <button id="btn-pause">&#x23F8;</button>
  <button id="btn-step">&gt;</button>
  <button id="btn-speed" class="speed-label">1x</button>
  <button id="btn-restart">&#x21BA;</button>
</div>

<script>
// ── State ─────────────────────────────────────────────────────────
var PIDS = [];
var LABELS = {};
var CLASS_NAMES = {};
var SUFFIXES = {};
var _playersInitialized = false;
var FACE_NAMES = {1:'ones',2:'twos',3:'threes',4:'fours',5:'fives',6:'sixes'};

var S = {
  finished: false,
  finalScores: {},
  models: {},
  round: 1,
  turnNumber: 0,
  turnCount: 0,
  totalDice: 0,
  diceCounts: {},
  allDice: {},
  currentBid: null,
  bidHistory: [],
  wildsActive: true,
  eliminated: [],
  activePlayer: '',
  matchScores: {},
  playerStats: {},
  challengeResult: null,
  roundHistory: [],
  gameNumber: 1,
  gamesPerMatch: 1,
  startingDice: 5,
  // commentary log
  commentLog: [],
  // shot clock
  shotClock: { timeLimitMs: 0, lastTurnTime: 0, waitingOn: '', strikes: {}, strikeLimit: 0 },
  violations: {},
  lastReasoning: '',
  lastModel: '',
};

// Player colors
var PLAYER_COLORS = ['--pa','--pb','--pc','--pd','--pe','--pf','--pg','--ph','--pi','--pj'];

function initPlayers(diceCounts) {
  PIDS = Object.keys(diceCounts).sort();
  var grid = document.getElementById('players');
  grid.innerHTML = '';
  var cols = Math.min(PIDS.length, 5);
  grid.style.gridTemplateColumns = 'repeat(' + cols + ', 1fr)';

  var letters = 'ABCDEFGHIJ';
  PIDS.forEach(function(pid, i) {
    LABELS[pid] = letters[i];
    CLASS_NAMES[pid] = 'player-' + letters[i].toLowerCase();
    SUFFIXES[pid] = letters[i].toLowerCase();

    var panel = document.createElement('div');
    panel.className = 'cup-panel';
    panel.id = 'cup-' + SUFFIXES[pid];
    panel.innerHTML =
      '<div class="model-name ' + CLASS_NAMES[pid] + '" id="name-' + SUFFIXES[pid] + '">Player ' + LABELS[pid] + '</div>' +
      '<div class="dice-row" id="dice-' + SUFFIXES[pid] + '"></div>' +
      '<div class="dice-tracker" id="tracker-' + SUFFIXES[pid] + '"></div>' +
      '<div class="bluff-rate" id="bluff-' + SUFFIXES[pid] + '"></div>';
    grid.appendChild(panel);
  });
  _playersInitialized = true;
}

// ── Replay machinery ──────────────────────────────────────────────
var allEvents = [];
var replayIdx = 0;
var isReplaying = false;
var isPaused = false;
var playbackSpeed = 1;
var playTimer = null;
var speeds = [0.25, 0.5, 1, 2, 4, 8];
var speedIdx = 2;

function resetState() {
  _playersInitialized = false;
  S.finished = false; S.finalScores = {}; S.models = {};
  S.round = 1; S.turnNumber = 0; S.turnCount = 0;
  S.totalDice = 0; S.diceCounts = {}; S.allDice = {};
  S.currentBid = null; S.bidHistory = []; S.wildsActive = true;
  S.eliminated = []; S.activePlayer = ''; S.matchScores = {};
  S.playerStats = {}; S.challengeResult = null; S.roundHistory = [];
  S.gameNumber = 1; S.gamesPerMatch = 1; S.startingDice = 5; S.mode = 'attrition'; S.commentLog = [];
  S.shotClock = { timeLimitMs: 0, lastTurnTime: 0, waitingOn: '', strikes: {}, strikeLimit: 0 };
  S.violations = {}; S.lastReasoning = ''; S.lastModel = '';
  document.getElementById('players').innerHTML = '';
}

function startReplay() {
  isReplaying = true;
  replayIdx = 0;
  resetState();
  scheduleNext();
}

function scheduleNext() {
  if (isPaused || replayIdx >= allEvents.length) return;
  var base = allEvents[replayIdx].record_type === 'match_summary' ? 400 : 80;
  var delay = base / playbackSpeed;
  playTimer = setTimeout(function() {
    processEvent(allEvents[replayIdx]);
    renderAll();
    replayIdx++;
    if (replayIdx < allEvents.length) scheduleNext();
    else { isReplaying = false; renderShotClock(); }
  }, delay);
}

document.getElementById('btn-pause').onclick = function() {
  isPaused = !isPaused;
  this.textContent = isPaused ? '\u25B6' : '\u23F8';
  if (!isPaused) scheduleNext();
  else clearTimeout(playTimer);
};
document.getElementById('btn-step').onclick = function() {
  isPaused = true;
  document.getElementById('btn-pause').textContent = '\u25B6';
  clearTimeout(playTimer);
  if (replayIdx < allEvents.length) {
    processEvent(allEvents[replayIdx]);
    renderAll();
    replayIdx++;
  }
};
document.getElementById('btn-speed').onclick = function() {
  speedIdx = (speedIdx + 1) % speeds.length;
  playbackSpeed = speeds[speedIdx];
  this.textContent = playbackSpeed + 'x';
};
document.getElementById('btn-restart').onclick = function() {
  clearTimeout(playTimer);
  isPaused = false;
  document.getElementById('btn-pause').textContent = '\u23F8';
  startReplay();
};

// ── Binomial probability ──────────────────────────────────────────
function binomPmf(k, n, p) {
  if (k < 0 || k > n) return 0;
  var coeff = 1;
  for (var i = 0; i < k; i++) coeff = coeff * (n - i) / (i + 1);
  return coeff * Math.pow(p, k) * Math.pow(1 - p, n - k);
}

function bidProbability(bidQty, bidFace, ownDice, totalDice, wildsActive) {
  var known = 0;
  ownDice.forEach(function(d) {
    if (d === bidFace) known++;
    else if (d === 1 && wildsActive && bidFace !== 1) known++;
  });
  var needed = bidQty - known;
  if (needed <= 0) return 1.0;
  var unknown = totalDice - ownDice.length;
  if (unknown <= 0) return 0.0;
  var p = (wildsActive && bidFace !== 1) ? 1/3 : 1/6;
  var probLess = 0;
  for (var k = 0; k < needed; k++) probLess += binomPmf(k, unknown, p);
  return 1.0 - probLess;
}

// ── Event processing ──────────────────────────────────────────────
function processEvent(data) {
  if (data.record_type === 'match_summary') {
    S.finished = true;
    S.finalScores = data.final_scores || {};
    var pm = data.player_models || {};
    PIDS.forEach(function(pid) { if (pm[pid]) S.models[pid] = pm[pid]; });
    return;
  }

  S.turnCount++;
  var snap = data.state_snapshot || {};
  var pid = data.player_id || '';
  var mid = data.model_id || '';

  if (snap.dice_counts && !_playersInitialized) initPlayers(snap.dice_counts);
  if (pid && mid) S.models[pid] = mid;

  // Populate all player models from snapshot (available from first turn)
  var pm2 = snap.player_models || {};
  Object.keys(pm2).forEach(function(k) { if (!S.models[k]) S.models[k] = pm2[k]; });

  // Shot clock
  if (data.time_limit_ms) S.shotClock.timeLimitMs = data.time_limit_ms;
  if (data.strike_limit) S.shotClock.strikeLimit = data.strike_limit;
  if (data.cumulative_strikes !== undefined && pid) S.shotClock.strikes[pid] = data.cumulative_strikes;
  S.shotClock.lastTurnTime = Date.now();
  S.shotClock.waitingOn = snap.active_player || S.activePlayer;

  S.gameNumber = snap.game_number || S.gameNumber;
  S.gamesPerMatch = snap.games_per_match || S.gamesPerMatch;
  if (snap.starting_dice) S.startingDice = snap.starting_dice;
  if (snap.mode) S.mode = snap.mode;
  S.round = snap.round || S.round;
  S.turnNumber = snap.turn_number || S.turnNumber;
  S.totalDice = snap.total_dice || S.totalDice;
  S.diceCounts = snap.dice_counts || S.diceCounts;
  S.allDice = snap.all_dice || S.allDice;
  S.currentBid = snap.current_bid || null;
  S.bidHistory = snap.bid_history || S.bidHistory;
  S.wildsActive = snap.wilds_active !== undefined ? snap.wilds_active : S.wildsActive;
  S.eliminated = snap.eliminated || S.eliminated;
  S.activePlayer = snap.active_player || S.activePlayer;
  S.matchScores = snap.match_scores || S.matchScores;
  S.playerStats = snap.player_stats || S.playerStats;
  if (snap.challenge_result) S.challengeResult = snap.challenge_result;
  if (snap.round_history) S.roundHistory = snap.round_history;

  // Build commentary entry
  var parsed = data.parsed_action || {};
  var reasoning = data.reasoning_output || '';
  if (reasoning) {
    S.lastReasoning = reasoning.length > 200 ? reasoning.substring(0, 197) + '...' : reasoning;
    S.lastModel = mid;
  }

  var comment = {
    round: S.round,
    player: pid,
    model: mid || S.models[pid] || '',
    action: parsed.action || '',
    quantity: parsed.quantity,
    face: parsed.face,
    latency: data.latency_ms ? (data.latency_ms / 1000).toFixed(1) : '?',
    reasoning: reasoning ? (reasoning.length > 150 ? reasoning.substring(0, 147) + '...' : reasoning) : '',
    violation: data.violation || null,
    isBluff: false,
  };

  // Annotate bluffs for god mode
  if (parsed.action === 'bid' && snap.bid_history && snap.bid_history.length) {
    var lastBid = snap.bid_history[snap.bid_history.length - 1];
    if (lastBid && lastBid.is_bluff) comment.isBluff = true;
  }

  if (parsed.action === 'liar' && snap.challenge_result) {
    comment.challengeResult = snap.challenge_result;
  }

  S.commentLog.push(comment);

  if (data.violation && pid) S.violations[pid] = (S.violations[pid] || 0) + 1;
}

// ── Rendering ─────────────────────────────────────────────────────
function renderAll() {
  if (!_playersInitialized) return;
  renderHeader();
  renderShotClock();
  renderPlayers();
  renderBidPanel();
  renderProbBar();
  renderChallengeReveal();
  renderBidLadder();
  renderSidebar();
  renderCommentary();
  renderFinal();
}

function renderShotClock() {
  var el = document.getElementById('shot-clock');
  if (!S.shotClock.timeLimitMs) return;
  el.style.display = 'block';
  var display = document.getElementById('clock-display');
  var label = document.getElementById('clock-label');
  var strikeEl = document.getElementById('strike-info');
  if (S.shotClock.lastTurnTime && !isReplaying) {
    var elapsed = Date.now() - S.shotClock.lastTurnTime;
    var remaining = Math.max(0, S.shotClock.timeLimitMs - elapsed);
    var secs = remaining / 1000;
    display.textContent = secs.toFixed(1) + 's';
    var cls = 'clock-display ';
    if (remaining <= 5000) cls += 'clock-danger';
    else if (remaining <= 10000) cls += 'clock-warn';
    else cls += 'clock-ok';
    display.className = cls;
  } else {
    display.textContent = (S.shotClock.timeLimitMs / 1000).toFixed(1) + 's';
    display.className = 'clock-display clock-ok';
  }
  var wModel = S.models[S.shotClock.waitingOn] || S.shotClock.waitingOn;
  label.innerHTML = 'SHOT CLOCK <span style="color:var(--dim)">&middot;</span> ' + wModel;
  if (S.shotClock.strikeLimit) {
    var parts = [];
    PIDS.forEach(function(pid) {
      var s = S.shotClock.strikes[pid] || 0;
      var m = S.models[pid] || LABELS[pid];
      parts.push('<span class="' + CLASS_NAMES[pid] + '">' + m + ': ' + s + '/' + S.shotClock.strikeLimit + '</span>');
    });
    strikeEl.innerHTML = parts.join(' &middot; ');
  }
  if (S.finished) el.style.display = 'none';
}

function renderHeader() {
  var badge = document.getElementById('badge');
  badge.textContent = S.finished ? 'FINAL' : 'LIVE';
  badge.className = 'badge ' + (S.finished ? 'badge-final' : 'badge-live');

  var modeBadge = document.getElementById('mode-badge');
  modeBadge.textContent = S.mode.toUpperCase();
  modeBadge.style.display = 'inline-block';

  var elimCount = S.eliminated.length;
  var info = 'Round ' + S.round;
  if (S.gamesPerMatch > 1) info = 'Game ' + S.gameNumber + ' | ' + info;
  info += ' | ' + S.totalDice + ' dice in play | ' + elimCount + ' eliminated';
  document.getElementById('round-info').textContent = info;
}

function renderPlayers() {
  PIDS.forEach(function(pid) {
    var suf = SUFFIXES[pid];
    var panel = document.getElementById('cup-' + suf);
    if (!panel) return;

    var isElim = S.eliminated.indexOf(pid) >= 0;
    var isActive = (S.activePlayer === pid && !S.finished);
    panel.className = 'cup-panel' + (isActive ? ' active' : '') + (isElim ? ' eliminated' : '');

    // Model name
    var model = S.models[pid] || ('Player ' + LABELS[pid]);
    var nameEl = document.getElementById('name-' + suf);
    nameEl.innerHTML = '<span class="' + CLASS_NAMES[pid] + '">' + LABELS[pid] + '</span> ' + model;

    // Dice display (god mode: show actual values)
    var diceEl = document.getElementById('dice-' + suf);
    var dice = S.allDice[pid] || [];
    var bidFace = S.currentBid ? S.currentBid.face : 0;
    var html = '';
    dice.forEach(function(d) {
      var cls = 'die';
      if (d === 1 && S.wildsActive) cls += ' wild';
      if (d === bidFace || (d === 1 && S.wildsActive && bidFace !== 1 && bidFace > 0)) cls += ' match';
      html += '<div class="' + cls + '">' + d + '</div>';
    });
    if (isElim) html = '<span style="color:var(--dim)">ELIMINATED</span>';
    diceEl.innerHTML = html;

    // Dice tracker (filled/empty dots)
    var trackerEl = document.getElementById('tracker-' + suf);
    var startDice = S.startingDice;

    var current = S.diceCounts[pid] || 0;
    var dots = '';
    for (var i = 0; i < startDice; i++) {
      dots += '<div class="dice-dot' + (i >= current ? ' lost' : '') + '"></div>';
    }
    trackerEl.innerHTML = dots;

    // Bluff rate
    var bluffEl = document.getElementById('bluff-' + suf);
    var stats = S.playerStats[pid] || {};
    var totalBids = stats.total_bids || 0;
    var bluffBids = stats.bluff_bids || 0;
    var rate = totalBids > 0 ? Math.round(100 * bluffBids / totalBids) : 0;
    var challengeInfo = '';
    if (stats.challenges_made > 0) {
      challengeInfo = ' | Challenges: ' + stats.challenges_won + '/' + stats.challenges_made;
    }
    bluffEl.innerHTML = 'Bluff: ' + rate + '% (' + bluffBids + '/' + totalBids + ')' + challengeInfo;
  });
}

function renderBidPanel() {
  var panel = document.getElementById('bid-panel');
  var textEl = document.getElementById('bid-text');
  var truthEl = document.getElementById('bid-truth');

  if (!S.currentBid) {
    panel.className = 'bid-panel';
    // Check if we just had a challenge (bid is null because new round started)
    if (S.challengeResult) {
      var cr = S.challengeResult;
      var cModel = S.models[cr.challenger] || cr.challenger;
      var bModel = S.models[cr.bidder] || cr.bidder;
      var lModel = S.models[cr.loser] || cr.loser;
      textEl.innerHTML = 'CHALLENGE RESOLVED';
      var detail = cModel + ' challenged ' + bModel + '\'s bid of ' +
        cr.bid.quantity + ' ' + FACE_NAMES[cr.bid.face] + ' &mdash; ';
      if (cr.bid_was_correct) {
        detail += '<span class="truth-true">BID WAS CORRECT (' + cr.actual_count + ' found)</span>';
        panel.className = 'bid-panel bid-true';
      } else {
        detail += '<span class="truth-bluff">BID WAS WRONG (' + cr.actual_count + ' found)</span>';
        panel.className = 'bid-panel bid-bluff';
      }
      detail += ' &mdash; <strong>' + lModel + ' loses a die</strong>';
      if (cr.eliminated) detail += ' <span style="color:var(--red)">(ELIMINATED)</span>';
      truthEl.innerHTML = detail;
    } else {
      textEl.textContent = 'Waiting for first bid...';
      truthEl.textContent = '';
    }
    return;
  }

  var bid = S.currentBid;
  var bidder = S.models[bid.bidder] || bid.bidder;
  var bidderClass = CLASS_NAMES[bid.bidder] || '';
  textEl.innerHTML = '<span class="' + bidderClass + '">' + bidder + '</span> bids: ' +
    '<strong>' + bid.quantity + ' ' + FACE_NAMES[bid.face].toUpperCase() + '</strong>';

  // God mode: show actual count
  var actual = countFace(bid.face);
  var isTrue = actual >= bid.quantity;
  panel.className = isTrue ? 'bid-panel bid-true' : 'bid-panel bid-bluff';

  // Show breakdown
  var faceCount = 0;
  var wildCount = 0;
  PIDS.forEach(function(pid) {
    (S.allDice[pid] || []).forEach(function(d) {
      if (d === bid.face) faceCount++;
      else if (d === 1 && S.wildsActive && bid.face !== 1) wildCount++;
    });
  });

  var truthHTML = 'Actual: <strong>' + faceCount + '</strong> ' + FACE_NAMES[bid.face];
  if (S.wildsActive && bid.face !== 1) {
    truthHTML += ' + <strong style="color:var(--gold)">' + wildCount + '</strong> wilds';
  }
  truthHTML += ' = <strong>' + actual + ' total</strong> ';
  if (isTrue) {
    truthHTML += '<span class="truth-true">BID IS TRUE</span>';
  } else {
    truthHTML += '<span class="truth-bluff">BLUFF (' + actual + ' < ' + bid.quantity + ')</span>';
  }
  truthEl.innerHTML = truthHTML;
}

function countFace(face) {
  var count = 0;
  PIDS.forEach(function(pid) {
    (S.allDice[pid] || []).forEach(function(d) {
      if (d === face) count++;
      else if (d === 1 && S.wildsActive && face !== 1) count++;
    });
  });
  return count;
}

function renderProbBar() {
  var label = document.getElementById('prob-label');
  var fill = document.getElementById('bar-fill');
  var value = document.getElementById('bar-value');

  if (!S.currentBid) {
    label.textContent = 'P(bid is true) — no active bid';
    fill.style.width = '0%';
    fill.style.background = 'var(--dim)';
    value.textContent = '—';
    return;
  }

  // Calculate probability for the active player (spectator perspective: use empty own_dice)
  // Actually for god mode we can show true probability or naive probability
  // Let's show naive probability (what a player would estimate with no info)
  var bid = S.currentBid;
  var prob = bidProbability(bid.quantity, bid.face, [], S.totalDice, S.wildsActive);
  var pct = Math.round(prob * 1000) / 10;

  label.innerHTML = 'Current bid "' + bid.quantity + ' ' + FACE_NAMES[bid.face] + '" &mdash; P(true) = <strong>' + pct.toFixed(1) + '%</strong>' +
    '  <span style="color:var(--dim)">Based on: ' + S.totalDice + ' total dice, wilds ' + (S.wildsActive ? 'active' : 'OFF') + '</span>';

  fill.style.width = pct + '%';
  if (pct >= 60) fill.style.background = 'var(--green)';
  else if (pct >= 30) fill.style.background = 'var(--yellow)';
  else fill.style.background = 'var(--red)';

  value.textContent = pct.toFixed(1) + '%';
}

function renderChallengeReveal() {
  var el = document.getElementById('challenge-reveal');
  if (!S.challengeResult || S.currentBid) {
    el.style.display = 'none';
    return;
  }
  var cr = S.challengeResult;
  el.style.display = 'block';

  var challengerModel = S.models[cr.challenger] || cr.challenger;
  var bidderModel = S.models[cr.bidder] || cr.bidder;
  var challengerClass = CLASS_NAMES[cr.challenger] || '';
  var bidderClass = CLASS_NAMES[cr.bidder] || '';

  var html = '<div class="reveal-title">CHALLENGE!</div>';
  html += '<div class="reveal-detail"><span class="' + challengerClass + '">' + challengerModel +
    '</span> calls LIAR on <span class="' + bidderClass + '">' + bidderModel + '</span></div>';
  html += '<div class="reveal-detail">Bid: <strong>' + cr.bid.quantity + ' ' + FACE_NAMES[cr.bid.face] + '</strong></div>';

  // Show actual count with breakdown
  html += '<div class="reveal-detail">Actual: ' + cr.face_count + ' ' + FACE_NAMES[cr.bid.face];
  if (cr.wilds_counted > 0) html += ' + ' + cr.wilds_counted + ' wilds';
  html += ' = <strong>' + cr.actual_count + ' total</strong></div>';

  var loserModel = S.models[cr.loser] || cr.loser;
  var loserClass = CLASS_NAMES[cr.loser] || '';
  if (cr.bid_was_correct) {
    html += '<div class="reveal-result reveal-wrong">Bid was CORRECT &mdash; <span class="' + loserClass + '">' + loserModel + '</span> loses a die!</div>';
  } else {
    html += '<div class="reveal-result reveal-correct">Bid was WRONG &mdash; <span class="' + loserClass + '">' + loserModel + '</span> loses a die!</div>';
  }
  if (cr.die_gained_by) {
    var winnerModel = S.models[cr.die_gained_by] || cr.die_gained_by;
    var winnerClass = CLASS_NAMES[cr.die_gained_by] || '';
    html += '<div style="color:var(--magenta);margin-top:4px"><span class="' + winnerClass + '">' + winnerModel + '</span> gains a die!</div>';
  }
  if (cr.eliminated) html += '<div style="color:var(--red);font-weight:bold;margin-top:4px">' + loserModel + ' ELIMINATED</div>';

  el.innerHTML = html;
}

function renderBidLadder() {
  var entries = document.getElementById('ladder-entries');
  var html = '';
  var history = S.bidHistory || [];

  if (history.length === 0 && S.challengeResult && !S.currentBid) {
    // Just had a challenge, show last round's bids from roundHistory
    if (S.roundHistory && S.roundHistory.length) {
      var lastRound = S.roundHistory[S.roundHistory.length - 1];
      history = lastRound.bids || [];
      html += '<div style="color:var(--dim);font-size:11px;margin-bottom:4px">Previous round:</div>';
    }
  }

  history.forEach(function(bid, i) {
    var isCurrent = (i === history.length - 1) && S.currentBid;
    var model = S.models[bid.player] || LABELS[bid.player] || bid.player;
    var cls = CLASS_NAMES[bid.player] || '';
    var arrow = isCurrent ? '<span class="arrow">&rarr;</span>' : '&nbsp;&nbsp;';
    var truthMark = '';
    if (bid.is_bluff !== undefined) {
      if (bid.is_bluff) truthMark = '<span class="truth-mark false">&times; bluff</span>';
      else truthMark = '<span class="truth-mark true">&check; true</span>';
    }
    html += '<div class="bid-entry' + (isCurrent ? ' current' : '') + '">' +
      arrow + ' <span class="' + cls + '">' + model + '</span>: ' +
      bid.quantity + ' ' + FACE_NAMES[bid.face] + truthMark + '</div>';
  });

  if (html === '') html = '<div style="color:var(--dim)">No bids yet this round</div>';
  entries.innerHTML = html;
}

function renderSidebar() {
  // Elimination log
  var elimEl = document.getElementById('elim-log');
  var elimHtml = '';
  S.eliminated.forEach(function(pid, i) {
    var model = S.models[pid] || LABELS[pid] || pid;
    var cls = CLASS_NAMES[pid] || '';
    elimHtml += '<div class="entry"><span class="' + cls + '">' + model + '</span></div>';
  });
  if (!elimHtml) elimHtml = '<div class="entry" style="color:var(--dim)">None yet</div>';
  elimEl.innerHTML = elimHtml;

  // Dice remaining
  var diceEl = document.getElementById('dice-remaining');
  var diceHtml = '';
  PIDS.forEach(function(pid) {
    var model = S.models[pid] || LABELS[pid];
    var cls = CLASS_NAMES[pid] || '';
    var count = S.diceCounts[pid] || 0;
    var isElim = S.eliminated.indexOf(pid) >= 0;
    var startDice = S.startingDice;
    var dots = '';
    for (var i = 0; i < startDice; i++) {
      dots += '<span style="display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:2px;' +
        'background:' + (i < count ? 'var(' + PLAYER_COLORS[PIDS.indexOf(pid)] + ')' : 'var(--border)') + '"></span>';
    }
    diceHtml += '<div class="dice-summary' + (isElim ? ' style="opacity:0.35"' : '') + '">' +
      '<span class="' + cls + '" style="width:20px;display:inline-block">' + LABELS[pid] + '</span> ' +
      dots + ' <span style="color:var(--dim)">(' + count + ')</span></div>';
  });
  diceEl.innerHTML = diceHtml;
}

function renderCommentary() {
  var el = document.getElementById('comment-entries');
  var html = '';
  var entries = S.commentLog.slice(-20);
  entries.forEach(function(c) {
    var cls = '';
    PIDS.forEach(function(pid) { if (pid === c.player) cls = CLASS_NAMES[pid]; });
    var model = c.model || S.models[c.player] || c.player;

    html += '<div class="comment-entry">';
    html += '<span style="color:var(--dim)">R' + c.round + '</span> ';
    html += '<span class="' + cls + '">' + model + '</span> ';

    if (c.action === 'bid') {
      html += 'bids <strong>' + c.quantity + ' ' + FACE_NAMES[c.face] + '</strong>';
      html += ' <span class="latency">(' + c.latency + 's)</span>';
      if (c.isBluff) html += ' <span class="bluff-tag">&larr; BLUFF</span>';
    } else if (c.action === 'liar') {
      html += 'calls <strong>LIAR!</strong>';
      html += ' <span class="latency">(' + c.latency + 's)</span>';
      if (c.challengeResult) {
        var cr = c.challengeResult;
        if (cr.bid_was_correct) {
          html += ' &mdash; <span style="color:var(--red)">Wrong call! (' + cr.actual_count + ' found)</span>';
        } else {
          html += ' &mdash; <span style="color:var(--green)">Caught! (' + cr.actual_count + ' found, bid was ' + cr.bid.quantity + ')</span>';
        }
      }
    } else if (c.violation) {
      html += '<span style="color:var(--red)">VIOLATION: ' + c.violation + '</span>';
    }

    if (c.reasoning) {
      html += '<div class="reasoning">"' + c.reasoning + '"</div>';
    }
    html += '</div>';
  });

  el.innerHTML = html;
  el.scrollTop = el.scrollHeight;
}

function renderFinal() {
  var el = document.getElementById('final-results');
  if (!S.finished) { el.style.display = 'none'; return; }
  el.style.display = 'block';

  var scores = S.finalScores || S.matchScores;
  var title = document.getElementById('final-title');

  // Find winner (highest score)
  var maxScore = -1;
  var winner = '';
  PIDS.forEach(function(pid) {
    var sc = scores[pid] || 0;
    if (sc > maxScore) { maxScore = sc; winner = pid; }
  });

  var winnerModel = S.models[winner] || winner;
  title.innerHTML = '<span class="' + CLASS_NAMES[winner] + '">' + winnerModel + '</span> WINS!';

  var scoresHtml = '';
  // Sort by score descending
  var sorted = PIDS.slice().sort(function(a, b) { return (scores[b] || 0) - (scores[a] || 0); });
  sorted.forEach(function(pid, i) {
    var model = S.models[pid] || LABELS[pid];
    var sc = scores[pid] || 0;
    var cls = CLASS_NAMES[pid] || '';
    var prefix = i === 0 ? '<span class="winner">' : '<span>';
    scoresHtml += '<div>' + prefix + (i + 1) + '. <span class="' + cls + '">' + model + '</span>: ' + Math.round(sc) + ' pts</span></div>';
  });
  document.getElementById('final-scores').innerHTML = scoresHtml;
}

// ── EventSource ───────────────────────────────────────────────────
var evtPath = '/events';
if (window.MATCH_ID) evtPath = '/events/' + window.MATCH_ID;
var es = new EventSource(evtPath);

es.onmessage = function(evt) {
  var data;
  try { data = JSON.parse(evt.data); } catch(e) { return; }
  allEvents.push(data);
  if (!isReplaying) {
    processEvent(data);
    renderAll();
  }
};

es.addEventListener('done', function() { es.close(); });

// Tick shot clock
setInterval(function() {
  if (S.shotClock.timeLimitMs && !S.finished && !isReplaying) renderShotClock();
}, 100);

</script>
</body>
</html>"""


# ── Multi-Event Match Page ─────────────────────────────────────────

MULTI_EVENT_HTML_PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Multi-Event Match</title>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body { margin: 0; overflow: hidden; background: #0a0a1a; font-family: 'Segoe UI', system-ui, sans-serif; color: #eee;
  display: flex; flex-direction: column; height: 100vh; }

.top-bar {
  display: flex; align-items: center; justify-content: space-between;
  height: 28px; padding: 0 12px; background: #1a1a2e;
  font-size: 12px; border-bottom: 1px solid #333; flex-shrink: 0;
}
.top-bar .player { flex: 1; }
.top-bar .player.left { text-align: left; }
.top-bar .player.right { text-align: right; }
.top-bar .score {
  flex: 0 0 auto; padding: 0 16px;
  font-size: 15px; font-weight: bold; color: #ffd700;
}
.top-bar .winner-tag {
  display: inline-block; margin-left: 6px;
  font-size: 9px; color: #4ecdc4; font-weight: bold;
}

#active-frame { flex: 1; min-height: 0; position: relative; }
#active-frame iframe { position: absolute; top: 0; left: 0; width: 100%; height: 100%; border: none; display: none; }
#active-frame iframe.visible { display: block; }

.scoreboard {
  display: flex; flex-shrink: 0; height: 36px;
  border-top: 1px solid #333; background: #1a1a2e;
}
.sb-cell {
  flex: 1; display: flex; align-items: center; justify-content: center;
  gap: 6px; font-size: 11px; color: #666; padding: 0 6px;
  border-right: 1px solid #222; cursor: pointer; transition: background 0.15s;
}
.sb-cell:last-child { border-right: none; }
.sb-cell:hover { background: #222; }
.sb-cell .sb-icon { font-size: 10px; width: 12px; text-align: center; }
.sb-cell .sb-label { white-space: nowrap; }
.sb-cell .sb-score { font-weight: bold; white-space: nowrap; }

.sb-cell.active { background: #1e2d4a; color: #58a6ff; border-bottom: 2px solid #58a6ff; }
.sb-cell.complete { color: #aaa; }
.sb-cell.complete .sb-icon { color: #3fb950; }
.sb-cell.win-a .sb-score { color: #4ecdc4; }
.sb-cell.win-b .sb-score { color: #ff6b6b; }
.sb-cell.draw .sb-score { color: #ffd700; }
.sb-cell.upcoming { color: #444; }
</style>
</head>
<body>

<div class="top-bar">
  <div class="player left" id="player-a">--</div>
  <div class="score" id="agg-score">- &ndash; -</div>
  <div class="player right" id="player-b">--</div>
</div>
<div id="active-frame"></div>
<div class="scoreboard" id="scoreboard"></div>

<script>
var MATCH_ID = '__MATCH_ID__';
var LABELS = {
  tictactoe: 'TTT', connectfour: 'C4',
  reversi: 'Rev', holdem: "Hold'em",
  checkers: 'Check', scrabble: 'Scrab'
};
var LONG_LABELS = {
  tictactoe: 'Tic-Tac-Toe', connectfour: 'Connect Four',
  reversi: 'Reversi', holdem: "Hold'em",
  checkers: 'Checkers', scrabble: 'Scrabble'
};

var eventOrder = [];
var eventMatchIds = {};
var currentEvent = null;
var iframeCache = {};
var lastMatch = null;

function findMatch(manifest) {
  if (!manifest.rounds) return null;
  for (var i = 0; i < manifest.rounds.length; i++) {
    var matches = manifest.rounds[i].matches;
    for (var j = 0; j < matches.length; j++) {
      if (matches[j].match_id === MATCH_ID) return matches[j];
    }
  }
  return null;
}

function getActiveEvent(match) {
  // First event without a score entry is the active one
  var es = match.event_scores || {};
  for (var i = 0; i < eventOrder.length; i++) {
    if (!es[eventOrder[i]]) return eventOrder[i];
  }
  // All complete — return last
  return eventOrder[eventOrder.length - 1];
}

function createAllIframes() {
  var container = document.getElementById('active-frame');
  for (var i = 0; i < eventOrder.length; i++) {
    var ev = eventOrder[i];
    var iframe = document.createElement('iframe');
    // Lazy-load: store URL but don't set src until activated
    iframe.setAttribute('data-src', '/match/' + eventMatchIds[ev] + '?compact=1');
    iframe.setAttribute('data-event', ev);
    container.appendChild(iframe);
    iframeCache[ev] = iframe;
  }
}

function showEvent(ev) {
  currentEvent = ev;
  for (var i = 0; i < eventOrder.length; i++) {
    var evName = eventOrder[i];
    var f = iframeCache[evName];
    if (!f) continue;
    var isActive = (evName === ev);
    f.classList.toggle('visible', isActive);
    // Load iframe on first activation
    if (isActive && !f.src) {
      f.src = f.getAttribute('data-src');
    }
  }
  renderScoreboard();
}

function updateTopBar(match) {
  if (!match) return;
  document.getElementById('player-a').innerHTML = match.model_a +
    (match.winner === match.model_a ? '<span class="winner-tag">WINNER</span>' : '');
  document.getElementById('player-b').innerHTML =
    (match.winner === match.model_b ? '<span class="winner-tag">WINNER</span>' : '') + match.model_b;
  var sa = match.scores && match.scores.player_a != null ? match.scores.player_a : '-';
  var sb = match.scores && match.scores.player_b != null ? match.scores.player_b : '-';
  var fmt = function(v) { return typeof v === 'number' ? v.toFixed(1) : v; };
  document.getElementById('agg-score').textContent = fmt(sa) + ' \u2013 ' + fmt(sb);
}

function updateScoreboard(match) {
  if (match) lastMatch = match;
  renderScoreboard();
}

function renderScoreboard() {
  var sb = document.getElementById('scoreboard');
  var es = lastMatch ? (lastMatch.event_scores || {}) : {};
  var activeEv = lastMatch ? getActiveEvent(lastMatch) : (eventOrder[0] || '');

  sb.innerHTML = '';
  for (var i = 0; i < eventOrder.length; i++) {
    var ev = eventOrder[i];
    var cell = document.createElement('div');
    cell.className = 'sb-cell';
    cell.setAttribute('data-event', ev);

    var scores = es[ev];
    var icon, scoreText = '';
    if (scores) {
      cell.classList.add('complete');
      icon = '\u2713';
      var sa = Math.round(scores.score_a), sb2 = Math.round(scores.score_b);
      scoreText = sa + '-' + sb2;
      if (scores.point_a > scores.point_b) cell.classList.add('win-a');
      else if (scores.point_b > scores.point_a) cell.classList.add('win-b');
      else cell.classList.add('draw');
    } else if (ev === activeEv) {
      icon = '\u25B6';
    } else {
      cell.classList.add('upcoming');
      icon = '\u00b7';
    }
    if (ev === currentEvent) cell.classList.add('active');

    cell.innerHTML =
      '<span class="sb-icon">' + icon + '</span>' +
      '<span class="sb-label">' + (LABELS[ev] || ev) + '</span>' +
      (scoreText ? '<span class="sb-score">' + scoreText + '</span>' : '');

    sb.appendChild(cell);
  }
}

var lastActiveEvent = null;

function onUpdate(match) {
  if (!match) return;
  updateTopBar(match);
  var activeEv = getActiveEvent(match);
  // Only auto-switch when a genuinely new event starts (previous one completed)
  if (activeEv !== lastActiveEvent) {
    lastActiveEvent = activeEv;
    showEvent(activeEv);
  }
  updateScoreboard(match);
}

function init() {
  fetch('/manifest').then(function(r) { return r.json(); }).then(function(manifest) {
    var match = findMatch(manifest);
    if (!match || !match.event_match_ids) {
      document.getElementById('active-frame').innerHTML =
        '<div style="display:flex;align-items:center;justify-content:center;height:100%;color:#666;">Waiting for match data\u2026</div>';
      setTimeout(init, 2000);
      return;
    }
    eventOrder = Object.keys(match.event_match_ids);
    eventMatchIds = match.event_match_ids;
    lastMatch = match;

    createAllIframes();

    // Delegated click handler for scoreboard tabs
    document.getElementById('scoreboard').addEventListener('click', function(e) {
      var cell = e.target.closest('.sb-cell');
      if (!cell) return;
      var ev = cell.getAttribute('data-event');
      if (ev) showEvent(ev);
    });

    var activeEv = getActiveEvent(match);
    showEvent(activeEv);
    updateTopBar(match);

    // Poll manifest instead of SSE to conserve browser connections
    // (each iframe SSE needs a connection; browser limit is ~6 per origin)
    var pollInterval = setInterval(function() {
      fetch('/manifest').then(function(r) { return r.json(); }).then(function(m) {
        var updated = findMatch(m);
        if (updated) onUpdate(updated);
        if (m.status === 'complete') clearInterval(pollInterval);
      }).catch(function() {});
    }, 3000);
  }).catch(function() { setTimeout(init, 2000); });
}

init();
</script>
</body>
</html>"""


# ── Gauntlet HTML/CSS/JS ────────────────────────────────────────

GAUNTLET_HTML_PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Gauntlet — LLM Tourney</title>
<style>
:root {
  --bg: #0a0a0f; --surface: #14141f; --border: #2a2a3a;
  --text: #e0e0e8; --dim: #888; --accent: #4fc3f7;
  --green: #66bb6a; --yellow: #fdd835; --red: #ef5350;
  --orange: #ffa726; --purple: #ab47bc; --cyan: #26c6da;
  --blue: #42a5f5; --pink: #ec407a;
}
* { margin:0; padding:0; box-sizing:border-box; }
body { font-family: 'JetBrains Mono', 'Fira Code', monospace; background:var(--bg); color:var(--text); }
.header { padding:12px 20px; border-bottom:1px solid var(--border); display:flex; justify-content:space-between; align-items:center; }
.header h1 { font-size:18px; font-weight:700; }
.header .race-info { font-size:13px; color:var(--dim); }
.track-container { padding:20px; }

/* Track visualization */
.track { position:relative; margin:10px 0; height:52px; background:var(--surface); border:1px solid var(--border); border-radius:6px; overflow:visible; }
.track-fill { position:absolute; top:0; left:0; height:100%; border-radius:5px; transition: width 0.5s ease; opacity:0.3; }
.track-label { position:absolute; left:8px; top:50%; transform:translateY(-50%); font-size:13px; font-weight:700; z-index:2; white-space:nowrap; }
.track-pos { position:absolute; right:8px; top:50%; transform:translateY(-50%); font-size:12px; color:var(--dim); z-index:2; }
.track-racer { position:absolute; top:4px; width:44px; height:44px; border-radius:50%; display:flex; align-items:center; justify-content:center; font-size:20px; font-weight:900; transition: left 0.5s ease; z-index:3; border:2px solid rgba(255,255,255,0.3); }
.track-obstacle { position:absolute; bottom:-18px; font-size:9px; color:var(--dim); text-transform:uppercase; }
.finish-flag { position:absolute; right:0; top:0; height:100%; width:4px; z-index:1; }
.finish-flag.striped { background: repeating-linear-gradient(45deg, #fff, #fff 3px, #000 3px, #000 6px); }

/* Obstacle markers on track */
.obstacle-markers { position:relative; height:24px; margin:0 0 4px 0; }
.obstacle-dot { position:absolute; top:4px; width:16px; height:16px; border-radius:3px; font-size:8px; display:flex; align-items:center; justify-content:center; color:#fff; font-weight:700; }
.obstacle-dot.straight { background:#2e7d32; }
.obstacle-dot.hurdle { background:#e65100; }
.obstacle-dot.curve { background:#1565c0; }
.obstacle-dot.jam { background:#6a1b9a; }

/* Stats panel */
.stats-panel { padding:20px; display:grid; grid-template-columns:repeat(auto-fit, minmax(240px, 1fr)); gap:12px; }
.player-card { background:var(--surface); border:1px solid var(--border); border-radius:8px; padding:14px; }
.player-card.finished { border-color:var(--green); }
.player-card.eliminated { border-color:var(--red); opacity:0.6; }
.player-card .name { font-size:14px; font-weight:700; margin-bottom:6px; }
.player-card .stat-row { font-size:11px; color:var(--dim); margin:2px 0; }
.player-card .stat-row span { color:var(--text); }
.player-card .position-badge { float:right; font-size:18px; font-weight:900; }

/* Reasoning feed */
.feed { padding:10px 20px; max-height:300px; overflow-y:auto; }
.feed-entry { font-size:11px; padding:4px 0; border-bottom:1px solid var(--border); }
.feed-entry .feed-player { font-weight:700; }
.feed-entry .feed-action { color:var(--accent); }
.feed-entry .feed-result { color:var(--green); }
.feed-entry .feed-result.stumble { color:var(--red); }
.feed-entry .feed-reasoning { color:var(--dim); font-style:italic; }

/* Final standings */
.final-overlay { display:none; position:fixed; top:0; left:0; width:100%; height:100%; background:rgba(0,0,0,0.85); z-index:100; align-items:center; justify-content:center; }
.final-overlay.show { display:flex; }
.final-box { background:var(--surface); border:2px solid var(--accent); border-radius:12px; padding:30px; max-width:500px; width:90%; }
.final-box h2 { text-align:center; margin-bottom:16px; }
.final-row { display:flex; justify-content:space-between; padding:6px 0; border-bottom:1px solid var(--border); font-size:14px; }
.final-row .rank { font-weight:900; width:30px; }
.final-row .score { color:var(--accent); font-weight:700; }

.controls { padding:8px 20px; display:flex; gap:10px; align-items:center; }
.controls button { background:var(--surface); color:var(--text); border:1px solid var(--border); border-radius:4px; padding:4px 12px; cursor:pointer; font-size:12px; font-family:inherit; }
.controls button:hover { border-color:var(--accent); }
.controls .status { font-size:11px; color:var(--dim); }
</style>
</head>
<body>
<div class="header">
  <h1>GAUNTLET</h1>
  <div class="race-info" id="race-info">Loading...</div>
</div>

<div class="controls">
  <button id="btn-play">Play</button>
  <button id="btn-pause">Pause</button>
  <button id="btn-speed">1x</button>
  <div class="status" id="status-text"></div>
</div>

<div class="track-container" id="track-container"></div>
<div class="stats-panel" id="stats-panel"></div>
<div class="feed" id="feed"></div>

<div class="final-overlay" id="final-overlay">
  <div class="final-box" id="final-box"></div>
</div>

<script>
var COLORS = ['var(--accent)', 'var(--green)', 'var(--orange)', 'var(--purple)', 'var(--cyan)', 'var(--pink)', 'var(--yellow)', 'var(--red)', 'var(--blue)'];
var PLAYER_IDS = [];
var MODELS = {};
var LABELS = {};
var TRACK_LENGTH = 15;
var TRACK = [];
var allEntries = [];
var currentIdx = 0;
var playInterval = null;
var playSpeed = 500;
var speedModes = [500, 200, 50];
var speedIdx = 0;
var isPlaying = true;
var _layoutDone = false;
var isFinished = false;

function startSSE() {
  var es = new EventSource('/events');
  es.onmessage = function(e) {
    try {
      var data = JSON.parse(e.data);
      processTurn(data);
    } catch(err) {}
  };
}

function processTurn(data) {
  // Match summary (final record)
  if (data.record_type === 'match_summary') {
    isFinished = true;
    // player_models might be in extra
    var pm = (data.extra || {}).player_models || data.player_models || {};
    Object.keys(pm).forEach(function(k) { if (pm[k]) MODELS[k] = pm[k]; });
    return;
  }

  var snap = data.state_snapshot || {};
  var pid = data.player_id || '';
  var mid = data.model_id || '';

  // Extract player info from first snapshot
  if (snap.player_labels && !_layoutDone) {
    LABELS = snap.player_labels;
    PLAYER_IDS = Object.keys(snap.positions || {}).sort();
    TRACK_LENGTH = snap.track_length || 15;
    if (snap.track) TRACK = snap.track;
    renderTrackLayout();
    _layoutDone = true;
  }

  // Track model names
  if (pid && mid) MODELS[pid] = mid;

  allEntries.push(data);

  if (isPlaying) {
    renderState(allEntries.length - 1);
  }
}

function modelName(pid) {
  return MODELS[pid] || LABELS[pid] || pid;
}

function playerColor(pid) {
  var idx = PLAYER_IDS.indexOf(pid);
  return COLORS[idx % COLORS.length];
}

function renderTrackLayout() {
  var container = document.getElementById('track-container');
  if (!PLAYER_IDS.length) return;

  // Obstacle legend
  var legendHtml = '<div class="obstacle-markers" style="margin:0 50px 8px 50px;position:relative;height:22px;">';
  if (TRACK.length) {
    for (var i = 0; i < TRACK.length; i++) {
      var pct = (i / TRACK_LENGTH) * 100;
      var t = TRACK[i].type;
      var letter = t === 'straight' ? 'S' : t === 'hurdle' ? 'H' : t === 'curve' ? 'C' : 'J';
      legendHtml += '<div class="obstacle-dot ' + t + '" style="left:' + pct + '%;position:absolute;">' + letter + '</div>';
    }
  }
  legendHtml += '</div>';

  // Track lanes
  var html = legendHtml;
  for (var i = 0; i < PLAYER_IDS.length; i++) {
    var pid = PLAYER_IDS[i];
    var color = playerColor(pid);
    html += '<div class="track" id="track-' + pid + '">';
    html += '<div class="finish-flag striped"></div>';
    html += '<div class="track-fill" id="fill-' + pid + '" style="background:' + color + ';width:0%"></div>';
    html += '<div class="track-racer" id="racer-' + pid + '" style="left:0%;background:' + color + '">' + (LABELS[pid] || '?') + '</div>';
    html += '<div class="track-label" style="color:' + color + '">' + modelName(pid) + '</div>';
    html += '<div class="track-pos" id="pos-' + pid + '">0/' + TRACK_LENGTH + '</div>';
    html += '</div>';
  }
  container.innerHTML = html;
}

function renderState(idx) {
  if (idx < 0 || idx >= allEntries.length) return;
  var entry = allEntries[idx];
  var s = entry.state_snapshot;
  if (!s) return;

  var positions = s.positions || {};
  var finishOrder = s.finish_order || [];
  var eliminated = s.eliminated || [];
  var stats = s.player_stats || {};
  var scores = s.match_scores || {};
  var raceNum = s.race_number || 1;
  var racesTotal = s.races_per_match || 3;

  // Update race info
  document.getElementById('race-info').textContent = 'Race ' + raceNum + '/' + racesTotal + ' | Turn ' + (idx + 1) + '/' + allEntries.length;

  // Update tracks
  for (var i = 0; i < PLAYER_IDS.length; i++) {
    var pid = PLAYER_IDS[i];
    var pos = positions[pid] || 0;
    var pct = Math.min(pos / TRACK_LENGTH * 100, 100);
    var fill = document.getElementById('fill-' + pid);
    var racer = document.getElementById('racer-' + pid);
    var posEl = document.getElementById('pos-' + pid);
    var trackEl = document.getElementById('track-' + pid);
    if (fill) fill.style.width = pct + '%';
    if (racer) racer.style.left = 'calc(' + pct + '% - 22px)';
    if (posEl) posEl.textContent = pos + '/' + TRACK_LENGTH;
    if (trackEl) {
      trackEl.style.borderColor = '';
      if (finishOrder.indexOf(pid) >= 0) trackEl.style.borderColor = 'var(--green)';
      else if (eliminated.indexOf(pid) >= 0) trackEl.style.borderColor = 'var(--red)';
    }
  }

  // Update stats cards
  var statsHtml = '';
  // Sort by score descending
  var sorted = PLAYER_IDS.slice().sort(function(a,b) { return (scores[b]||0) - (scores[a]||0); });
  for (var i = 0; i < sorted.length; i++) {
    var pid = sorted[i];
    var st = stats[pid] || {};
    var pos = positions[pid] || 0;
    var finIdx = finishOrder.indexOf(pid);
    var isElim = eliminated.indexOf(pid) >= 0;
    var cls = finIdx >= 0 ? 'finished' : isElim ? 'eliminated' : '';

    var badge = '';
    if (finIdx === 0) badge = '<span class="position-badge" style="color:var(--yellow)">1st</span>';
    else if (finIdx === 1) badge = '<span class="position-badge" style="color:var(--dim)">2nd</span>';
    else if (finIdx === 2) badge = '<span class="position-badge" style="color:var(--orange)">3rd</span>';
    else if (isElim) badge = '<span class="position-badge" style="color:var(--red)">DNF</span>';

    statsHtml += '<div class="player-card ' + cls + '">';
    statsHtml += badge;
    statsHtml += '<div class="name" style="color:' + playerColor(pid) + '">' + modelName(pid) + '</div>';
    statsHtml += '<div class="stat-row">Score: <span style="font-weight:700">' + (scores[pid] || 0).toFixed(1) + '</span></div>';
    statsHtml += '<div class="stat-row">Position: <span>' + pos + '/' + TRACK_LENGTH + '</span> | Turns: <span>' + (st.turns_taken || 0) + '</span></div>';
    statsHtml += '<div class="stat-row">Sprints: <span>' + (st.sprints||0) + '</span> | Jogs: <span>' + (st.jogs||0) + '</span> | Stumbles: <span style="color:var(--red)">' + (st.stumbles||0) + '</span></div>';
    statsHtml += '<div class="stat-row">Hurdles: <span style="color:var(--green)">' + (st.hurdles_correct||0) + '</span>/<span>' + ((st.hurdles_correct||0)+(st.hurdles_wrong||0)) + '</span> | Blocks set: <span>' + (st.blocks_set||0) + '</span> | Dodges: <span>' + (st.dodges||0) + '</span></div>';
    statsHtml += '</div>';
  }
  document.getElementById('stats-panel').innerHTML = statsHtml;

  // Feed: show current turn action
  var feed = document.getElementById('feed');
  if (entry.player_id && entry.state_snapshot) {
    var pid = entry.player_id;
    var action = '';
    var reasoning = '';
    try {
      var parsed = typeof entry.parsed_action === 'string' ? JSON.parse(entry.parsed_action) : entry.parsed_action;
      if (parsed) {
        action = parsed.action || '';
        reasoning = parsed.reasoning || '';
        if (parsed.value !== undefined) action += ' ' + parsed.value;
      }
    } catch(e) {}
    var violation = entry.violation || '';
    var resultCls = violation ? 'stumble' : '';
    var feedEntry = document.createElement('div');
    feedEntry.className = 'feed-entry';
    feedEntry.innerHTML = '<span class="feed-player" style="color:' + playerColor(pid) + '">' + modelName(pid) + '</span> '
      + (action ? '<span class="feed-action">' + action + '</span> ' : '')
      + (violation ? '<span class="feed-result stumble">[' + violation + ']</span> ' : '')
      + (reasoning ? '<span class="feed-reasoning">' + reasoning.substring(0, 120) + '</span>' : '');
    feed.insertBefore(feedEntry, feed.firstChild);
    if (feed.children.length > 50) feed.removeChild(feed.lastChild);
  }

  // Check if match is complete
  if (s.terminal && idx === allEntries.length - 1) {
    showFinal(s);
  }
}

function showFinal(s) {
  var scores = s.match_scores || {};
  var sorted = PLAYER_IDS.slice().sort(function(a,b) { return (scores[b]||0) - (scores[a]||0); });
  var html = '<h2>RACE RESULTS</h2>';
  var medals = ['&#x1F947;', '&#x1F948;', '&#x1F949;'];
  for (var i = 0; i < sorted.length; i++) {
    var pid = sorted[i];
    var medal = i < 3 ? medals[i] + ' ' : (i+1) + '. ';
    html += '<div class="final-row"><span class="rank">' + medal + '</span><span>' + modelName(pid) + '</span><span class="score">' + (scores[pid]||0).toFixed(1) + ' pts</span></div>';
  }
  document.getElementById('final-box').innerHTML = html;
  document.getElementById('final-overlay').classList.add('show');
}

function startPlayback() {
  if (playInterval) clearInterval(playInterval);
  isPlaying = true;
  playInterval = setInterval(function() {
    if (currentIdx < allEntries.length) {
      renderState(currentIdx);
      currentIdx++;
    } else {
      clearInterval(playInterval);
      playInterval = null;
    }
  }, playSpeed);
}

document.getElementById('btn-play').onclick = function() {
  isPlaying = true;
  // If paused mid-replay, resume from currentIdx
  if (currentIdx < allEntries.length) startPlayback();
};
document.getElementById('btn-pause').onclick = function() {
  isPlaying = false;
  if (playInterval) { clearInterval(playInterval); playInterval = null; }
};
document.getElementById('btn-speed').onclick = function() {
  speedIdx = (speedIdx + 1) % speedModes.length;
  playSpeed = speedModes[speedIdx];
  this.textContent = ['1x','2x','10x'][speedIdx];
  if (isPlaying && playInterval) startPlayback();
};
document.getElementById('final-overlay').onclick = function() { this.classList.remove('show'); };

startSSE();
</script>
</body>
</html>"""


# ── Concurrent Yahtzee (Roller Derby) HTML/CSS/JS ─────────────────

CONCURRENT_YAHTZEE_HTML_PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Roller Derby Spectator</title>
<style>
:root {
  --bg: #0d1117;
  --surface: #161b22;
  --border: #30363d;
  --text: #e6edf3;
  --dim: #7d8590;
  --cyan: #58a6ff;
  --magenta: #d2a8ff;
  --green: #3fb950;
  --red: #f85149;
  --yellow: #d29922;
  --gold: #f0c040;
  --pa: #58a6ff;
  --pb: #d2a8ff;
  --pc: #3fb950;
  --pd: #d29922;
  --pe: #f97583;
  --pf: #79c0ff;
  --pg: #ffa657;
  --ph: #b392f0;
  --pi: #56d4dd;
  --pj: #e3b341;
}
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
  background: var(--bg);
  color: var(--text);
  font-family: 'SF Mono', 'Cascadia Code', 'Fira Code', 'Consolas', monospace;
  font-size: 13px;
  line-height: 1.4;
  padding: 12px;
  max-width: 1400px;
  margin: 0 auto;
}

#header {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 12px 16px;
  margin-bottom: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 16px;
  flex-wrap: wrap;
}
#header .badge {
  display: inline-block;
  padding: 2px 10px;
  border-radius: 4px;
  font-weight: bold;
}
#header .game-badge {
  background: var(--magenta);
  color: var(--bg);
}
#header .turn-badge {
  background: var(--cyan);
  color: var(--bg);
}

/* Race progress panel */
#race-panel {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 12px;
  margin-bottom: 10px;
}
#race-panel h3 {
  color: var(--cyan);
  margin-bottom: 8px;
  font-size: 13px;
}
.race-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}
.race-label {
  width: 140px;
  font-weight: bold;
  font-size: 12px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.race-track {
  flex: 1;
  height: 22px;
  background: var(--bg);
  border-radius: 4px;
  position: relative;
  display: flex;
}
.race-segment {
  flex: 1;
  height: 100%;
  border-right: 1px solid var(--border);
  position: relative;
}
.race-segment:last-child { border-right: none; }
.race-segment.filled {
  opacity: 1;
}
.race-segment.current {
  animation: pulse-seg 1s infinite;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: visible;
}
.race-segment .seg-clock {
  font-size: 8px;
  font-weight: bold;
  color: var(--bg);
  text-shadow: 0 0 2px rgba(0,0,0,0.8);
  white-space: nowrap;
  pointer-events: none;
  z-index: 1;
}
.race-segment .seg-clock.clock-warn { color: var(--yellow); text-shadow: none; }
.race-segment .seg-clock.clock-danger { color: var(--red); text-shadow: none; }
@keyframes pulse-seg {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}
.race-segment.empty { opacity: 0.15; }
.race-info {
  width: 100px;
  text-align: right;
  font-size: 11px;
  color: var(--dim);
  white-space: nowrap;
}
.race-info .finish-tag {
  color: var(--gold);
  font-weight: bold;
}
.race-info .dnf-tag {
  color: var(--red);
  font-weight: bold;
}

/* Layout */
#main {
  display: grid;
  grid-template-columns: 1fr 320px;
  gap: 10px;
}

/* Scorecard table */
#scorecard-panel {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 12px;
  overflow-x: auto;
}
#scorecard-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}
#scorecard-table th, #scorecard-table td {
  padding: 4px 8px;
  border: 1px solid var(--border);
  text-align: center;
  white-space: nowrap;
}
#scorecard-table th {
  background: var(--bg);
  color: var(--dim);
  font-weight: 600;
  position: sticky;
  top: 0;
}
#scorecard-table th.cat-col {
  text-align: left;
  min-width: 120px;
}
#scorecard-table .section-header {
  background: var(--bg);
  color: var(--cyan);
  font-weight: bold;
  text-align: left;
  border-bottom: 2px solid var(--cyan);
}
#scorecard-table .bonus-row {
  color: var(--gold);
  font-weight: bold;
}
#scorecard-table .total-row {
  font-weight: bold;
  font-size: 14px;
  border-top: 2px solid var(--text);
}
#scorecard-table .total-row td {
  padding: 6px 8px;
}
#scorecard-table .clock-row td {
  padding: 6px 4px;
  font-variant-numeric: tabular-nums;
  font-size: 13px;
  font-weight: bold;
  letter-spacing: 0.5px;
  border-bottom: 2px solid var(--border);
}
.clock-ok { color: var(--green); }
.clock-warn { color: var(--yellow); }
.clock-danger { color: var(--red); animation: pulse 0.5s infinite; }
.clock-idle { color: var(--dim); font-size: 11px; font-weight: normal; }
@keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.4; } }
#scorecard-table td.active-col {
  background: rgba(88, 166, 255, 0.08);
  border-color: var(--cyan);
}
#scorecard-table td.potential {
  color: var(--dim);
  font-style: italic;
}
#scorecard-table td.scored { color: var(--text); }
#scorecard-table td.scored-zero { color: var(--red); opacity: 0.6; }
#scorecard-table td.just-scored {
  color: var(--gold);
  font-weight: bold;
  animation: flash-score 1s ease;
}
@keyframes flash-score {
  0% { background: rgba(240, 192, 64, 0.3); }
  100% { background: transparent; }
}
#scorecard-table td.finished-col {
  background: rgba(63, 185, 80, 0.06);
}

/* Right sidebar */
#sidebar {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

/* Dice display */
#dice-panel {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 12px;
}
#dice-panel h3 {
  color: var(--cyan);
  margin-bottom: 8px;
  font-size: 13px;
}
.dice-row {
  display: flex;
  gap: 6px;
  margin-bottom: 14px;
  align-items: center;
}
.dice-row .player-label {
  width: 90px;
  font-weight: bold;
  font-size: 11px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.dice-row .roll-tag {
  width: 32px;
  font-size: 10px;
  color: var(--dim);
  text-align: center;
}
.die {
  width: 32px;
  height: 32px;
  background: var(--bg);
  border: 2px solid var(--border);
  border-radius: 6px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 16px;
  font-weight: bold;
}
.die.active {
  border-color: var(--cyan);
  box-shadow: 0 0 6px rgba(88, 166, 255, 0.3);
}
.die.held {
  border-color: var(--gold);
  box-shadow: 0 0 8px rgba(240, 192, 64, 0.5);
  background: rgba(240, 192, 64, 0.12);
}
.die.held::after {
  content: 'HELD';
  position: absolute;
  bottom: -12px;
  left: 50%;
  transform: translateX(-50%);
  font-size: 7px;
  color: var(--gold);
  letter-spacing: 0.5px;
}
.die {
  position: relative;
}
.die.finished-die {
  border-color: var(--green);
  opacity: 0.5;
}

/* Finish order */
#finish-panel {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 12px;
}
#finish-panel h3 {
  color: var(--cyan);
  margin-bottom: 8px;
  font-size: 13px;
}
.finish-entry {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 0;
  font-size: 12px;
}
.finish-pos {
  width: 24px;
  font-weight: bold;
  text-align: center;
}
.finish-pos.gold { color: var(--gold); }
.finish-pos.silver { color: #c0c0c0; }
.finish-pos.bronze { color: #cd7f32; }
.finish-bonus {
  color: var(--green);
  font-weight: bold;
  font-size: 11px;
}

/* Score bars */
#score-bar-panel {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 12px;
}
#score-bar-panel h3 {
  color: var(--cyan);
  margin-bottom: 8px;
  font-size: 13px;
}
.score-bar-row {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 4px;
}
.score-bar-label {
  width: 90px;
  font-weight: bold;
  font-size: 11px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.score-bar-track {
  flex: 1;
  height: 16px;
  background: var(--bg);
  border-radius: 3px;
  overflow: hidden;
}
.score-bar-fill {
  height: 100%;
  border-radius: 3px;
  transition: width 0.4s ease;
}
.score-bar-value {
  width: 40px;
  text-align: right;
  font-size: 12px;
  font-weight: bold;
}

/* Match scores */
#match-panel {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 12px;
}
#match-panel h3 {
  color: var(--cyan);
  margin-bottom: 8px;
  font-size: 13px;
}

/* Action feed */
#action-panel {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 12px;
  flex: 1;
  min-height: 150px;
  max-height: 300px;
  overflow-y: auto;
}
#action-panel h3 {
  color: var(--cyan);
  margin-bottom: 8px;
  font-size: 13px;
}
.action-entry {
  padding: 3px 0;
  border-bottom: 1px solid var(--border);
  font-size: 11px;
}
.action-entry:last-child { border-bottom: none; }

/* Replay controls */
#replay-bar {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 8px 16px;
  margin-bottom: 10px;
  display: flex;
  align-items: center;
  gap: 12px;
}
#replay-bar button {
  background: var(--bg);
  color: var(--text);
  border: 1px solid var(--border);
  border-radius: 4px;
  padding: 4px 12px;
  cursor: pointer;
  font-family: inherit;
  font-size: 12px;
}
#replay-bar button:hover { border-color: var(--cyan); }
#replay-bar button.active {
  background: var(--cyan);
  color: var(--bg);
  border-color: var(--cyan);
}
#replay-slider { flex: 1; accent-color: var(--cyan); }
#replay-counter { color: var(--dim); font-size: 12px; min-width: 60px; text-align: right; }

/* Reasoning panel */
#reasoning-panel {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 12px;
  margin-top: 10px;
  display: none;
}
#reasoning-panel h3 { color: var(--cyan); margin-bottom: 8px; font-size: 13px; }
#reasoning-text { font-size: 12px; color: var(--dim); white-space: pre-wrap; max-height: 120px; overflow-y: auto; }
</style>
</head>
<body>

<div id="header">
  <span style="font-size: 16px; font-weight: bold;">ROLLER DERBY</span>
  <span class="badge turn-badge" id="turn-badge">Turn 0</span>
  <span class="badge game-badge" id="game-badge" style="display:none">Game 1</span>
  <span id="active-info" style="color: var(--dim);"></span>
</div>

<div id="replay-bar">
  <button id="btn-prev" title="Previous">&#9664;&#9664;</button>
  <button id="btn-play" title="Play/Pause">&#9654;</button>
  <button id="btn-next" title="Next">&#9654;&#9654;</button>
  <input type="range" id="replay-slider" min="0" max="0" value="0">
  <span id="replay-counter">0 / 0</span>
  <button id="btn-live" class="active">LIVE</button>
</div>

<div id="race-panel">
  <h3>RACE PROGRESS</h3>
  <div id="race-area"></div>
</div>

<div id="main">
  <div id="scorecard-panel">
    <table id="scorecard-table">
      <thead><tr id="sc-header"></tr></thead>
      <tbody id="sc-body"></tbody>
    </table>
  </div>

  <div id="sidebar">
    <div id="dice-panel">
      <h3>CURRENT DICE</h3>
      <div id="dice-area"></div>
    </div>

    <div id="finish-panel" style="display:none;">
      <h3>FINISH ORDER</h3>
      <div id="finish-area"></div>
    </div>

    <div id="score-bar-panel">
      <h3>YAHTZEE TOTALS</h3>
      <div id="score-bars"></div>
    </div>

    <div id="match-panel" style="display:none;">
      <h3>MATCH SCORES</h3>
      <div id="match-scores"></div>
    </div>

    <div id="action-panel">
      <h3>ACTION FEED</h3>
      <div id="action-feed"></div>
    </div>
  </div>
</div>

<div id="reasoning-panel">
  <h3>REASONING</h3>
  <div id="reasoning-text"></div>
</div>

<script>
const PLAYER_COLORS = ['pa','pb','pc','pd','pe','pf','pg','ph','pi','pj'];
const UPPER = ['ones','twos','threes','fours','fives','sixes'];
const LOWER = ['three_of_a_kind','four_of_a_kind','full_house','small_straight','large_straight','yahtzee','chance'];
const ALL_CATS = UPPER.concat(LOWER);
const CAT_LABELS = {
  ones:'Ones', twos:'Twos', threes:'Threes', fours:'Fours', fives:'Fives', sixes:'Sixes',
  three_of_a_kind:'3 of a Kind', four_of_a_kind:'4 of a Kind', full_house:'Full House',
  small_straight:'Sm Straight', large_straight:'Lg Straight', yahtzee:'Yahtzee', chance:'Chance'
};
const TOTAL_ROUNDS = 13;
const MAX_SCORE = 400;
const FINISH_BONUS_DEFAULT = [3, 2, 1];

let entries = [];
let replayIdx = -1;
let isLive = true;
let isReplaying = false;
let replayTimer = null;
let playerIds = [];
let playerLabels = {};
let playerModels = {};
let finishBonus = FINISH_BONUS_DEFAULT;
let actionLog = [];

// Per-player held dice indices (from last reroll action)
let heldDice = {};  // pid -> [indices] or null

// Per-player turn timing (for shot clock in race segments)
let playerTurnStart = {};  // pid -> timestamp when last turn started
let playerPending = {};    // pid -> true if waiting for response

// Shot clock
let shotClock = {
  timeLimitMs: 0,
  lastLatency: {},
  allLatencies: {},  // pid -> [ms, ms, ...]
  strikes: {},
  strikeLimit: null,
};

// Previous snapshot for detecting newly scored categories
let prevScoreSnap = {};

function shortModel(name) {
  if (!name) return '';
  return name.replace(/^(openai|anthropic|google|x-ai|deepseek|meta|mistralai|amazon|perplexity|cohere)\//i, '')
             .replace(/-instruct$/i, '');
}

function displayName(pid) {
  return playerModels[pid] || ('Player ' + (playerLabels[pid] || pid));
}

function extractModels(data) {
  let changed = false;
  const pm = (data.state_snapshot && data.state_snapshot.player_models) || data.player_models || {};
  Object.keys(pm).forEach(k => {
    if (pm[k] && !playerModels[k]) { playerModels[k] = shortModel(pm[k]); changed = true; }
  });
  if (data.player_id && data.model_id && !playerModels[data.player_id]) {
    playerModels[data.player_id] = shortModel(data.model_id); changed = true;
  }
  if (changed) refreshLabels();
}

function refreshLabels() {
  document.querySelectorAll('#sc-header th[data-pid]').forEach(th => {
    th.textContent = displayName(th.dataset.pid);
  });
  document.querySelectorAll('.dice-row .player-label').forEach(lbl => {
    const pid = lbl.parentElement.dataset.pid;
    if (pid) lbl.textContent = displayName(pid);
  });
  document.querySelectorAll('.score-bar-label').forEach(lbl => {
    const row = lbl.closest('.score-bar-row');
    if (!row) return;
    const fill = row.querySelector('.score-bar-fill');
    if (fill && fill.dataset.pid) lbl.textContent = displayName(fill.dataset.pid);
  });
  document.querySelectorAll('.race-label').forEach(lbl => {
    const row = lbl.closest('.race-row');
    if (row && row.dataset.pid) lbl.textContent = displayName(row.dataset.pid);
  });
}

function initPlayers(snap) {
  if (playerIds.length > 0) return;
  playerIds = Object.keys(snap.scorecards || {});
  const labels = snap.player_labels || {};
  playerIds.forEach((pid, i) => {
    playerLabels[pid] = labels[pid] || String.fromCharCode(65 + i);
  });
  const pm = snap.player_models || {};
  Object.keys(pm).forEach(k => {
    if (pm[k]) playerModels[k] = shortModel(pm[k]);
  });
  buildScorecard();
  buildDiceArea();
  buildScoreBars();
  buildRaceArea();
}

// ── Race progress ──

function buildRaceArea() {
  const area = document.getElementById('race-area');
  area.innerHTML = '';
  playerIds.forEach((pid, i) => {
    const row = document.createElement('div');
    row.className = 'race-row';
    row.dataset.pid = pid;
    row.innerHTML = `
      <span class="race-label" style="color:var(--${PLAYER_COLORS[i]})">${displayName(pid)}</span>
      <div class="race-track" data-pid="${pid}"></div>
      <span class="race-info" data-pid="${pid}"></span>
    `;
    const track = row.querySelector('.race-track');
    for (let r = 0; r < TOTAL_ROUNDS; r++) {
      const seg = document.createElement('div');
      seg.className = 'race-segment empty';
      seg.style.background = `var(--${PLAYER_COLORS[i]})`;
      track.appendChild(seg);
    }
    area.appendChild(row);
  });
}

function renderRaceProgress(snap) {
  const players = snap.players || {};
  const fo = snap.finish_order || [];
  const elim = new Set(snap.eliminated || []);

  playerIds.forEach((pid, i) => {
    const ps = players[pid] || {};
    const track = document.querySelector(`.race-track[data-pid="${pid}"]`);
    const info = document.querySelector(`.race-info[data-pid="${pid}"]`);
    if (!track) return;

    const segs = track.querySelectorAll('.race-segment');
    const round = ps.round || 0;
    const finished = ps.finished || false;

    segs.forEach((seg, r) => {
      seg.className = 'race-segment';
      seg.style.background = `var(--${PLAYER_COLORS[i]})`;
      seg.innerHTML = '';
      if (r < round - (finished ? 0 : 1)) {
        seg.classList.add('filled');
        seg.style.opacity = '1';
      } else if (!finished && r === round - 1) {
        seg.classList.add('current');
        seg.style.opacity = '0.7';
        // Shot clock inside the current segment
        const start = playerTurnStart[pid];
        if (start && playerPending[pid] && shotClock.timeLimitMs && !isReplaying) {
          const elapsed = Date.now() - start;
          const remaining = Math.max(0, shotClock.timeLimitMs - elapsed);
          const secs = remaining / 1000;
          const span = document.createElement('span');
          span.className = 'seg-clock' + (secs > 10 ? '' : secs > 5 ? ' clock-warn' : ' clock-danger');
          span.textContent = secs.toFixed(0) + 's';
          seg.appendChild(span);
        }
      } else {
        seg.classList.add('empty');
      }
    });

    if (info) {
      if (elim.has(pid)) {
        info.innerHTML = '<span class="dnf-tag">DNF</span>';
      } else if (finished && ps.finish_order_idx !== null && ps.finish_order_idx !== undefined) {
        const pos = ps.finish_order_idx + 1;
        const bonus = (pos - 1 < finishBonus.length) ? finishBonus[pos - 1] : 0;
        const bonusStr = bonus > 0 ? ` <span class="finish-bonus">+${bonus}</span>` : '';
        info.innerHTML = `<span class="finish-tag">#${pos}</span> (${ps.turns_taken}t)${bonusStr}`;
      } else {
        const rollStr = ps.roll_number ? `R${round} roll ${ps.roll_number}/3` : '';
        info.textContent = rollStr;
      }
    }
  });
}

// ── Scorecard ──

function buildScorecard() {
  const hdr = document.getElementById('sc-header');
  hdr.innerHTML = '<th class="cat-col">Category</th>';
  playerIds.forEach((pid, i) => {
    const th = document.createElement('th');
    th.textContent = displayName(pid);
    th.style.color = `var(--${PLAYER_COLORS[i]})`;
    th.dataset.pid = pid;
    hdr.appendChild(th);
  });
  const body = document.getElementById('sc-body');
  body.innerHTML = '';
  addClockRow(body);
  addSectionRow(body, 'UPPER SECTION');
  UPPER.forEach(cat => addCatRow(body, cat));
  addSpecialRow(body, '_upper_subtotal', 'Upper Subtotal');
  addSpecialRow(body, '_upper_bonus', 'Bonus (63+)', true);
  addSectionRow(body, 'LOWER SECTION');
  LOWER.forEach(cat => addCatRow(body, cat));
  addSpecialRow(body, '_yahtzee_bonuses', 'Yahtzee Bonus');
  addSpecialRow(body, '_finish_bonus', 'Finisher Bonus', true);
  addTotalRow(body);
}

function addSectionRow(body, label) {
  const tr = document.createElement('tr');
  const td = document.createElement('td');
  td.className = 'section-header';
  td.colSpan = playerIds.length + 1;
  td.textContent = label;
  tr.appendChild(td);
  body.appendChild(tr);
}

function addCatRow(body, cat) {
  const tr = document.createElement('tr');
  tr.dataset.cat = cat;
  const td = document.createElement('td');
  td.className = 'cat-col';
  td.textContent = CAT_LABELS[cat] || cat;
  tr.appendChild(td);
  playerIds.forEach(pid => {
    const cell = document.createElement('td');
    cell.dataset.pid = pid;
    cell.dataset.cat = cat;
    tr.appendChild(cell);
  });
  body.appendChild(tr);
}

function addSpecialRow(body, key, label, isBonus) {
  const tr = document.createElement('tr');
  if (isBonus) tr.className = 'bonus-row';
  tr.dataset.special = key;
  const td = document.createElement('td');
  td.className = 'cat-col';
  td.textContent = label;
  tr.appendChild(td);
  playerIds.forEach(pid => {
    const cell = document.createElement('td');
    cell.dataset.pid = pid;
    cell.dataset.special = key;
    tr.appendChild(cell);
  });
  body.appendChild(tr);
}

function addTotalRow(body) {
  const tr = document.createElement('tr');
  tr.className = 'total-row';
  tr.dataset.special = '_total';
  const td = document.createElement('td');
  td.className = 'cat-col';
  td.textContent = 'TOTAL';
  tr.appendChild(td);
  playerIds.forEach(pid => {
    const cell = document.createElement('td');
    cell.dataset.pid = pid;
    cell.dataset.special = '_total';
    cell.style.fontWeight = 'bold';
    tr.appendChild(cell);
  });
  body.appendChild(tr);
}

function addClockRow(body) {
  const tr = document.createElement('tr');
  tr.className = 'clock-row';
  const td = document.createElement('td');
  td.className = 'cat-col';
  td.textContent = 'SHOT CLOCK';
  td.style.color = 'var(--dim)';
  td.style.fontSize = '10px';
  td.style.letterSpacing = '1px';
  tr.appendChild(td);
  playerIds.forEach(pid => {
    const cell = document.createElement('td');
    cell.dataset.pid = pid;
    cell.dataset.clock = '1';
    cell.textContent = '--';
    cell.className = 'clock-idle';
    tr.appendChild(cell);
  });
  body.appendChild(tr);
}

function renderClocks() {
  playerIds.forEach(pid => {
    const cell = document.querySelector('td[data-pid="' + pid + '"][data-clock="1"]');
    if (!cell) return;
    cell.style.color = '';
    cell.innerHTML = '';
    const lats = shotClock.allLatencies[pid];
    if (lats && lats.length > 0) {
      const avg = lats.reduce((a, b) => a + b, 0) / lats.length / 1000;
      const lo = Math.min(...lats) / 1000;
      const hi = Math.max(...lats) / 1000;
      cell.innerHTML = avg.toFixed(1) + 's <span style="font-size:10px">(<span style="color:var(--green)">' + lo.toFixed(1) + '</span>/<span style="color:var(--red)">' + hi.toFixed(1) + '</span>)</span>';
      cell.className = 'clock-idle';
      const strikes = shotClock.strikes[pid] || 0;
      if (strikes > 0) {
        cell.innerHTML += ' <span style="color:var(--yellow)">\u26A0' + strikes + '</span>';
      }
    } else {
      cell.textContent = '--';
      cell.className = 'clock-idle';
    }
  });
}

// ── Dice ──

function buildDiceArea() {
  const area = document.getElementById('dice-area');
  area.innerHTML = '';
  playerIds.forEach((pid, i) => {
    const row = document.createElement('div');
    row.className = 'dice-row';
    row.dataset.pid = pid;
    const lbl = document.createElement('span');
    lbl.className = 'player-label';
    lbl.textContent = displayName(pid);
    lbl.style.color = `var(--${PLAYER_COLORS[i]})`;
    row.appendChild(lbl);
    const rtag = document.createElement('span');
    rtag.className = 'roll-tag';
    rtag.dataset.pid = pid;
    row.appendChild(rtag);
    for (let d = 0; d < 5; d++) {
      const die = document.createElement('div');
      die.className = 'die';
      die.dataset.idx = d;
      row.appendChild(die);
    }
    area.appendChild(row);
  });
}

// ── Score bars ──

function buildScoreBars() {
  const container = document.getElementById('score-bars');
  container.innerHTML = '';
  playerIds.forEach((pid, i) => {
    const row = document.createElement('div');
    row.className = 'score-bar-row';
    row.innerHTML = `
      <span class="score-bar-label" style="color:var(--${PLAYER_COLORS[i]})">${displayName(pid)}</span>
      <div class="score-bar-track">
        <div class="score-bar-fill" data-pid="${pid}" style="background:var(--${PLAYER_COLORS[i]});width:0%"></div>
      </div>
      <span class="score-bar-value" data-pid="${pid}">0</span>
    `;
    container.appendChild(row);
  });
}

// ── Render ──

function renderState(snap) {
  if (!snap) return;
  initPlayers(snap);

  const players = snap.players || {};
  const scorecards = snap.scorecards || {};
  const potential = snap.potential_scores || {};

  // Header
  document.getElementById('turn-badge').textContent = `Turn ${snap.turn_number || 0}`;
  const gpMatch = snap.games_per_match || 1;
  const gameBadge = document.getElementById('game-badge');
  if (gpMatch > 1) {
    gameBadge.textContent = `Game ${snap.game_number}/${gpMatch}`;
    gameBadge.style.display = '';
  } else {
    gameBadge.style.display = 'none';
  }

  const finished = (snap.finish_order || []).length;
  const active = playerIds.filter(pid => !(players[pid] || {}).finished).length;
  if (!snap.terminal) {
    document.getElementById('active-info').innerHTML =
      `<span style="color:var(--green)">${finished} finished</span> &mdash; <span style="color:var(--cyan)">${active} racing</span>`;
  } else {
    document.getElementById('active-info').textContent = 'GAME OVER';
  }

  // Race progress
  renderRaceProgress(snap);

  // Detect newly scored categories for flash
  const justScored = {};
  playerIds.forEach(pid => {
    justScored[pid] = {};
    const sc = scorecards[pid] || {};
    const prev = prevScoreSnap[pid] || {};
    ALL_CATS.forEach(cat => {
      if (sc[cat] !== null && sc[cat] !== undefined && (prev[cat] === null || prev[cat] === undefined)) {
        justScored[pid][cat] = true;
      }
    });
  });

  // Update scorecard
  playerIds.forEach((pid, i) => {
    const sc = scorecards[pid] || {};
    const pot = potential[pid] || {};
    const ps = players[pid] || {};
    const isActive = !ps.finished && !snap.terminal;
    const isFinished = ps.finished;

    ALL_CATS.forEach(cat => {
      const cell = document.querySelector(`td[data-pid="${pid}"][data-cat="${cat}"]`);
      if (!cell) return;
      cell.className = isFinished ? 'finished-col' : (isActive ? 'active-col' : '');

      const val = sc[cat];
      if (val !== null && val !== undefined) {
        cell.textContent = val;
        if (justScored[pid][cat]) {
          cell.className += ' just-scored';
        } else if (val === 0) {
          cell.className += ' scored-zero';
        } else {
          cell.className += ' scored';
        }
      } else if (isActive && pot[cat] !== undefined) {
        cell.textContent = pot[cat];
        cell.className += ' potential';
      } else {
        cell.textContent = '';
      }
    });

    // Special rows
    ['_upper_subtotal', '_upper_bonus', '_yahtzee_bonuses', '_finish_bonus', '_total'].forEach(key => {
      const cell = document.querySelector(`td[data-pid="${pid}"][data-special="${key}"]`);
      if (!cell) return;
      const val = sc[key];
      cell.className = isFinished ? 'finished-col' : (isActive ? 'active-col' : '');
      if (key === '_yahtzee_bonuses') {
        cell.textContent = val ? `+${val * 100}` : '';
      } else if (key === '_finish_bonus') {
        cell.textContent = val ? `+${val}` : '';
        if (val > 0) cell.style.color = 'var(--green)';
        else cell.style.color = '';
      } else if (val !== undefined && val !== null) {
        cell.textContent = val;
      } else {
        cell.textContent = '';
      }
    });
  });

  // Save for next diff
  prevScoreSnap = {};
  playerIds.forEach(pid => {
    prevScoreSnap[pid] = Object.assign({}, (scorecards[pid] || {}));
  });

  // Update dice — per-player from snap.players
  playerIds.forEach((pid, i) => {
    const ps = players[pid] || {};
    const row = document.querySelector(`.dice-row[data-pid="${pid}"]`);
    if (!row) return;
    const dies = row.querySelectorAll('.die');
    const pDice = ps.dice || [];
    const isActive = !ps.finished && !snap.terminal;
    const kept = heldDice[pid] || [];
    dies.forEach((die, d) => {
      die.textContent = pDice[d] || '';
      const isHeld = kept.includes(d) && isActive;
      die.className = 'die'
        + (isActive ? ' active' : (ps.finished ? ' finished-die' : ''))
        + (isHeld ? ' held' : '');
      die.style.color = `var(--${PLAYER_COLORS[i]})`;
    });
    // Roll tag
    const rtag = row.querySelector('.roll-tag');
    if (rtag) {
      if (ps.finished) {
        rtag.textContent = 'DONE';
        rtag.style.color = 'var(--green)';
      } else if (ps.roll_number) {
        rtag.textContent = `${ps.roll_number}/3`;
        rtag.style.color = 'var(--dim)';
      } else {
        rtag.textContent = '';
      }
    }
  });

  // Finish order
  const fo = snap.finish_order || [];
  const fPanel = document.getElementById('finish-panel');
  const fArea = document.getElementById('finish-area');
  if (fo.length > 0) {
    fPanel.style.display = '';
    fArea.innerHTML = '';
    fo.forEach((pid, idx) => {
      const pi = playerIds.indexOf(pid);
      const color = PLAYER_COLORS[pi] || 'dim';
      const posClass = idx === 0 ? 'gold' : idx === 1 ? 'silver' : idx === 2 ? 'bronze' : '';
      const bonus = (idx < finishBonus.length) ? finishBonus[idx] : 0;
      const bonusStr = bonus > 0 ? `<span class="finish-bonus">+${bonus}</span>` : '';
      const ps = players[pid] || {};
      const turns = ps.turns_taken || '?';
      const div = document.createElement('div');
      div.className = 'finish-entry';
      div.innerHTML = `<span class="finish-pos ${posClass}">#${idx+1}</span>
        <span style="color:var(--${color})">${displayName(pid)}</span>
        <span style="color:var(--dim);font-size:10px">(${turns}t)</span> ${bonusStr}`;
      fArea.appendChild(div);
    });
  } else {
    fPanel.style.display = 'none';
  }

  // Score bars
  playerIds.forEach(pid => {
    const sc = scorecards[pid] || {};
    const total = sc._total || 0;
    const pct = Math.min(100, (total / MAX_SCORE) * 100);
    const fill = document.querySelector(`.score-bar-fill[data-pid="${pid}"]`);
    const val = document.querySelector(`.score-bar-value[data-pid="${pid}"]`);
    if (fill) fill.style.width = pct + '%';
    if (val) val.textContent = total;
  });

  // Match scores
  const ms = snap.match_scores || {};
  const hasMatch = Object.values(ms).some(v => v > 0);
  const mPanel = document.getElementById('match-panel');
  if (hasMatch) {
    mPanel.style.display = '';
    const mDiv = document.getElementById('match-scores');
    mDiv.innerHTML = playerIds.map((pid, i) =>
      `<span style="color:var(--${PLAYER_COLORS[i]})">${displayName(pid)}: ${(ms[pid]||0).toFixed(1)}</span>`
    ).join(' &nbsp; ');
  }

  renderClocks();
}

function addActionEntry(data) {
  if (!data.player_id || !data.parsed_action) return;
  const pid = data.player_id;
  const act = data.parsed_action;
  const pi = playerIds.indexOf(pid);
  const color = PLAYER_COLORS[pi] || 'dim';
  const name = displayName(pid);
  let desc = '';
  if (act.action === 'score') {
    desc = `scored <b>${CAT_LABELS[act.category] || act.category}</b>`;
  } else if (act.action === 'reroll') {
    const kept = (act.keep || []).length;
    desc = `rerolled (kept ${kept})`;
  } else {
    desc = act.action || '?';
  }
  actionLog.push({color, name, desc});
  if (actionLog.length > 50) actionLog.shift();
  renderActionFeed();
}

function renderActionFeed() {
  const feed = document.getElementById('action-feed');
  feed.innerHTML = '';
  actionLog.slice(-20).reverse().forEach(e => {
    const div = document.createElement('div');
    div.className = 'action-entry';
    div.innerHTML = `<span style="color:var(--${e.color})">${e.name}</span> ${e.desc}`;
    feed.appendChild(div);
  });
}

function renderReasoning(entry) {
  const panel = document.getElementById('reasoning-panel');
  const text = entry.reasoning_output || (entry.parsed_action && entry.parsed_action.reasoning) || '';
  if (text) {
    panel.style.display = '';
    const pi = playerIds.indexOf(entry.player_id);
    const color = PLAYER_COLORS[pi] || 'dim';
    const name = displayName(entry.player_id);
    document.getElementById('reasoning-text').innerHTML =
      `<span style="color:var(--${color})">${name}:</span> ${text.replace(/</g,'&lt;')}`;
  } else {
    panel.style.display = 'none';
  }
}

// ── Replay ──

const slider = document.getElementById('replay-slider');
const counter = document.getElementById('replay-counter');
const btnPrev = document.getElementById('btn-prev');
const btnPlay = document.getElementById('btn-play');
const btnNext = document.getElementById('btn-next');
const btnLive = document.getElementById('btn-live');

function goToEntry(idx) {
  if (idx < 0) idx = 0;
  if (idx >= entries.length) idx = entries.length - 1;
  replayIdx = idx;
  slider.value = idx;
  counter.textContent = `${idx + 1} / ${entries.length}`;
  const e = entries[idx];
  renderState(e.state_snapshot);
  renderReasoning(e);
}

function goLive() {
  isLive = true;
  isReplaying = false;
  if (replayTimer) { clearInterval(replayTimer); replayTimer = null; }
  btnLive.classList.add('active');
  btnPlay.textContent = '\u25B6';
  if (entries.length > 0) goToEntry(entries.length - 1);
}

function exitLive() {
  isLive = false;
  btnLive.classList.remove('active');
}

slider.addEventListener('input', () => { exitLive(); goToEntry(parseInt(slider.value)); });
btnPrev.addEventListener('click', () => { exitLive(); goToEntry(replayIdx - 1); });
btnNext.addEventListener('click', () => { exitLive(); goToEntry(replayIdx + 1); });
btnLive.addEventListener('click', goLive);
btnPlay.addEventListener('click', () => {
  if (isReplaying) {
    isReplaying = false;
    if (replayTimer) { clearInterval(replayTimer); replayTimer = null; }
    btnPlay.textContent = '\u25B6';
  } else {
    exitLive();
    isReplaying = true;
    btnPlay.textContent = '\u23F8';
    if (replayIdx >= entries.length - 1) replayIdx = -1;
    replayTimer = setInterval(() => {
      if (replayIdx >= entries.length - 1) {
        isReplaying = false;
        clearInterval(replayTimer);
        replayTimer = null;
        btnPlay.textContent = '\u25B6';
        return;
      }
      goToEntry(replayIdx + 1);
    }, 400);
  }
});

// ── SSE ──

const evtSource = new EventSource('/events');
evtSource.onmessage = (event) => {
  try {
    const data = JSON.parse(event.data);
    extractModels(data);
    if (data.time_limit_ms) shotClock.timeLimitMs = data.time_limit_ms;
    if (data.strike_limit) shotClock.strikeLimit = data.strike_limit;
    if (data.player_id && data.latency_ms !== undefined) {
      shotClock.lastLatency[data.player_id] = data.latency_ms;
      if (!shotClock.allLatencies[data.player_id]) shotClock.allLatencies[data.player_id] = [];
      shotClock.allLatencies[data.player_id].push(data.latency_ms);
      // This player just responded — no longer pending
      playerPending[data.player_id] = false;
    }
    if (data.player_id && data.cumulative_strikes !== undefined) {
      shotClock.strikes[data.player_id] = data.cumulative_strikes;
    }
    // Track held dice from reroll actions
    if (data.player_id && data.parsed_action) {
      const act = data.parsed_action;
      if (act.action === 'reroll') {
        heldDice[data.player_id] = act.keep || [];
      } else {
        // Scored — clear held state
        heldDice[data.player_id] = null;
      }
    }
    // In concurrent mode, all non-finished players are pending after each turn event
    // Mark all active players as pending (they might be queried next)
    if (data.state_snapshot && data.state_snapshot.players) {
      const ps = data.state_snapshot.players;
      Object.keys(ps).forEach(pid => {
        if (!ps[pid].finished && !playerPending[pid]) {
          playerPending[pid] = true;
          playerTurnStart[pid] = Date.now();
        }
      });
    }
    addActionEntry(data);
    entries.push(data);
    slider.max = entries.length - 1;
    if (isLive) goToEntry(entries.length - 1);
  } catch(e) {}
};
evtSource.onerror = () => { setTimeout(() => location.reload(), 3000); };
// Tick race segment clocks every 100ms
setInterval(function() {
  if (shotClock.timeLimitMs && !isReplaying) {
    renderClocks();
    // Re-render race progress to update segment clocks
    if (entries.length > 0 && isLive) {
      const lastSnap = entries[entries.length - 1].state_snapshot;
      if (lastSnap) renderRaceProgress(lastSnap);
    }
  }
}, 100);
</script>
</body>
</html>"""


# ── Yahtzee HTML/CSS/JS ──────────────────────────────────────────

YAHTZEE_HTML_PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Yahtzee Spectator</title>
<style>
:root {
  --bg: #0d1117;
  --surface: #161b22;
  --border: #30363d;
  --text: #e6edf3;
  --dim: #7d8590;
  --cyan: #58a6ff;
  --magenta: #d2a8ff;
  --green: #3fb950;
  --red: #f85149;
  --yellow: #d29922;
  --gold: #f0c040;
  --pa: #58a6ff;
  --pb: #d2a8ff;
  --pc: #3fb950;
  --pd: #d29922;
  --pe: #f97583;
  --pf: #79c0ff;
  --pg: #ffa657;
  --ph: #b392f0;
  --pi: #56d4dd;
  --pj: #e3b341;
}
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
  background: var(--bg);
  color: var(--text);
  font-family: 'SF Mono', 'Cascadia Code', 'Fira Code', 'Consolas', monospace;
  font-size: 13px;
  line-height: 1.4;
  padding: 12px;
  max-width: 1400px;
  margin: 0 auto;
}

#header {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 12px 16px;
  margin-bottom: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 16px;
  flex-wrap: wrap;
}
#header .badge {
  display: inline-block;
  padding: 2px 10px;
  border-radius: 4px;
  font-weight: bold;
}
#header .round-badge {
  background: var(--cyan);
  color: var(--bg);
}
#header .game-badge {
  background: var(--magenta);
  color: var(--bg);
}

/* Layout */
#main {
  display: grid;
  grid-template-columns: 1fr 320px;
  gap: 10px;
}

/* Scorecard table */
#scorecard-panel {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 12px;
  overflow-x: auto;
}
#scorecard-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}
#scorecard-table th, #scorecard-table td {
  padding: 4px 8px;
  border: 1px solid var(--border);
  text-align: center;
  white-space: nowrap;
}
#scorecard-table th {
  background: var(--bg);
  color: var(--dim);
  font-weight: 600;
  position: sticky;
  top: 0;
}
#scorecard-table th.cat-col {
  text-align: left;
  min-width: 120px;
}
#scorecard-table .section-header {
  background: var(--bg);
  color: var(--cyan);
  font-weight: bold;
  text-align: left;
  border-bottom: 2px solid var(--cyan);
}
#scorecard-table .bonus-row {
  color: var(--gold);
  font-weight: bold;
}
#scorecard-table .total-row {
  font-weight: bold;
  font-size: 14px;
  border-top: 2px solid var(--text);
}
#scorecard-table .total-row td {
  padding: 6px 8px;
}
/* Per-player shot clocks in header */
#scorecard-table .clock-row td {
  padding: 6px 4px;
  font-variant-numeric: tabular-nums;
  font-size: 13px;
  font-weight: bold;
  letter-spacing: 0.5px;
  border-bottom: 2px solid var(--border);
}
#scorecard-table .clock-row td.clock-active {
  border-bottom-color: var(--cyan);
}
.clock-ok { color: var(--green); }
.clock-warn { color: var(--yellow); }
.clock-danger { color: var(--red); animation: pulse 0.5s infinite; }
.clock-idle { color: var(--dim); font-size: 11px; font-weight: normal; }
@keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.4; } }
#scorecard-table td.active-col {
  background: rgba(88, 166, 255, 0.08);
  border-color: var(--cyan);
}
#scorecard-table td.potential {
  color: var(--dim);
  font-style: italic;
}
#scorecard-table td.scored {
  color: var(--text);
}
#scorecard-table td.scored-zero {
  color: var(--red);
  opacity: 0.6;
}
#scorecard-table td.just-scored {
  color: var(--gold);
  font-weight: bold;
  animation: flash-score 1s ease;
}
@keyframes flash-score {
  0% { background: rgba(240, 192, 64, 0.3); }
  100% { background: transparent; }
}

/* Right sidebar */
#sidebar {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

/* Dice display */
#dice-panel {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 12px;
}
#dice-panel h3 {
  color: var(--cyan);
  margin-bottom: 8px;
  font-size: 13px;
}
.dice-row {
  display: flex;
  gap: 8px;
  margin-bottom: 6px;
  align-items: center;
}
.dice-row .player-label {
  width: 24px;
  font-weight: bold;
  text-align: center;
}
.die {
  width: 36px;
  height: 36px;
  background: var(--bg);
  border: 2px solid var(--border);
  border-radius: 6px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 18px;
  font-weight: bold;
}
.die.active {
  border-color: var(--cyan);
  box-shadow: 0 0 6px rgba(88, 166, 255, 0.3);
}
.dice-index {
  font-size: 9px;
  color: var(--dim);
  text-align: center;
  width: 36px;
}

/* Score bar */
#score-bar-panel {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 12px;
}
#score-bar-panel h3 {
  color: var(--cyan);
  margin-bottom: 8px;
  font-size: 13px;
}
.score-bar-row {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 4px;
}
.score-bar-label {
  width: 24px;
  font-weight: bold;
  text-align: center;
}
.score-bar-track {
  flex: 1;
  height: 16px;
  background: var(--bg);
  border-radius: 3px;
  overflow: hidden;
  position: relative;
}
.score-bar-fill {
  height: 100%;
  border-radius: 3px;
  transition: width 0.4s ease;
}
.score-bar-value {
  width: 40px;
  text-align: right;
  font-size: 12px;
  font-weight: bold;
}

/* Commentary feed */
#commentary-panel {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 12px;
  flex: 1;
  min-height: 200px;
  max-height: 400px;
  overflow-y: auto;
}
#commentary-panel h3 {
  color: var(--cyan);
  margin-bottom: 8px;
  font-size: 13px;
}
.commentary-entry {
  padding: 4px 0;
  border-bottom: 1px solid var(--border);
  font-size: 12px;
}
.commentary-entry:last-child {
  border-bottom: none;
}
.commentary-entry .round-tag {
  color: var(--dim);
  font-size: 10px;
}

/* Match scores */
#match-panel {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 12px;
}
#match-panel h3 {
  color: var(--cyan);
  margin-bottom: 8px;
  font-size: 13px;
}

/* Replay controls */
#replay-bar {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 8px 16px;
  margin-bottom: 10px;
  display: flex;
  align-items: center;
  gap: 12px;
}
#replay-bar button {
  background: var(--bg);
  color: var(--text);
  border: 1px solid var(--border);
  border-radius: 4px;
  padding: 4px 12px;
  cursor: pointer;
  font-family: inherit;
  font-size: 12px;
}
#replay-bar button:hover {
  border-color: var(--cyan);
}
#replay-bar button.active {
  background: var(--cyan);
  color: var(--bg);
  border-color: var(--cyan);
}
#replay-slider {
  flex: 1;
  accent-color: var(--cyan);
}
#replay-counter {
  color: var(--dim);
  font-size: 12px;
  min-width: 60px;
  text-align: right;
}

/* Reasoning panel */
#reasoning-panel {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 12px;
  margin-top: 10px;
  display: none;
}
#reasoning-panel h3 {
  color: var(--cyan);
  margin-bottom: 8px;
  font-size: 13px;
}
#reasoning-text {
  font-size: 12px;
  color: var(--dim);
  white-space: pre-wrap;
  max-height: 120px;
  overflow-y: auto;
}
</style>
</head>
<body>

<div id="header">
  <span style="font-size: 16px; font-weight: bold;">YAHTZEE</span>
  <span class="badge round-badge" id="round-badge">Round 1/13</span>
  <span class="badge game-badge" id="game-badge">Game 1</span>
  <span id="active-info" style="color: var(--dim);"></span>
</div>

<div id="replay-bar">
  <button id="btn-prev" title="Previous">&#9664;&#9664;</button>
  <button id="btn-play" title="Play/Pause">&#9654;</button>
  <button id="btn-next" title="Next">&#9654;&#9654;</button>
  <input type="range" id="replay-slider" min="0" max="0" value="0">
  <span id="replay-counter">0 / 0</span>
  <button id="btn-live" class="active">LIVE</button>
</div>

<div id="main">
  <div id="scorecard-panel">
    <table id="scorecard-table">
      <thead><tr id="sc-header"></tr></thead>
      <tbody id="sc-body"></tbody>
    </table>
  </div>

  <div id="sidebar">
    <div id="dice-panel">
      <h3>CURRENT DICE</h3>
      <div id="dice-area"></div>
    </div>

    <div id="score-bar-panel">
      <h3>SCORE TOTALS</h3>
      <div id="score-bars"></div>
    </div>

    <div id="match-panel" style="display:none;">
      <h3>MATCH SCORES</h3>
      <div id="match-scores"></div>
    </div>

    <div id="commentary-panel">
      <h3>COMMENTARY</h3>
      <div id="commentary-feed"></div>
    </div>
  </div>
</div>

<div id="reasoning-panel">
  <h3>REASONING</h3>
  <div id="reasoning-text"></div>
</div>

<script>
const PLAYER_COLORS = ['pa','pb','pc','pd','pe','pf','pg','ph','pi','pj'];
const UPPER = ['ones','twos','threes','fours','fives','sixes'];
const LOWER = ['three_of_a_kind','four_of_a_kind','full_house','small_straight','large_straight','yahtzee','chance'];
const ALL_CATS = UPPER.concat(LOWER);
const CAT_LABELS = {
  ones:'Ones', twos:'Twos', threes:'Threes', fours:'Fours', fives:'Fives', sixes:'Sixes',
  three_of_a_kind:'3 of a Kind', four_of_a_kind:'4 of a Kind', full_house:'Full House',
  small_straight:'Sm Straight', large_straight:'Lg Straight', yahtzee:'Yahtzee', chance:'Chance'
};
const MAX_SCORE = 400;

let entries = [];
let replayIdx = -1;
let isLive = true;
let isReplaying = false;
let replayTimer = null;
let playerIds = [];
let playerLabels = {};
let playerModels = {};

// Per-player shot clock state
let shotClock = {
  timeLimitMs: 0,
  activePid: null,
  turnStartTime: Date.now(),
  lastLatency: {},   // pid -> last latency in ms
  strikes: {},       // pid -> cumulative strikes
  strikeLimit: null,
};

function shortModel(name) {
  if (!name) return '';
  return name.replace(/^(openai|anthropic|google|x-ai|deepseek|meta|mistralai|amazon|perplexity)\//i, '')
             .replace(/-instruct$/i, '');
}

function displayName(pid) {
  return playerModels[pid] || ('Player ' + (playerLabels[pid] || pid));
}

function extractModels(data) {
  let changed = false;
  const pm = (data.state_snapshot && data.state_snapshot.player_models) || data.player_models || {};
  Object.keys(pm).forEach(k => {
    if (pm[k] && !playerModels[k]) { playerModels[k] = shortModel(pm[k]); changed = true; }
  });
  if (data.player_id && data.model_id && !playerModels[data.player_id]) {
    playerModels[data.player_id] = shortModel(data.model_id); changed = true;
  }
  if (changed) refreshLabels();
}

function refreshLabels() {
  // Update scorecard headers
  document.querySelectorAll('#sc-header th[data-pid]').forEach(th => {
    th.textContent = displayName(th.dataset.pid);
  });
  // Update dice row labels
  document.querySelectorAll('.dice-row .player-label').forEach(lbl => {
    const pid = lbl.parentElement.dataset.pid;
    if (pid) lbl.textContent = displayName(pid);
  });
  // Update score bar labels
  document.querySelectorAll('.score-bar-label').forEach(lbl => {
    const row = lbl.closest('.score-bar-row');
    if (!row) return;
    const fill = row.querySelector('.score-bar-fill');
    if (fill && fill.dataset.pid) lbl.textContent = displayName(fill.dataset.pid);
  });
}

function initPlayers(snap) {
  if (playerIds.length > 0) return;
  playerIds = Object.keys(snap.scorecards || {});
  playerIds.forEach((pid, i) => {
    playerLabels[pid] = String.fromCharCode(65 + i);
  });
  const pm = snap.player_models || {};
  Object.keys(pm).forEach(k => {
    if (pm[k]) playerModels[k] = shortModel(pm[k]);
  });
  buildScorecard();
  buildDiceArea();
  buildScoreBars();
}

function buildScorecard() {
  const hdr = document.getElementById('sc-header');
  hdr.innerHTML = '<th class="cat-col">Category</th>';
  playerIds.forEach((pid, i) => {
    const th = document.createElement('th');
    th.textContent = displayName(pid);
    th.style.color = `var(--${PLAYER_COLORS[i]})`;
    th.dataset.pid = pid;
    hdr.appendChild(th);
  });

  const body = document.getElementById('sc-body');
  body.innerHTML = '';

  // Shot clock row
  addClockRow(body);

  // Upper section header
  addSectionRow(body, 'UPPER SECTION');
  UPPER.forEach(cat => addCatRow(body, cat));
  addSpecialRow(body, '_upper_subtotal', 'Upper Subtotal');
  addSpecialRow(body, '_upper_bonus', 'Bonus (63+)', true);

  // Lower section header
  addSectionRow(body, 'LOWER SECTION');
  LOWER.forEach(cat => addCatRow(body, cat));
  addSpecialRow(body, '_yahtzee_bonuses', 'Yahtzee Bonus');

  // Total
  addTotalRow(body);
}

function addSectionRow(body, label) {
  const tr = document.createElement('tr');
  const td = document.createElement('td');
  td.className = 'section-header';
  td.colSpan = playerIds.length + 1;
  td.textContent = label;
  tr.appendChild(td);
  body.appendChild(tr);
}

function addCatRow(body, cat) {
  const tr = document.createElement('tr');
  tr.dataset.cat = cat;
  const td = document.createElement('td');
  td.className = 'cat-col';
  td.textContent = CAT_LABELS[cat] || cat;
  tr.appendChild(td);
  playerIds.forEach(pid => {
    const cell = document.createElement('td');
    cell.dataset.pid = pid;
    cell.dataset.cat = cat;
    tr.appendChild(cell);
  });
  body.appendChild(tr);
}

function addSpecialRow(body, key, label, isBonus) {
  const tr = document.createElement('tr');
  if (isBonus) tr.className = 'bonus-row';
  tr.dataset.special = key;
  const td = document.createElement('td');
  td.className = 'cat-col';
  td.textContent = label;
  tr.appendChild(td);
  playerIds.forEach(pid => {
    const cell = document.createElement('td');
    cell.dataset.pid = pid;
    cell.dataset.special = key;
    tr.appendChild(cell);
  });
  body.appendChild(tr);
}

function addTotalRow(body) {
  const tr = document.createElement('tr');
  tr.className = 'total-row';
  tr.dataset.special = '_total';
  const td = document.createElement('td');
  td.className = 'cat-col';
  td.textContent = 'TOTAL';
  tr.appendChild(td);
  playerIds.forEach(pid => {
    const cell = document.createElement('td');
    cell.dataset.pid = pid;
    cell.dataset.special = '_total';
    cell.style.fontWeight = 'bold';
    tr.appendChild(cell);
  });
  body.appendChild(tr);
}

function addClockRow(body) {
  const tr = document.createElement('tr');
  tr.className = 'clock-row';
  const td = document.createElement('td');
  td.className = 'cat-col';
  td.textContent = 'SHOT CLOCK';
  td.style.color = 'var(--dim)';
  td.style.fontSize = '10px';
  td.style.letterSpacing = '1px';
  tr.appendChild(td);
  playerIds.forEach(pid => {
    const cell = document.createElement('td');
    cell.dataset.pid = pid;
    cell.dataset.clock = '1';
    cell.textContent = '--';
    cell.className = 'clock-idle';
    tr.appendChild(cell);
  });
  body.appendChild(tr);
}

function renderClocks() {
  const now = Date.now();
  const pending = shotClock.pendingPids || new Set();
  playerIds.forEach(pid => {
    const cell = document.querySelector('td[data-pid="' + pid + '"][data-clock="1"]');
    if (!cell) return;
    cell.style.color = '';
    if (pid === shotClock.activePid && shotClock.timeLimitMs && !isReplaying && pending.has(pid)) {
      // Currently being queried — live countdown
      const elapsed = now - shotClock.turnStartTime;
      const remaining = Math.max(0, shotClock.timeLimitMs - elapsed);
      const secs = remaining / 1000;
      cell.textContent = secs.toFixed(1) + 's';
      cell.className = secs > 20 ? 'clock-ok clock-active' : secs > 5 ? 'clock-warn clock-active' : 'clock-danger clock-active';
    } else if (pending.has(pid) && shotClock.timeLimitMs && !isReplaying) {
      // Pending this round but not yet being queried — waiting
      cell.textContent = 'ON CLOCK';
      cell.className = 'clock-ok clock-active';
    } else if (shotClock.lastLatency[pid] !== undefined) {
      // Already decided or between rounds — show last latency
      const lat = shotClock.lastLatency[pid] / 1000;
      cell.textContent = lat.toFixed(1) + 's';
      cell.className = 'clock-idle';
      const strikes = shotClock.strikes[pid] || 0;
      if (strikes > 0) {
        cell.textContent += ' \u26A0' + strikes;
        cell.style.color = 'var(--yellow)';
      }
    } else {
      cell.textContent = '--';
      cell.className = 'clock-idle';
    }
  });
}

function buildDiceArea() {
  const area = document.getElementById('dice-area');
  area.innerHTML = '';
  playerIds.forEach((pid, i) => {
    const row = document.createElement('div');
    row.className = 'dice-row';
    row.dataset.pid = pid;
    const lbl = document.createElement('span');
    lbl.className = 'player-label';
    lbl.textContent = displayName(pid);
    lbl.style.color = `var(--${PLAYER_COLORS[i]})`;
    row.appendChild(lbl);
    for (let d = 0; d < 5; d++) {
      const die = document.createElement('div');
      die.className = 'die';
      die.dataset.idx = d;
      row.appendChild(die);
    }
    area.appendChild(row);
  });
}

function buildScoreBars() {
  const container = document.getElementById('score-bars');
  container.innerHTML = '';
  playerIds.forEach((pid, i) => {
    const row = document.createElement('div');
    row.className = 'score-bar-row';
    row.innerHTML = `
      <span class="score-bar-label" style="color:var(--${PLAYER_COLORS[i]})">${displayName(pid)}</span>
      <div class="score-bar-track">
        <div class="score-bar-fill" data-pid="${pid}" style="background:var(--${PLAYER_COLORS[i]});width:0%"></div>
      </div>
      <span class="score-bar-value" data-pid="${pid}">0</span>
    `;
    container.appendChild(row);
  });
}

function renderState(snap) {
  if (!snap) return;
  initPlayers(snap);

  const activePid = snap.active_player;

  // Header
  document.getElementById('round-badge').textContent = `Round ${snap.round || 0}/${snap.total_rounds || 13}`;
  const gpMatch = snap.games_per_match || 1;
  document.getElementById('game-badge').textContent = gpMatch > 1 ? `Game ${snap.game_number}/${gpMatch}` : '';
  document.getElementById('game-badge').style.display = gpMatch > 1 ? '' : 'none';

  // Concurrent: all players who haven't scored this round are "active"
  const roundDec = snap.round_decisions || {};
  const pendingPids = new Set(playerIds.filter(pid => !roundDec[pid]));
  const decided = Object.keys(roundDec).length;

  if (!snap.terminal) {
    document.getElementById('active-info').innerHTML =
      `Round ${snap.round || 0} — <span style="color:var(--cyan)">${decided}/${playerIds.length} decided</span>`;
  } else {
    document.getElementById('active-info').textContent = 'GAME OVER';
  }

  // Track which players are pending for shot clocks
  shotClock.pendingPids = pendingPids;

  // Update scorecard
  const scorecards = snap.scorecards || {};
  const potential = snap.potential_scores || {};

  playerIds.forEach((pid, i) => {
    const sc = scorecards[pid] || {};
    const pot = potential[pid] || {};
    const isActive = pendingPids.has(pid) && !snap.terminal;

    ALL_CATS.forEach(cat => {
      const cell = document.querySelector(`td[data-pid="${pid}"][data-cat="${cat}"]`);
      if (!cell) return;
      cell.className = isActive ? 'active-col' : '';

      const val = sc[cat];
      if (val !== null && val !== undefined) {
        cell.textContent = val;
        // Check if this was just scored this round
        const dec = roundDec[pid];
        if (dec && dec.category === cat) {
          cell.className += ' just-scored';
        } else if (val === 0) {
          cell.className += ' scored-zero';
        } else {
          cell.className += ' scored';
        }
      } else if (isActive && pot[cat] !== undefined) {
        cell.textContent = pot[cat];
        cell.className += ' potential';
      } else {
        cell.textContent = '';
      }
    });

    // Special rows
    ['_upper_subtotal', '_upper_bonus', '_yahtzee_bonuses', '_total'].forEach(key => {
      const cell = document.querySelector(`td[data-pid="${pid}"][data-special="${key}"]`);
      if (!cell) return;
      const val = sc[key];
      cell.className = isActive ? 'active-col' : '';
      if (key === '_yahtzee_bonuses') {
        cell.textContent = val ? `+${val * 100}` : '';
      } else if (val !== undefined && val !== null) {
        cell.textContent = val;
      } else {
        cell.textContent = '';
      }
    });
  });

  // Update dice
  const dice = snap.dice || {};
  playerIds.forEach((pid, i) => {
    const row = document.querySelector(`.dice-row[data-pid="${pid}"]`);
    if (!row) return;
    const dies = row.querySelectorAll('.die');
    const pDice = dice[pid] || [];
    const isActive = pendingPids.has(pid) && !snap.terminal;
    dies.forEach((die, d) => {
      die.textContent = pDice[d] || '';
      die.className = 'die' + (isActive ? ' active' : '');
      die.style.color = `var(--${PLAYER_COLORS[i]})`;
    });
  });

  // Score bars
  playerIds.forEach(pid => {
    const sc = scorecards[pid] || {};
    const total = sc._total || 0;
    const pct = Math.min(100, (total / MAX_SCORE) * 100);
    const fill = document.querySelector(`.score-bar-fill[data-pid="${pid}"]`);
    const val = document.querySelector(`.score-bar-value[data-pid="${pid}"]`);
    if (fill) fill.style.width = pct + '%';
    if (val) val.textContent = total;
  });

  // Match scores
  const ms = snap.match_scores || {};
  const hasMatch = Object.values(ms).some(v => v > 0);
  const mPanel = document.getElementById('match-panel');
  if (hasMatch) {
    mPanel.style.display = '';
    const mDiv = document.getElementById('match-scores');
    mDiv.innerHTML = playerIds.map((pid, i) =>
      `<span style="color:var(--${PLAYER_COLORS[i]})">${displayName(pid)}: ${(ms[pid]||0).toFixed(1)}</span>`
    ).join(' &nbsp; ');
  }

  // Commentary
  const comments = snap.commentary || [];
  const feed = document.getElementById('commentary-feed');
  feed.innerHTML = '';
  comments.slice(-15).reverse().forEach(c => {
    const div = document.createElement('div');
    div.className = 'commentary-entry';
    const pi = playerIds.indexOf(c.player);
    const color = PLAYER_COLORS[pi] || 'dim';
    const cName = displayName(c.player);
    if (c.event === 'scored') {
      div.innerHTML = `<span class="round-tag">R${c.round}</span> <span style="color:var(--${color})">${cName}</span> scored <b>${c.points}</b> in ${CAT_LABELS[c.category] || c.category} (total: ${c.total})`;
    } else if (c.event === 'yahtzee_bonus') {
      div.innerHTML = `<span class="round-tag">R${c.round}</span> <span style="color:var(--${color})">${cName}</span> <span style="color:var(--gold)">YAHTZEE BONUS! +100</span>`;
    } else if (c.event === 'game_end') {
      div.innerHTML = `<span class="round-tag">END</span> <span style="color:var(--${color})">${cName}</span> final: ${c.game_total} (match: ${(c.match_score||0).toFixed(1)})`;
    }
    feed.appendChild(div);
  });
}

function renderReasoning(entry) {
  const panel = document.getElementById('reasoning-panel');
  const text = entry.reasoning_output || (entry.parsed_action && entry.parsed_action.reasoning) || '';
  if (text) {
    panel.style.display = '';
    const pi = playerIds.indexOf(entry.player_id);
    const color = PLAYER_COLORS[pi] || 'dim';
    const name = displayName(entry.player_id);
    document.getElementById('reasoning-text').innerHTML =
      `<span style="color:var(--${color})">${name}:</span> ${text.replace(/</g,'&lt;')}`;
  } else {
    panel.style.display = 'none';
  }
}

// ── Replay controls ──

const slider = document.getElementById('replay-slider');
const counter = document.getElementById('replay-counter');
const btnPrev = document.getElementById('btn-prev');
const btnPlay = document.getElementById('btn-play');
const btnNext = document.getElementById('btn-next');
const btnLive = document.getElementById('btn-live');

function goToEntry(idx) {
  if (idx < 0) idx = 0;
  if (idx >= entries.length) idx = entries.length - 1;
  replayIdx = idx;
  slider.value = idx;
  counter.textContent = `${idx + 1} / ${entries.length}`;
  const e = entries[idx];
  renderState(e.state_snapshot);
  renderReasoning(e);
}

function goLive() {
  isLive = true;
  isReplaying = false;
  if (replayTimer) { clearInterval(replayTimer); replayTimer = null; }
  btnLive.classList.add('active');
  btnPlay.textContent = '\u25B6';
  if (entries.length > 0) goToEntry(entries.length - 1);
}

function exitLive() {
  isLive = false;
  btnLive.classList.remove('active');
}

slider.addEventListener('input', () => {
  exitLive();
  goToEntry(parseInt(slider.value));
});
btnPrev.addEventListener('click', () => {
  exitLive();
  goToEntry(replayIdx - 1);
});
btnNext.addEventListener('click', () => {
  exitLive();
  goToEntry(replayIdx + 1);
});
btnLive.addEventListener('click', goLive);
btnPlay.addEventListener('click', () => {
  if (isReplaying) {
    isReplaying = false;
    if (replayTimer) { clearInterval(replayTimer); replayTimer = null; }
    btnPlay.textContent = '\u25B6';
  } else {
    exitLive();
    isReplaying = true;
    btnPlay.textContent = '\u23F8';
    if (replayIdx >= entries.length - 1) replayIdx = -1;
    replayTimer = setInterval(() => {
      if (replayIdx >= entries.length - 1) {
        isReplaying = false;
        clearInterval(replayTimer);
        replayTimer = null;
        btnPlay.textContent = '\u25B6';
        return;
      }
      goToEntry(replayIdx + 1);
    }, 800);
  }
});

// ── SSE connection ──

const evtSource = new EventSource('/events');
evtSource.onmessage = (event) => {
  try {
    const data = JSON.parse(event.data);
    extractModels(data);
    // Update shot clock state from telemetry
    if (data.time_limit_ms) shotClock.timeLimitMs = data.time_limit_ms;
    if (data.strike_limit) shotClock.strikeLimit = data.strike_limit;
    if (data.player_id && data.latency_ms !== undefined) {
      shotClock.lastLatency[data.player_id] = data.latency_ms;
    }
    if (data.player_id && data.cumulative_strikes !== undefined) {
      shotClock.strikes[data.player_id] = data.cumulative_strikes;
    }
    // Figure out who's next from state snapshot
    if (data.state_snapshot && data.state_snapshot.active_player) {
      shotClock.activePid = data.state_snapshot.active_player;
      shotClock.turnStartTime = Date.now();
    }
    if (data.state_snapshot && data.state_snapshot.terminal) {
      shotClock.activePid = null;
    }
    entries.push(data);
    slider.max = entries.length - 1;
    if (isLive) goToEntry(entries.length - 1);
  } catch(e) {}
};
evtSource.onerror = () => {
  setTimeout(() => location.reload(), 3000);
};
// Per-player shot clock countdown
setInterval(function() {
  if (shotClock.timeLimitMs && !isReplaying) renderClocks();
}, 100);
</script>
</body>
</html>"""


# ── Storyteller HTML/CSS/JS ──────────────────────────────────────

STORYTELLER_HTML_PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Storyteller — Live Spectator</title>
<style>
:root {
  --bg: #0d1117;
  --surface: #161b22;
  --border: #30363d;
  --text: #e6edf3;
  --dim: #7d8590;
  --cyan: #58a6ff;
  --magenta: #d2a8ff;
  --green: #3fb950;
  --red: #f85149;
  --yellow: #d29922;
  --orange: #db6d28;
  --gold: #f0c040;
  --silver: #b0b8c0;
  --bronze: #cd7f32;
  --pa: #58a6ff; --pb: #d2a8ff; --pc: #3fb950; --pd: #f0883e;
  --pe: #f85149; --pf: #d29922; --pg: #56d4dd; --ph: #ec6cb9;
}
*, *::before, *::after { box-sizing: border-box; }
body {
  margin: 0; padding: 12px 16px;
  background: var(--bg); color: var(--text);
  font-family: 'SF Mono', 'Fira Code', 'Consolas', monospace;
  font-size: 13px; line-height: 1.5;
}
.header {
  display: flex; align-items: center; gap: 16px;
  padding: 8px 12px; margin-bottom: 10px;
  background: var(--surface); border: 1px solid var(--border); border-radius: 6px;
}
.header h1 { margin: 0; font-size: 18px; color: var(--magenta); }
.header .round-info { color: var(--cyan); font-size: 14px; }
.header .phase-badge {
  padding: 2px 10px; border-radius: 12px; font-size: 11px; font-weight: 600;
  text-transform: uppercase; letter-spacing: 0.5px;
}
.phase-judge-write { background: var(--magenta); color: #000; }
.phase-player-write { background: var(--cyan); color: #000; }
.phase-judge-pick { background: var(--gold); color: #000; }

/* Scoreboard */
.scoreboard {
  display: flex; flex-wrap: wrap; gap: 6px;
  padding: 8px 12px; margin-bottom: 10px;
  background: var(--surface); border: 1px solid var(--border); border-radius: 6px;
}
.score-chip {
  display: flex; align-items: center; gap: 6px;
  padding: 4px 10px; border-radius: 4px;
  background: rgba(255,255,255,0.04); font-size: 12px;
}
.score-chip .model-name { font-weight: 600; }
.score-chip .pts { color: var(--gold); font-weight: 700; }
.score-chip .medals { font-size: 10px; color: var(--dim); }
.score-chip.is-judge { border: 1px solid var(--magenta); }

/* Main grid */
.main { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-bottom: 10px; }
@media (max-width: 900px) { .main { grid-template-columns: 1fr; } }

.panel {
  background: var(--surface); border: 1px solid var(--border);
  border-radius: 6px; padding: 10px 12px;
}
.panel h2 {
  margin: 0 0 8px; font-size: 12px; text-transform: uppercase;
  letter-spacing: 1px; color: var(--dim);
}

/* Theme panel (god mode) */
.theme-panel {
  border-color: var(--magenta); position: relative;
}
.theme-panel::before {
  content: 'GOD MODE'; position: absolute; top: -9px; right: 12px;
  background: var(--magenta); color: #000; font-size: 9px; font-weight: 700;
  padding: 1px 6px; border-radius: 3px; letter-spacing: 1px;
}
.theme-category { color: var(--magenta); font-size: 16px; font-weight: 700; }
.theme-constraint { color: var(--dim); font-size: 13px; margin-top: 2px; }

/* Judge prompt */
.judge-prompt {
  font-style: italic; color: var(--text); font-size: 14px;
  line-height: 1.6; padding: 8px 12px; margin-top: 6px;
  border-left: 3px solid var(--magenta); background: rgba(210,168,255,0.05);
}

/* Responses */
.responses-grid {
  display: grid; grid-template-columns: 1fr; gap: 8px;
}
.response-card {
  padding: 8px 12px; border-radius: 6px;
  background: rgba(255,255,255,0.03); border: 1px solid var(--border);
  position: relative;
}
.response-card.pending {
  border-style: dashed; opacity: 0.5;
}
.response-card .resp-header {
  display: flex; align-items: center; gap: 8px; margin-bottom: 4px;
}
.response-card .resp-label {
  font-weight: 700; font-size: 12px; color: var(--cyan);
}
.response-card .resp-model {
  font-size: 11px; color: var(--dim);
}
.response-card .resp-text {
  font-size: 13px; line-height: 1.5; color: var(--text);
}
.response-card .medal {
  position: absolute; top: 6px; right: 10px;
  font-size: 11px; font-weight: 700; padding: 2px 8px;
  border-radius: 3px; letter-spacing: 0.5px;
}
.medal-gold { background: var(--gold); color: #000; }
.medal-silver { background: var(--silver); color: #000; }
.medal-bronze { background: var(--bronze); color: #000; }

/* Round log */
.round-entry {
  padding: 6px 0; border-bottom: 1px solid var(--border); font-size: 12px;
}
.round-entry:last-child { border-bottom: none; }
.round-entry .re-header {
  display: flex; align-items: center; gap: 8px; margin-bottom: 3px;
}
.round-entry .re-round { font-weight: 700; color: var(--cyan); }
.round-entry .re-judge { color: var(--magenta); }
.round-entry .re-theme { color: var(--dim); font-size: 11px; }
.round-entry .re-picks { font-size: 11px; }
.re-gold { color: var(--gold); font-weight: 600; }
.re-silver { color: var(--silver); font-weight: 600; }
.re-bronze { color: var(--bronze); font-weight: 600; }

/* Reasoning */
.reasoning-panel { grid-column: 1 / -1; }
.reasoning-who { color: var(--cyan); font-weight: 600; font-size: 12px; margin-bottom: 4px; }
.reasoning-text {
  white-space: pre-wrap; word-break: break-word;
  color: var(--dim); font-size: 12px; max-height: 120px; overflow-y: auto;
}

/* Final standings */
.final-panel {
  grid-column: 1 / -1; display: none;
  border-color: var(--gold);
}
.final-panel.show { display: block; }
.standing-row {
  display: flex; align-items: center; gap: 12px;
  padding: 6px 8px; border-radius: 4px; margin-bottom: 4px;
}
.standing-row:nth-child(1) { background: rgba(240,192,64,0.1); border: 1px solid var(--gold); }
.standing-row:nth-child(2) { background: rgba(176,184,192,0.08); border: 1px solid var(--silver); }
.standing-row:nth-child(3) { background: rgba(205,127,50,0.08); border: 1px solid var(--bronze); }
.standing-rank { font-size: 18px; font-weight: 700; min-width: 30px; text-align: center; }
.standing-model { font-weight: 600; flex: 1; }
.standing-score { font-size: 16px; font-weight: 700; color: var(--gold); }
.standing-detail { font-size: 11px; color: var(--dim); }

/* Footer */
.footer {
  display: flex; align-items: center; gap: 12px;
  padding: 6px 12px; margin-top: 8px;
  background: var(--surface); border: 1px solid var(--border); border-radius: 6px;
  font-size: 11px; color: var(--dim);
}
.status-dot {
  width: 8px; height: 8px; border-radius: 50%; background: var(--green);
  display: inline-block;
}
.status-dot.done { background: var(--dim); }

/* Writer progress */
.writer-progress {
  display: flex; gap: 4px; margin-top: 6px; flex-wrap: wrap;
}
.writer-pip {
  width: 12px; height: 12px; border-radius: 3px;
  border: 1px solid var(--border);
}
.writer-pip.done { background: var(--green); border-color: var(--green); }
.writer-pip.active { background: var(--cyan); border-color: var(--cyan); animation: pulse 1s infinite; }
@keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.4; } }
</style>
</head>
<body>

<div class="header" id="header">
  <h1>STORYTELLER</h1>
  <span class="round-info" id="roundInfo">Waiting...</span>
  <span class="phase-badge" id="phaseBadge"></span>
  <span style="margin-left:auto;color:var(--dim);font-size:11px" id="turnInfo"></span>
</div>

<div class="scoreboard" id="scoreboard"></div>

<div class="main">
  <div>
    <div class="panel theme-panel" id="themePanel">
      <h2>Theme</h2>
      <div class="theme-category" id="themeCategory">---</div>
      <div class="theme-constraint" id="themeConstraint"></div>
    </div>

    <div class="panel" id="judgePanel" style="margin-top:10px">
      <h2>Judge's Piece</h2>
      <div id="judgeName" style="font-size:12px;color:var(--magenta);margin-bottom:4px"></div>
      <div class="judge-prompt" id="judgePrompt" style="display:none"></div>
      <div id="judgeWaiting" style="color:var(--dim);font-style:italic">Waiting for judge...</div>
    </div>

    <div class="panel" id="writerPanel" style="margin-top:10px">
      <h2>Writers <span id="writerCount" style="color:var(--dim)"></span></h2>
      <div class="writer-progress" id="writerProgress"></div>
    </div>
  </div>

  <div>
    <div class="panel" id="responsesPanel">
      <h2>Responses</h2>
      <div class="responses-grid" id="responsesGrid">
        <div style="color:var(--dim);font-style:italic">No responses yet</div>
      </div>
    </div>
  </div>

  <div class="panel reasoning-panel" id="reasoningPanel">
    <h2>Reasoning</h2>
    <div class="reasoning-who" id="reasoningWho"></div>
    <div class="reasoning-text" id="reasoningText" style="color:var(--dim);font-style:italic">---</div>
  </div>

  <div class="panel" id="roundLogPanel" style="grid-column:1/-1">
    <h2>Round History</h2>
    <div id="roundLog"><span style="color:var(--dim)">No rounds completed yet</span></div>
  </div>

  <div class="panel final-panel" id="finalPanel">
    <h2>Final Standings</h2>
    <div id="finalStandings"></div>
  </div>
</div>

<div class="footer">
  <span class="status-dot" id="statusDot"></span>
  <span id="statusText">Connecting...</span>
  <span id="latencyInfo" style="margin-left:auto"></span>
</div>

<script>
var PLAYER_COLORS = {
  player_a:'var(--pa)',player_b:'var(--pb)',player_c:'var(--pc)',player_d:'var(--pd)',
  player_e:'var(--pe)',player_f:'var(--pf)',player_g:'var(--pg)',player_h:'var(--ph)'
};
var RESPONSE_LABELS = ['Response A','Response B','Response C','Response D',
                       'Response E','Response F','Response G'];

var S = {
  models: {},
  round: 0,
  numRounds: 8,
  phase: '',
  currentJudge: '',
  themeCategory: '',
  themeConstraint: '',
  judgePrompt: '',
  playerResponses: {},
  responseOrder: [],
  picks: {gold:'',silver:'',bronze:''},
  matchScores: {},
  playerStats: {},
  roundLog: [],
  judgeOrder: [],
  turnNumber: 0,
  turnCount: 0,
  finished: false,
  finalScores: {},
  lastReasoning: '',
  lastModel: '',
  lastLatency: 0,
  lastAction: '',
  writersTotal: 0,
  writersDone: 0
};

var rawLines = [];
var turnQueue = [];
var isReplaying = false;

function processTurn(data) {
  rawLines.push(data);
  S.turnCount++;

  if (data.record_type === 'match_summary') {
    S.finished = true;
    S.finalScores = data.final_scores || {};
    if (data.player_models) S.models = data.player_models;
    return;
  }

  var snap = data.state_snapshot || {};
  var pid = data.player_id || '';
  var mid = data.model_id || '';

  // Init models
  if (snap.player_models) S.models = snap.player_models;
  if (pid && mid) S.models[pid] = mid;

  // Core state
  S.round = snap.round || S.round;
  S.numRounds = snap.num_rounds || S.numRounds;
  S.phase = snap.phase || S.phase;
  S.currentJudge = snap.current_judge || S.currentJudge;
  S.themeCategory = snap.theme_category || S.themeCategory;
  S.themeConstraint = snap.theme_constraint || S.themeConstraint;
  S.judgePrompt = snap.judge_prompt || S.judgePrompt;
  S.matchScores = snap.match_scores || S.matchScores;
  S.turnNumber = snap.turn_number || S.turnNumber;

  // Player responses — merge incrementally
  if (snap.player_responses) {
    for (var k in snap.player_responses) {
      S.playerResponses[k] = snap.player_responses[k];
    }
  }
  S.responseOrder = snap.response_order || S.responseOrder;

  // Picks
  if (snap.picks) S.picks = snap.picks;

  // Round log
  if (snap.round_log) S.roundLog = snap.round_log;
  if (snap.player_stats) S.playerStats = snap.player_stats;
  if (snap.judge_order) S.judgeOrder = snap.judge_order;

  // Action tracking
  var act = data.parsed_action || {};
  S.lastAction = act.action || '';
  S.lastReasoning = data.reasoning_output || '';
  S.lastModel = mid || S.models[pid] || '';
  S.lastLatency = data.latency_ms || 0;

  // Writer progress
  if (S.phase === 'player_write') {
    var total = Object.keys(S.models).length - 1;
    var done = Object.keys(S.playerResponses).length;
    S.writersTotal = total;
    S.writersDone = done;
  }

  // Detect round transition: if phase went back to judge_write and we have responses from prev round
  if (S.phase === 'judge_write' && S.lastAction === 'write_prompt') {
    S.playerResponses = {};
    S.responseOrder = [];
    S.picks = {gold:'',silver:'',bronze:''};
    S.writersDone = 0;
  }
}

function modelShort(name) {
  if (!name) return '?';
  return name.replace('claude-','').replace('anthropic/','')
    .replace('openai/','').replace('x-ai/','').replace('deepseek/','')
    .replace('google/','').replace('meta-llama/','').replace('amazon/','');
}

function renderAll() {
  renderHeader();
  renderScoreboard();
  renderTheme();
  renderJudge();
  renderWriterProgress();
  renderResponses();
  renderReasoning();
  renderRoundLog();
  renderFinal();
  renderFooter();
}

function renderHeader() {
  var el = document.getElementById('roundInfo');
  el.textContent = 'Round ' + S.round + ' / ' + S.numRounds;

  var badge = document.getElementById('phaseBadge');
  if (S.phase === 'judge_write') {
    badge.textContent = 'Judge Writing';
    badge.className = 'phase-badge phase-judge-write';
  } else if (S.phase === 'player_write') {
    badge.textContent = 'Players Writing (' + S.writersDone + '/' + S.writersTotal + ')';
    badge.className = 'phase-badge phase-player-write';
  } else if (S.phase === 'judge_pick') {
    badge.textContent = 'Judge Picking';
    badge.className = 'phase-badge phase-judge-pick';
  }

  document.getElementById('turnInfo').textContent = 'Turn ' + S.turnCount;
}

function renderScoreboard() {
  var el = document.getElementById('scoreboard');
  // Sort by score descending
  var pids = Object.keys(S.matchScores).sort(function(a,b) {
    return (S.matchScores[b]||0) - (S.matchScores[a]||0);
  });
  if (pids.length === 0) { el.innerHTML = '<span style="color:var(--dim)">Waiting for players...</span>'; return; }
  var html = '';
  pids.forEach(function(pid) {
    var m = modelShort(S.models[pid] || pid);
    var score = S.matchScores[pid] || 0;
    var stats = S.playerStats[pid] || {};
    var g = stats.gold_count || 0;
    var s = stats.silver_count || 0;
    var b = stats.bronze_count || 0;
    var isJudge = pid === S.currentJudge && !S.finished;
    var cls = 'score-chip' + (isJudge ? ' is-judge' : '');
    var color = PLAYER_COLORS[pid] || 'var(--text)';
    html += '<div class="' + cls + '">'
      + '<span class="model-name" style="color:' + color + '">' + m + '</span>'
      + '<span class="pts">' + score + '</span>'
      + '<span class="medals">' + g + 'G ' + s + 'S ' + b + 'B</span>'
      + (isJudge ? '<span style="color:var(--magenta);font-size:10px">JUDGE</span>' : '')
      + '</div>';
  });
  el.innerHTML = html;
}

function renderTheme() {
  var cat = document.getElementById('themeCategory');
  var con = document.getElementById('themeConstraint');
  if (S.themeCategory) {
    cat.textContent = S.themeCategory;
    con.textContent = S.themeConstraint;
  }
}

function renderJudge() {
  var nameEl = document.getElementById('judgeName');
  var promptEl = document.getElementById('judgePrompt');
  var waitEl = document.getElementById('judgeWaiting');

  var judgeModel = modelShort(S.models[S.currentJudge] || '');
  nameEl.textContent = judgeModel ? 'Judge: ' + judgeModel : '';

  if (S.judgePrompt) {
    promptEl.textContent = S.judgePrompt;
    promptEl.style.display = 'block';
    waitEl.style.display = 'none';
  } else {
    promptEl.style.display = 'none';
    waitEl.style.display = 'block';
  }
}

function renderWriterProgress() {
  var el = document.getElementById('writerProgress');
  var countEl = document.getElementById('writerCount');
  if (S.phase !== 'player_write' && S.phase !== 'judge_pick') {
    el.innerHTML = '';
    countEl.textContent = '';
    return;
  }
  countEl.textContent = '(' + S.writersDone + '/' + S.writersTotal + ')';
  var pips = '';
  var allPlayers = Object.keys(S.models).filter(function(p) { return p !== S.currentJudge; });
  allPlayers.forEach(function(pid, i) {
    var done = !!S.playerResponses[pid];
    var cls = 'writer-pip' + (done ? ' done' : (i === S.writersDone ? ' active' : ''));
    var color = PLAYER_COLORS[pid] || 'var(--border)';
    var title = modelShort(S.models[pid]) + (done ? ' (done)' : '');
    pips += '<div class="' + cls + '" title="' + title + '" style="border-color:' + (done ? color : '') + ';background:' + (done ? color : '') + '"></div>';
  });
  el.innerHTML = pips;
}

function renderResponses() {
  var grid = document.getElementById('responsesGrid');
  // During judge_pick or after, show shuffled response order with picks
  if (S.responseOrder.length > 0 && (S.phase === 'judge_pick' || S.picks.gold)) {
    var html = '';
    S.responseOrder.forEach(function(pid, i) {
      var label = RESPONSE_LABELS[i] || ('Response ' + String.fromCharCode(65+i));
      var model = modelShort(S.models[pid] || pid);
      var text = S.playerResponses[pid] || '(no response)';
      var color = PLAYER_COLORS[pid] || 'var(--text)';
      var medal = '';
      if (S.picks.gold === pid) medal = '<span class="medal medal-gold">GOLD +5</span>';
      else if (S.picks.silver === pid) medal = '<span class="medal medal-silver">SILVER +3</span>';
      else if (S.picks.bronze === pid) medal = '<span class="medal medal-bronze">BRONZE +1</span>';
      html += '<div class="response-card">'
        + medal
        + '<div class="resp-header">'
        + '<span class="resp-label">' + label + '</span>'
        + '<span class="resp-model" style="color:' + color + '">' + model + '</span>'
        + '</div>'
        + '<div class="resp-text">' + escHtml(text) + '</div>'
        + '</div>';
    });
    grid.innerHTML = html;
  } else if (Object.keys(S.playerResponses).length > 0) {
    // During writing phase — show completed responses (god mode)
    var html = '';
    var respondents = Object.keys(S.playerResponses);
    respondents.forEach(function(pid) {
      var model = modelShort(S.models[pid] || pid);
      var text = S.playerResponses[pid];
      var color = PLAYER_COLORS[pid] || 'var(--text)';
      html += '<div class="response-card">'
        + '<div class="resp-header">'
        + '<span class="resp-model" style="color:' + color + '">' + model + '</span>'
        + '</div>'
        + '<div class="resp-text">' + escHtml(text) + '</div>'
        + '</div>';
    });
    // Pending writers
    var allPlayers = Object.keys(S.models).filter(function(p) { return p !== S.currentJudge; });
    allPlayers.forEach(function(pid) {
      if (!S.playerResponses[pid]) {
        var model = modelShort(S.models[pid] || pid);
        var color = PLAYER_COLORS[pid] || 'var(--text)';
        html += '<div class="response-card pending">'
          + '<div class="resp-header">'
          + '<span class="resp-model" style="color:' + color + '">' + model + '</span>'
          + '</div>'
          + '<div class="resp-text" style="color:var(--dim)">Writing...</div>'
          + '</div>';
      }
    });
    grid.innerHTML = html;
  } else {
    grid.innerHTML = '<div style="color:var(--dim);font-style:italic">No responses yet</div>';
  }
}

function renderReasoning() {
  var whoEl = document.getElementById('reasoningWho');
  var textEl = document.getElementById('reasoningText');
  if (S.lastReasoning) {
    whoEl.textContent = S.lastModel + (S.lastLatency ? ' (' + (S.lastLatency/1000).toFixed(1) + 's)' : '');
    textEl.textContent = S.lastReasoning;
    textEl.style.fontStyle = 'normal';
    textEl.style.color = 'var(--dim)';
  }
}

function renderRoundLog() {
  var el = document.getElementById('roundLog');
  if (S.roundLog.length === 0) return;
  var html = '';
  S.roundLog.forEach(function(r) {
    var judgeModel = modelShort(S.models[r.judge] || r.judge);
    var goldModel = modelShort(S.models[r.picks.gold] || '?');
    var silverModel = modelShort(S.models[r.picks.silver] || '?');
    var bronzeModel = modelShort(S.models[r.picks.bronze] || '?');
    html += '<div class="round-entry">'
      + '<div class="re-header">'
      + '<span class="re-round">R' + r.round + '</span>'
      + '<span class="re-judge">Judge: ' + judgeModel + '</span>'
      + '<span class="re-theme">' + r.theme_category + ' / ' + r.theme_constraint + '</span>'
      + '</div>'
      + '<div class="re-picks">'
      + '<span class="re-gold">GOLD: ' + goldModel + '</span> · '
      + '<span class="re-silver">SILVER: ' + silverModel + '</span> · '
      + '<span class="re-bronze">BRONZE: ' + bronzeModel + '</span>'
      + '</div>'
      + '</div>';
  });
  el.innerHTML = html;
}

function renderFinal() {
  var panel = document.getElementById('finalPanel');
  if (!S.finished) return;
  panel.classList.add('show');
  var scores = S.finalScores;
  if (!scores || Object.keys(scores).length === 0) scores = S.matchScores;
  var sorted = Object.keys(scores).sort(function(a,b) { return scores[b] - scores[a]; });
  var html = '';
  sorted.forEach(function(pid, i) {
    var model = modelShort(S.models[pid] || pid);
    var score = scores[pid];
    var stats = S.playerStats[pid] || {};
    var detail = (stats.gold_count||0) + 'G ' + (stats.silver_count||0) + 'S ' + (stats.bronze_count||0) + 'B';
    var rankColors = ['var(--gold)','var(--silver)','var(--bronze)','var(--dim)','var(--dim)','var(--dim)','var(--dim)','var(--dim)'];
    html += '<div class="standing-row">'
      + '<span class="standing-rank" style="color:' + rankColors[i] + '">#' + (i+1) + '</span>'
      + '<span class="standing-model" style="color:' + (PLAYER_COLORS[pid]||'var(--text)') + '">' + model + '</span>'
      + '<span class="standing-score">' + score + '</span>'
      + '<span class="standing-detail">' + detail + '</span>'
      + '</div>';
  });
  document.getElementById('finalStandings').innerHTML = html;
}

function renderFooter() {
  var dot = document.getElementById('statusDot');
  var text = document.getElementById('statusText');
  var lat = document.getElementById('latencyInfo');
  if (S.finished) {
    dot.className = 'status-dot done';
    text.textContent = 'Match complete';
  } else {
    dot.className = 'status-dot';
    text.textContent = 'LIVE';
  }
  if (S.lastLatency) {
    lat.textContent = 'Last: ' + (S.lastLatency/1000).toFixed(1) + 's';
  }
}

function escHtml(s) {
  var d = document.createElement('div');
  d.textContent = s;
  return d.innerHTML;
}

// SSE
var es = new EventSource('/events');
es.onmessage = function(e) {
  var data = JSON.parse(e.data);
  if (isReplaying) {
    turnQueue.push(data);
  } else if (rawLines.length === 0) {
    turnQueue.push(data);
    isReplaying = true;
    drainQueue();
  } else {
    processTurn(data);
    renderAll();
  }
};
es.addEventListener('done', function() {
  S.finished = true;
  renderAll();
});
es.onerror = function() {
  setTimeout(function() { location.reload(); }, 3000);
};

function drainQueue() {
  if (turnQueue.length === 0) { isReplaying = false; renderAll(); return; }
  var batch = turnQueue.splice(0, 5);
  batch.forEach(function(d) { processTurn(d); });
  renderAll();
  if (turnQueue.length > 0) {
    setTimeout(drainQueue, 150);
  } else {
    isReplaying = false;
    renderAll();
  }
}
</script>
</body>
</html>"""


# ── Spades HTML/CSS/JS ────────────────────────────────────────────

SPADES_HTML_PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Spades Spectator</title>
<style>
:root {
  --bg: #0d1117;
  --surface: #161b22;
  --border: #30363d;
  --text: #e6edf3;
  --dim: #7d8590;
  --cyan: #58a6ff;
  --magenta: #d2a8ff;
  --green: #3fb950;
  --red: #f85149;
  --yellow: #d29922;
  --felt: #1a3a1a;
  --team1: #58a6ff;
  --team2: #d2a8ff;
  --pa: #58a6ff;
  --pb: #d2a8ff;
  --pc: #3fb950;
  --pd: #d29922;
}
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
  background: var(--bg);
  color: var(--text);
  font-family: 'SF Mono', 'Cascadia Code', 'Fira Code', 'Consolas', monospace;
  font-size: 13px;
  line-height: 1.4;
  padding: 12px;
  max-width: 1200px;
  margin: 0 auto;
}

/* Header */
#header {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 12px 16px;
  margin-bottom: 10px;
  text-align: center;
}
.badge {
  display: inline-block;
  padding: 2px 10px;
  border-radius: 4px;
  font-weight: bold;
  font-size: 12px;
  margin-right: 8px;
  vertical-align: middle;
}
.badge-live { background: var(--green); color: #000; animation: pulse 2s infinite; }
.badge-final { background: var(--red); color: #fff; }
.badge-bid { background: var(--magenta); color: #000; }
.badge-play { background: var(--cyan); color: #000; }
@keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.6; } }
#header .title { font-size: 18px; font-weight: bold; letter-spacing: 1px; }
#header .sub { margin-top: 4px; color: var(--dim); }
.player-a { color: var(--pa); }
.player-b { color: var(--pb); }
.player-c { color: var(--pc); }
.player-d { color: var(--pd); }

/* Team scoreboard */
#team-scores {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
  margin-bottom: 10px;
}
.team-panel {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px 14px;
  border-left: 4px solid var(--border);
}
.team-panel.team-1 { border-left-color: var(--team1); }
.team-panel.team-2 { border-left-color: var(--team2); }
.team-panel .team-name { font-weight: bold; font-size: 14px; margin-bottom: 4px; }
.team-panel .team-score { font-size: 24px; font-weight: bold; margin: 4px 0; }
.team-panel .bags-display { font-size: 12px; margin: 2px 0; }
.bags-ok { color: var(--dim); }
.bags-warn { color: var(--yellow); }
.bags-danger { color: var(--red); font-weight: bold; }
.team-panel .member-bids { font-size: 12px; color: var(--dim); margin: 4px 0; }
.team-panel .contract-line { font-size: 13px; margin-top: 4px; }
.nil-badge { display: inline-block; background: var(--red); color: #fff; font-size: 10px; padding: 0 4px; border-radius: 3px; font-weight: bold; }
.nil-success { background: var(--green); color: #000; }

/* Shot clock */
#shot-clock {
  display: none;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 8px 16px;
  margin-bottom: 10px;
  text-align: center;
}
#shot-clock .clock-label { font-size: 11px; color: var(--dim); text-transform: uppercase; letter-spacing: 1px; }
#shot-clock .clock-display { font-size: 24px; font-weight: bold; font-variant-numeric: tabular-nums; letter-spacing: 1px; margin: 2px 0; }
#shot-clock .clock-display.clock-ok { color: var(--green); }
#shot-clock .clock-display.clock-warn { color: var(--yellow); }
#shot-clock .clock-display.clock-danger { color: var(--red); animation: pulse 0.5s infinite; }
#shot-clock .strike-info { font-size: 11px; color: var(--dim); }

/* Main area: trick + hands side by side */
#main-area {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
  margin-bottom: 10px;
}

/* Trick area */
#trick-area {
  background: var(--felt);
  border: 1px solid #2d5a2d;
  border-radius: 8px;
  padding: 14px;
  min-height: 300px;
  display: flex;
  flex-direction: column;
}
#trick-area .section-label { font-size: 11px; text-transform: uppercase; color: var(--dim); letter-spacing: 1px; margin-bottom: 8px; }

/* Compass trick display */
.compass {
  display: grid;
  grid-template-areas:
    ".    north ."
    "west center east"
    ".    south .";
  grid-template-columns: 1fr 1fr 1fr;
  grid-template-rows: auto auto auto;
  gap: 4px;
  margin: 8px 0;
  min-height: 140px;
  align-items: center;
  justify-items: center;
}
.compass-n { grid-area: north; }
.compass-e { grid-area: east; }
.compass-s { grid-area: south; }
.compass-w { grid-area: west; }
.compass-center { grid-area: center; font-size: 12px; color: var(--dim); text-align: center; }
.compass-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 6px 10px;
  text-align: center;
  min-width: 70px;
}
.compass-card .card-label { font-size: 10px; color: var(--dim); margin-bottom: 2px; }
.compass-card .card-value { font-size: 16px; font-weight: bold; }
.compass-card.winner { border-color: var(--green); background: rgba(63,185,80,0.1); }
.compass-card.empty { opacity: 0.3; }
.compass-card .card-value.red { color: var(--red); }
.compass-card .card-value.black { color: var(--text); }

/* Spades broken indicator */
.spades-broken { color: var(--cyan); font-weight: bold; font-size: 12px; margin-top: 6px; }

/* Bid collection panel (replaces trick area during bid phase) */
.bid-panel {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 8px 12px;
  margin: 4px 0;
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.bid-panel.done { border-color: var(--green); }
.bid-panel.waiting { border-color: var(--yellow); border-style: dashed; }

/* Hand history */
#hand-history {
  margin-top: auto;
  max-height: 180px;
  overflow-y: auto;
  font-size: 11px;
  border-top: 1px solid #2d5a2d;
  padding-top: 8px;
}
#hand-history .hh-entry { padding: 2px 0; border-bottom: 1px solid rgba(255,255,255,0.05); }
.hh-positive { color: var(--green); }
.hh-negative { color: var(--red); }

/* Player hands (god mode) */
#player-hands {
  display: grid;
  grid-template-columns: 1fr 1fr;
  grid-template-rows: 1fr 1fr;
  gap: 8px;
}
.hand-panel {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px 12px;
  transition: border-color 0.3s;
  position: relative;
}
.hand-panel.active { border-color: var(--green); border-width: 2px; }
.hand-panel.team-1-border { border-top: 3px solid var(--team1); }
.hand-panel.team-2-border { border-top: 3px solid var(--team2); }
.hand-panel .model-name { font-weight: bold; font-size: 13px; margin-bottom: 4px; }
.hand-panel .bid-info { font-size: 12px; color: var(--dim); margin-bottom: 4px; }
.hand-panel .hand {
  display: flex;
  flex-wrap: wrap;
  gap: 3px;
  margin: 6px 0;
  min-height: 24px;
}
.god-badge {
  position: absolute;
  top: 6px;
  right: 8px;
  background: var(--magenta);
  color: #000;
  font-size: 9px;
  font-weight: bold;
  padding: 1px 6px;
  border-radius: 3px;
  letter-spacing: 1px;
}
.card-pill {
  display: inline-block;
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 3px;
  padding: 1px 4px;
  font-size: 10px;
  font-weight: bold;
  white-space: nowrap;
}
.card-pill.red { color: var(--red); }
.card-pill.black { color: var(--text); }
.card-pill.playable { outline: 1px solid var(--green); background: rgba(63,185,80,0.08); }

/* Panels */
.panel {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px 14px;
  margin-bottom: 10px;
}
.panel h3 {
  font-size: 11px;
  text-transform: uppercase;
  color: var(--dim);
  border-bottom: 1px solid var(--border);
  padding-bottom: 4px;
  margin-bottom: 6px;
}

/* Reasoning panel */
#reasoning-panel { cursor: pointer; }
#reasoning-panel .content { max-height: 60px; overflow: hidden; transition: max-height 0.3s; }
#reasoning-panel.expanded .content { max-height: 300px; }

/* Final panel */
#final-panel { display: none; text-align: center; border-color: var(--yellow); }
#final-panel.show { display: block; }
#final-panel .winner { font-size: 20px; font-weight: bold; margin: 8px 0; }
#final-panel .standings { font-size: 13px; margin: 6px 0; }

/* Footer */
#footer {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 6px 14px;
  display: flex;
  justify-content: space-between;
  color: var(--dim);
  font-size: 11px;
}

/* Compact mode */
body.compact { padding: 4px; font-size: 11px; }
body.compact #header { padding: 6px 10px; margin-bottom: 6px; }
body.compact #header .title { font-size: 13px; }
body.compact .team-panel { padding: 6px 10px; }
body.compact .hand-panel { padding: 6px 8px; }
body.compact .card-pill { font-size: 9px; padding: 0 3px; }
body.compact #reasoning-panel { display: none; }
body.compact .panel { padding: 6px 10px; margin-bottom: 6px; }
</style>
</head>
<body>

<div id="header">
  <span id="badge" class="badge badge-live">LIVE</span>
  <span id="phase-badge" class="badge badge-bid" style="display:none">BID</span>
  <span class="title">SPADES</span>
  <div class="sub" id="sub-info">Loading...</div>
</div>

<div id="team-scores">
  <div class="team-panel team-1" id="team-1-panel">
    <div class="team-name" style="color:var(--team1)">Team 1</div>
    <div class="team-score" id="t1-score">0</div>
    <div class="bags-display bags-ok" id="t1-bags">Bags: 0/10</div>
    <div class="member-bids" id="t1-bids"></div>
    <div class="contract-line" id="t1-contract"></div>
  </div>
  <div class="team-panel team-2" id="team-2-panel">
    <div class="team-name" style="color:var(--team2)">Team 2</div>
    <div class="team-score" id="t2-score">0</div>
    <div class="bags-display bags-ok" id="t2-bags">Bags: 0/10</div>
    <div class="member-bids" id="t2-bids"></div>
    <div class="contract-line" id="t2-contract"></div>
  </div>
</div>

<div id="shot-clock">
  <div class="clock-label" id="clock-label">SHOT CLOCK</div>
  <div class="clock-display clock-ok" id="clock-display">--.-s</div>
  <div class="strike-info" id="strike-info"></div>
</div>

<div id="main-area">
  <div id="trick-area">
    <div class="section-label" id="trick-label">Trick 0/13</div>
    <div id="trick-content"></div>
    <div id="hand-history">
      <div class="section-label">Hand History</div>
      <div id="hh-content"><span style="color:var(--dim);font-style:italic">No completed hands</span></div>
    </div>
  </div>
  <div id="player-hands"></div>
</div>

<div class="panel" id="reasoning-panel" onclick="this.classList.toggle('expanded')">
  <h3>Reasoning (click to expand)</h3>
  <div class="content" id="reasoning-content"><span style="color:var(--dim);font-style:italic">Waiting...</span></div>
</div>

<div class="panel" id="final-panel">
  <h3>Final Results</h3>
  <div id="final-content"></div>
</div>

<div id="footer">
  <span id="status-text"><span class="badge badge-live" style="font-size:10px">LIVE</span> Watching...</span>
  <span>Turns: <span id="turn-count">0</span></span>
</div>

<script>
// Teams: team_1 = A+C, team_2 = B+D
var TEAMS = {team_1: ['player_a','player_c'], team_2: ['player_b','player_d']};
var PLAYER_TEAM = {};
Object.keys(TEAMS).forEach(function(t) { TEAMS[t].forEach(function(p) { PLAYER_TEAM[p] = t; }); });
var PLAY_ORDER = ['player_a','player_b','player_c','player_d'];
var PIDS = PLAY_ORDER.slice();
var LABELS = {player_a:'A', player_b:'B', player_c:'C', player_d:'D'};
var CLASS_NAMES = {player_a:'player-a', player_b:'player-b', player_c:'player-c', player_d:'player-d'};
// Compass positions: A=north, B=east, C=south, D=west
var COMPASS = {player_a:'n', player_b:'e', player_c:'s', player_d:'w'};

var S = {
  models: {},
  phase: 'bid',
  gameNumber: 1,
  gamesPerMatch: 1,
  handNumber: 1,
  trickNumber: 0,
  totalTricks: 13,
  turnNumber: 0,
  hands: {},
  bids: {},
  teamContracts: {},
  tricksTaken: {},
  currentTrick: [],
  trickLeader: 'player_a',
  spadesBroken: false,
  scores: {team_1:0, team_2:0},
  bags: {team_1:0, team_2:0},
  trickHistory: [],
  handHistory: [],
  matchScores: {},
  terminal: false,
  finished: false,
  finalScores: {},
  turnCount: 0,
  lastReasoning: '',
  lastModel: '',
  lastLatency: 0,
  violations: {},
  shotClock: { timeLimitMs: null, lastTurnTime: null, strikes: {}, strikeLimit: null, waitingOn: '' }
};

var rawLines = [];
var turnQueue = [];
var isReplaying = false;
var _handsInitialized = false;

if (new URLSearchParams(window.location.search).get('compact') === '1') {
  document.body.classList.add('compact');
}

function initHandPanels() {
  if (_handsInitialized) return;
  var html = '';
  // Order: A (team1), B (team2), C (team1), D (team2)
  PIDS.forEach(function(pid, i) {
    var team = PLAYER_TEAM[pid];
    var teamCls = team === 'team_1' ? 'team-1-border' : 'team-2-border';
    html += '<div class="hand-panel ' + teamCls + '" id="hp-' + pid + '">';
    if (i === 0) html += '<span class="god-badge">GOD MODE</span>';
    html += '<div class="model-name ' + CLASS_NAMES[pid] + '" id="hp-name-' + pid + '">Player ' + LABELS[pid] + '</div>';
    html += '<div class="bid-info" id="hp-bid-' + pid + '"></div>';
    html += '<div class="hand" id="hp-hand-' + pid + '"></div>';
    html += '</div>';
  });
  document.getElementById('player-hands').innerHTML = html;
  _handsInitialized = true;
}

function processTurn(data) {
  rawLines.push(data);

  if (data.record_type === 'match_summary') {
    S.finished = true;
    S.finalScores = data.final_scores || {};
    var pm = data.player_models || {};
    PIDS.forEach(function(pid) { if (pm[pid]) S.models[pid] = pm[pid]; });
    return;
  }

  S.turnCount++;
  var snap = data.state_snapshot || {};
  var pid = data.player_id || '';
  var mid = data.model_id || '';

  if (pid && mid) S.models[pid] = mid;
  var pm = snap.player_models || {};
  Object.keys(pm).forEach(function(k) { if (!S.models[k]) S.models[k] = pm[k]; });

  // Shot clock
  if (data.time_limit_ms) S.shotClock.timeLimitMs = data.time_limit_ms;
  if (data.strike_limit) S.shotClock.strikeLimit = data.strike_limit;
  if (data.cumulative_strikes !== undefined && pid) S.shotClock.strikes[pid] = data.cumulative_strikes;
  S.shotClock.lastTurnTime = Date.now();

  S.phase = snap.phase || S.phase;
  S.gameNumber = snap.game_number || S.gameNumber;
  S.gamesPerMatch = snap.games_per_match || S.gamesPerMatch;
  S.handNumber = snap.hand_number || S.handNumber;
  S.trickNumber = snap.trick_number || S.trickNumber;
  S.turnNumber = snap.turn_number || S.turnNumber;
  S.hands = snap.hands || S.hands;
  S.bids = snap.bids || S.bids;
  S.teamContracts = snap.team_contracts || S.teamContracts;
  S.tricksTaken = snap.tricks_taken || S.tricksTaken;
  S.currentTrick = snap.current_trick || S.currentTrick;
  S.trickLeader = snap.trick_leader || S.trickLeader;
  S.spadesBroken = snap.spades_broken || false;
  S.scores = snap.scores || S.scores;
  S.bags = snap.bags || S.bags;
  S.trickHistory = snap.trick_history || S.trickHistory;
  S.handHistory = snap.hand_history || S.handHistory;
  S.matchScores = snap.match_scores || S.matchScores;
  S.terminal = snap.terminal || false;

  // Derive total tricks from hand sizes at start
  var anyHand = S.hands[PIDS[0]] || [];
  var tricksTakenThisHand = 0;
  PIDS.forEach(function(p) { tricksTakenThisHand += (S.tricksTaken[p] || 0); });
  S.totalTricks = tricksTakenThisHand + anyHand.length + (S.currentTrick ? S.currentTrick.length : 0);
  if (S.totalTricks < 1) S.totalTricks = 13;

  // Derive who shot clock is waiting on
  S.shotClock.waitingOn = deriveActivePlayer();

  var reasoning = data.reasoning_output || '';
  if (reasoning) {
    S.lastReasoning = reasoning.length > 200 ? reasoning.substring(0, 197) + '...' : reasoning;
    S.lastModel = mid;
  }
  S.lastLatency = data.latency_ms || 0;

  if (data.violation && pid) {
    S.violations[pid] = (S.violations[pid] || 0) + 1;
  }
}

function deriveActivePlayer() {
  if (S.phase === 'bid') {
    // First player without a bid, starting from trick leader (rotates each hand)
    var startIdx = PLAY_ORDER.indexOf(S.trickLeader);
    for (var i = 0; i < 4; i++) {
      var p = PLAY_ORDER[(startIdx + i) % 4];
      if (S.bids[p] == null) return p;
    }
    return S.trickLeader;
  }
  // Play phase: trickLeader + offset based on cards played this trick
  var leaderIdx = PLAY_ORDER.indexOf(S.trickLeader);
  var offset = S.currentTrick ? S.currentTrick.length : 0;
  if (offset >= 4) return S.trickLeader; // trick complete, next leader
  return PLAY_ORDER[(leaderIdx + offset) % 4];
}

function renderAll() {
  if (!_handsInitialized) initHandPanels();
  renderHeader();
  renderTeamScores();
  renderShotClock();
  renderTrickArea();
  renderPlayerHands();
  renderHandHistory();
  renderReasoning();
  renderFinal();
  renderFooter();
}

function renderHeader() {
  var badge = document.getElementById('badge');
  badge.textContent = S.finished ? 'FINAL' : 'LIVE';
  badge.className = 'badge ' + (S.finished ? 'badge-final' : 'badge-live');

  var phaseBadge = document.getElementById('phase-badge');
  if (!S.finished) {
    phaseBadge.style.display = 'inline-block';
    phaseBadge.textContent = S.phase.toUpperCase();
    phaseBadge.className = 'badge ' + (S.phase === 'bid' ? 'badge-bid' : 'badge-play');
  } else {
    phaseBadge.style.display = 'none';
  }

  var parts = [];
  if (S.gamesPerMatch > 1) parts.push('Game ' + S.gameNumber + '/' + S.gamesPerMatch);
  parts.push('Hand ' + S.handNumber);
  if (S.phase === 'play') parts.push('Trick ' + S.trickNumber + '/' + S.totalTricks);
  parts.push('Turn ' + S.turnNumber);

  var models = [];
  PIDS.forEach(function(pid) {
    var m = S.models[pid] || ('Player ' + LABELS[pid]);
    models.push('<span class="' + CLASS_NAMES[pid] + '">' + m + '</span>');
  });
  document.getElementById('sub-info').innerHTML = models.join(' <span style="color:var(--dim)">vs</span> ') + ' <span style="color:var(--dim)">|</span> ' + parts.join(' <span style="color:var(--dim)">|</span> ');
}

function renderTeamScores() {
  ['team_1','team_2'].forEach(function(team, ti) {
    var prefix = ti === 0 ? 't1' : 't2';
    var score = S.scores[team] || 0;
    var bags = S.bags[team] || 0;

    document.getElementById(prefix + '-score').textContent = score;

    var bagsEl = document.getElementById(prefix + '-bags');
    bagsEl.textContent = 'Bags: ' + bags + '/10';
    bagsEl.className = 'bags-display ' + (bags >= 9 ? 'bags-danger' : bags >= 7 ? 'bags-warn' : 'bags-ok');

    // Member bids
    var members = TEAMS[team];
    var bidParts = [];
    members.forEach(function(pid) {
      var m = S.models[pid] || LABELS[pid];
      var bid = S.bids[pid];
      var bidStr = bid != null ? bid : '...';
      var nilBadge = '';
      if (bid === 0) nilBadge = ' <span class="nil-badge">NIL</span>';
      bidParts.push('<span class="' + CLASS_NAMES[pid] + '">' + m + '</span>: ' + bidStr + nilBadge);
    });
    document.getElementById(prefix + '-bids').innerHTML = bidParts.join(' &middot; ');

    // Contract vs tricks
    var contract = S.teamContracts[team];
    var tricks = 0;
    members.forEach(function(pid) { tricks += (S.tricksTaken[pid] || 0); });
    if (contract != null) {
      document.getElementById(prefix + '-contract').innerHTML = 'Contract: <strong>' + contract + '</strong> Won: <strong>' + tricks + '</strong>';
    } else {
      document.getElementById(prefix + '-contract').innerHTML = '';
    }
  });
}

function renderShotClock() {
  var el = document.getElementById('shot-clock');
  if (!S.shotClock.timeLimitMs) return;
  el.style.display = 'block';
  var display = document.getElementById('clock-display');
  var label = document.getElementById('clock-label');
  var strikeEl = document.getElementById('strike-info');
  if (S.shotClock.lastTurnTime && !isReplaying) {
    var elapsed = Date.now() - S.shotClock.lastTurnTime;
    var remaining = Math.max(0, S.shotClock.timeLimitMs - elapsed);
    var secs = remaining / 1000;
    display.textContent = secs.toFixed(1) + 's';
    var cls = 'clock-display ';
    if (remaining <= 5000) cls += 'clock-danger';
    else if (remaining <= 10000) cls += 'clock-warn';
    else cls += 'clock-ok';
    display.className = cls;
  } else {
    display.textContent = (S.shotClock.timeLimitMs / 1000).toFixed(1) + 's';
    display.className = 'clock-display clock-ok';
  }
  var wPid = S.shotClock.waitingOn;
  var wModel = S.models[wPid] || wPid;
  label.innerHTML = 'SHOT CLOCK <span style="color:var(--dim)">&middot;</span> ' + wModel;
  if (S.shotClock.strikeLimit) {
    var strikeParts = [];
    PIDS.forEach(function(pid) {
      var s = S.shotClock.strikes[pid] || 0;
      var m = S.models[pid] || LABELS[pid];
      strikeParts.push('<span class="' + CLASS_NAMES[pid] + '">' + m + ': ' + s + '/' + S.shotClock.strikeLimit + '</span>');
    });
    strikeEl.innerHTML = strikeParts.join(' &middot; ');
  } else { strikeEl.innerHTML = ''; }
  if (S.finished) el.style.display = 'none';
}

function cardHTML(card, extraClass) {
  var suit = card.slice(-1);
  var isRed = (suit === '\u2665' || suit === '\u2666');
  var cls = 'card-pill ' + (isRed ? 'red' : 'black');
  if (extraClass) cls += ' ' + extraClass;
  return '<span class="' + cls + '">' + card + '</span>';
}

function renderTrickArea() {
  var labelEl = document.getElementById('trick-label');

  if (S.phase === 'bid') {
    labelEl.textContent = 'Bidding — Hand ' + S.handNumber;
    var html = '';
    PLAY_ORDER.forEach(function(pid) {
      var m = S.models[pid] || LABELS[pid];
      var bid = S.bids[pid];
      var hasBid = bid != null;
      var cls = hasBid ? 'bid-panel done' : 'bid-panel waiting';
      var bidText = hasBid ? '<strong>' + bid + '</strong>' + (bid === 0 ? ' <span class="nil-badge">NIL</span>' : '') : '<span style="color:var(--yellow)">waiting...</span>';
      html += '<div class="' + cls + '"><span class="' + CLASS_NAMES[pid] + '">' + m + '</span><span>' + bidText + '</span></div>';
    });
    document.getElementById('trick-content').innerHTML = html;
    return;
  }

  labelEl.textContent = 'Trick ' + S.trickNumber + '/' + S.totalTricks;

  // Build compass with current trick cards
  var played = {};
  var trickWinner = null;
  var trickComplete = S.currentTrick && S.currentTrick.length >= 4;
  var ledSuit = S.currentTrick && S.currentTrick.length > 0 ? S.currentTrick[0].card.slice(-1) : '';

  if (S.currentTrick) {
    S.currentTrick.forEach(function(entry) { played[entry.player] = entry.card; });
  }
  // If trick just completed, find winner from trick_history
  if (trickComplete && S.trickHistory.length > 0) {
    var lastTrick = S.trickHistory[S.trickHistory.length - 1];
    trickWinner = lastTrick.winner;
  }

  var compassHTML = '<div class="compass">';
  var positions = [{pid:'player_a',cls:'compass-n'},{pid:'player_b',cls:'compass-e'},{pid:'player_c',cls:'compass-s'},{pid:'player_d',cls:'compass-w'}];
  positions.forEach(function(pos) {
    var card = played[pos.pid];
    var m = S.models[pos.pid] || LABELS[pos.pid];
    var shortName = m.length > 12 ? m.substring(0,10) + '..' : m;
    var isWinner = trickWinner === pos.pid;
    var winCls = isWinner ? ' winner' : '';
    var emptyCls = card ? '' : ' empty';
    compassHTML += '<div class="compass-card' + winCls + emptyCls + ' ' + pos.cls + '">';
    compassHTML += '<div class="card-label ' + CLASS_NAMES[pos.pid] + '">' + shortName + '</div>';
    if (card) {
      var suit = card.slice(-1);
      var isRed = (suit === '\u2665' || suit === '\u2666');
      compassHTML += '<div class="card-value ' + (isRed ? 'red' : 'black') + '">' + card + '</div>';
    } else {
      compassHTML += '<div class="card-value" style="color:var(--dim)">--</div>';
    }
    compassHTML += '</div>';
  });
  // Center: trick info
  var centerText = '';
  if (trickComplete && trickWinner) {
    var wm = S.models[trickWinner] || LABELS[trickWinner];
    centerText = '<span class="' + CLASS_NAMES[trickWinner] + '">' + wm + '</span> wins';
  } else if (ledSuit) {
    var suitNames = {'\u2663':'Clubs','\u2666':'Diamonds','\u2665':'Hearts','\u2660':'Spades'};
    centerText = 'Led: ' + (suitNames[ledSuit] || ledSuit);
  } else {
    centerText = 'Leading...';
  }
  compassHTML += '<div class="compass-center">' + centerText + '</div>';
  compassHTML += '</div>';

  // Spades broken indicator
  if (S.spadesBroken) {
    compassHTML += '<div class="spades-broken">\u2660 SPADES BROKEN</div>';
  }

  document.getElementById('trick-content').innerHTML = compassHTML;
}

function renderPlayerHands() {
  if (!_handsInitialized) return;
  var activePlayer = deriveActivePlayer();

  PIDS.forEach(function(pid) {
    var panel = document.getElementById('hp-' + pid);
    var nameEl = document.getElementById('hp-name-' + pid);
    var bidEl = document.getElementById('hp-bid-' + pid);
    var handEl = document.getElementById('hp-hand-' + pid);

    var model = S.models[pid] || ('Player ' + LABELS[pid]);
    nameEl.textContent = model;

    // Active highlight
    var isActive = (pid === activePlayer && !S.finished);
    panel.className = panel.className.replace(/ ?active/g, '');
    if (isActive) panel.className += ' active';

    // Bid + tricks info
    var bid = S.bids[pid];
    var tricks = S.tricksTaken[pid] || 0;
    if (bid != null) {
      var nilBadge = bid === 0 ? ' <span class="nil-badge">NIL</span>' : '';
      bidEl.innerHTML = 'Bid: <strong>' + bid + '</strong>' + nilBadge + ' | Won: <strong>' + tricks + '</strong>';
    } else {
      bidEl.innerHTML = S.phase === 'bid' ? 'Waiting to bid...' : '';
    }

    // Hand cards
    var hand = S.hands[pid] || [];
    if (hand.length > 0) {
      // Determine playable cards for active player during play phase
      var playable = {};
      if (S.phase === 'play' && pid === activePlayer && !S.finished) {
        var ledS = S.currentTrick && S.currentTrick.length > 0 ? S.currentTrick[0].card.slice(-1) : null;
        if (ledS) {
          var hasSuit = hand.some(function(c) { return c.slice(-1) === ledS; });
          hand.forEach(function(c) {
            if (hasSuit) { if (c.slice(-1) === ledS) playable[c] = true; }
            else playable[c] = true;
          });
        } else {
          // Leading
          hand.forEach(function(c) {
            if (!S.spadesBroken && c.slice(-1) === '\u2660') {
              // Can only lead spades if all cards are spades
              var allSpades = hand.every(function(cc) { return cc.slice(-1) === '\u2660'; });
              if (allSpades) playable[c] = true;
            } else {
              playable[c] = true;
            }
          });
        }
      }
      handEl.innerHTML = hand.map(function(card) {
        return cardHTML(card, playable[card] ? 'playable' : '');
      }).join('');
    } else {
      handEl.innerHTML = '<span style="color:var(--dim)">(empty)</span>';
    }
  });
}

function renderHandHistory() {
  var el = document.getElementById('hh-content');
  if (!S.handHistory || S.handHistory.length === 0) {
    el.innerHTML = '<span style="color:var(--dim);font-style:italic">No completed hands</span>';
    return;
  }
  var html = '';
  S.handHistory.slice().reverse().forEach(function(h) {
    html += '<div class="hh-entry" style="margin-bottom:4px">';
    html += '<strong>H' + h.hand_number + '</strong>: ';
    ['team_1','team_2'].forEach(function(team, ti) {
      var t = h.teams ? h.teams[team] : null;
      if (!t) return;
      var label = ti === 0 ? 'T1' : 'T2';
      var pts = t.hand_points || 0;
      var ptsCls = pts >= 0 ? 'hh-positive' : 'hh-negative';
      var sign = pts >= 0 ? '+' : '';
      html += label + ' bid ' + t.contract + ' <span class="' + ptsCls + '">' + sign + pts + '</span>';
      // Nil results
      if (t.nil_results && t.nil_results.length > 0) {
        t.nil_results.forEach(function(nr) {
          var nm = S.models[nr.player] || LABELS[nr.player] || nr.player;
          if (nr.success) {
            html += ' <span class="nil-badge nil-success">' + nm + ' NIL OK</span>';
          } else {
            html += ' <span class="nil-badge">' + nm + ' NIL FAIL</span>';
          }
        });
      }
      html += ' (total: ' + t.total_score + ') ';
    });
    html += '</div>';
  });
  el.innerHTML = html;
}

function renderReasoning() {
  var el = document.getElementById('reasoning-content');
  if (!S.lastReasoning) {
    el.innerHTML = '<span style="color:var(--dim);font-style:italic">Waiting...</span>';
    return;
  }
  var latStr = S.lastLatency ? ' (' + (S.lastLatency / 1000).toFixed(1) + 's)' : '';
  el.innerHTML = '<span style="font-weight:bold">' + (S.lastModel || '?') + latStr + ':</span> <span style="font-style:italic;color:var(--dim)">' + S.lastReasoning.replace(/</g,'&lt;').replace(/>/g,'&gt;') + '</span>';
}

function renderFinal() {
  var panel = document.getElementById('final-panel');
  if (!S.finished) { panel.className = 'panel'; return; }
  panel.className = 'panel show';

  var scores = S.finalScores || S.matchScores;
  // Determine winning team
  var t1Total = 0, t2Total = 0;
  TEAMS.team_1.forEach(function(p) { t1Total += (scores[p] || 0); });
  TEAMS.team_2.forEach(function(p) { t2Total += (scores[p] || 0); });

  var winTeam = t1Total >= t2Total ? 'team_1' : 'team_2';
  var winColor = winTeam === 'team_1' ? 'var(--team1)' : 'var(--team2)';
  var winLabel = winTeam === 'team_1' ? 'Team 1' : 'Team 2';
  var winMembers = TEAMS[winTeam].map(function(p) { return S.models[p] || LABELS[p]; }).join(' + ');

  var html = '<div class="winner" style="color:' + winColor + '">' + winLabel + ' WINS!</div>';
  html += '<div style="font-size:14px;margin:4px 0">' + winMembers + '</div>';
  html += '<div class="standings" style="margin-top:8px">';
  html += '<div style="color:var(--team1)">Team 1: ' + S.scores.team_1 + ' pts, ' + S.bags.team_1 + ' bags</div>';
  html += '<div style="color:var(--team2)">Team 2: ' + S.scores.team_2 + ' pts, ' + S.bags.team_2 + ' bags</div>';
  html += '</div>';
  html += '<div class="standings" style="margin-top:8px"><strong>Match Scores</strong>';
  PIDS.forEach(function(pid) {
    var m = S.models[pid] || LABELS[pid];
    html += '<div><span class="' + CLASS_NAMES[pid] + '">' + m + '</span>: ' + Math.round(scores[pid] || 0) + ' pts</div>';
  });
  html += '</div>';

  document.getElementById('final-content').innerHTML = html;
}

function renderFooter() {
  var st = document.getElementById('status-text');
  if (S.finished) {
    st.innerHTML = '<span class="badge badge-final" style="font-size:10px">FINAL</span> Match Complete';
  } else {
    st.innerHTML = '<span class="badge badge-live" style="font-size:10px">LIVE</span> Watching...';
  }
  document.getElementById('turn-count').textContent = S.turnCount;
}

function drainQueue() {
  if (turnQueue.length === 0) { isReplaying = false; return; }
  var batch = turnQueue.splice(0, 5);
  batch.forEach(function(d) { processTurn(d); });
  renderAll();
  if (turnQueue.length > 0) {
    setTimeout(drainQueue, 150);
  } else {
    isReplaying = false;
    renderShotClock();
  }
}

// SSE connection
var evtPath = '/events';
if (window.location.pathname.match(/^\/match\//)) {
  var matchId = window.location.pathname.split('/match/')[1];
  if (matchId) evtPath = '/events/' + matchId;
}
var es = new EventSource(evtPath);
es.onmessage = function(e) {
  var data = JSON.parse(e.data);
  if (isReplaying) {
    turnQueue.push(data);
  } else if (rawLines.length === 0) {
    turnQueue.push(data);
    isReplaying = true;
    drainQueue();
  } else {
    processTurn(data);
    renderAll();
  }
};
setInterval(function() {
  if (S.shotClock.timeLimitMs && !S.finished && !isReplaying) renderShotClock();
}, 100);
</script>
</body>
</html>"""


# ── Hearts HTML/CSS/JS ────────────────────────────────────────────

HEARTS_HTML_PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Hearts Spectator</title>
<style>
:root {
  --bg: #0d1117;
  --surface: #161b22;
  --border: #30363d;
  --text: #e6edf3;
  --dim: #7d8590;
  --cyan: #58a6ff;
  --magenta: #d2a8ff;
  --green: #3fb950;
  --red: #f85149;
  --yellow: #d29922;
  --felt: #1a3a1a;
  --gold: #ffd700;
  --pa: #58a6ff;
  --pb: #d2a8ff;
  --pc: #3fb950;
  --pd: #d29922;
}
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
  background: var(--bg);
  color: var(--text);
  font-family: 'SF Mono', 'Cascadia Code', 'Fira Code', 'Consolas', monospace;
  font-size: 13px;
  line-height: 1.4;
  padding: 12px;
  max-width: 1200px;
  margin: 0 auto;
}

/* Header */
#header {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 12px 16px;
  margin-bottom: 10px;
  text-align: center;
}
.badge {
  display: inline-block;
  padding: 2px 10px;
  border-radius: 4px;
  font-weight: bold;
  font-size: 12px;
  margin-right: 8px;
  vertical-align: middle;
}
.badge-live { background: var(--green); color: #000; animation: pulse 2s infinite; }
.badge-final { background: var(--red); color: #fff; }
.badge-pass { background: var(--magenta); color: #000; }
.badge-play { background: var(--cyan); color: #000; }
@keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.6; } }
#header .title { font-size: 18px; font-weight: bold; letter-spacing: 1px; }
#header .sub { margin-top: 4px; color: var(--dim); }
.player-a { color: var(--pa); }
.player-b { color: var(--pb); }
.player-c { color: var(--pc); }
.player-d { color: var(--pd); }

/* Player scoreboard — 4 individual panels */
#player-scores {
  display: grid;
  grid-template-columns: 1fr 1fr 1fr 1fr;
  gap: 8px;
  margin-bottom: 10px;
}
.score-panel {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px 14px;
  text-align: center;
  border-top: 3px solid var(--border);
}
.score-panel.sp-a { border-top-color: var(--pa); }
.score-panel.sp-b { border-top-color: var(--pb); }
.score-panel.sp-c { border-top-color: var(--pc); }
.score-panel.sp-d { border-top-color: var(--pd); }
.score-panel .sp-name { font-weight: bold; font-size: 12px; margin-bottom: 4px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.score-panel .sp-total { font-size: 24px; font-weight: bold; margin: 4px 0; }
.score-panel .sp-hand-pts { font-size: 12px; color: var(--dim); }
.score-panel .sp-hearts-broken { font-size: 11px; margin-top: 4px; }
.hearts-broken-badge { color: var(--red); font-weight: bold; }

/* Shot clock */
#shot-clock {
  display: none;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 8px 16px;
  margin-bottom: 10px;
  text-align: center;
}
#shot-clock .clock-label { font-size: 11px; color: var(--dim); text-transform: uppercase; letter-spacing: 1px; }
#shot-clock .clock-display { font-size: 24px; font-weight: bold; font-variant-numeric: tabular-nums; letter-spacing: 1px; margin: 2px 0; }
#shot-clock .clock-display.clock-ok { color: var(--green); }
#shot-clock .clock-display.clock-warn { color: var(--yellow); }
#shot-clock .clock-display.clock-danger { color: var(--red); animation: pulse 0.5s infinite; }
#shot-clock .strike-info { font-size: 11px; color: var(--dim); }

/* Shoot the Moon alert */
#moon-alert {
  display: none;
  background: rgba(255,215,0,0.1);
  border: 2px solid var(--gold);
  border-radius: 8px;
  padding: 8px 16px;
  margin-bottom: 10px;
  text-align: center;
  font-weight: bold;
  color: var(--gold);
  animation: pulse 1s infinite;
}

/* Main area: trick + hands side by side */
#main-area {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
  margin-bottom: 10px;
}

/* Trick area */
#trick-area {
  background: var(--felt);
  border: 1px solid #2d5a2d;
  border-radius: 8px;
  padding: 14px;
  min-height: 300px;
  display: flex;
  flex-direction: column;
}
#trick-area .section-label { font-size: 11px; text-transform: uppercase; color: var(--dim); letter-spacing: 1px; margin-bottom: 8px; }

/* Compass trick display */
.compass {
  display: grid;
  grid-template-areas:
    ".    north ."
    "west center east"
    ".    south .";
  grid-template-columns: 1fr 1fr 1fr;
  grid-template-rows: auto auto auto;
  gap: 4px;
  margin: 8px 0;
  min-height: 140px;
  align-items: center;
  justify-items: center;
}
.compass-n { grid-area: north; }
.compass-e { grid-area: east; }
.compass-s { grid-area: south; }
.compass-w { grid-area: west; }
.compass-center { grid-area: center; font-size: 12px; color: var(--dim); text-align: center; }
.compass-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 6px 10px;
  text-align: center;
  min-width: 70px;
}
.compass-card .card-label { font-size: 10px; color: var(--dim); margin-bottom: 2px; }
.compass-card .card-value { font-size: 16px; font-weight: bold; }
.compass-card.winner { border-color: var(--green); background: rgba(63,185,80,0.1); }
.compass-card.empty { opacity: 0.3; }
.compass-card .card-value.red { color: var(--red); }
.compass-card .card-value.black { color: var(--text); }

/* Hearts broken indicator */
.hearts-broken { color: var(--red); font-weight: bold; font-size: 12px; margin-top: 6px; }

/* Pass phase panel */
.pass-panel {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 8px 12px;
  margin: 4px 0;
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.pass-panel.done { border-color: var(--green); }
.pass-panel.waiting { border-color: var(--yellow); border-style: dashed; }
.pass-direction-label { font-size: 11px; color: var(--dim); text-transform: uppercase; letter-spacing: 1px; margin-bottom: 4px; }

/* Hand history */
#hand-history {
  margin-top: auto;
  max-height: 180px;
  overflow-y: auto;
  font-size: 11px;
  border-top: 1px solid #2d5a2d;
  padding-top: 8px;
}
#hand-history .hh-entry { padding: 2px 0; border-bottom: 1px solid rgba(255,255,255,0.05); }
.hh-positive { color: var(--green); }
.hh-negative { color: var(--red); }
.hh-moon { color: var(--gold); font-weight: bold; }

/* Player hands (god mode) */
#player-hands {
  display: grid;
  grid-template-columns: 1fr 1fr;
  grid-template-rows: 1fr 1fr;
  gap: 8px;
}
.hand-panel {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px 12px;
  transition: border-color 0.3s;
  position: relative;
}
.hand-panel.active { border-color: var(--green); border-width: 2px; }
.hand-panel.sp-a-border { border-top: 3px solid var(--pa); }
.hand-panel.sp-b-border { border-top: 3px solid var(--pb); }
.hand-panel.sp-c-border { border-top: 3px solid var(--pc); }
.hand-panel.sp-d-border { border-top: 3px solid var(--pd); }
.hand-panel .model-name { font-weight: bold; font-size: 13px; margin-bottom: 4px; }
.hand-panel .penalty-info { font-size: 12px; color: var(--dim); margin-bottom: 4px; }
.hand-panel .hand {
  display: flex;
  flex-wrap: wrap;
  gap: 3px;
  margin: 6px 0;
  min-height: 24px;
}
.god-badge {
  position: absolute;
  top: 6px;
  right: 8px;
  background: var(--magenta);
  color: #000;
  font-size: 9px;
  font-weight: bold;
  padding: 1px 6px;
  border-radius: 3px;
  letter-spacing: 1px;
}
.card-pill {
  display: inline-block;
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 3px;
  padding: 1px 4px;
  font-size: 10px;
  font-weight: bold;
  white-space: nowrap;
}
.card-pill.red { color: var(--red); }
.card-pill.black { color: var(--text); }
.card-pill.playable { outline: 1px solid var(--green); background: rgba(63,185,80,0.08); }
.card-pill.penalty-heart { outline: 1px solid var(--red); }
.card-pill.penalty-queen { outline: 1px solid var(--magenta); }

/* Panels */
.panel {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px 14px;
  margin-bottom: 10px;
}
.panel h3 {
  font-size: 11px;
  text-transform: uppercase;
  color: var(--dim);
  border-bottom: 1px solid var(--border);
  padding-bottom: 4px;
  margin-bottom: 6px;
}

/* Reasoning panel */
#reasoning-panel { cursor: pointer; }
#reasoning-panel .content { max-height: 60px; overflow: hidden; transition: max-height 0.3s; }
#reasoning-panel.expanded .content { max-height: 300px; }

/* Final panel */
#final-panel { display: none; text-align: center; border-color: var(--yellow); }
#final-panel.show { display: block; }
#final-panel .winner { font-size: 20px; font-weight: bold; margin: 8px 0; }
#final-panel .standings { font-size: 13px; margin: 6px 0; }

/* Footer */
#footer {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 6px 14px;
  display: flex;
  justify-content: space-between;
  color: var(--dim);
  font-size: 11px;
}

/* Compact mode */
body.compact { padding: 4px; font-size: 11px; }
body.compact #header { padding: 6px 10px; margin-bottom: 6px; }
body.compact #header .title { font-size: 13px; }
body.compact .score-panel { padding: 6px 10px; }
body.compact .hand-panel { padding: 6px 8px; }
body.compact .card-pill { font-size: 9px; padding: 0 3px; }
body.compact #reasoning-panel { display: none; }
body.compact .panel { padding: 6px 10px; margin-bottom: 6px; }
</style>
</head>
<body>

<div id="header">
  <span id="badge" class="badge badge-live">LIVE</span>
  <span id="phase-badge" class="badge badge-pass" style="display:none">PASS</span>
  <span class="title">HEARTS</span>
  <div class="sub" id="sub-info">Loading...</div>
</div>

<div id="player-scores">
  <div class="score-panel sp-a" id="sp-a">
    <div class="sp-name player-a" id="sp-name-a">Player A</div>
    <div class="sp-total" id="sp-total-a">0</div>
    <div class="sp-hand-pts" id="sp-hand-a">This hand: 0</div>
  </div>
  <div class="score-panel sp-b" id="sp-b">
    <div class="sp-name player-b" id="sp-name-b">Player B</div>
    <div class="sp-total" id="sp-total-b">0</div>
    <div class="sp-hand-pts" id="sp-hand-b">This hand: 0</div>
  </div>
  <div class="score-panel sp-c" id="sp-c">
    <div class="sp-name player-c" id="sp-name-c">Player C</div>
    <div class="sp-total" id="sp-total-c">0</div>
    <div class="sp-hand-pts" id="sp-hand-c">This hand: 0</div>
  </div>
  <div class="score-panel sp-d" id="sp-d">
    <div class="sp-name player-d" id="sp-name-d">Player D</div>
    <div class="sp-total" id="sp-total-d">0</div>
    <div class="sp-hand-pts" id="sp-hand-d">This hand: 0</div>
  </div>
</div>

<div id="shot-clock">
  <div class="clock-label" id="clock-label">SHOT CLOCK</div>
  <div class="clock-display clock-ok" id="clock-display">--.-s</div>
  <div class="strike-info" id="strike-info"></div>
</div>

<div id="moon-alert">SHOOT THE MOON ATTEMPT!</div>

<div id="main-area">
  <div id="trick-area">
    <div class="section-label" id="trick-label">Trick 0/13</div>
    <div id="trick-content"></div>
    <div id="hand-history">
      <div class="section-label">Hand History</div>
      <div id="hh-content"><span style="color:var(--dim);font-style:italic">No completed hands</span></div>
    </div>
  </div>
  <div id="player-hands"></div>
</div>

<div class="panel" id="reasoning-panel" onclick="this.classList.toggle('expanded')">
  <h3>Reasoning (click to expand)</h3>
  <div class="content" id="reasoning-content"><span style="color:var(--dim);font-style:italic">Waiting...</span></div>
</div>

<div class="panel" id="final-panel">
  <h3>Final Results</h3>
  <div id="final-content"></div>
</div>

<div id="footer">
  <span id="status-text"><span class="badge badge-live" style="font-size:10px">LIVE</span> Watching...</span>
  <span>Turns: <span id="turn-count">0</span></span>
</div>

<script>
var PLAY_ORDER = ['player_a','player_b','player_c','player_d'];
var PIDS = PLAY_ORDER.slice();
var LABELS = {player_a:'A', player_b:'B', player_c:'C', player_d:'D'};
var CLASS_NAMES = {player_a:'player-a', player_b:'player-b', player_c:'player-c', player_d:'player-d'};
var COMPASS = {player_a:'n', player_b:'e', player_c:'s', player_d:'w'};
var PLAYER_COLORS = {player_a:'var(--pa)', player_b:'var(--pb)', player_c:'var(--pc)', player_d:'var(--pd)'};

var S = {
  models: {},
  phase: 'pass',
  gameNumber: 1,
  gamesPerMatch: 1,
  handNumber: 1,
  trickNumber: 0,
  totalTricks: 13,
  turnNumber: 0,
  hands: {},
  passDirection: 'left',
  passedCards: {},
  receivedCards: {},
  currentTrick: [],
  trickLeader: 'player_a',
  dealer: 'player_a',
  penaltyThisHand: {},
  gameScores: {},
  heartsBroken: false,
  queenTakenBy: null,
  trickHistory: [],
  handHistory: [],
  matchScores: {},
  terminal: false,
  finished: false,
  finalScores: {},
  turnCount: 0,
  lastReasoning: '',
  lastModel: '',
  lastLatency: 0,
  violations: {},
  shotClock: { timeLimitMs: null, lastTurnTime: null, strikes: {}, strikeLimit: null, waitingOn: '' }
};

var rawLines = [];
var turnQueue = [];
var isReplaying = false;
var _handsInitialized = false;

if (new URLSearchParams(window.location.search).get('compact') === '1') {
  document.body.classList.add('compact');
}

function initHandPanels() {
  if (_handsInitialized) return;
  var html = '';
  PIDS.forEach(function(pid, i) {
    var borderCls = 'sp-' + LABELS[pid].toLowerCase() + '-border';
    html += '<div class="hand-panel ' + borderCls + '" id="hp-' + pid + '">';
    if (i === 0) html += '<span class="god-badge">GOD MODE</span>';
    html += '<div class="model-name ' + CLASS_NAMES[pid] + '" id="hp-name-' + pid + '">Player ' + LABELS[pid] + '</div>';
    html += '<div class="penalty-info" id="hp-penalty-' + pid + '"></div>';
    html += '<div class="hand" id="hp-hand-' + pid + '"></div>';
    html += '</div>';
  });
  document.getElementById('player-hands').innerHTML = html;
  _handsInitialized = true;
}

function processTurn(data) {
  rawLines.push(data);

  if (data.record_type === 'match_summary') {
    S.finished = true;
    S.finalScores = data.final_scores || {};
    var pm = data.player_models || {};
    PIDS.forEach(function(pid) { if (pm[pid]) S.models[pid] = pm[pid]; });
    return;
  }

  S.turnCount++;
  var snap = data.state_snapshot || {};
  var pid = data.player_id || '';
  var mid = data.model_id || '';

  if (pid && mid) S.models[pid] = mid;
  var pm = snap.player_models || {};
  Object.keys(pm).forEach(function(k) { if (!S.models[k]) S.models[k] = pm[k]; });

  // Shot clock
  if (data.time_limit_ms) S.shotClock.timeLimitMs = data.time_limit_ms;
  if (data.strike_limit) S.shotClock.strikeLimit = data.strike_limit;
  if (data.cumulative_strikes !== undefined && pid) S.shotClock.strikes[pid] = data.cumulative_strikes;
  S.shotClock.lastTurnTime = Date.now();

  S.phase = snap.phase || S.phase;
  S.gameNumber = snap.game_number || S.gameNumber;
  S.gamesPerMatch = snap.games_per_match || S.gamesPerMatch;
  S.handNumber = snap.hand_number || S.handNumber;
  S.trickNumber = snap.trick_number || S.trickNumber;
  S.turnNumber = snap.turn_number || S.turnNumber;
  S.hands = snap.hands || S.hands;
  S.passDirection = snap.pass_direction || S.passDirection;
  S.passedCards = snap.passed_cards || S.passedCards;
  S.receivedCards = snap.received_cards || S.receivedCards;
  S.currentTrick = snap.current_trick || S.currentTrick;
  S.trickLeader = snap.trick_leader || S.trickLeader;
  S.dealer = snap.dealer || S.dealer;
  S.penaltyThisHand = snap.penalty_this_hand || S.penaltyThisHand;
  S.gameScores = snap.game_scores || S.gameScores;
  S.heartsBroken = snap.hearts_broken || false;
  S.queenTakenBy = snap.queen_taken_by || null;
  S.trickHistory = snap.trick_history || S.trickHistory;
  S.handHistory = snap.hand_history || S.handHistory;
  S.matchScores = snap.match_scores || S.matchScores;
  S.terminal = snap.terminal || false;

  // Derive total tricks
  var anyHand = S.hands[PIDS[0]] || [];
  var tricksTakenThisHand = 0;
  PIDS.forEach(function(p) { tricksTakenThisHand += (S.penaltyThisHand[p] !== undefined ? 1 : 0); });
  // Better estimate from trick history length this hand
  S.totalTricks = 13;

  S.shotClock.waitingOn = deriveActivePlayer();

  var reasoning = data.reasoning_output || '';
  if (reasoning) {
    S.lastReasoning = reasoning.length > 200 ? reasoning.substring(0, 197) + '...' : reasoning;
    S.lastModel = mid;
  }
  S.lastLatency = data.latency_ms || 0;

  if (data.violation && pid) {
    S.violations[pid] = (S.violations[pid] || 0) + 1;
  }
}

function deriveActivePlayer() {
  if (S.phase === 'pass') {
    // During pass, first player who hasn't passed yet
    for (var i = 0; i < 4; i++) {
      var p = PLAY_ORDER[i];
      if (!S.passedCards[p] || S.passedCards[p].length === 0) return p;
    }
    return PLAY_ORDER[0];
  }
  // Play phase: trickLeader + offset based on cards played this trick
  var leaderIdx = PLAY_ORDER.indexOf(S.trickLeader);
  var offset = S.currentTrick ? S.currentTrick.length : 0;
  if (offset >= 4) return S.trickLeader;
  return PLAY_ORDER[(leaderIdx + offset) % 4];
}

function renderAll() {
  if (!_handsInitialized) initHandPanels();
  renderHeader();
  renderPlayerScores();
  renderShotClock();
  renderMoonAlert();
  renderTrickArea();
  renderPlayerHands();
  renderHandHistory();
  renderReasoning();
  renderFinal();
  renderFooter();
}

function renderHeader() {
  var badge = document.getElementById('badge');
  badge.textContent = S.finished ? 'FINAL' : 'LIVE';
  badge.className = 'badge ' + (S.finished ? 'badge-final' : 'badge-live');

  var phaseBadge = document.getElementById('phase-badge');
  if (!S.finished) {
    phaseBadge.style.display = 'inline-block';
    phaseBadge.textContent = S.phase.toUpperCase();
    phaseBadge.className = 'badge ' + (S.phase === 'pass' ? 'badge-pass' : 'badge-play');
  } else {
    phaseBadge.style.display = 'none';
  }

  var parts = [];
  if (S.gamesPerMatch > 1) parts.push('Game ' + S.gameNumber + '/' + S.gamesPerMatch);
  parts.push('Hand ' + S.handNumber);
  if (S.phase === 'play') parts.push('Trick ' + S.trickNumber + '/' + S.totalTricks);
  parts.push('Turn ' + S.turnNumber);

  var models = [];
  PIDS.forEach(function(pid) {
    var m = S.models[pid] || ('Player ' + LABELS[pid]);
    models.push('<span class="' + CLASS_NAMES[pid] + '">' + m + '</span>');
  });
  document.getElementById('sub-info').innerHTML = models.join(' <span style="color:var(--dim)">vs</span> ') + ' <span style="color:var(--dim)">|</span> ' + parts.join(' <span style="color:var(--dim)">|</span> ');
}

function renderPlayerScores() {
  PIDS.forEach(function(pid) {
    var suffix = LABELS[pid].toLowerCase();
    var model = S.models[pid] || ('Player ' + LABELS[pid]);
    var shortName = model.length > 16 ? model.substring(0, 14) + '..' : model;
    document.getElementById('sp-name-' + suffix).textContent = shortName;
    document.getElementById('sp-total-' + suffix).textContent = S.gameScores[pid] || 0;
    var handPts = S.penaltyThisHand[pid] || 0;
    document.getElementById('sp-hand-' + suffix).textContent = 'This hand: ' + handPts;
  });
}

function renderShotClock() {
  var el = document.getElementById('shot-clock');
  if (!S.shotClock.timeLimitMs) return;
  el.style.display = 'block';
  var display = document.getElementById('clock-display');
  var label = document.getElementById('clock-label');
  var strikeEl = document.getElementById('strike-info');
  if (S.shotClock.lastTurnTime && !isReplaying) {
    var elapsed = Date.now() - S.shotClock.lastTurnTime;
    var remaining = Math.max(0, S.shotClock.timeLimitMs - elapsed);
    var secs = remaining / 1000;
    display.textContent = secs.toFixed(1) + 's';
    var cls = 'clock-display ';
    if (remaining <= 5000) cls += 'clock-danger';
    else if (remaining <= 10000) cls += 'clock-warn';
    else cls += 'clock-ok';
    display.className = cls;
  } else {
    display.textContent = (S.shotClock.timeLimitMs / 1000).toFixed(1) + 's';
    display.className = 'clock-display clock-ok';
  }
  var wPid = S.shotClock.waitingOn;
  var wModel = S.models[wPid] || wPid;
  label.innerHTML = 'SHOT CLOCK <span style="color:var(--dim)">&middot;</span> ' + wModel;
  if (S.shotClock.strikeLimit) {
    var strikeParts = [];
    PIDS.forEach(function(pid) {
      var s = S.shotClock.strikes[pid] || 0;
      var m = S.models[pid] || LABELS[pid];
      strikeParts.push('<span class="' + CLASS_NAMES[pid] + '">' + m + ': ' + s + '/' + S.shotClock.strikeLimit + '</span>');
    });
    strikeEl.innerHTML = strikeParts.join(' &middot; ');
  } else { strikeEl.innerHTML = ''; }
  if (S.finished) el.style.display = 'none';
}

function renderMoonAlert() {
  var el = document.getElementById('moon-alert');
  if (S.finished || S.phase !== 'play') { el.style.display = 'none'; return; }
  // Check if any player has 20+ penalty points this hand (potential moon)
  var moonCandidate = null;
  PIDS.forEach(function(pid) {
    var pts = S.penaltyThisHand[pid] || 0;
    if (pts >= 20) moonCandidate = pid;
  });
  if (moonCandidate) {
    var m = S.models[moonCandidate] || LABELS[moonCandidate];
    el.innerHTML = '\u{1F319} SHOOT THE MOON ATTEMPT \u2014 ' + m + ' has ' + S.penaltyThisHand[moonCandidate] + ' pts!';
    el.style.display = 'block';
  } else {
    el.style.display = 'none';
  }
}

function cardHTML(card, extraClass) {
  var suit = card.slice(-1);
  var isRed = (suit === '\u2665' || suit === '\u2666');
  var cls = 'card-pill ' + (isRed ? 'red' : 'black');
  if (extraClass) cls += ' ' + extraClass;
  return '<span class="' + cls + '">' + card + '</span>';
}

function isPenaltyCard(card) {
  var suit = card.slice(-1);
  if (suit === '\u2665') return 'heart';
  if (card === 'Q\u2660') return 'queen';
  return null;
}

function renderTrickArea() {
  var labelEl = document.getElementById('trick-label');

  if (S.phase === 'pass') {
    var dirLabel = S.passDirection === 'none' ? 'No Pass' : 'Pass ' + S.passDirection.charAt(0).toUpperCase() + S.passDirection.slice(1);
    labelEl.textContent = 'Passing \u2014 Hand ' + S.handNumber;
    var html = '<div class="pass-direction-label">' + dirLabel + '</div>';
    if (S.passDirection === 'none') {
      html += '<div style="color:var(--dim);font-style:italic;padding:8px 0">No passing this hand</div>';
    } else {
      PLAY_ORDER.forEach(function(pid) {
        var m = S.models[pid] || LABELS[pid];
        var hasPassed = S.passedCards[pid] && S.passedCards[pid].length > 0;
        var cls = hasPassed ? 'pass-panel done' : 'pass-panel waiting';
        var statusText = hasPassed ? '<span style="color:var(--green)">\u2713 Passed</span>' : '<span style="color:var(--yellow)">waiting...</span>';
        // Show received cards indicator
        var received = S.receivedCards[pid] || [];
        var recvText = received.length > 0 ? ' <span style="color:var(--dim)">| Received ' + received.length + ' cards</span>' : '';
        html += '<div class="' + cls + '"><span class="' + CLASS_NAMES[pid] + '">' + m + '</span><span>' + statusText + recvText + '</span></div>';
      });
    }
    document.getElementById('trick-content').innerHTML = html;
    return;
  }

  labelEl.textContent = 'Trick ' + S.trickNumber + '/' + S.totalTricks;

  // Build compass with current trick cards
  var played = {};
  var trickWinner = null;
  var trickComplete = S.currentTrick && S.currentTrick.length >= 4;
  var ledSuit = S.currentTrick && S.currentTrick.length > 0 ? S.currentTrick[0].card.slice(-1) : '';

  if (S.currentTrick) {
    S.currentTrick.forEach(function(entry) { played[entry.player] = entry.card; });
  }
  if (trickComplete && S.trickHistory.length > 0) {
    var lastTrick = S.trickHistory[S.trickHistory.length - 1];
    trickWinner = lastTrick.winner;
  }

  var compassHTML = '<div class="compass">';
  var positions = [{pid:'player_a',cls:'compass-n'},{pid:'player_b',cls:'compass-e'},{pid:'player_c',cls:'compass-s'},{pid:'player_d',cls:'compass-w'}];
  positions.forEach(function(pos) {
    var card = played[pos.pid];
    var m = S.models[pos.pid] || LABELS[pos.pid];
    var shortName = m.length > 12 ? m.substring(0,10) + '..' : m;
    var isWinner = trickWinner === pos.pid;
    var winCls = isWinner ? ' winner' : '';
    var emptyCls = card ? '' : ' empty';
    compassHTML += '<div class="compass-card' + winCls + emptyCls + ' ' + pos.cls + '">';
    compassHTML += '<div class="card-label ' + CLASS_NAMES[pos.pid] + '">' + shortName + '</div>';
    if (card) {
      var suit = card.slice(-1);
      var isRed = (suit === '\u2665' || suit === '\u2666');
      compassHTML += '<div class="card-value ' + (isRed ? 'red' : 'black') + '">' + card + '</div>';
    } else {
      compassHTML += '<div class="card-value" style="color:var(--dim)">--</div>';
    }
    compassHTML += '</div>';
  });

  // Center: trick info
  var centerText = '';
  if (trickComplete && trickWinner) {
    var wm = S.models[trickWinner] || LABELS[trickWinner];
    centerText = '<span class="' + CLASS_NAMES[trickWinner] + '">' + wm + '</span> wins';
  } else if (ledSuit) {
    var suitNames = {'\u2663':'Clubs','\u2666':'Diamonds','\u2665':'Hearts','\u2660':'Spades'};
    centerText = 'Led: ' + (suitNames[ledSuit] || ledSuit);
  } else {
    centerText = 'Leading...';
  }
  compassHTML += '<div class="compass-center">' + centerText + '</div>';
  compassHTML += '</div>';

  // Hearts broken indicator
  if (S.heartsBroken) {
    compassHTML += '<div class="hearts-broken">\u2665 HEARTS BROKEN</div>';
  }

  document.getElementById('trick-content').innerHTML = compassHTML;
}

function renderPlayerHands() {
  if (!_handsInitialized) return;
  var activePlayer = deriveActivePlayer();

  PIDS.forEach(function(pid) {
    var panel = document.getElementById('hp-' + pid);
    var nameEl = document.getElementById('hp-name-' + pid);
    var penaltyEl = document.getElementById('hp-penalty-' + pid);
    var handEl = document.getElementById('hp-hand-' + pid);

    var model = S.models[pid] || ('Player ' + LABELS[pid]);
    nameEl.textContent = model;

    // Active highlight
    var isActive = (pid === activePlayer && !S.finished);
    panel.className = panel.className.replace(/ ?active/g, '');
    if (isActive) panel.className += ' active';

    // Penalty info
    var handPts = S.penaltyThisHand[pid] || 0;
    var gamePts = S.gameScores[pid] || 0;
    var queenInfo = S.queenTakenBy === pid ? ' | <span style="color:var(--magenta)">Q\u2660</span>' : '';
    penaltyEl.innerHTML = 'Hand: <strong>' + handPts + '</strong> | Game: <strong>' + gamePts + '</strong>' + queenInfo;

    // Hand cards
    var hand = S.hands[pid] || [];
    if (hand.length > 0) {
      // Determine playable cards for active player during play phase
      var playable = {};
      if (S.phase === 'play' && pid === activePlayer && !S.finished) {
        var ledS = S.currentTrick && S.currentTrick.length > 0 ? S.currentTrick[0].card.slice(-1) : null;
        if (ledS) {
          // Must follow suit
          var hasSuit = hand.some(function(c) { return c.slice(-1) === ledS; });
          hand.forEach(function(c) {
            if (hasSuit) { if (c.slice(-1) === ledS) playable[c] = true; }
            else playable[c] = true;
          });
        } else {
          // Leading: can't lead hearts unless broken (or all hearts)
          var allHearts = hand.every(function(c) { return c.slice(-1) === '\u2665'; });
          hand.forEach(function(c) {
            if (!S.heartsBroken && c.slice(-1) === '\u2665' && !allHearts) {
              // Can't lead hearts
            } else {
              playable[c] = true;
            }
          });
        }
        // First trick: no penalty cards unless all penalty
        if (S.trickNumber === 1) {
          var allPenalty = hand.every(function(c) { return isPenaltyCard(c) !== null; });
          if (!allPenalty && ledS) {
            // If following suit, the suit constraint already applies
            // If void in led suit, can't play penalty cards unless all are penalty
            var hasLedSuit = hand.some(function(c) { return c.slice(-1) === ledS; });
            if (!hasLedSuit) {
              var nonPenalty = hand.filter(function(c) { return isPenaltyCard(c) === null; });
              if (nonPenalty.length > 0) {
                playable = {};
                nonPenalty.forEach(function(c) { playable[c] = true; });
              }
            }
          }
        }
      }
      handEl.innerHTML = hand.map(function(card) {
        var extra = playable[card] ? 'playable' : '';
        var pen = isPenaltyCard(card);
        if (pen === 'heart') extra += (extra ? ' ' : '') + 'penalty-heart';
        if (pen === 'queen') extra += (extra ? ' ' : '') + 'penalty-queen';
        return cardHTML(card, extra);
      }).join('');
    } else {
      handEl.innerHTML = '<span style="color:var(--dim)">(empty)</span>';
    }
  });
}

function renderHandHistory() {
  var el = document.getElementById('hh-content');
  if (!S.handHistory || S.handHistory.length === 0) {
    el.innerHTML = '<span style="color:var(--dim);font-style:italic">No completed hands</span>';
    return;
  }
  var html = '';
  S.handHistory.slice().reverse().forEach(function(h) {
    html += '<div class="hh-entry" style="margin-bottom:4px">';
    html += '<strong>H' + h.hand_number + '</strong>: ';
    // Per-player penalties
    PIDS.forEach(function(pid) {
      var m = S.models[pid] || LABELS[pid];
      var shortM = m.length > 10 ? m.substring(0,8) + '..' : m;
      var pts = (h.penalty && h.penalty[pid]) || 0;
      var cls = pts > 0 ? 'hh-negative' : 'hh-positive';
      html += '<span class="' + CLASS_NAMES[pid] + '">' + shortM + '</span>: <span class="' + cls + '">' + pts + '</span> ';
    });
    // Shoot the Moon annotation
    if (h.shoot_the_moon) {
      var shooter = S.models[h.shoot_the_moon] || h.shoot_the_moon;
      html += '<span class="hh-moon">\u{1F319} ' + shooter + ' SHOT THE MOON!</span>';
    }
    html += '</div>';
  });
  el.innerHTML = html;
}

function renderReasoning() {
  var el = document.getElementById('reasoning-content');
  if (!S.lastReasoning) {
    el.innerHTML = '<span style="color:var(--dim);font-style:italic">Waiting...</span>';
    return;
  }
  var latStr = S.lastLatency ? ' (' + (S.lastLatency / 1000).toFixed(1) + 's)' : '';
  el.innerHTML = '<span style="font-weight:bold">' + (S.lastModel || '?') + latStr + ':</span> <span style="font-style:italic;color:var(--dim)">' + S.lastReasoning.replace(/</g,'&lt;').replace(/>/g,'&gt;') + '</span>';
}

function renderFinal() {
  var panel = document.getElementById('final-panel');
  if (!S.finished) { panel.className = 'panel'; return; }
  panel.className = 'panel show';

  var scores = S.finalScores || S.matchScores;
  // Sort by match score desc (highest = winner)
  var sorted = PIDS.slice().sort(function(a,b) { return (scores[b] || 0) - (scores[a] || 0); });

  var winPid = sorted[0];
  var winModel = S.models[winPid] || LABELS[winPid];
  var winColor = PLAYER_COLORS[winPid];

  var html = '<div class="winner" style="color:' + winColor + '">' + winModel + ' WINS!</div>';
  html += '<div style="font-size:12px;color:var(--dim);margin:4px 0">Lowest penalty = Highest match score</div>';
  html += '<div class="standings" style="margin-top:8px">';
  sorted.forEach(function(pid, i) {
    var m = S.models[pid] || LABELS[pid];
    var matchPts = Math.round(scores[pid] || 0);
    var gamePts = S.gameScores[pid] || 0;
    var rank = i === 0 ? '\u{1F947}' : i === 1 ? '\u{1F948}' : i === 2 ? '\u{1F949}' : '';
    html += '<div><span class="' + CLASS_NAMES[pid] + '">' + rank + ' ' + m + '</span>: ' + matchPts + ' match pts (game penalty: ' + gamePts + ')</div>';
  });
  html += '</div>';

  document.getElementById('final-content').innerHTML = html;
}

function renderFooter() {
  var st = document.getElementById('status-text');
  if (S.finished) {
    st.innerHTML = '<span class="badge badge-final" style="font-size:10px">FINAL</span> Match Complete';
  } else {
    st.innerHTML = '<span class="badge badge-live" style="font-size:10px">LIVE</span> Watching...';
  }
  document.getElementById('turn-count').textContent = S.turnCount;
}

function drainQueue() {
  if (turnQueue.length === 0) { isReplaying = false; return; }
  var batch = turnQueue.splice(0, 5);
  batch.forEach(function(d) { processTurn(d); });
  renderAll();
  if (turnQueue.length > 0) {
    setTimeout(drainQueue, 150);
  } else {
    isReplaying = false;
    renderShotClock();
  }
}

// SSE connection
var evtPath = '/events';
if (window.location.pathname.match(/^\/match\//)) {
  var matchId = window.location.pathname.split('/match/')[1];
  if (matchId) evtPath = '/events/' + matchId;
}
var es = new EventSource(evtPath);
es.onmessage = function(e) {
  var data = JSON.parse(e.data);
  if (isReplaying) {
    turnQueue.push(data);
  } else if (rawLines.length === 0) {
    turnQueue.push(data);
    isReplaying = true;
    drainQueue();
  } else {
    processTurn(data);
    renderAll();
  }
};
setInterval(function() {
  if (S.shotClock.timeLimitMs && !S.finished && !isReplaying) renderShotClock();
}, 100);
</script>
</body>
</html>"""


# ── Avalon HTML/CSS/JS ────────────────────────────────────────────

AVALON_HTML_PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Avalon — LLM Tourney Spectator</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{background:#1a1a2e;color:#e0e0e0;font-family:'Courier New',monospace;padding:12px}
h1{text-align:center;color:#c9a0dc;font-size:1.4em;margin-bottom:8px}
.match-info{text-align:center;font-size:.85em;color:#888;margin-bottom:12px}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:12px;max-width:1400px;margin:0 auto}
.panel{background:#16213e;border:1px solid #333;border-radius:8px;padding:12px}
.panel h2{font-size:1em;color:#c9a0dc;margin-bottom:8px;border-bottom:1px solid #333;padding-bottom:4px}

/* Quest tracker */
.quest-tracker{display:flex;gap:12px;justify-content:center;margin:12px 0}
.quest-circle{width:52px;height:52px;border-radius:50%;border:3px solid #444;display:flex;align-items:center;justify-content:center;font-weight:bold;font-size:.9em;flex-direction:column}
.quest-circle.success{border-color:#4caf50;background:rgba(76,175,80,.2);color:#4caf50}
.quest-circle.fail{border-color:#f44336;background:rgba(244,67,54,.2);color:#f44336}
.quest-circle.current{border-color:#ffd700;box-shadow:0 0 10px rgba(255,215,0,.3)}
.quest-circle .q-num{font-size:.7em;color:#888}
.quest-circle .q-size{font-size:.65em;color:#666}

/* Player cards */
.player-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}
.player-card{background:#0f3460;border:1px solid #444;border-radius:6px;padding:8px;text-align:center}
.player-card.good{border-color:#4caf50}
.player-card.evil{border-color:#f44336}
.player-card .name{font-weight:bold;font-size:.9em}
.player-card .role{font-size:.75em;margin-top:2px;padding:2px 6px;border-radius:3px;display:inline-block}
.player-card .role.good-role{background:rgba(76,175,80,.3);color:#4caf50}
.player-card .role.evil-role{background:rgba(244,67,54,.3);color:#f44336}
.player-card .score{font-size:.8em;color:#ffd700;margin-top:4px}
.player-card.leader{box-shadow:0 0 8px rgba(255,215,0,.4)}

/* Discussion feed */
.discussion{max-height:300px;overflow-y:auto;font-size:.82em}
.discussion .msg{padding:4px 8px;margin:2px 0;border-left:3px solid #444;background:rgba(255,255,255,.03)}
.discussion .msg .speaker{color:#c9a0dc;font-weight:bold}
.discussion .msg.good-msg{border-left-color:#4caf50}
.discussion .msg.evil-msg{border-left-color:#f44336}

/* Vote history */
.vote-table{width:100%;border-collapse:collapse;font-size:.78em}
.vote-table th,.vote-table td{padding:3px 6px;border:1px solid #333;text-align:center}
.vote-table th{background:#0f3460;color:#c9a0dc}
.vote-table .approve{color:#4caf50}
.vote-table .reject{color:#f44336}

/* Phase indicator */
.phase-bar{text-align:center;padding:8px;margin:8px 0;border-radius:6px;font-weight:bold;font-size:1em}
.phase-bar.discuss{background:rgba(100,181,246,.2);color:#64b5f6}
.phase-bar.nominate{background:rgba(255,215,0,.2);color:#ffd700}
.phase-bar.vote{background:rgba(206,147,216,.2);color:#ce93d8}
.phase-bar.quest{background:rgba(76,175,80,.2);color:#4caf50}
.phase-bar.assassinate{background:rgba(244,67,54,.3);color:#f44336;animation:pulse 1s infinite}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.6}}

/* Assassination reveal */
.assassination{text-align:center;padding:16px;margin:8px 0;border:2px solid #f44336;border-radius:8px;background:rgba(244,67,54,.1)}
.assassination h3{color:#f44336;font-size:1.2em;margin-bottom:8px}
.assassination .result{font-size:1.1em;margin-top:8px}
.assassination .result.evil-wins{color:#f44336}
.assassination .result.good-wins{color:#4caf50}

/* Scores */
.score-row{display:flex;justify-content:space-between;padding:4px 0;border-bottom:1px solid #222;font-size:.85em}
.score-row .pts{color:#ffd700;font-weight:bold}

.status{text-align:center;color:#888;font-size:.85em;margin-top:8px}
</style>
</head>
<body>
<h1>THE RESISTANCE: AVALON</h1>
<div class="match-info" id="matchInfo">Connecting...</div>

<div class="phase-bar" id="phaseBar">Waiting...</div>

<div class="quest-tracker" id="questTracker"></div>

<div class="grid">
  <div class="panel">
    <h2>Players (God Mode)</h2>
    <div class="player-grid" id="playerGrid"></div>
  </div>
  <div class="panel">
    <h2>Discussion</h2>
    <div class="discussion" id="discussion"></div>
  </div>
  <div class="panel">
    <h2>Proposal & Vote History</h2>
    <div id="voteHistory" style="max-height:300px;overflow-y:auto"></div>
  </div>
  <div class="panel">
    <h2>Match Scores</h2>
    <div id="scores"></div>
  </div>
</div>

<div id="assassination" style="display:none"></div>
<div class="status" id="status"></div>

<script>
let lastTurn = 0;
let isReplaying = false;
let turnQueue = [];
let latestSnap = null;
const playerModels = {};  // player_id -> short model name

function shortModel(name) {
  if (!name) return '';
  return name.replace(/^(openai|anthropic|google|x-ai|deepseek|meta-llama|meta|mistralai|amazon|perplexity|cohere|qwen)\//i, '')
             .replace(/-instruct$/i, '');
}

function displayName(pid, snap) {
  if (playerModels[pid]) return playerModels[pid];
  const labels = (snap && snap.player_labels) || {};
  return labels[pid] || pid;
}

function renderQuestTracker(snap) {
  const el = document.getElementById('questTracker');
  const sizes = {5:[2,3,2,3,3],6:[2,3,4,3,4],7:[2,3,3,4,4],8:[3,4,4,5,5]};
  const np = (snap.player_order||[]).length || 6;
  const qs = sizes[np] || sizes[6];
  let html = '';
  for (let i = 0; i < 5; i++) {
    const qr = (snap.quest_results||[]).find(r => r.quest === i+1);
    let cls = '';
    if (qr) cls = qr.result === 'success' ? 'success' : 'fail';
    else if (i+1 === snap.quest_number) cls = 'current';
    html += `<div class="quest-circle ${cls}">
      <span class="q-num">Q${i+1}</span>
      ${qr ? qr.result.toUpperCase() : qs[i]}
      <span class="q-size">${qr ? qr.success_count+'S '+qr.fail_count+'F' : 'need '+qs[i]}</span>
    </div>`;
  }
  el.innerHTML = html;
}

function renderPhase(snap) {
  const el = document.getElementById('phaseBar');
  const p = snap.phase || 'unknown';
  el.className = 'phase-bar ' + p;
  const leaderName = displayName(snap.leader||'', snap);
  const teamNames = (snap.proposed_team||[]).map(id => displayName(id, snap));
  const phaseLabels = {
    discuss: 'DISCUSSION PHASE',
    nominate: 'NOMINATION PHASE — Leader: ' + leaderName,
    vote: 'VOTING PHASE — Team: ' + teamNames.join(', '),
    quest: 'QUEST PHASE — Team: ' + teamNames.join(', '),
    assassinate: 'ASSASSINATION PHASE'
  };
  el.textContent = phaseLabels[p] || p.toUpperCase();
}

function renderPlayers(snap) {
  const el = document.getElementById('playerGrid');
  const order = snap.player_order || [];
  const roles = snap.roles || {};
  const teams = snap.teams || {};
  const scores = snap.match_scores || {};
  const labels = snap.player_labels || {};
  const leader = snap.leader || '';
  let html = '';
  for (const pid of order) {
    const role = roles[pid] || '?';
    const team = teams[pid] || '?';
    const name = displayName(pid, snap);
    const isLeader = pid === leader;
    html += `<div class="player-card ${team} ${isLeader?'leader':''}">
      <div class="name">${name} ${isLeader?'&#x1f451;':''}</div>
      <div class="role ${team==='good'?'good-role':'evil-role'}">${role.toUpperCase()}</div>
      <div class="score">${(scores[pid]||0).toFixed(0)} pts</div>
    </div>`;
  }
  el.innerHTML = html;
}

function renderDiscussion(snap) {
  const el = document.getElementById('discussion');
  const stmts = snap.discussion_statements || {};
  const roles = snap.roles || {};
  const teams = snap.teams || {};
  const labels = snap.player_labels || {};
  let html = '';
  for (const [pid, stmt] of Object.entries(stmts)) {
    const team = teams[pid] || 'good';
    const name = displayName(pid, snap);
    const role = roles[pid] || '';
    html += `<div class="msg ${team}-msg">
      <span class="speaker">${name} [${role}]:</span> ${stmt}
    </div>`;
  }
  if (!html) html = '<div style="color:#666;text-align:center;padding:20px">No discussion yet</div>';
  el.innerHTML = html;
  el.scrollTop = el.scrollHeight;
}

function renderVoteHistory(snap) {
  const el = document.getElementById('voteHistory');
  const history = snap.proposal_history || [];
  if (!history.length) { el.innerHTML = '<div style="color:#666;text-align:center;padding:20px">No proposals yet</div>'; return; }
  const labels = snap.player_labels || {};
  let html = '<table class="vote-table"><thead><tr><th>Q</th><th>#</th><th>Leader</th><th>Team</th>';
  const order = snap.player_order || [];
  for (const pid of order) html += `<th>${displayName(pid, snap)}</th>`;
  html += '<th>Result</th></tr></thead><tbody>';
  for (const p of history) {
    html += `<tr><td>${p.quest}</td><td>${p.attempt}</td><td>${displayName(p.leader, snap)}</td>`;
    const team = (p.proposed_team||[]).map(id=>displayName(id, snap)).join(', ');
    html += `<td>${team}</td>`;
    for (const pid of order) {
      const v = (p.votes||{})[pid] || '-';
      const cls = v==='approve'?'approve':v==='reject'?'reject':'';
      html += `<td class="${cls}">${v==='approve'?'Y':v==='reject'?'N':'-'}</td>`;
    }
    html += `<td>${p.approved?'<span class="approve">PASS</span>':'<span class="reject">FAIL</span>'}</td></tr>`;
  }
  html += '</tbody></table>';
  el.innerHTML = html;
}

function renderScores(snap) {
  const el = document.getElementById('scores');
  const scores = snap.match_scores || {};
  const labels = snap.player_labels || {};
  const roles = snap.roles || {};
  const teams = snap.teams || {};
  const order = snap.player_order || [];
  let entries = order.map(pid => ({pid, name: displayName(pid, snap), score: scores[pid]||0, role: roles[pid]||'', team: teams[pid]||''}));
  entries.sort((a,b) => b.score - a.score);
  let html = '';
  for (const e of entries) {
    html += `<div class="score-row">
      <span>${e.name} <span style="color:${e.team==='good'?'#4caf50':'#f44336'};font-size:.8em">[${e.role}]</span></span>
      <span class="pts">${e.score.toFixed(0)}</span>
    </div>`;
  }
  el.innerHTML = html;
}

function renderAssassination(snap) {
  const el = document.getElementById('assassination');
  if (snap.phase !== 'assassinate' && !snap.assassination_target) { el.style.display = 'none'; return; }
  const labels = snap.player_labels || {};
  const roles = snap.roles || {};
  if (snap.assassination_target) {
    const target = snap.assassination_target;
    const correct = snap.assassination_correct;
    el.style.display = 'block';
    el.innerHTML = `<div class="assassination">
      <h3>ASSASSINATION ATTEMPT</h3>
      <div>Target: <strong>${displayName(target, snap)}</strong> (${roles[target]||'?'})</div>
      <div class="result ${correct?'evil-wins':'good-wins'}">
        ${correct ? 'CORRECT! Merlin identified — EVIL WINS!' : 'WRONG! Merlin survives — GOOD WINS!'}
      </div>
    </div>`;
  } else if (snap.phase === 'assassinate') {
    el.style.display = 'block';
    el.innerHTML = `<div class="assassination"><h3>ASSASSINATION PHASE</h3><div>Assassin is choosing a target...</div></div>`;
  }
}

function renderAll(snap) {
  if (!snap) return;
  latestSnap = snap;
  document.getElementById('matchInfo').textContent =
    `Game ${snap.game_number||1} of ${snap.games_per_match||3} | Turn ${snap.turn_number||0} | Good: ${snap.good_wins||0} Evil: ${snap.evil_wins||0}`;
  renderQuestTracker(snap);
  renderPhase(snap);
  renderPlayers(snap);
  renderDiscussion(snap);
  renderVoteHistory(snap);
  renderScores(snap);
  renderAssassination(snap);
  document.getElementById('status').textContent = snap.terminal ? 'Match complete' : '';
}

// SSE connection
const es = new EventSource('/events');
es.onmessage = function(e) {
  try {
    const data = JSON.parse(e.data);
    // Extract model names from each turn
    if (data.player_id && data.model_id && !playerModels[data.player_id]) {
      playerModels[data.player_id] = shortModel(data.model_id);
    }
    const pm = data.player_models || {};
    Object.keys(pm).forEach(k => {
      if (pm[k] && !playerModels[k]) playerModels[k] = shortModel(pm[k]);
    });
    if (data.record_type === 'match_summary') {
      document.getElementById('status').textContent = 'Match complete';
      if (data.state_snapshot) renderAll(data.state_snapshot);
      return;
    }
    const snap = data.state_snapshot || {};
    if (snap.phase) renderAll(snap);
  } catch(err) { console.error('Parse error:', err); }
};
es.onerror = function() {
  document.getElementById('status').textContent = 'Connection lost — retrying...';
};
</script>
</body>
</html>"""


# ── Gin Rummy HTML/CSS/JS ─────────────────────────────────────────

GIN_RUMMY_HTML_PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Gin Rummy Spectator</title>
<style>
:root {
  --bg: #0d1117;
  --surface: #161b22;
  --border: #30363d;
  --text: #e6edf3;
  --dim: #7d8590;
  --cyan: #58a6ff;
  --magenta: #d2a8ff;
  --green: #3fb950;
  --red: #f85149;
  --yellow: #d29922;
  --felt: #1a3a1a;
  --gold: #ffd700;
  --pa: #58a6ff;
  --pb: #d2a8ff;
}
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
  background: var(--bg);
  color: var(--text);
  font-family: 'SF Mono', 'Cascadia Code', 'Fira Code', 'Consolas', monospace;
  font-size: 13px;
  line-height: 1.4;
  padding: 12px;
  max-width: 1200px;
  margin: 0 auto;
}

/* Header */
#header {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 12px 16px;
  margin-bottom: 10px;
  text-align: center;
}
.badge {
  display: inline-block;
  padding: 2px 10px;
  border-radius: 4px;
  font-weight: bold;
  font-size: 12px;
  margin-right: 8px;
  vertical-align: middle;
}
.badge-live { background: var(--green); color: #000; animation: pulse 2s infinite; }
.badge-final { background: var(--red); color: #fff; }
.badge-knock { background: var(--yellow); color: #000; }
.badge-gin { background: var(--gold); color: #000; }
@keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.6; } }
#header .title { font-size: 18px; font-weight: bold; letter-spacing: 1px; }
#header .sub { margin-top: 4px; color: var(--dim); }
.player-a { color: var(--pa); }
.player-b { color: var(--pb); }

/* Player scoreboard — 2 panels */
#player-scores {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
  margin-bottom: 10px;
}
.score-panel {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px 14px;
  text-align: center;
  border-top: 3px solid var(--border);
}
.score-panel.sp-a { border-top-color: var(--pa); }
.score-panel.sp-b { border-top-color: var(--pb); }
.score-panel .sp-name { font-weight: bold; font-size: 12px; margin-bottom: 4px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.score-panel .sp-total { font-size: 28px; font-weight: bold; margin: 4px 0; }
.score-panel .sp-detail { font-size: 12px; color: var(--dim); }
.score-panel .sp-series { font-size: 11px; color: var(--dim); margin-top: 4px; }
.score-panel.active-turn { border-color: var(--green); border-width: 2px; }

/* Shot clock */
#shot-clock {
  display: none;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 8px 16px;
  margin-bottom: 10px;
  text-align: center;
}
#shot-clock .clock-label { font-size: 11px; color: var(--dim); text-transform: uppercase; letter-spacing: 1px; }
#shot-clock .clock-display { font-size: 24px; font-weight: bold; font-variant-numeric: tabular-nums; letter-spacing: 1px; margin: 2px 0; }
#shot-clock .clock-display.clock-ok { color: var(--green); }
#shot-clock .clock-display.clock-warn { color: var(--yellow); }
#shot-clock .clock-display.clock-danger { color: var(--red); animation: pulse 0.5s infinite; }
#shot-clock .strike-info { font-size: 11px; color: var(--dim); }

/* Main area: table + hands side by side */
#main-area {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
  margin-bottom: 10px;
}

/* Table area (discard pile, stock, last action) */
#table-area {
  background: var(--felt);
  border: 1px solid #2d5a2d;
  border-radius: 8px;
  padding: 14px;
  min-height: 320px;
  display: flex;
  flex-direction: column;
}
#table-area .section-label { font-size: 11px; text-transform: uppercase; color: var(--dim); letter-spacing: 1px; margin-bottom: 8px; }

/* Card table layout */
.table-layout {
  display: flex;
  justify-content: center;
  align-items: center;
  gap: 24px;
  margin: 16px 0;
  flex: 1;
}
.pile {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
}
.pile-label {
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 1px;
  color: var(--dim);
}
.pile-count {
  font-size: 11px;
  color: var(--dim);
}

/* Big card display */
.big-card {
  width: 80px;
  height: 110px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 22px;
  font-weight: bold;
  border: 2px solid var(--border);
}
.big-card.face-up {
  background: #fff;
  color: #000;
}
.big-card.face-up.red { color: var(--red); }
.big-card.face-down {
  background: linear-gradient(135deg, #2d5a8c 0%, #1a3d5c 100%);
  color: var(--dim);
  font-size: 14px;
}
.big-card.empty-pile {
  background: rgba(255,255,255,0.05);
  border-style: dashed;
  color: var(--dim);
  font-size: 12px;
}

/* Draw indicator */
.draw-indicator {
  background: rgba(63,185,80,0.15);
  border: 1px solid var(--green);
  border-radius: 6px;
  padding: 6px 12px;
  text-align: center;
  font-size: 12px;
  color: var(--green);
  margin-top: 8px;
}
.draw-indicator.knock { border-color: var(--yellow); color: var(--yellow); background: rgba(210,153,34,0.15); }
.draw-indicator.gin { border-color: var(--gold); color: var(--gold); background: rgba(255,215,0,0.15); animation: pulse 1s infinite; }
.draw-indicator.undercut { border-color: var(--magenta); color: var(--magenta); background: rgba(210,168,255,0.15); }

/* Discard history */
#discard-history {
  margin-top: auto;
  max-height: 120px;
  overflow-y: auto;
  font-size: 11px;
  border-top: 1px solid #2d5a2d;
  padding-top: 8px;
}
#discard-history .dh-entry { padding: 2px 0; border-bottom: 1px solid rgba(255,255,255,0.05); }

/* Player hands (god mode) */
#player-hands {
  display: grid;
  grid-template-rows: 1fr 1fr;
  gap: 8px;
}
.hand-panel {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px 12px;
  transition: border-color 0.3s;
  position: relative;
}
.hand-panel.active { border-color: var(--green); border-width: 2px; }
.hand-panel.sp-a-border { border-top: 3px solid var(--pa); }
.hand-panel.sp-b-border { border-top: 3px solid var(--pb); }
.hand-panel .model-name { font-weight: bold; font-size: 13px; margin-bottom: 4px; }
.hand-panel .hand-info { font-size: 12px; color: var(--dim); margin-bottom: 4px; }
.hand-panel .hand {
  display: flex;
  flex-wrap: wrap;
  gap: 3px;
  margin: 6px 0;
  min-height: 24px;
}
.hand-panel .melds-section {
  border-top: 1px solid var(--border);
  padding-top: 6px;
  margin-top: 6px;
  font-size: 11px;
}
.god-badge {
  position: absolute;
  top: 6px;
  right: 8px;
  background: var(--magenta);
  color: #000;
  font-size: 9px;
  font-weight: bold;
  padding: 1px 6px;
  border-radius: 3px;
  letter-spacing: 1px;
}
.card-pill {
  display: inline-block;
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 3px;
  padding: 1px 4px;
  font-size: 10px;
  font-weight: bold;
  white-space: nowrap;
}
.card-pill.red { color: var(--red); }
.card-pill.black { color: var(--text); }
.card-pill.in-meld { outline: 1px solid var(--green); background: rgba(63,185,80,0.08); }
.card-pill.deadwood { outline: 1px solid var(--yellow); background: rgba(210,153,34,0.06); }

/* Meld group display */
.meld-group {
  display: inline-flex;
  gap: 2px;
  margin-right: 8px;
  padding: 2px 4px;
  background: rgba(63,185,80,0.06);
  border: 1px solid rgba(63,185,80,0.2);
  border-radius: 4px;
}

/* Panels */
.panel {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px 14px;
  margin-bottom: 10px;
}
.panel h3 {
  font-size: 11px;
  text-transform: uppercase;
  color: var(--dim);
  border-bottom: 1px solid var(--border);
  padding-bottom: 4px;
  margin-bottom: 6px;
}

/* Hand history panel */
#hand-history-panel .hh-entry { padding: 3px 0; border-bottom: 1px solid rgba(255,255,255,0.05); font-size: 12px; }
.hh-gin { color: var(--gold); font-weight: bold; }
.hh-knock { color: var(--yellow); }
.hh-undercut { color: var(--magenta); font-weight: bold; }
.hh-draw { color: var(--dim); font-style: italic; }

/* Reasoning panel */
#reasoning-panel { cursor: pointer; }
#reasoning-panel .content { max-height: 60px; overflow: hidden; transition: max-height 0.3s; }
#reasoning-panel.expanded .content { max-height: 300px; }

/* Final panel */
#final-panel { display: none; text-align: center; border-color: var(--yellow); }
#final-panel.show { display: block; }
#final-panel .winner { font-size: 20px; font-weight: bold; margin: 8px 0; }
#final-panel .standings { font-size: 13px; margin: 6px 0; }

/* Footer */
#footer {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 6px 14px;
  display: flex;
  justify-content: space-between;
  color: var(--dim);
  font-size: 11px;
}

/* Compact mode */
body.compact { padding: 4px; font-size: 11px; }
body.compact #header { padding: 6px 10px; margin-bottom: 6px; }
body.compact #header .title { font-size: 13px; }
body.compact .score-panel { padding: 6px 10px; }
body.compact .hand-panel { padding: 6px 8px; }
body.compact .card-pill { font-size: 9px; padding: 0 3px; }
body.compact #reasoning-panel { display: none; }
body.compact .panel { padding: 6px 10px; margin-bottom: 6px; }
</style>
</head>
<body>

<div id="header">
  <span id="badge" class="badge badge-live">LIVE</span>
  <span id="action-badge" class="badge badge-knock" style="display:none">KNOCK</span>
  <span class="title">GIN RUMMY</span>
  <div class="sub" id="sub-info">Loading...</div>
</div>

<div id="player-scores">
  <div class="score-panel sp-a" id="sp-a">
    <div class="sp-name player-a" id="sp-name-a">Player A</div>
    <div class="sp-total" id="sp-total-a">0</div>
    <div class="sp-detail" id="sp-detail-a">Hands won: 0</div>
    <div class="sp-series" id="sp-series-a"></div>
  </div>
  <div class="score-panel sp-b" id="sp-b">
    <div class="sp-name player-b" id="sp-name-b">Player B</div>
    <div class="sp-total" id="sp-total-b">0</div>
    <div class="sp-detail" id="sp-detail-b">Hands won: 0</div>
    <div class="sp-series" id="sp-series-b"></div>
  </div>
</div>

<div id="shot-clock">
  <div class="clock-label" id="clock-label">SHOT CLOCK</div>
  <div class="clock-display clock-ok" id="clock-display">--.-s</div>
  <div class="strike-info" id="strike-info"></div>
</div>

<div id="main-area">
  <div id="table-area">
    <div class="section-label" id="table-label">Table</div>
    <div class="table-layout">
      <div class="pile">
        <div class="pile-label">Stock</div>
        <div class="big-card face-down" id="stock-card">31</div>
        <div class="pile-count" id="stock-count">31 cards</div>
      </div>
      <div class="pile">
        <div class="pile-label">Discard</div>
        <div class="big-card face-up" id="discard-card">--</div>
        <div class="pile-count" id="discard-count">0 cards</div>
      </div>
    </div>
    <div id="last-action"></div>
    <div id="discard-history">
      <div class="section-label">Discard History</div>
      <div id="dh-content"><span style="color:var(--dim);font-style:italic">No discards yet</span></div>
    </div>
  </div>
  <div id="player-hands"></div>
</div>

<div class="panel" id="hand-history-panel">
  <h3>Hand History</h3>
  <div id="hh-content"><span style="color:var(--dim);font-style:italic">No completed hands</span></div>
</div>

<div class="panel" id="reasoning-panel" onclick="this.classList.toggle('expanded')">
  <h3>Reasoning (click to expand)</h3>
  <div class="content" id="reasoning-content"><span style="color:var(--dim);font-style:italic">Waiting...</span></div>
</div>

<div class="panel" id="final-panel">
  <h3>Final Results</h3>
  <div id="final-content"></div>
</div>

<div id="footer">
  <span id="status-text"><span class="badge badge-live" style="font-size:10px">LIVE</span> Watching...</span>
  <span>Turns: <span id="turn-count">0</span></span>
</div>

<script>
var PIDS = ['player_a','player_b'];
var LABELS = {player_a:'A', player_b:'B'};
var CLASS_NAMES = {player_a:'player-a', player_b:'player-b'};
var PLAYER_COLORS = {player_a:'var(--pa)', player_b:'var(--pb)'};

var S = {
  models: {},
  gameNumber: 1,
  gamesPerMatch: 1,
  handNumber: 1,
  turnNumber: 0,
  dealer: 'player_a',
  activePlayer: 'player_a',
  hands: {},
  stockSize: 31,
  discardPile: [],
  discardHistory: [],
  gameScores: {},
  handsWon: {},
  seriesScores: {},
  handHistory: [],
  terminal: false,
  finished: false,
  finalScores: {},
  turnCount: 0,
  lastReasoning: '',
  lastModel: '',
  lastLatency: 0,
  lastAction: null,
  violations: {},
  shotClock: { timeLimitMs: null, lastTurnTime: null, strikes: {}, strikeLimit: null, waitingOn: '' }
};

var rawLines = [];
var turnQueue = [];
var isReplaying = false;
var _handsInitialized = false;

if (new URLSearchParams(window.location.search).get('compact') === '1') {
  document.body.classList.add('compact');
}

function initHandPanels() {
  if (_handsInitialized) return;
  var html = '';
  PIDS.forEach(function(pid, i) {
    var borderCls = 'sp-' + LABELS[pid].toLowerCase() + '-border';
    html += '<div class="hand-panel ' + borderCls + '" id="hp-' + pid + '">';
    if (i === 0) html += '<span class="god-badge">GOD MODE</span>';
    html += '<div class="model-name ' + CLASS_NAMES[pid] + '" id="hp-name-' + pid + '">Player ' + LABELS[pid] + '</div>';
    html += '<div class="hand-info" id="hp-info-' + pid + '"></div>';
    html += '<div class="hand" id="hp-hand-' + pid + '"></div>';
    html += '<div class="melds-section" id="hp-melds-' + pid + '"></div>';
    html += '</div>';
  });
  document.getElementById('player-hands').innerHTML = html;
  _handsInitialized = true;
}

function processTurn(data) {
  rawLines.push(data);

  if (data.record_type === 'match_summary') {
    S.finished = true;
    S.finalScores = data.final_scores || {};
    var pm = data.player_models || {};
    PIDS.forEach(function(pid) { if (pm[pid]) S.models[pid] = pm[pid]; });
    return;
  }

  S.turnCount++;
  var snap = data.state_snapshot || {};
  var pid = data.player_id || '';
  var mid = data.model_id || '';

  if (pid && mid) S.models[pid] = mid;
  var pm = snap.player_models || {};
  Object.keys(pm).forEach(function(k) { if (!S.models[k]) S.models[k] = pm[k]; });

  // Shot clock
  if (data.time_limit_ms) S.shotClock.timeLimitMs = data.time_limit_ms;
  if (data.strike_limit) S.shotClock.strikeLimit = data.strike_limit;
  if (data.cumulative_strikes !== undefined && pid) S.shotClock.strikes[pid] = data.cumulative_strikes;
  S.shotClock.lastTurnTime = Date.now();

  S.gameNumber = snap.game_number || S.gameNumber;
  S.gamesPerMatch = snap.games_per_match || S.gamesPerMatch;
  S.handNumber = snap.hand_number || S.handNumber;
  S.turnNumber = snap.turn_number || S.turnNumber;
  S.dealer = snap.dealer || S.dealer;
  S.activePlayer = snap.active_player || S.activePlayer;
  S.hands = snap.hands || S.hands;
  S.stockSize = snap.stock_size !== undefined ? snap.stock_size : S.stockSize;
  S.discardPile = snap.discard_pile || S.discardPile;
  S.discardHistory = snap.discard_history || S.discardHistory;
  S.gameScores = snap.game_scores || S.gameScores;
  S.handsWon = snap.hands_won || S.handsWon;
  S.seriesScores = snap.series_scores || S.seriesScores;
  S.handHistory = snap.hand_history || S.handHistory;
  S.terminal = snap.terminal || false;

  // Track last action from discard history
  if (S.discardHistory.length > 0) {
    S.lastAction = S.discardHistory[S.discardHistory.length - 1];
  }

  S.shotClock.waitingOn = S.activePlayer;

  var reasoning = data.reasoning_output || '';
  if (reasoning) {
    S.lastReasoning = reasoning.length > 200 ? reasoning.substring(0, 197) + '...' : reasoning;
    S.lastModel = mid;
  }
  S.lastLatency = data.latency_ms || 0;

  if (data.violation && pid) {
    S.violations[pid] = (S.violations[pid] || 0) + 1;
  }
}

function cardHTML(card, extraClass) {
  var suit = card.slice(-1);
  var isRed = (suit === '\u2665' || suit === '\u2666');
  var cls = 'card-pill ' + (isRed ? 'red' : 'black');
  if (extraClass) cls += ' ' + extraClass;
  return '<span class="' + cls + '">' + card + '</span>';
}

function bigCardHTML(card) {
  if (!card) return '--';
  var suit = card.slice(-1);
  var isRed = (suit === '\u2665' || suit === '\u2666');
  return '<span style="color:' + (isRed ? 'var(--red)' : '#000') + '">' + card + '</span>';
}

/* ---- Simple meld detection for spectator display ---- */
var RANK_ORDER = {'A':0,'2':1,'3':2,'4':3,'5':4,'6':5,'7':6,'8':7,'9':8,'10':9,'J':10,'Q':11,'K':12};
var DW_VALUES = {'A':1,'2':2,'3':3,'4':4,'5':5,'6':6,'7':7,'8':8,'9':9,'10':10,'J':10,'Q':10,'K':10};

function cardRank(c) { return c.slice(0,-1); }
function cardSuit(c) { return c.slice(-1); }
function cardRankVal(c) { return RANK_ORDER[cardRank(c)]; }
function dwValue(c) { return DW_VALUES[cardRank(c)]; }

function findMelds(cards) {
  /* Enumerate all possible melds */
  var allMelds = [];
  /* Sets */
  var byRank = {};
  cards.forEach(function(c) { var r = cardRank(c); if (!byRank[r]) byRank[r] = []; byRank[r].push(c); });
  Object.keys(byRank).forEach(function(r) {
    var g = byRank[r];
    if (g.length >= 3) {
      for (var i = 0; i < g.length; i++)
        for (var j = i+1; j < g.length; j++)
          for (var k = j+1; k < g.length; k++)
            allMelds.push([g[i],g[j],g[k]]);
      if (g.length === 4) allMelds.push(g.slice());
    }
  });
  /* Runs */
  var bySuit = {};
  cards.forEach(function(c) { var s = cardSuit(c); if (!bySuit[s]) bySuit[s] = []; bySuit[s].push(c); });
  Object.keys(bySuit).forEach(function(s) {
    var g = bySuit[s].slice().sort(function(a,b) { return cardRankVal(a) - cardRankVal(b); });
    for (var start = 0; start < g.length; start++) {
      var run = [g[start]];
      for (var end = start+1; end < g.length; end++) {
        if (cardRankVal(g[end]) === cardRankVal(g[end-1]) + 1) {
          run.push(g[end]);
          if (run.length >= 3) allMelds.push(run.slice());
        } else break;
      }
    }
  });
  /* Backtrack to minimize deadwood */
  var bestDW = 99999;
  var bestMelds = [];
  var bestDeadwood = cards.slice();
  function bt(remaining, chosen) {
    var dw = 0;
    remaining.forEach(function(c) { dw += dwValue(c); });
    if (dw < bestDW) {
      bestDW = dw;
      bestMelds = chosen.map(function(m) { return m.slice(); });
      bestDeadwood = remaining.slice();
    }
    var remSet = {};
    remaining.forEach(function(c) { remSet[c] = true; });
    var candidates = allMelds.filter(function(m) { return m.every(function(c) { return remSet[c]; }); });
    var seen = {};
    candidates.forEach(function(m) {
      var key = m.slice().sort().join(',');
      if (seen[key]) return;
      seen[key] = true;
      var newRem = remaining.filter(function(c) { return m.indexOf(c) === -1; });
      chosen.push(m);
      bt(newRem, chosen);
      chosen.pop();
    });
  }
  bt(cards.slice(), []);
  return { melds: bestMelds, deadwood: bestDeadwood, dwValue: bestDW };
}

function renderAll() {
  if (!_handsInitialized) initHandPanels();
  renderHeader();
  renderPlayerScores();
  renderShotClock();
  renderTable();
  renderPlayerHands();
  renderDiscardHistory();
  renderHandHistory();
  renderReasoning();
  renderFinal();
  renderFooter();
}

function renderHeader() {
  var badge = document.getElementById('badge');
  badge.textContent = S.finished ? 'FINAL' : 'LIVE';
  badge.className = 'badge ' + (S.finished ? 'badge-final' : 'badge-live');

  /* Action badge */
  var ab = document.getElementById('action-badge');
  if (S.lastAction && !S.finished) {
    var act = S.lastAction.action;
    if (act === 'knock') { ab.style.display = 'inline-block'; ab.textContent = 'KNOCK'; ab.className = 'badge badge-knock'; }
    else if (act === 'gin') { ab.style.display = 'inline-block'; ab.textContent = 'GIN!'; ab.className = 'badge badge-gin'; }
    else ab.style.display = 'none';
  } else ab.style.display = 'none';

  var parts = [];
  if (S.gamesPerMatch > 1) parts.push('Game ' + S.gameNumber + '/' + S.gamesPerMatch);
  parts.push('Hand ' + S.handNumber);
  parts.push('Turn ' + S.turnNumber);

  var models = [];
  PIDS.forEach(function(pid) {
    var m = S.models[pid] || ('Player ' + LABELS[pid]);
    models.push('<span class="' + CLASS_NAMES[pid] + '">' + m + '</span>');
  });
  document.getElementById('sub-info').innerHTML = models.join(' <span style="color:var(--dim)">vs</span> ') + ' <span style="color:var(--dim)">|</span> ' + parts.join(' <span style="color:var(--dim)">|</span> ');
}

function renderPlayerScores() {
  PIDS.forEach(function(pid) {
    var suffix = LABELS[pid].toLowerCase();
    var model = S.models[pid] || ('Player ' + LABELS[pid]);
    var shortName = model.length > 20 ? model.substring(0, 18) + '..' : model;
    document.getElementById('sp-name-' + suffix).textContent = shortName;
    document.getElementById('sp-total-' + suffix).textContent = S.gameScores[pid] || 0;
    document.getElementById('sp-detail-' + suffix).textContent = 'Hands won: ' + (S.handsWon[pid] || 0);

    var panel = document.getElementById('sp-' + suffix);
    panel.className = panel.className.replace(/ ?active-turn/g, '');
    if (pid === S.activePlayer && !S.finished) panel.className += ' active-turn';

    /* Series score */
    var seriesEl = document.getElementById('sp-series-' + suffix);
    if (S.gamesPerMatch > 1) {
      seriesEl.textContent = 'Series: ' + Math.round(S.seriesScores[pid] || 0);
    } else {
      seriesEl.textContent = '';
    }
  });
}

function renderShotClock() {
  var el = document.getElementById('shot-clock');
  if (!S.shotClock.timeLimitMs) return;
  el.style.display = 'block';
  var display = document.getElementById('clock-display');
  var label = document.getElementById('clock-label');
  var strikeEl = document.getElementById('strike-info');
  if (S.shotClock.lastTurnTime && !isReplaying) {
    var elapsed = Date.now() - S.shotClock.lastTurnTime;
    var remaining = Math.max(0, S.shotClock.timeLimitMs - elapsed);
    var secs = remaining / 1000;
    display.textContent = secs.toFixed(1) + 's';
    var cls = 'clock-display ';
    if (remaining <= 5000) cls += 'clock-danger';
    else if (remaining <= 10000) cls += 'clock-warn';
    else cls += 'clock-ok';
    display.className = cls;
  } else {
    display.textContent = (S.shotClock.timeLimitMs / 1000).toFixed(1) + 's';
    display.className = 'clock-display clock-ok';
  }
  var wPid = S.shotClock.waitingOn;
  var wModel = S.models[wPid] || wPid;
  label.innerHTML = 'SHOT CLOCK <span style="color:var(--dim)">&middot;</span> ' + wModel;
  if (S.shotClock.strikeLimit) {
    var strikeParts = [];
    PIDS.forEach(function(pid) {
      var s = S.shotClock.strikes[pid] || 0;
      var m = S.models[pid] || LABELS[pid];
      strikeParts.push('<span class="' + CLASS_NAMES[pid] + '">' + m + ': ' + s + '/' + S.shotClock.strikeLimit + '</span>');
    });
    strikeEl.innerHTML = strikeParts.join(' &middot; ');
  } else { strikeEl.innerHTML = ''; }
  if (S.finished) el.style.display = 'none';
}

function renderTable() {
  var tableLabel = document.getElementById('table-label');
  tableLabel.textContent = 'Table \u2014 Hand ' + S.handNumber;

  /* Stock card */
  var stockEl = document.getElementById('stock-card');
  var stockCountEl = document.getElementById('stock-count');
  if (S.stockSize > 0) {
    stockEl.className = 'big-card face-down';
    stockEl.textContent = S.stockSize;
  } else {
    stockEl.className = 'big-card empty-pile';
    stockEl.textContent = 'empty';
  }
  stockCountEl.textContent = S.stockSize + ' cards';

  /* Discard pile top */
  var discardEl = document.getElementById('discard-card');
  var discardCountEl = document.getElementById('discard-count');
  if (S.discardPile.length > 0) {
    var topCard = S.discardPile[S.discardPile.length - 1];
    var suit = topCard.slice(-1);
    var isRed = (suit === '\u2665' || suit === '\u2666');
    discardEl.className = 'big-card face-up' + (isRed ? ' red' : '');
    discardEl.innerHTML = bigCardHTML(topCard);
  } else {
    discardEl.className = 'big-card empty-pile';
    discardEl.textContent = 'empty';
  }
  discardCountEl.textContent = S.discardPile.length + ' cards';

  /* Last action indicator */
  var actionEl = document.getElementById('last-action');
  if (S.lastAction) {
    var who = S.models[S.lastAction.player] || LABELS[S.lastAction.player] || '?';
    var shortWho = who.length > 16 ? who.substring(0,14) + '..' : who;
    var drewFrom = S.lastAction.drew_from === 'discard' ? 'discard pile' : 'stock';
    var discarded = S.lastAction.discarded;
    var act = S.lastAction.action;
    var cls = 'draw-indicator';
    var text = '<span class="' + CLASS_NAMES[S.lastAction.player] + '">' + shortWho + '</span> drew from ' + drewFrom + ', discarded ' + cardHTML(discarded);
    if (act === 'knock') { cls += ' knock'; text += ' \u2014 <strong>KNOCK!</strong>'; }
    else if (act === 'gin') { cls += ' gin'; text += ' \u2014 <strong>GIN!</strong>'; }
    actionEl.className = cls;
    actionEl.innerHTML = text;
    actionEl.style.display = 'block';
  } else {
    actionEl.style.display = 'none';
  }
}

function renderPlayerHands() {
  if (!_handsInitialized) return;

  PIDS.forEach(function(pid) {
    var panel = document.getElementById('hp-' + pid);
    var nameEl = document.getElementById('hp-name-' + pid);
    var infoEl = document.getElementById('hp-info-' + pid);
    var handEl = document.getElementById('hp-hand-' + pid);
    var meldsEl = document.getElementById('hp-melds-' + pid);

    var model = S.models[pid] || ('Player ' + LABELS[pid]);
    nameEl.textContent = model;

    /* Active highlight */
    var isActive = (pid === S.activePlayer && !S.finished);
    panel.className = panel.className.replace(/ ?active/g, '');
    if (isActive) panel.className += ' active';

    /* Hand cards with meld detection */
    var hand = S.hands[pid] || [];
    if (hand.length > 0) {
      var result = findMelds(hand);
      var inMeld = {};
      result.melds.forEach(function(m) { m.forEach(function(c) { inMeld[c] = true; }); });

      /* Info line */
      infoEl.innerHTML = 'Deadwood: <strong>' + result.dwValue + '</strong>' +
        (result.dwValue <= 10 ? ' <span style="color:var(--green)">(can knock)</span>' : '') +
        (result.dwValue === 0 ? ' <span style="color:var(--gold)">(GIN!)</span>' : '');

      /* Render cards */
      handEl.innerHTML = hand.map(function(card) {
        var extra = inMeld[card] ? 'in-meld' : 'deadwood';
        return cardHTML(card, extra);
      }).join('');

      /* Meld groups */
      if (result.melds.length > 0) {
        var meldHTML = '<span style="color:var(--dim)">Melds: </span>';
        result.melds.forEach(function(m) {
          meldHTML += '<span class="meld-group">';
          m.forEach(function(c) { meldHTML += cardHTML(c, 'in-meld'); });
          meldHTML += '</span>';
        });
        if (result.deadwood.length > 0) {
          meldHTML += '<span style="color:var(--dim);margin-left:8px">DW: </span>';
          result.deadwood.forEach(function(c) { meldHTML += cardHTML(c, 'deadwood'); });
        }
        meldsEl.innerHTML = meldHTML;
        meldsEl.style.display = 'block';
      } else {
        meldsEl.innerHTML = '<span style="color:var(--dim)">No melds</span>';
        meldsEl.style.display = 'block';
      }
    } else {
      handEl.innerHTML = '<span style="color:var(--dim)">(empty)</span>';
      meldsEl.innerHTML = '';
      infoEl.innerHTML = '';
    }
  });
}

function renderDiscardHistory() {
  var el = document.getElementById('dh-content');
  if (!S.discardHistory || S.discardHistory.length === 0) {
    el.innerHTML = '<span style="color:var(--dim);font-style:italic">No discards yet</span>';
    return;
  }
  var html = '';
  S.discardHistory.slice().reverse().slice(0, 10).forEach(function(d) {
    var who = S.models[d.player] || LABELS[d.player] || '?';
    var shortWho = who.length > 12 ? who.substring(0,10) + '..' : who;
    var drewFrom = d.drew_from;
    html += '<div class="dh-entry"><span class="' + CLASS_NAMES[d.player] + '">' + shortWho + '</span> drew ' + drewFrom + ', discarded ' + cardHTML(d.discarded) + '</div>';
  });
  el.innerHTML = html;
}

function renderHandHistory() {
  var el = document.getElementById('hh-content');
  if (!S.handHistory || S.handHistory.length === 0) {
    el.innerHTML = '<span style="color:var(--dim);font-style:italic">No completed hands</span>';
    return;
  }
  var html = '';
  S.handHistory.slice().reverse().forEach(function(h) {
    var cls = 'hh-entry';
    html += '<div class="' + cls + '">';
    html += '<strong>H' + h.hand_number + '</strong>: ';
    if (h.result === 'draw') {
      html += '<span class="hh-draw">Draw (stock depleted)</span>';
    } else if (h.result === 'gin') {
      var w = S.models[h.winner] || h.winner || '?';
      html += '<span class="hh-gin">GIN! ' + w + ' +' + h.points_awarded + '</span>';
    } else if (h.result === 'undercut') {
      var w = S.models[h.winner] || h.winner || '?';
      html += '<span class="hh-undercut">UNDERCUT! ' + w + ' +' + h.points_awarded + '</span>';
    } else if (h.result === 'knock') {
      var w = S.models[h.winner] || h.winner || '?';
      html += '<span class="hh-knock">Knock: ' + w + ' +' + h.points_awarded + '</span>';
    }
    /* Show melds if available */
    if (h.knocker_melds && h.knocker_melds.length > 0) {
      var knockerName = S.models[h.knocker] || h.knocker || '?';
      var shortK = knockerName.length > 10 ? knockerName.substring(0,8) + '..' : knockerName;
      html += ' <span style="color:var(--dim)">(' + shortK + ': ' + h.knocker_deadwood_value + ' dw)</span>';
    }
    html += '</div>';
  });
  el.innerHTML = html;
}

function renderReasoning() {
  var el = document.getElementById('reasoning-content');
  if (!S.lastReasoning) {
    el.innerHTML = '<span style="color:var(--dim);font-style:italic">Waiting...</span>';
    return;
  }
  var latStr = S.lastLatency ? ' (' + (S.lastLatency / 1000).toFixed(1) + 's)' : '';
  el.innerHTML = '<span style="font-weight:bold">' + (S.lastModel || '?') + latStr + ':</span> <span style="font-style:italic;color:var(--dim)">' + S.lastReasoning.replace(/</g,'&lt;').replace(/>/g,'&gt;') + '</span>';
}

function renderFinal() {
  var panel = document.getElementById('final-panel');
  if (!S.finished) { panel.className = 'panel'; return; }
  panel.className = 'panel show';

  var scores = S.finalScores;
  if (!scores || Object.keys(scores).length === 0) scores = S.seriesScores;
  var sorted = PIDS.slice().sort(function(a,b) { return (scores[b] || 0) - (scores[a] || 0); });

  var winPid = sorted[0];
  var winModel = S.models[winPid] || LABELS[winPid];
  var winColor = PLAYER_COLORS[winPid];

  var html = '<div class="winner" style="color:' + winColor + '">' + winModel + ' WINS!</div>';
  html += '<div style="font-size:12px;color:var(--dim);margin:4px 0">Best-of-' + S.gamesPerMatch + ' series</div>';
  html += '<div class="standings" style="margin-top:8px">';
  sorted.forEach(function(pid, i) {
    var m = S.models[pid] || LABELS[pid];
    var pts = Math.round(scores[pid] || 0);
    var rank = i === 0 ? '\u{1F947}' : '\u{1F948}';
    html += '<div><span class="' + CLASS_NAMES[pid] + '">' + rank + ' ' + m + '</span>: ' + pts + ' series points</div>';
  });
  html += '</div>';

  document.getElementById('final-content').innerHTML = html;
}

function renderFooter() {
  var st = document.getElementById('status-text');
  if (S.finished) {
    st.innerHTML = '<span class="badge badge-final" style="font-size:10px">FINAL</span> Match Complete';
  } else {
    st.innerHTML = '<span class="badge badge-live" style="font-size:10px">LIVE</span> Watching...';
  }
  document.getElementById('turn-count').textContent = S.turnCount;
}

function drainQueue() {
  if (turnQueue.length === 0) { isReplaying = false; return; }
  var batch = turnQueue.splice(0, 5);
  batch.forEach(function(d) { processTurn(d); });
  renderAll();
  if (turnQueue.length > 0) {
    setTimeout(drainQueue, 150);
  } else {
    isReplaying = false;
    renderShotClock();
  }
}

/* SSE connection */
var evtPath = '/events';
if (window.location.pathname.match(/^\/match\//)) {
  var matchId = window.location.pathname.split('/match/')[1];
  if (matchId) evtPath = '/events/' + matchId;
}
var es = new EventSource(evtPath);
es.onmessage = function(e) {
  var data = JSON.parse(e.data);
  if (isReplaying) {
    turnQueue.push(data);
  } else if (rawLines.length === 0) {
    turnQueue.push(data);
    isReplaying = true;
    drainQueue();
  } else {
    processTurn(data);
    renderAll();
  }
};
setInterval(function() {
  if (S.shotClock.timeLimitMs && !S.finished && !isReplaying) renderShotClock();
}, 100);
</script>
</body>
</html>"""


# ── Bracket HTML/CSS/JS ───────────────────────────────────────────

BRACKET_HTML_PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Bracket Spectator — Live</title>
<style>
:root {
  --bg: #0d1117;
  --surface: #161b22;
  --border: #30363d;
  --text: #e6edf3;
  --dim: #7d8590;
  --cyan: #58a6ff;
  --magenta: #d2a8ff;
  --green: #3fb950;
  --red: #f85149;
  --yellow: #d29922;
  --amber: #e3b341;
  --gold: #f0c040;
}
* { margin: 0; padding: 0; box-sizing: border-box; }
html, body { height: 100%; overflow: hidden; }
body {
  background: var(--bg);
  color: var(--text);
  font-family: 'SF Mono', 'Cascadia Code', 'Fira Code', 'Consolas', monospace;
  font-size: 13px;
  line-height: 1.4;
  display: flex;
  flex-direction: column;
}

/* ── Bracket Header (collapsible) ── */
#bracket-header {
  flex-shrink: 0;
}
#header-bar {
  background: var(--surface);
  border-bottom: 1px solid var(--border);
  padding: 8px 16px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  cursor: pointer;
  user-select: none;
}
#header-bar:hover { background: #1c2333; }
#header-bar .left { display: flex; align-items: center; gap: 10px; }
#header-bar .badge {
  display: inline-block;
  padding: 2px 10px;
  border-radius: 4px;
  font-weight: bold;
  font-size: 11px;
}
.badge-live { background: var(--green); color: #000; animation: pulse 2s infinite; }
.badge-complete { background: var(--cyan); color: #000; }
.badge-pending { background: var(--dim); color: #000; }
@keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.6; } }
#header-bar .round-label { font-size: 15px; font-weight: bold; }
#header-bar .round-meta { color: var(--dim); font-size: 12px; }
#header-bar .toggle-arrow {
  font-size: 16px;
  color: var(--dim);
  transition: transform 0.2s;
}
#header-bar .toggle-arrow.open { transform: rotate(180deg); }

/* Bracket tree (collapsed by default) */
#bracket-tree {
  max-height: 0;
  overflow: hidden;
  transition: max-height 0.3s ease;
  background: var(--surface);
  border-bottom: 1px solid var(--border);
}
#bracket-tree.open { max-height: 600px; overflow-x: auto; }
#bracket-tree-inner { padding: 12px 16px; }
.bracket-grid {
  display: flex;
  gap: 0;
  align-items: center;
  min-height: 120px;
}
.bracket-round {
  display: flex;
  flex-direction: column;
  justify-content: space-around;
  min-width: 180px;
  flex: 1;
}
.bracket-round-label {
  text-align: center;
  font-size: 10px;
  text-transform: uppercase;
  color: var(--dim);
  margin-bottom: 6px;
  letter-spacing: 1px;
  font-weight: bold;
}
.bracket-matchup {
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 4px;
  margin: 3px 6px;
  padding: 4px 8px;
  font-size: 11px;
}
.bracket-matchup.status-complete { border-left: 3px solid var(--green); }
.bracket-matchup.status-in_progress { border-left: 3px solid var(--amber); }
.bracket-matchup.status-pending { border-left: 3px solid var(--dim); opacity: 0.5; }
.matchup-player {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 1px 0;
}
.matchup-player .seed { color: var(--dim); font-size: 9px; margin-right: 3px; min-width: 18px; }
.matchup-player .name { flex: 1; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.matchup-player .score { font-weight: bold; margin-left: 6px; min-width: 20px; text-align: right; }
.matchup-player.winner .name { color: var(--green); font-weight: bold; }
.matchup-player.loser { opacity: 0.5; }
.matchup-vs { text-align: center; color: var(--dim); font-size: 9px; }
.bracket-connectors { min-width: 20px; flex-shrink: 0; }

/* Champion banner */
#champion-banner {
  display: none;
  background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);
  border-bottom: 2px solid var(--gold);
  padding: 16px;
  text-align: center;
  flex-shrink: 0;
}
#champion-banner.show { display: block; }
#champion-banner .trophy { font-size: 28px; }
#champion-banner .champ-name { font-size: 18px; font-weight: bold; color: var(--gold); margin: 2px 0; }
#champion-banner .champ-sub { color: var(--dim); font-size: 11px; }

/* ── Match Viewport (iframe grid) ── */
#match-viewport {
  flex: 1;
  display: grid;
  gap: 2px;
  padding: 2px;
  min-height: 0;
}
.match-viewport-4 { grid-template-columns: 1fr 1fr; grid-template-rows: 1fr 1fr; }
.match-viewport-3 { grid-template-columns: 1fr 1fr; grid-template-rows: 1fr 1fr; }
.match-viewport-2 { grid-template-columns: 1fr 1fr; grid-template-rows: 1fr; }
.match-viewport-1 { grid-template-columns: 1fr; grid-template-rows: 1fr; }

.match-cell {
  display: flex;
  flex-direction: column;
  border: 1px solid var(--border);
  border-radius: 4px;
  overflow: hidden;
  min-height: 0;
  background: var(--surface);
}
.match-cell-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 3px 8px;
  background: var(--surface);
  border-bottom: 1px solid var(--border);
  font-size: 11px;
  flex-shrink: 0;
}
.match-cell-header .players { font-weight: bold; }
.match-cell-header .seed-tag { color: var(--dim); font-size: 10px; }
.match-cell-header .player-a { color: var(--cyan); }
.match-cell-header .player-b { color: var(--magenta); }
.match-cell-header .status-tag {
  font-size: 9px;
  padding: 1px 6px;
  border-radius: 3px;
  font-weight: bold;
  text-transform: uppercase;
}
.status-tag.live { background: var(--green); color: #000; }
.status-tag.complete { background: var(--dim); color: #000; }
.status-tag.winner-tag { background: var(--green); color: #000; }

.match-cell iframe {
  flex: 1;
  width: 100%;
  border: none;
  background: var(--bg);
  min-height: 0;
}

/* Transition overlay */
.match-cell .winner-overlay {
  position: absolute;
  inset: 0;
  background: rgba(13,17,23,0.85);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 16px;
  font-weight: bold;
  color: var(--green);
  z-index: 10;
}
.match-cell { position: relative; }

/* Waiting state */
#waiting-msg {
  display: flex;
  align-items: center;
  justify-content: center;
  flex: 1;
  color: var(--dim);
  font-size: 16px;
}
</style>
</head>
<body>

<div id="bracket-header">
  <div id="header-bar" onclick="toggleBracket()">
    <div class="left">
      <span class="badge badge-pending" id="status-badge">WAITING</span>
      <span class="round-label" id="round-label">Loading...</span>
      <span class="round-meta" id="round-meta"></span>
    </div>
    <span class="toggle-arrow" id="toggle-arrow">&#9660;</span>
  </div>
  <div id="bracket-tree">
    <div id="bracket-tree-inner">
      <div class="bracket-grid" id="bracket-grid"></div>
    </div>
  </div>
</div>

<div id="champion-banner">
  <div class="trophy">&#127942;</div>
  <div class="champ-name" id="champ-name"></div>
  <div class="champ-sub" id="champ-sub">Tournament Champion</div>
</div>

<div id="match-viewport"></div>
<div id="waiting-msg">Waiting for bracket data...</div>

<script>
// ── State ──
var manifest = null;
var currentRoundIdx = -1;
var previousRoundIdx = -1;
var bracketOpen = false;
var transitionTimer = null;

// ── Manifest SSE ──
function startManifestSSE() {
  var es = new EventSource('/events/manifest');
  es.onmessage = function(e) {
    try {
      manifest = JSON.parse(e.data);
      onManifestUpdate();
    } catch(err) {}
  };
  es.addEventListener('done', function() { es.close(); });
  es.onerror = function() {
    setTimeout(function() { es.close(); startManifestSSE(); }, 3000);
  };
}

fetch('/manifest')
  .then(function(r) { return r.json(); })
  .then(function(m) { manifest = m; onManifestUpdate(); })
  .catch(function() {});
startManifestSSE();

// ── Core orchestration ──
function onManifestUpdate() {
  if (!manifest) return;
  var activeIdx = findActiveRound();
  renderBracketHeader();
  renderBracketTree();
  renderChampion();

  if (activeIdx < 0) {
    // No active round yet
    document.getElementById('waiting-msg').style.display = 'flex';
    document.getElementById('match-viewport').style.display = 'none';
    return;
  }
  document.getElementById('waiting-msg').style.display = 'none';
  document.getElementById('match-viewport').style.display = '';

  if (activeIdx !== currentRoundIdx) {
    if (currentRoundIdx >= 0 && activeIdx > currentRoundIdx) {
      // Round transition: show winners on current round, then switch after delay
      updateMatchCellHeaders();
      if (!transitionTimer) {
        // Briefly flash bracket open
        setBracketOpen(true);
        transitionTimer = setTimeout(function() {
          transitionTimer = null;
          setBracketOpen(false);
          transitionToRound(activeIdx);
        }, 3000);
      }
    } else {
      transitionToRound(activeIdx);
    }
  } else {
    updateMatchCellHeaders();
  }
}

function findActiveRound() {
  if (!manifest || !manifest.rounds) return -1;
  var rounds = manifest.rounds;
  // First in_progress round
  for (var i = 0; i < rounds.length; i++) {
    if (rounds[i].status === 'in_progress') return i;
  }
  // If all complete, return last round
  var lastComplete = -1;
  for (var i = 0; i < rounds.length; i++) {
    if (rounds[i].status === 'complete') lastComplete = i;
  }
  return lastComplete;
}

function transitionToRound(idx) {
  previousRoundIdx = currentRoundIdx;
  currentRoundIdx = idx;
  var rounds = manifest.rounds || [];
  var rd = rounds[idx];
  if (!rd) return;

  var viewport = document.getElementById('match-viewport');
  viewport.innerHTML = '';

  var matches = rd.matches || [];
  var count = matches.length;

  // Set grid class
  viewport.className = 'match-viewport-' + Math.min(count, 4);

  for (var i = 0; i < matches.length; i++) {
    viewport.appendChild(createMatchCell(matches[i]));
  }
}

function createMatchCell(match) {
  var cell = document.createElement('div');
  cell.className = 'match-cell';
  cell.setAttribute('data-match-id', match.match_id || '');

  // Header
  var header = document.createElement('div');
  header.className = 'match-cell-header';

  var playersSpan = document.createElement('span');
  playersSpan.className = 'players';
  playersSpan.innerHTML =
    '<span class="seed-tag">[' + match.seed_a + ']</span> ' +
    '<span class="player-a">' + escapeHtml(match.model_a || 'TBD') + '</span>' +
    ' <span style="color:var(--dim)">vs</span> ' +
    '<span class="seed-tag">[' + match.seed_b + ']</span> ' +
    '<span class="player-b">' + escapeHtml(match.model_b || 'TBD') + '</span>';

  var statusTag = document.createElement('span');
  statusTag.className = 'status-tag live';
  statusTag.textContent = 'LIVE';
  if (match.winner) {
    statusTag.className = 'status-tag winner-tag';
    statusTag.textContent = escapeHtml(match.winner) + ' wins';
  }

  header.appendChild(playersSpan);
  header.appendChild(statusTag);
  cell.appendChild(header);

  // Iframe
  if (match.match_id) {
    var iframe = document.createElement('iframe');
    iframe.src = '/match/' + match.match_id + '?compact=1';
    cell.appendChild(iframe);
  }

  return cell;
}

function updateMatchCellHeaders() {
  if (!manifest || currentRoundIdx < 0) return;
  var rounds = manifest.rounds || [];
  var rd = rounds[currentRoundIdx];
  if (!rd) return;

  var cells = document.querySelectorAll('.match-cell');
  for (var i = 0; i < cells.length; i++) {
    var matchId = cells[i].getAttribute('data-match-id');
    if (!matchId) continue;

    // Find match in current round
    var match = null;
    for (var j = 0; j < rd.matches.length; j++) {
      if (rd.matches[j].match_id === matchId) {
        match = rd.matches[j];
        break;
      }
    }
    if (!match) continue;

    var statusTag = cells[i].querySelector('.status-tag');
    if (!statusTag) continue;

    if (match.winner) {
      statusTag.className = 'status-tag winner-tag';
      var scoreA = match.scores ? (match.scores.player_a ?? '') : '';
      var scoreB = match.scores ? (match.scores.player_b ?? '') : '';
      var scoreStr = (scoreA !== '' && scoreB !== '') ? ' (' + Math.round(scoreA) + '-' + Math.round(scoreB) + ')' : '';
      statusTag.textContent = escapeHtml(match.winner) + ' wins' + scoreStr;
    } else {
      statusTag.className = 'status-tag live';
      statusTag.textContent = 'LIVE';
    }
  }
}

// ── Bracket Header ──
function renderBracketHeader() {
  var badge = document.getElementById('status-badge');
  var label = document.getElementById('round-label');
  var meta = document.getElementById('round-meta');

  if (!manifest) return;

  var rounds = manifest.rounds || [];
  var activeIdx = findActiveRound();
  var rd = activeIdx >= 0 ? rounds[activeIdx] : null;

  if (manifest.status === 'complete') {
    badge.className = 'badge badge-complete';
    badge.textContent = 'COMPLETE';
    label.textContent = manifest.tournament_name || 'Tournament Complete';
    meta.textContent = '';
    // Expand bracket permanently when tournament complete
    setBracketOpen(true);
  } else if (rd) {
    badge.className = 'badge badge-live';
    badge.textContent = 'LIVE';
    label.textContent = rd.label || ('Round ' + (activeIdx + 1));
    var matchCount = rd.matches ? rd.matches.length : 0;
    var doneCount = 0;
    for (var i = 0; i < (rd.matches || []).length; i++) {
      if (rd.matches[i].winner) doneCount++;
    }
    meta.textContent = matchCount + ' matches' + (doneCount > 0 ? ' \u00b7 ' + doneCount + ' complete' : '');
  } else {
    badge.className = 'badge badge-pending';
    badge.textContent = 'WAITING';
    label.textContent = manifest.tournament_name || 'Waiting...';
    meta.textContent = '';
  }
}

// ── Bracket Tree ──
function renderBracketTree() {
  var grid = document.getElementById('bracket-grid');
  grid.innerHTML = '';

  if (!manifest) return;
  var rounds = manifest.rounds || [];
  if (!rounds.length) {
    grid.innerHTML = '<div style="color:var(--dim);padding:12px;text-align:center;">Waiting for bracket data...</div>';
    return;
  }

  var totalRounds = manifest.num_rounds || rounds.length;

  for (var ri = 0; ri < totalRounds; ri++) {
    if (ri > 0) {
      var conn = document.createElement('div');
      conn.className = 'bracket-connectors';
      grid.appendChild(conn);
    }

    var roundDiv = document.createElement('div');
    roundDiv.className = 'bracket-round';

    var rd = rounds[ri];
    var labelEl = document.createElement('div');
    labelEl.className = 'bracket-round-label';
    labelEl.textContent = rd ? rd.label : ('Round ' + (ri + 1));
    roundDiv.appendChild(labelEl);

    if (rd) {
      for (var mi = 0; mi < rd.matches.length; mi++) {
        roundDiv.appendChild(createMatchupEl(rd.matches[mi], rd.status));
      }
    } else {
      var numMatches = Math.max(1, Math.pow(2, totalRounds - ri - 1) / 2);
      for (var j = 0; j < numMatches; j++) {
        var tbd = document.createElement('div');
        tbd.className = 'bracket-matchup status-pending';
        tbd.innerHTML = '<div class="matchup-player"><span class="name" style="color:var(--dim)">TBD</span></div>' +
          '<div class="matchup-vs">vs</div>' +
          '<div class="matchup-player"><span class="name" style="color:var(--dim)">TBD</span></div>';
        roundDiv.appendChild(tbd);
      }
    }
    grid.appendChild(roundDiv);
  }
}

function createMatchupEl(m, roundStatus) {
  var el = document.createElement('div');
  var status = m.winner ? 'complete' : (roundStatus === 'in_progress' ? 'in_progress' : 'pending');
  el.className = 'bracket-matchup status-' + status;

  var isAWinner = m.winner === m.model_a;
  var isBWinner = m.winner === m.model_b;
  var scoreA = m.scores ? (m.scores.player_a != null ? m.scores.player_a : '') : '';
  var scoreB = m.scores ? (m.scores.player_b != null ? m.scores.player_b : '') : '';

  el.innerHTML =
    '<div class="matchup-player ' + (isAWinner ? 'winner' : (m.winner ? 'loser' : '')) + '">' +
      '<span class="seed">[' + m.seed_a + ']</span>' +
      '<span class="name">' + escapeHtml(m.model_a || 'TBD') + '</span>' +
      '<span class="score">' + (scoreA !== '' ? Math.round(scoreA) : '') + '</span>' +
    '</div>' +
    '<div class="matchup-vs">vs</div>' +
    '<div class="matchup-player ' + (isBWinner ? 'winner' : (m.winner ? 'loser' : '')) + '">' +
      '<span class="seed">[' + m.seed_b + ']</span>' +
      '<span class="name">' + escapeHtml(m.model_b || 'TBD') + '</span>' +
      '<span class="score">' + (scoreB !== '' ? Math.round(scoreB) : '') + '</span>' +
    '</div>';

  return el;
}

// ── Champion ──
function renderChampion() {
  var banner = document.getElementById('champion-banner');
  if (manifest && manifest.champion) {
    banner.classList.add('show');
    document.getElementById('champ-name').textContent = manifest.champion;
    var seeds = manifest.seeds || [];
    var seed = null;
    for (var i = 0; i < seeds.length; i++) {
      if (seeds[i].model === manifest.champion) { seed = seeds[i]; break; }
    }
    document.getElementById('champ-sub').textContent =
      seed ? ('Seed #' + seed.seed + ' \u00b7 Tournament Champion') : 'Tournament Champion';
  } else {
    banner.classList.remove('show');
  }
}

// ── Toggle bracket ──
function toggleBracket() {
  setBracketOpen(!bracketOpen);
}

function setBracketOpen(open) {
  bracketOpen = open;
  var tree = document.getElementById('bracket-tree');
  var arrow = document.getElementById('toggle-arrow');
  if (open) {
    tree.classList.add('open');
    arrow.classList.add('open');
  } else {
    tree.classList.remove('open');
    arrow.classList.remove('open');
  }
}

function escapeHtml(text) {
  var div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}
</script>
</body>
</html>"""


# ── HTTP Handler ──────────────────────────────────────────────────

def _get_mongo_client():
    """Lazy singleton Mongo client for spectator stats."""
    if not hasattr(_get_mongo_client, '_client'):
        import os
        uri = os.environ.get('TOURNEY_MONGO_URI')
        if uri:
            try:
                from pymongo import MongoClient
                _get_mongo_client._client = MongoClient(uri, serverSelectionTimeoutMS=3000)
                _get_mongo_client._client.admin.command('ping')
                _get_mongo_client._db = _get_mongo_client._client['llmtourney']
            except Exception:
                _get_mongo_client._client = None
                _get_mongo_client._db = None
        else:
            _get_mongo_client._client = None
            _get_mongo_client._db = None
    return _get_mongo_client._db


class SpectatorHandler(BaseHTTPRequestHandler):
    jsonl_path: Path  # set on class before serving
    html_page: str = ""  # set on class before serving

    def log_message(self, format, *args):
        pass  # Suppress request logging

    def do_GET(self):
        if self.path == '/':
            self._serve_html()
        elif self.path == '/events':
            self._serve_sse()
        elif self.path == '/runlog':
            self._serve_runlog()
        elif self.path == '/filepath':
            self._serve_filepath()
        elif self.path == '/mongo-stats':
            self._serve_mongo_stats()
        else:
            self.send_error(404)

    def _serve_html(self):
        body = self.html_page.encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_sse(self):
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream')
        self.send_header('Cache-Control', 'no-cache')
        self.send_header('Connection', 'keep-alive')
        self.send_header('X-Accel-Buffering', 'no')
        self.end_headers()

        event_filter = getattr(self.__class__, 'event_filter', None)

        # Re-discover latest match for this event type on each connection
        if event_filter:
            latest = discover_latest_match(event_filter)
            path = latest if latest else self.jsonl_path
        else:
            path = self.jsonl_path
        pos = 0
        done = False

        try:
            while not done:
                try:
                    size = path.stat().st_size
                except FileNotFoundError:
                    time.sleep(0.5)
                    continue

                if size > pos:
                    with open(path, 'r') as f:
                        f.seek(pos)
                        while True:
                            raw_line = f.readline()
                            if not raw_line:
                                break
                            raw_line = raw_line.strip()
                            if not raw_line:
                                continue
                            try:
                                data = json.loads(raw_line)
                            except json.JSONDecodeError:
                                continue
                            self.wfile.write(f"data: {raw_line}\n\n".encode())
                            self.wfile.flush()
                            if data.get('record_type') == 'match_summary':
                                self.wfile.write(b"event: done\ndata: end\n\n")
                                self.wfile.flush()
                                done = True
                                break
                        pos = f.tell()

                if not done:
                    time.sleep(0.5)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _serve_runlog(self):
        try:
            body = self.jsonl_path.read_bytes()
        except FileNotFoundError:
            body = b''
        self.send_response(200)
        self.send_header('Content-Type', 'application/jsonl')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_filepath(self):
        body = str(self.jsonl_path.resolve()).encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'text/plain; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_mongo_stats(self):
        db = _get_mongo_client()
        match_id = self.jsonl_path.stem
        result = {"connected": False, "turns": 0, "match_synced": False}
        if db is not None:
            result["connected"] = True
            try:
                result["turns"] = db.turns.count_documents({"match_id": match_id})
                result["match_synced"] = db.matches.count_documents({"match_id": match_id}) > 0
            except Exception:
                pass
        body = json.dumps(result).encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)


# ── Bracket Spectator Handler ────────────────────────────────────

class BracketSpectatorHandler(BaseHTTPRequestHandler):
    """Handler for bracket tournament multi-view spectator."""
    manifest_path: Path      # set on class before serving
    telemetry_dir: Path      # set on class before serving
    html_page: str = ""      # set on class before serving
    page_map: dict = {}      # event_type -> HTML page, set before serving
    _last_mtime: float = 0   # track manifest changes

    def log_message(self, format, *args):
        pass

    def do_GET(self):
        path = self.path.split('?')[0]  # strip query string for routing
        if path == '/':
            self._serve_html()
        elif path == '/manifest':
            self._serve_manifest()
        elif path == '/events/manifest':
            self._serve_manifest_sse()
        elif path.startswith('/match/'):
            match_id = path[len('/match/'):]
            self._serve_match_page(match_id)
        elif path.startswith('/events/'):
            match_id = path[len('/events/'):]
            self._serve_match_sse(match_id)
        else:
            self.send_error(404)

    def _serve_html(self):
        body = self.html_page.encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _get_event_type(self):
        """Read manifest and return event type (e.g. 'tictactoe' or 'multi')."""
        try:
            data = json.loads(self.manifest_path.read_text())
            evt = data.get("event", "scrabble")
            if "+" in evt:
                return "multi"
            return evt
        except (FileNotFoundError, json.JSONDecodeError):
            return "scrabble"

    def _resolve_match_event_type(self, match_id):
        """For multi-event tournaments, determine if match_id is composite or per-event.

        Returns the specific event name (e.g. 'tictactoe') if it's a per-event
        match, or 'multi' if it's the composite match_id.
        """
        try:
            data = json.loads(self.manifest_path.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            return "multi"
        for rd in data.get("rounds", []):
            for m in rd.get("matches", []):
                if m.get("match_id") == match_id:
                    return "multi"
                for evt, emid in m.get("event_match_ids", {}).items():
                    if emid == match_id:
                        return evt
        return "multi"

    def _serve_match_page(self, match_id):
        """Serve a single-match HTML page patched to connect to /events/{match_id}."""
        event_type = self._get_event_type()
        if event_type == "multi":
            # Resolve whether this specific match_id is composite or per-event
            event_type = self._resolve_match_event_type(match_id)
        if event_type == "multi":
            # Multi-event composite page — child iframes handle their own SSE
            html = self.page_map.get("multi", "")
            if not html:
                self.send_error(404, "Unknown event type")
                return
            html = html.replace("'__MATCH_ID__'", f"'{match_id}'")
            if '?compact=1' in self.path:
                compact_css = (
                    "\n/* compact overrides for iframe embedding */\n"
                    "body { overflow: hidden !important; }\n"
                    ".top-bar { height: 24px !important; font-size: 11px !important; }\n"
                    ".top-bar .score { font-size: 13px !important; }\n"
                )
                html = html.replace("</style>", compact_css + "</style>", 1)
        else:
            html = self.page_map.get(event_type, self.page_map.get("scrabble", ""))
            if not html:
                self.send_error(404, "Unknown event type")
                return
            # Patch EventSource to point at the match-specific SSE endpoint
            html = html.replace(
                "EventSource('/events')",
                f"EventSource('/events/{match_id}')"
            )
            # Inject compact CSS if ?compact=1
            if '?compact=1' in self.path:
                compact_css = (
                    "\n/* compact overrides for iframe embedding */\n"
                    "body { max-width: none !important; padding: 4px !important; font-size: 11px !important; overflow: hidden !important; }\n"
                    "#header { padding: 4px 8px !important; margin-bottom: 4px !important; }\n"
                )
                html = html.replace("</style>", compact_css + "</style>", 1)
        body = html.encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_manifest(self):
        try:
            body = self.manifest_path.read_bytes()
        except FileNotFoundError:
            body = b'{}'
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_manifest_sse(self):
        """SSE stream that emits when manifest file mtime changes."""
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream')
        self.send_header('Cache-Control', 'no-cache')
        self.send_header('Connection', 'keep-alive')
        self.send_header('X-Accel-Buffering', 'no')
        self.end_headers()

        last_mtime = 0.0
        try:
            while True:
                try:
                    mtime = self.manifest_path.stat().st_mtime
                except FileNotFoundError:
                    time.sleep(1)
                    continue

                if mtime > last_mtime:
                    last_mtime = mtime
                    try:
                        data = self.manifest_path.read_text()
                    except FileNotFoundError:
                        continue
                    self.wfile.write(f"data: {data}\n\n".encode())
                    self.wfile.flush()

                    # Check if tournament complete
                    try:
                        manifest = json.loads(data)
                        if manifest.get("status") == "complete":
                            self.wfile.write(b"event: done\ndata: complete\n\n")
                            self.wfile.flush()
                            break
                    except json.JSONDecodeError:
                        pass

                time.sleep(1)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _serve_match_sse(self, match_id: str):
        """SSE stream that tail-reads a match's JSONL file."""
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream')
        self.send_header('Cache-Control', 'no-cache')
        self.send_header('Connection', 'keep-alive')
        self.send_header('X-Accel-Buffering', 'no')
        self.end_headers()

        jsonl_path = self.telemetry_dir / f"{match_id}.jsonl"
        pos = 0
        done = False

        try:
            while not done:
                try:
                    size = jsonl_path.stat().st_size
                except FileNotFoundError:
                    time.sleep(0.5)
                    continue

                if size > pos:
                    with open(jsonl_path, 'r') as f:
                        f.seek(pos)
                        while True:
                            raw_line = f.readline()
                            if not raw_line:
                                break
                            raw_line = raw_line.strip()
                            if not raw_line:
                                continue
                            try:
                                data = json.loads(raw_line)
                            except json.JSONDecodeError:
                                continue
                            self.wfile.write(f"data: {raw_line}\n\n".encode())
                            self.wfile.flush()
                            if data.get('record_type') == 'match_summary':
                                self.wfile.write(b"event: done\ndata: end\n\n")
                                self.wfile.flush()
                                done = True
                                break
                        pos = f.tell()

                if not done:
                    time.sleep(0.5)
        except (BrokenPipeError, ConnectionResetError):
            pass

# ── Main ──────────────────────────────────────────────────────────

def resolve_bracket_manifest(arg: str) -> Path:
    """Resolve a bracket manifest path from a name or path."""
    p = Path(arg)
    if p.exists():
        return p
    # Try as bracket name in telemetry dir
    p = TELEMETRY_DIR / f"bracket-{arg}.json"
    if p.exists():
        return p
    p = TELEMETRY_DIR / f"{arg}.json"
    if p.exists():
        return p
    # Return expected path even if it doesn't exist yet — server will wait
    expected = TELEMETRY_DIR / f"bracket-{arg}.json"
    print(f"Bracket manifest not found yet, will wait for: {expected}")
    return expected


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Web spectator for LLM tournament matches",
    )
    parser.add_argument(
        "match",
        nargs="?",
        default=None,
        help="JSONL file or match ID to spectate (default: latest)",
    )
    parser.add_argument(
        "--bracket",
        type=str,
        default=None,
        help="Bracket tournament name or manifest path",
    )
    parser.add_argument(
        "-p", "--port",
        type=int,
        default=PORT,
        help=f"Port to serve on (default: {PORT})",
    )
    parser.add_argument(
        "--event",
        type=str,
        default=None,
        help="Filter auto-discovery to this event type (e.g., holdem, bullshit)",
    )
    args = parser.parse_args()

    if args.bracket:
        # Bracket spectator mode
        manifest_path = resolve_bracket_manifest(args.bracket)
        BracketSpectatorHandler.manifest_path = manifest_path
        BracketSpectatorHandler.telemetry_dir = manifest_path.parent
        BracketSpectatorHandler.html_page = BRACKET_HTML_PAGE
        BracketSpectatorHandler.page_map = {
            "tictactoe": TTT_HTML_PAGE, "checkers": CHECKERS_HTML_PAGE,
            "scrabble": HTML_PAGE, "connectfour": CONNECTFOUR_HTML_PAGE,
            "holdem": HOLDEM_HTML_PAGE, "reversi": REVERSI_HTML_PAGE,
            "bullshit": BULLSHIT_HTML_PAGE, "liarsdice": LIARSDICE_HTML_PAGE,
            "gauntlet": GAUNTLET_HTML_PAGE, "rollerderby": CONCURRENT_YAHTZEE_HTML_PAGE,
            "yahtzee": YAHTZEE_HTML_PAGE, "storyteller": STORYTELLER_HTML_PAGE,
            "spades": SPADES_HTML_PAGE,
            "hearts": HEARTS_HTML_PAGE,
            "ginrummy": GIN_RUMMY_HTML_PAGE,
            "avalon": AVALON_HTML_PAGE,
            "multi": MULTI_EVENT_HTML_PAGE,
        }

        print(f"Bracket Spectator")
        print(f"  Manifest: {manifest_path}")
        print(f"  URL:      http://127.0.0.1:{args.port}")
        print()

        server = ThreadingHTTPServer(('127.0.0.1', args.port), BracketSpectatorHandler)
    else:
        # Single-match spectator mode
        page_map = {"tictactoe": TTT_HTML_PAGE, "checkers": CHECKERS_HTML_PAGE, "scrabble": HTML_PAGE, "connectfour": CONNECTFOUR_HTML_PAGE, "holdem": HOLDEM_HTML_PAGE, "reversi": REVERSI_HTML_PAGE, "bullshit": BULLSHIT_HTML_PAGE, "liarsdice": LIARSDICE_HTML_PAGE, "gauntlet": GAUNTLET_HTML_PAGE, "rollerderby": CONCURRENT_YAHTZEE_HTML_PAGE, "yahtzee": YAHTZEE_HTML_PAGE, "storyteller": STORYTELLER_HTML_PAGE, "spades": SPADES_HTML_PAGE, "hearts": HEARTS_HTML_PAGE, "ginrummy": GIN_RUMMY_HTML_PAGE, "avalon": AVALON_HTML_PAGE}
        label_map = {"tictactoe": "Tic-Tac-Toe", "checkers": "Checkers", "scrabble": "Scrabble", "connectfour": "Connect Four", "holdem": "Hold'em", "reversi": "Reversi", "bullshit": "Bullshit", "liarsdice": "Liar's Dice", "gauntlet": "Gauntlet", "rollerderby": "Roller Derby", "yahtzee": "Yahtzee", "storyteller": "Storyteller", "spades": "Spades", "hearts": "Hearts", "ginrummy": "Gin Rummy", "avalon": "Avalon"}

        SpectatorHandler.event_filter = args.event

        if args.event and not args.match:
            # Event-filter mode: discover latest match for this event type
            jsonl_path = discover_latest_match(args.event)
            if jsonl_path is None:
                # No match yet — create a placeholder path; SSE will wait for it
                jsonl_path = TELEMETRY_DIR / f"{args.event}-pending.jsonl"
            event_type = args.event
        else:
            jsonl_path = resolve_jsonl_path(args.match)
            event_type = detect_event_type(jsonl_path)

        SpectatorHandler.jsonl_path = jsonl_path
        SpectatorHandler.html_page = page_map.get(event_type, HTML_PAGE)

        label = label_map.get(event_type, event_type)
        print(f"{label} Web Spectator")
        if args.event:
            print(f"  Event filter: {args.event}")
        print(f"  File: {jsonl_path}")
        print(f"  URL:  http://127.0.0.1:{args.port}")
        print()

        server = ThreadingHTTPServer(('127.0.0.1', args.port), SpectatorHandler)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.shutdown()


if __name__ == '__main__':
    main()
