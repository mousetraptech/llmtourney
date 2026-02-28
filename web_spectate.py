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
    for prefix in ("scrabble-", "tictactoe-", "checkers-", "connectfour-", "holdem-", "reversi-", "bullshit-", "liarsdice-", "yahtzee-"):
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
    if stem.startswith("yahtzee"):
        return "yahtzee"
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

    var statParts = [];
    if (total > 0) {
      var liePct = Math.round(lies * 100 / total);
      statParts.push('Bluff: ' + liePct + '%');
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
    html += '<div><span class="' + clr + '">' + m + '</span>: bluff ' + liePct + '%, caught ' + caught + 'x, BS calls ' + calls + ' (' + callAcc + '% acc)</div>';
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

  if (activePid && !snap.terminal) {
    const pi = playerIds.indexOf(activePid);
    const name = displayName(activePid);
    document.getElementById('active-info').innerHTML =
      `<span style="color:var(--${PLAYER_COLORS[pi]})">${name}</span> — Roll ${snap.roll_number || 1} of 3`;
  } else if (snap.terminal) {
    document.getElementById('active-info').textContent = 'GAME OVER';
  }

  // Update scorecard
  const scorecards = snap.scorecards || {};
  const potential = snap.potential_scores || {};
  const roundDec = snap.round_decisions || {};

  playerIds.forEach((pid, i) => {
    const sc = scorecards[pid] || {};
    const pot = potential[pid] || {};
    const isActive = pid === activePid;

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
    const isActive = pid === activePid;
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
    entries.push(data);
    slider.max = entries.length - 1;
    if (isLive) goToEntry(entries.length - 1);
  } catch(e) {}
};
evtSource.onerror = () => {
  setTimeout(() => location.reload(), 3000);
};
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
            "yahtzee": YAHTZEE_HTML_PAGE, "multi": MULTI_EVENT_HTML_PAGE,
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
        page_map = {"tictactoe": TTT_HTML_PAGE, "checkers": CHECKERS_HTML_PAGE, "scrabble": HTML_PAGE, "connectfour": CONNECTFOUR_HTML_PAGE, "holdem": HOLDEM_HTML_PAGE, "reversi": REVERSI_HTML_PAGE, "bullshit": BULLSHIT_HTML_PAGE, "liarsdice": LIARSDICE_HTML_PAGE, "yahtzee": YAHTZEE_HTML_PAGE}
        SpectatorHandler.html_page = page_map.get(event_type, HTML_PAGE)

        label = {"tictactoe": "Tic-Tac-Toe", "checkers": "Checkers", "scrabble": "Scrabble", "connectfour": "Connect Four", "holdem": "Hold'em", "reversi": "Reversi", "bullshit": "Bullshit", "liarsdice": "Liar's Dice", "yahtzee": "Yahtzee"}.get(event_type, event_type)
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
