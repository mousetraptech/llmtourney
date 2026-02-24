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
    for prefix in ("scrabble-", "tictactoe-"):
        p = TELEMETRY_DIR / f"{prefix}{arg}.jsonl"
        if p.exists():
            return p
    print(f"Cannot find: {arg}")
    sys.exit(1)


def detect_event_type(jsonl_path: Path) -> str:
    stem = jsonl_path.stem
    if stem.startswith("tictactoe"):
        return "tictactoe"
    if stem.startswith("scrabble"):
        return "scrabble"
    # Fallback: peek at first line
    try:
        with open(jsonl_path) as f:
            first = f.readline()
            if '"tictactoe"' in first:
                return "tictactoe"
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
</style>
</head>
<body>

<div id="header">
  <span class="badge badge-live" id="badge">LIVE</span>
  <span class="title">TIC-TAC-TOE</span>
  <span id="matchup"></span>
  <div class="sub" id="sub-info"></div>
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
    Copy Runlog <span class="count" id="line-count">0</span>
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
  emojis: { player_a: '', player_b: '' }
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

function renderAll() {
  renderHeader();
  renderBoard();
  renderSidebar();
  renderGameHistory();
  renderCommentary();
  renderFinal();
  renderFooter();
}

// ── Copy runlog ──────────────────────────────────────────────────
function copyRunlog() {
  const text = rawLines.join('\n');
  const btn = document.getElementById('copy-btn');
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(text).then(() => {
      btn.classList.add('copied');
      btn.textContent = 'Copied!';
      setTimeout(() => {
        btn.classList.remove('copied');
        btn.innerHTML = 'Copy Runlog <span class="count">' + rawLines.length + '</span>';
      }, 2000);
    });
  } else {
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.style.position = 'fixed';
    ta.style.left = '-9999px';
    document.body.appendChild(ta);
    ta.select();
    document.execCommand('copy');
    document.body.removeChild(ta);
    btn.classList.add('copied');
    btn.textContent = 'Copied!';
    setTimeout(() => {
      btn.classList.remove('copied');
      btn.innerHTML = 'Copy Runlog <span class="count">' + rawLines.length + '</span>';
    }, 2000);
  }
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
</style>
</head>
<body>

<div id="header">
  <span class="badge badge-live" id="badge">LIVE</span>
  <span class="title">SCRABBLE</span>
  <span id="matchup"></span>
  <div class="sub" id="sub-info"></div>
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
    Copy Runlog <span class="count" id="line-count">0</span>
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

function renderAll() {
  renderHeader();
  renderBoard();
  renderSidebar();
  renderWordHistory();
  renderCommentary();
  renderFinal();
  renderFooter();
}

// ── Copy runlog ──────────────────────────────────────────────────
function copyRunlog() {
  const text = rawLines.join('\n');
  const btn = document.getElementById('copy-btn');
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(text).then(() => {
      btn.classList.add('copied');
      btn.textContent = 'Copied!';
      setTimeout(() => {
        btn.classList.remove('copied');
        btn.innerHTML = 'Copy Runlog <span class="count">' + rawLines.length + '</span>';
      }, 2000);
    });
  } else {
    // Fallback
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.style.position = 'fixed';
    ta.style.left = '-9999px';
    document.body.appendChild(ta);
    ta.select();
    document.execCommand('copy');
    document.body.removeChild(ta);
    btn.classList.add('copied');
    btn.textContent = 'Copied!';
    setTimeout(() => {
      btn.classList.remove('copied');
      btn.innerHTML = 'Copy Runlog <span class="count">' + rawLines.length + '</span>';
    }, 2000);
  }
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


# ── Main ──────────────────────────────────────────────────────────

def main():
    arg = sys.argv[1] if len(sys.argv) > 1 else None
    jsonl_path = resolve_jsonl_path(arg)
    event_type = detect_event_type(jsonl_path)

    SpectatorHandler.jsonl_path = jsonl_path
    SpectatorHandler.html_page = TTT_HTML_PAGE if event_type == "tictactoe" else HTML_PAGE

    label = {"tictactoe": "Tic-Tac-Toe", "scrabble": "Scrabble"}.get(event_type, event_type)
    print(f"{label} Web Spectator")
    print(f"  File: {jsonl_path}")
    print(f"  URL:  http://127.0.0.1:{PORT}")
    print()

    server = ThreadingHTTPServer(('127.0.0.1', PORT), SpectatorHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.shutdown()


if __name__ == '__main__':
    main()
