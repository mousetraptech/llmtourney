#!/usr/bin/env python3
"""Web-based spectator UI for LLM tournament matches.

Usage:
    python web_spectate.py <jsonl_file_or_match_id>
    python web_spectate.py                              # Auto-discover latest

Opens http://127.0.0.1:8080 with a live-updating board.
Zero external dependencies — stdlib only.
"""

import json
import sys
import time
import threading
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path

TELEMETRY_DIR = Path("output/telemetry")
PORT = 8080


def discover_latest_match() -> Path | None:
    if not TELEMETRY_DIR.exists():
        return None
    jsonl_files = list(TELEMETRY_DIR.glob("*.jsonl"))
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
    for prefix in ("scrabble-", "tictactoe-", "checkers-", "connectfour-", "holdem-", "reversi-"):
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
  el.style.display = '';
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
  el.style.display = '';
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
  el.style.display = '';
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
  el.style.display = '';
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
  el.style.display = '';
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
  --cyan: #58a6ff;
  --magenta: #d2a8ff;
  --green: #3fb950;
  --red: #f85149;
  --yellow: #d29922;
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
.badge-live { background: var(--green); color: #000; }
.badge-final { background: var(--yellow); color: #000; }
.player-a { color: var(--cyan); }
.player-b { color: var(--magenta); }
#matchup { font-size: 16px; font-weight: bold; }
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

/* Player section */
.player-section {
  padding: 10px 14px;
  border-radius: 8px;
  margin-bottom: 6px;
}
.player-name {
  font-weight: bold;
  font-size: 14px;
  margin-bottom: 4px;
}
.chip-bar-container {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 4px 0;
}
.chip-bar {
  height: 14px;
  border-radius: 3px;
  transition: width 0.5s ease;
  min-width: 2px;
}
.chip-count {
  font-weight: bold;
  font-size: 14px;
  white-space: nowrap;
}
.hole-cards {
  display: flex;
  gap: 4px;
  margin-top: 6px;
}
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
.action-badge {
  display: inline-block;
  padding: 1px 8px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: bold;
  margin-left: 8px;
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
  width: 38px;
  height: 52px;
  border-radius: 5px;
  font-weight: bold;
  font-size: 15px;
  border: 2px solid #555;
  position: relative;
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
  font-size: 18px;
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
  padding: 16px;
  margin: 8px 0;
  text-align: center;
}
.community-cards {
  display: flex;
  gap: 6px;
  justify-content: center;
  margin: 8px 0;
}
.pot-display {
  font-size: 18px;
  font-weight: bold;
  color: var(--yellow);
  margin-top: 8px;
}
.street-badge {
  display: inline-block;
  padding: 2px 10px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: bold;
  text-transform: uppercase;
  margin-bottom: 6px;
}
.street-preflop { background: #30363d; color: var(--text); }
.street-flop { background: #1f4d1f; color: var(--green); }
.street-turn { background: #4d3d1f; color: var(--yellow); }
.street-river { background: #3d1f1f; color: var(--red); }
.street-showdown { background: #1f1f4d; color: var(--cyan); }

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
.breakdown { font-size: 14px; color: var(--dim); }
.stats { font-size: 11px; color: var(--dim); margin-top: 4px; }

/* Shot clock */
#shot-clock {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 8px 14px;
  margin-bottom: 10px;
  text-align: center;
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

<div id="shot-clock" style="display:none">
  <div id="clock-label">SHOT CLOCK</div>
  <div id="clock-display" class="clock-display clock-ok">--</div>
  <div id="strike-info"></div>
</div>

<div class="main">
  <div class="table-area">
    <div id="player-a-section" class="player-section panel"></div>
    <div class="community-area">
      <div id="street-label" class="street-badge street-preflop">PREFLOP</div>
      <div id="community-cards" class="community-cards"></div>
      <div id="pot-display" class="pot-display">Pot: 0</div>
    </div>
    <div id="player-b-section" class="player-section panel"></div>
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

// ── Card rendering helpers ───────────────────────────────────────
const SUIT_SYMBOLS = { H: '\u2665', D: '\u2666', S: '\u2660', C: '\u2663' };
const SUIT_CLASSES = { H: 'suit-h', D: 'suit-d', S: 'suit-s', C: 'suit-c' };

function renderCard(cardStr) {
  // cardStr like "AH", "TD", "2S"
  if (!cardStr || cardStr === '??') {
    return '<div class="card card-back"></div>';
  }
  const rank = cardStr.slice(0, -1);
  const suit = cardStr.slice(-1).toUpperCase();
  const sym = SUIT_SYMBOLS[suit] || suit;
  const cls = SUIT_CLASSES[suit] || '';
  return '<div class="card card-front ' + cls + '">' + rank + sym + '</div>';
}

function renderEmptyCard() {
  return '<div class="card card-empty"></div>';
}

// ── Match state ──────────────────────────────────────────────────
const S = {
  matchId: '', modelA: '', modelB: '',
  handNumber: 0,
  totalHands: 50,
  street: 'preflop',
  pot: 0,
  blinds: [1, 2],
  stacks: { player_a: 200, player_b: 200 },
  communityCards: [],
  dealer: 'player_a',
  holeCards: { player_a: [], player_b: [] },
  lastAction: { playerId: '', action: '', amount: null },
  handStartStacks: {},
  currentHandLastPot: 0,
  currentHandLastAction: '',
  handHistory: [],  // last 8: {handNum, winnerModel, winnerId, margin, ending}
  commentary: [],   // last 12
  turnCount: 0,
  violations: { player_a: 0, player_b: 0 },
  finished: false,
  finalScores: {},
  highlightHands: [],
  emojis: { player_a: '', player_b: '' },
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
    // Record last hand if pending
    const snap = data.final_snapshot || {};
    if (snap.stacks && S.handStartStacks && Object.keys(S.handStartStacks).length) {
      recordHandResult(snap.stacks);
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

  const handNum = data.hand_number || snap.hand_number || 1;

  // Extract total hands from prompt
  const prompt = data.prompt || '';
  if (prompt) {
    const m = prompt.match(/Hand \d+ of (\d+)/);
    if (m) S.totalHands = parseInt(m[1]);
  }

  // Detect hand transition -> record previous hand result
  if (handNum > S.handNumber && S.handNumber > 0 && snap.stacks) {
    recordHandResult(snap.stacks);
  }

  // Track hand start stacks + reset hole cards on new hand
  if (handNum > S.handNumber || !Object.keys(S.handStartStacks).length) {
    S.handStartStacks = { ...snap.stacks };
    S.holeCards = { player_a: [], player_b: [] };
  }

  // Extract hole cards from prompt text
  if (playerId && prompt) {
    const m = prompt.match(/Your hole cards:\s*(.+)/);
    if (m) {
      S.holeCards[playerId] = m[1].trim().split(/\s+/);
    }
  }

  // Update current state
  S.handNumber = handNum;
  S.street = data.street || snap.street || 'preflop';
  S.pot = snap.pot !== undefined ? snap.pot : S.pot;
  if (snap.stacks) S.stacks = { ...snap.stacks };
  S.communityCards = snap.community_cards || S.communityCards;
  S.dealer = snap.dealer || S.dealer;
  if (snap.blinds) S.blinds = snap.blinds;

  // Parse action
  const parsed = data.parsed_action || {};
  const action = parsed.action || '???';
  const amount = parsed.amount;
  const violation = data.violation;

  if (data.validation_result === 'forfeit') {
    S.lastAction = { playerId, action: 'forfeit', amount: null };
  } else {
    S.lastAction = { playerId, action, amount };
  }

  S.currentHandLastPot = snap.pot || 0;
  S.currentHandLastAction = action;

  // Violations
  if (violation) S.violations[playerId] = (S.violations[playerId] || 0) + 1;

  // Commentary
  const reasoning = truncateReasoning(data.reasoning_output);
  S.commentary.push({
    turnNumber: S.turnCount,
    handNumber: handNum,
    street: S.street,
    model: modelId,
    playerId,
    action: S.lastAction.action,
    amount: S.lastAction.amount,
    reasoning,
    latencyMs: data.latency_ms || 0,
    isViolation: !!violation
  });
  if (S.commentary.length > 12) S.commentary.shift();
}

function recordHandResult(newStacks) {
  if (!S.handStartStacks || !newStacks) return;
  const deltaA = (newStacks.player_a || 0) - (S.handStartStacks.player_a || 0);
  const deltaB = (newStacks.player_b || 0) - (S.handStartStacks.player_b || 0);

  let winnerId, margin;
  if (deltaA > 0) { winnerId = 'player_a'; margin = deltaA; }
  else if (deltaB > 0) { winnerId = 'player_b'; margin = deltaB; }
  else return; // split or no change

  const winnerModel = winnerId === 'player_a' ? S.modelA : S.modelB;
  const ending = S.currentHandLastAction === 'fold' ? 'fold' : 'showdown';

  S.handHistory.push({
    handNum: S.handNumber,
    winnerModel,
    winnerId,
    margin,
    ending,
    pot: S.currentHandLastPot
  });
  if (S.handHistory.length > 8) S.handHistory.shift();
}

// ── Rendering ────────────────────────────────────────────────────
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

  const streetLabel = S.street.charAt(0).toUpperCase() + S.street.slice(1);
  document.getElementById('sub-info').innerHTML =
    '<strong>Hand ' + S.handNumber + ' of ' + S.totalHands + '</strong>' +
    ' <span style="color:var(--dim)">|</span> ' +
    streetLabel +
    ' <span style="color:var(--dim)">|</span> ' +
    '<span style="color:var(--yellow)">Pot: ' + S.pot + '</span>' +
    ' <span style="color:var(--dim)">|</span> ' +
    'Blinds: ' + S.blinds[0] + '/' + S.blinds[1];
}

function renderPlayerSection(pid, elId) {
  const el = document.getElementById(elId);
  const name = pid === 'player_a' ? (S.modelA || 'Player A') : (S.modelB || 'Player B');
  const emoji = S.emojis[pid] || '';
  const color = pid === 'player_a' ? 'var(--cyan)' : 'var(--magenta)';
  const chips = S.stacks[pid] || 0;
  const total = (S.stacks.player_a || 0) + (S.stacks.player_b || 0);
  const pct = total > 0 ? Math.max(1, (chips / total) * 100) : 50;

  const isDealer = S.dealer === pid;
  const dealerHTML = isDealer ? '<span class="dealer-btn">D</span>' : '';

  // Last action badge
  let actionHTML = '';
  if (S.lastAction.playerId === pid && S.turnCount > 0) {
    const a = S.lastAction.action;
    const amt = S.lastAction.amount;
    if (a === 'fold') actionHTML = '<span class="action-badge action-fold">FOLD</span>';
    else if (a === 'raise') actionHTML = '<span class="action-badge action-raise">RAISE ' + (amt || '') + '</span>';
    else if (a === 'call' && amt === 0) actionHTML = '<span class="action-badge action-check">CHECK</span>';
    else if (a === 'call') actionHTML = '<span class="action-badge action-call">CALL ' + (amt || '') + '</span>';
    else if (a === 'forfeit') actionHTML = '<span class="action-badge action-fold">FORFEIT</span>';
  }

  // Hole cards
  const cards = S.holeCards[pid] || [];
  let cardsHTML = '';
  if (cards.length) {
    cardsHTML = '<div class="hole-cards">' + cards.map(c => renderCard(c)).join('') + '</div>';
  } else if (S.handNumber > 0) {
    cardsHTML = '<div class="hole-cards">' + renderCard('??') + renderCard('??') + '</div>';
  }

  // Violations
  const v = S.violations[pid] || 0;
  const vHTML = v > 0 ? ' <span style="color:var(--red);font-size:11px">' + v + ' violations</span>' : '';

  el.innerHTML =
    '<div class="player-name" style="color:' + color + '">' + emoji + ' ' + name + dealerHTML + actionHTML + '</div>' +
    '<div class="chip-bar-container">' +
      '<div class="chip-bar" style="width:' + pct + '%;background:' + color + '"></div>' +
      '<span class="chip-count" style="color:' + color + '">' + chips + '</span>' +
    '</div>' +
    cardsHTML + vHTML;
}

function renderCommunity() {
  const cc = document.getElementById('community-cards');
  let html = '';
  for (let i = 0; i < 5; i++) {
    if (i < S.communityCards.length) {
      html += renderCard(S.communityCards[i]);
    } else {
      html += renderEmptyCard();
    }
  }
  cc.innerHTML = html;

  // Street label
  const sl = document.getElementById('street-label');
  const street = S.street || 'preflop';
  sl.textContent = street.toUpperCase();
  sl.className = 'street-badge street-' + street;

  // Pot
  document.getElementById('pot-display').innerHTML = 'Pot: <strong>' + S.pot + '</strong>';
}

function renderHandHistory() {
  const el = document.getElementById('hand-history');
  if (!S.handHistory.length) {
    el.innerHTML = '<span style="color:var(--dim);font-style:italic">No completed hands</span>';
    return;
  }
  el.innerHTML = [...S.handHistory].reverse().map(function(h) {
    const color = h.winnerId === 'player_a' ? 'var(--cyan)' : 'var(--magenta)';
    const hl = S.highlightHands.includes(h.handNum) ? '<span style="color:var(--yellow)">\u2605 </span>' : '';
    return '<div class="hand-entry">' +
      '<span>' + hl + 'Hand ' + h.handNum + '</span>' +
      '<span class="hand-winner" style="color:' + color + '">' + (h.winnerModel || '?') + '</span>' +
      '<span class="hand-margin">+' + h.margin + '</span>' +
      '<span class="hand-ending">(' + h.ending + ')</span>' +
    '</div>';
  }).join('');
}

function renderCommentary() {
  const el = document.getElementById('commentary');
  if (!S.commentary.length) {
    el.innerHTML = '<span style="color:var(--dim);font-style:italic">Waiting for action...</span>';
    return;
  }
  el.innerHTML = [...S.commentary].reverse().map(function(e) {
    const color = e.playerId === 'player_a' ? 'var(--cyan)' : 'var(--magenta)';
    let actionHTML;
    if (e.isViolation) {
      actionHTML = '<span style="color:var(--red);font-weight:bold">violation!</span>';
    } else if (e.action === 'fold') {
      actionHTML = '<span style="color:var(--red)">fold</span>';
    } else if (e.action === 'raise') {
      actionHTML = '<span style="color:var(--yellow)">raise ' + (e.amount || '') + '</span>';
    } else if (e.action === 'call') {
      actionHTML = '<span style="color:var(--green)">' + (e.amount === 0 ? 'check' : 'call ' + (e.amount || '')) + '</span>';
    } else {
      actionHTML = '<span style="color:var(--dim)">' + e.action + '</span>';
    }
    const latency = e.latencyMs > 100 ? ' <span style="color:var(--dim)">(' + (e.latencyMs/1000).toFixed(1) + 's)</span>' : '';
    const reason = e.reasoning ? '<span class="reasoning">"' + e.reasoning + '"</span>' : '';
    return '<div class="comment-entry">' +
      '<span style="color:var(--dim)">H' + e.handNumber + ' ' + e.street + '</span> ' +
      '<span style="color:' + color + ';font-weight:bold">' + e.model + '</span> ' +
      actionHTML + latency + reason +
    '</div>';
  }).join('');
}

function renderFinal() {
  const el = document.getElementById('final-panel');
  if (!S.finished) { el.className = 'panel'; return; }
  el.className = 'panel show';
  const sa = S.finalScores.player_a || 0;
  const sb = S.finalScores.player_b || 0;

  let html;
  if (sa === sb) {
    html = '<div class="winner" style="color:var(--yellow)">DRAW</div><div class="breakdown">' + sa + ' chips each</div>';
  } else {
    const wPid = sa > sb ? 'player_a' : 'player_b';
    const emoji = S.emojis[wPid] || '';
    const wName = wPid === 'player_a' ? S.modelA : S.modelB;
    const wColor = wPid === 'player_a' ? 'var(--cyan)' : 'var(--magenta)';
    html = '<div class="winner" style="color:' + wColor + '">' + emoji + ' ' + wName + ' WINS</div>' +
           '<div class="breakdown">' + sa + ' \u2013 ' + sb + ' chips</div>';
  }
  const va = S.violations.player_a || 0, vb = S.violations.player_b || 0;
  if (va + vb > 0) html += '<div class="stats" style="color:var(--red)">Violations: A:' + va + ' B:' + vb + '</div>';
  const handsPlayed = S.handHistory.length;
  html += '<div class="stats">' + handsPlayed + ' hands recorded over ' + S.turnCount + ' turns</div>';
  document.getElementById('final-content').innerHTML = html;
}

function renderShotClock() {
  var el = document.getElementById('shot-clock');
  if (!S.shotClock.timeLimitMs || S.finished) { el.style.display = 'none'; return; }
  el.style.display = '';
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

function renderFooter() {
  var st = document.getElementById('status-text');
  if (S.finished) {
    st.innerHTML = '<span class="badge badge-final" style="font-size:10px">FINAL</span> Match Complete';
  } else {
    st.innerHTML = '<span class="badge badge-live" style="font-size:10px">LIVE</span> Watching...';
  }
  document.getElementById('line-count').textContent = rawLines.length;
}

function renderAll() {
  renderHeader();
  renderShotClock();
  renderPlayerSection('player_a', 'player-a-section');
  renderCommunity();
  renderPlayerSection('player_b', 'player-b-section');
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
      if (isReplaying) {
        turnQueue.push(data);
      } else {
        processTurn(data);
        renderAll();
      }
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
  var data = turnQueue.shift();
  processTurn(data);
  renderAll();
  var delay = data.record_type === 'match_summary' ? 200 : 50;
  setTimeout(drainQueue, delay);
}

// Init
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
        """Read manifest and return event type (e.g. 'tictactoe')."""
        try:
            data = json.loads(self.manifest_path.read_text())
            return data.get("event", "scrabble")
        except (FileNotFoundError, json.JSONDecodeError):
            return "scrabble"

    def _serve_match_page(self, match_id):
        """Serve a single-match HTML page patched to connect to /events/{match_id}."""
        event_type = self._get_event_type()
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
        }

        print(f"Bracket Spectator")
        print(f"  Manifest: {manifest_path}")
        print(f"  URL:      http://127.0.0.1:{args.port}")
        print()

        server = ThreadingHTTPServer(('127.0.0.1', args.port), BracketSpectatorHandler)
    else:
        # Single-match spectator mode
        jsonl_path = resolve_jsonl_path(args.match)
        event_type = detect_event_type(jsonl_path)

        SpectatorHandler.jsonl_path = jsonl_path
        page_map = {"tictactoe": TTT_HTML_PAGE, "checkers": CHECKERS_HTML_PAGE, "scrabble": HTML_PAGE, "connectfour": CONNECTFOUR_HTML_PAGE, "holdem": HOLDEM_HTML_PAGE, "reversi": REVERSI_HTML_PAGE}
        SpectatorHandler.html_page = page_map.get(event_type, HTML_PAGE)

        label = {"tictactoe": "Tic-Tac-Toe", "checkers": "Checkers", "scrabble": "Scrabble", "connectfour": "Connect Four", "holdem": "Hold'em", "reversi": "Reversi"}.get(event_type, event_type)
        print(f"{label} Web Spectator")
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
