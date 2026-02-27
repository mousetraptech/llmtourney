"""HTML dashboard generator for Bullshit match reports.

Takes a BullshitReport and produces a self-contained HTML file with
Chart.js visualizations, scoreboard, and key findings.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from .bullshit_analyzer import BullshitReport


# Model color palette — deterministic assignment by sorted model name
_COLOR_PALETTE = [
    "#7dd3fc",  # sky blue
    "#a78bfa",  # violet
    "#4ade80",  # green
    "#fbbf24",  # amber
    "#f87171",  # red
    "#fb923c",  # orange
    "#2dd4bf",  # teal
    "#e879f9",  # fuchsia
    "#818cf8",  # indigo
    "#facc15",  # yellow
]


def _assign_colors(models: list[str]) -> dict[str, str]:
    """Assign colors to models deterministically."""
    return {m: _COLOR_PALETTE[i % len(_COLOR_PALETTE)] for i, m in enumerate(models)}


def _short_name(model: str) -> str:
    """Convert model id to display name."""
    replacements = {
        "claude-haiku-4.5": "Haiku 4.5",
        "claude-sonnet-4.5": "Sonnet 4.5",
        "claude-opus-4.6": "Opus 4.6",
        "gpt-4o": "GPT-4o",
        "gpt-4o-mini": "GPT-4o mini",
        "gpt-5": "GPT-5",
        "gemini-2.5-flash": "Gemini Flash",
        "gemini-2.5-pro": "Gemini Pro",
        "llama-4-scout": "Llama Scout",
        "llama-4-maverick": "Llama Maverick",
        "mistral-large": "Mistral Large",
        "mistral-small": "Mistral Small",
        "deepseek-v3": "DeepSeek v3",
        "deepseek-v3.2": "DeepSeek v3.2",
        "grok-3-mini": "Grok-3 mini",
        "grok-3": "Grok-3",
    }
    return replacements.get(model, model)


def generate_dashboard(report: BullshitReport, output_path: str | Path) -> Path:
    """Generate an HTML dashboard from a BullshitReport.

    Returns the path to the generated file.
    """
    output_path = Path(output_path)

    # Sort models by finish position
    sorted_models = sorted(
        report.model_stats.keys(),
        key=lambda m: report.model_stats[m].finish_position,
    )

    colors = _assign_colors(sorted_models)
    short_names = {m: _short_name(m) for m in sorted_models}

    # Build data payload for JS
    data = {
        "match_id": report.match_id,
        "num_players": report.num_players,
        "total_turns": report.total_turns,
        "total_plays": report.total_plays,
        "total_calls": report.total_calls,
        "total_passes": report.total_passes,
        "finish_order": report.finish_order,
        "models": sorted_models,
        "colors": colors,
        "short_names": short_names,
        "stats": {
            m: {
                "finish_position": s.finish_position,
                "bluff_rate": s.bluff_rate,
                "times_caught": s.times_caught,
                "bs_calls": s.bs_calls,
                "call_accuracy": s.call_accuracy,
                "total_plays": s.total_plays,
                "total_turns": s.total_turns,
                "avg_output_tokens": s.avg_output_tokens,
                "avg_latency_ms": s.avg_latency_ms,
                "bluff_with_truth": s.bluff_with_truth_count,
            }
            for m, s in report.model_stats.items()
        },
        "card_trajectories": report.card_trajectories,
        "trajectory_indices": report.trajectory_indices,
        "bluff_timeline": report.bluff_timeline,
        "call_timeline": report.call_timeline,
        "challenge_counts": report.challenge_counts,
        "suboptimal_summary": {
            m: {
                "total": sum(
                    1 for s in report.suboptimal_plays if s.model == m
                ),
                "hallucinations": sum(
                    1
                    for s in report.suboptimal_plays
                    if s.model == m and s.failure_mode == "hallucination"
                ),
                "strategic_errors": sum(
                    1
                    for s in report.suboptimal_plays
                    if s.model == m and s.failure_mode == "strategic_error"
                ),
            }
            for m in sorted_models
        },
    }

    # Generate key findings
    findings = _generate_findings(report, short_names)

    html = _TEMPLATE.replace("/*DATA_PLACEHOLDER*/", json.dumps(data))
    html = html.replace("<!--FINDINGS-->", findings)

    output_path.write_text(html)
    return output_path


def _generate_findings(report: BullshitReport, names: dict[str, str]) -> str:
    """Auto-generate key findings from the report data."""
    items = []

    # Most aggressive caller
    caller = max(
        report.model_stats.values(), key=lambda s: s.bs_calls
    )
    next_caller = sorted(report.model_stats.values(), key=lambda s: -s.bs_calls)
    if len(next_caller) > 1:
        ratio = caller.bs_calls / next_caller[1].bs_calls if next_caller[1].bs_calls else float("inf")
        if ratio > 1.5:
            items.append(
                f'<strong>{names[caller.model]} compulsive challenger:</strong> '
                f'<code>{caller.bs_calls}</code> BS calls — '
                f'{ratio:.1f}× more than next-highest ({names[next_caller[1].model]} at {next_caller[1].bs_calls}). '
                f'Call accuracy: {caller.call_accuracy}%.'
            )

    # Highest bluff rate
    bluffer = max(report.model_stats.values(), key=lambda s: s.bluff_rate)
    if bluffer.bluff_rate > 60:
        items.append(
            f'<strong>{names[bluffer.model]} high bluff rate:</strong> '
            f'<code>{bluffer.bluff_rate}%</code> bluff rate, caught <code>{bluffer.times_caught}</code> times, '
            f'finished #{bluffer.finish_position}.'
        )

    # Zero bluff-with-truth models
    clean_models = [
        names[m]
        for m, s in report.model_stats.items()
        if s.bluff_with_truth_count == 0 and s.total_plays > 5
    ]
    if clean_models:
        items.append(
            f'<strong>Clean play:</strong> {", ".join(clean_models)} had '
            f'<code>0</code> bluff-with-truth incidents — never bluffed while holding the correct rank.'
        )

    # Worst bluff-with-truth offender
    bwt_worst = max(report.model_stats.values(), key=lambda s: s.bluff_with_truth_count)
    if bwt_worst.bluff_with_truth_count > 0:
        items.append(
            f'<strong>{names[bwt_worst.model]} suboptimal play:</strong> '
            f'<code>{bwt_worst.bluff_with_truth_count}</code> times bluffed while holding correct rank.'
        )

    # Hallucination vs strategic error breakdown
    hallucinations = [s for s in report.suboptimal_plays if s.failure_mode == "hallucination"]
    strategic = [s for s in report.suboptimal_plays if s.failure_mode == "strategic_error"]
    if hallucinations:
        h_models = set(s.model for s in hallucinations)
        items.append(
            f'<strong>Hand hallucinations:</strong> {len(hallucinations)} instances of models claiming '
            f'"I have no [rank]" while holding it — '
            f'{", ".join(names.get(m, m) for m in h_models)}.'
        )

    # Winner summary
    if report.finish_order:
        winner = report.finish_order[0]
        ws = report.model_stats.get(winner)
        if ws:
            items.append(
                f'<strong>{names.get(winner, winner)} won:</strong> '
                f'{ws.bluff_rate}% bluff rate, {ws.call_accuracy}% call accuracy, '
                f'out in {ws.total_plays} plays.'
            )

    return "\n".join(f'    <div class="insight-item">{item}</div>' for item in items)


_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>LLM Tourney — Bullshit Match Telemetry</title>
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@300;400;500;600;700&family=DM+Sans:wght@400;500;600&display=swap" rel="stylesheet">
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<style>
:root {
  --bg: #0a0a0f;
  --bg-card: #12121a;
  --border: #1e1e2e;
  --border-bright: #2a2a3e;
  --text: #e0e0e8;
  --text-dim: #6a6a80;
  --text-bright: #fff;
  --accent: #ff6b35;
}
* { margin:0; padding:0; box-sizing:border-box; }
body {
  background: var(--bg); color: var(--text);
  font-family: 'DM Sans', sans-serif; min-height: 100vh;
}
body::before {
  content:''; position:fixed; inset:0;
  background-image:
    linear-gradient(rgba(255,255,255,.02) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255,255,255,.02) 1px, transparent 1px);
  background-size: 40px 40px; pointer-events:none; z-index:0;
}
.container { position:relative; z-index:1; max-width:1400px; margin:0 auto; padding:40px 24px; }
.header { margin-bottom:48px; position:relative; }
.header::after {
  content:''; position:absolute; bottom:-24px; left:0;
  width:120px; height:3px; background:var(--accent); border-radius:2px;
}
.header h1 {
  font-family:'JetBrains Mono',monospace; font-size:32px; font-weight:700;
  color:var(--text-bright); letter-spacing:-.5px; margin-bottom:8px;
}
.header h1 span { color:var(--accent); }
.header .subtitle {
  font-family:'JetBrains Mono',monospace; font-size:13px;
  color:var(--text-dim); letter-spacing:.5px;
}
.scoreboard { display:grid; gap:12px; margin-bottom:40px; }
.score-card {
  background:var(--bg-card); border:1px solid var(--border);
  border-radius:12px; padding:16px; position:relative; overflow:hidden;
  transition: border-color .2s, transform .15s;
}
.score-card:hover { border-color:var(--border-bright); transform:translateY(-2px); }
.score-card .rank {
  position:absolute; top:8px; right:12px;
  font-family:'JetBrains Mono',monospace; font-size:36px;
  font-weight:700; opacity:.08; line-height:1;
}
.score-card .model-name {
  font-family:'JetBrains Mono',monospace; font-size:13px;
  font-weight:600; margin-bottom:8px; display:flex; align-items:center; gap:8px;
}
.score-card .model-dot { width:8px; height:8px; border-radius:50%; flex-shrink:0; }
.score-card .stats-row { display:flex; gap:12px; flex-wrap:wrap; }
.score-card .stat {
  font-size:11px; color:var(--text-dim); font-family:'JetBrains Mono',monospace;
}
.score-card .stat strong { color:var(--text); font-weight:600; }
.score-card .finish-tag {
  display:inline-block; font-family:'JetBrains Mono',monospace;
  font-size:10px; font-weight:600; padding:2px 6px; border-radius:4px;
  margin-bottom:6px; text-transform:uppercase; letter-spacing:.5px;
}
.chart-grid { display:grid; grid-template-columns:1fr 1fr; gap:20px; margin-bottom:20px; }
.chart-panel {
  background:var(--bg-card); border:1px solid var(--border);
  border-radius:12px; padding:24px;
}
.chart-panel.full-width { grid-column:1/-1; }
.chart-panel h3 {
  font-family:'JetBrains Mono',monospace; font-size:13px; font-weight:600;
  color:var(--text-bright); margin-bottom:4px; text-transform:uppercase; letter-spacing:.5px;
}
.chart-panel .chart-desc { font-size:12px; color:var(--text-dim); margin-bottom:16px; }
.chart-panel canvas { width:100%!important; max-height:300px; }
.chart-panel.tall canvas { max-height:400px; }
.bar-chart-custom { display:flex; flex-direction:column; gap:10px; }
.bar-row { display:grid; grid-template-columns:140px 1fr 60px; align-items:center; gap:12px; }
.bar-label {
  font-family:'JetBrains Mono',monospace; font-size:12px; color:var(--text);
  text-align:right; display:flex; align-items:center; justify-content:flex-end; gap:6px;
}
.bar-label .dot { width:6px; height:6px; border-radius:50%; flex-shrink:0; }
.bar-track {
  height:24px; background:rgba(255,255,255,.03); border-radius:4px;
  overflow:hidden; position:relative;
}
.bar-fill { height:100%; border-radius:4px; transition:width 1s ease; }
.bar-fill.striped {
  background-image:repeating-linear-gradient(-45deg,transparent,transparent 4px,rgba(0,0,0,.15) 4px,rgba(0,0,0,.15) 8px);
}
.bar-value {
  font-family:'JetBrains Mono',monospace; font-size:12px; color:var(--text-dim); font-weight:500;
}
.insights {
  background:var(--bg-card); border:1px solid var(--border);
  border-left:3px solid var(--accent); border-radius:0 12px 12px 0; padding:24px; margin-top:20px;
}
.insights h3 {
  font-family:'JetBrains Mono',monospace; font-size:13px; font-weight:600;
  color:var(--accent); margin-bottom:12px; text-transform:uppercase; letter-spacing:.5px;
}
.insight-item {
  font-size:14px; color:var(--text); margin-bottom:10px;
  padding-left:16px; position:relative; line-height:1.5;
}
.insight-item::before { content:'▸'; position:absolute; left:0; color:var(--accent); }
.insight-item code {
  font-family:'JetBrains Mono',monospace; font-size:12px;
  background:rgba(255,107,53,.1); color:var(--accent); padding:1px 5px; border-radius:3px;
}
@media(max-width:900px) { .chart-grid{grid-template-columns:1fr;} }
@keyframes fadeUp { from{opacity:0;transform:translateY(12px)} to{opacity:1;transform:translateY(0)} }
.chart-panel,.score-card,.insights { animation:fadeUp .5s ease both; }
.score-card:nth-child(1){animation-delay:.05s}
.score-card:nth-child(2){animation-delay:.1s}
.score-card:nth-child(3){animation-delay:.15s}
.score-card:nth-child(4){animation-delay:.2s}
.score-card:nth-child(5){animation-delay:.25s}
.score-card:nth-child(6){animation-delay:.3s}
.score-card:nth-child(7){animation-delay:.35s}
.score-card:nth-child(8){animation-delay:.4s}
.score-card:nth-child(9){animation-delay:.45s}
.score-card:nth-child(10){animation-delay:.5s}
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <h1>BULLSHIT<span>_</span>TELEMETRY</h1>
    <div class="subtitle" id="subtitle"></div>
  </div>
  <div class="scoreboard" id="scoreboard"></div>
  <div class="chart-grid">
    <div class="chart-panel full-width tall">
      <h3>Hand Size Over Time</h3>
      <div class="chart-desc">Card count per player across all plays. First to 0 wins.</div>
      <canvas id="trajectoryChart"></canvas>
    </div>
    <div class="chart-panel">
      <h3>Bluff Rate (Rolling 10)</h3>
      <div class="chart-desc">% of last 10 plays that were bluffs</div>
      <canvas id="bluffChart"></canvas>
    </div>
    <div class="chart-panel">
      <h3>BS Call Accuracy (Rolling 10)</h3>
      <div class="chart-desc">% of last 10 BS calls that were correct</div>
      <canvas id="callChart"></canvas>
    </div>
    <div class="chart-panel">
      <h3>Bluff When Holding Truth</h3>
      <div class="chart-desc">Times a model bluffed despite having matching rank cards</div>
      <div id="bluffTruthBars" class="bar-chart-custom"></div>
    </div>
    <div class="chart-panel">
      <h3>Challenge Frequency</h3>
      <div class="chart-desc">BS calls vs passes per model</div>
      <canvas id="challengeChart"></canvas>
    </div>
    <div class="chart-panel">
      <h3>Avg Response Latency</h3>
      <div class="chart-desc">Mean milliseconds per turn</div>
      <div id="latencyBars" class="bar-chart-custom"></div>
    </div>
    <div class="chart-panel">
      <h3>Output Verbosity</h3>
      <div class="chart-desc">Average output tokens per turn</div>
      <div id="verbosityBars" class="bar-chart-custom"></div>
    </div>
  </div>
  <div class="insights">
    <h3>Key Findings</h3>
<!--FINDINGS-->
  </div>
</div>
<script>
const D = /*DATA_PLACEHOLDER*/{};
const FINISH_LABELS = ['\u{1F947}','\u{1F948}','\u{1F949}','4th','5th','6th','7th','8th','9th','10th'];
const FINISH_COLORS = ['#fbbf24','#94a3b8','#d97706','#6b7280','#6b7280','#6b7280','#6b7280','#6b7280','#6b7280','#6b7280'];

Chart.defaults.color = '#6a6a80';
Chart.defaults.borderColor = '#1e1e2e';
Chart.defaults.font.family = "'JetBrains Mono', monospace";
Chart.defaults.font.size = 11;

const models = D.models;

// Subtitle
document.getElementById('subtitle').textContent =
  `${D.num_players}-Player Exhibition \u00b7 ${D.total_turns} turns \u00b7 ${D.total_plays} plays`;

// Scoreboard grid columns
const sb = document.getElementById('scoreboard');
sb.style.gridTemplateColumns = `repeat(${Math.min(models.length, 6)}, 1fr)`;

models.forEach(m => {
  const s = D.stats[m];
  const color = D.colors[m];
  const pos = s.finish_position;
  const card = document.createElement('div');
  card.className = 'score-card';
  const label = pos <= D.num_players - 2 ? 'OUT' : pos === D.num_players ? 'LAST' : pos + 'th';
  card.innerHTML = `
    <div class="rank">#${pos}</div>
    <div class="finish-tag" style="background:${FINISH_COLORS[pos-1]}22;color:${FINISH_COLORS[pos-1]}">${FINISH_LABELS[pos-1]} ${label}</div>
    <div class="model-name"><span class="model-dot" style="background:${color}"></span>${D.short_names[m]}</div>
    <div class="stats-row">
      <span class="stat">Bluff <strong>${s.bluff_rate}%</strong></span>
      <span class="stat">Caught <strong>${s.times_caught}\u00d7</strong></span>
      <span class="stat">Calls <strong>${s.bs_calls}</strong></span>
      <span class="stat">Acc <strong>${s.call_accuracy}%</strong></span>
    </div>`;
  sb.appendChild(card);
});

// Trajectory chart
const trajIdx = D.trajectory_indices.filter((_,i) => i%2===0);
new Chart(document.getElementById('trajectoryChart'), {
  type:'line',
  data: {
    labels: trajIdx,
    datasets: models.map(m => ({
      label: D.short_names[m],
      data: (D.card_trajectories[m]||[]).filter((_,i)=>i%2===0),
      borderColor: D.colors[m], borderWidth:2, pointRadius:0, tension:.3, fill:false,
    }))
  },
  options: {
    responsive:true, maintainAspectRatio:false,
    interaction:{mode:'index',intersect:false},
    plugins:{legend:{position:'top',labels:{usePointStyle:true,pointStyle:'circle',padding:16,font:{size:11}}}},
    scales:{
      x:{title:{display:true,text:'Play #',font:{size:11}},ticks:{maxTicksLimit:12},grid:{display:false}},
      y:{title:{display:true,text:'Cards in Hand',font:{size:11}},grid:{color:'#1e1e2e'},min:0}
    }
  }
});

// Bluff rate rolling
new Chart(document.getElementById('bluffChart'), {
  type:'line',
  data:{
    datasets: models.map(m => ({
      label:D.short_names[m],
      data:(D.bluff_timeline[m]||[]).map(([x,y])=>({x,y})),
      borderColor:D.colors[m], borderWidth:2, pointRadius:0, tension:.4,
    }))
  },
  options:{
    responsive:true,maintainAspectRatio:false,
    interaction:{mode:'nearest',intersect:false},
    plugins:{legend:{display:false}},
    scales:{
      x:{type:'linear',title:{display:true,text:'Play #',font:{size:11}},grid:{display:false}},
      y:{title:{display:true,text:'% Bluff',font:{size:11}},grid:{color:'#1e1e2e'},min:0,max:100,ticks:{callback:v=>v+'%'}}
    }
  }
});

// Call accuracy rolling
new Chart(document.getElementById('callChart'), {
  type:'line',
  data:{
    datasets: models.map(m => ({
      label:D.short_names[m],
      data:(D.call_timeline[m]||[]).map(([x,y])=>({x,y})),
      borderColor:D.colors[m], borderWidth:2, pointRadius:0, tension:.4,
    }))
  },
  options:{
    responsive:true,maintainAspectRatio:false,
    interaction:{mode:'nearest',intersect:false},
    plugins:{legend:{display:false}},
    scales:{
      x:{type:'linear',title:{display:true,text:'Call #',font:{size:11}},grid:{display:false}},
      y:{title:{display:true,text:'% Correct',font:{size:11}},grid:{color:'#1e1e2e'},min:0,max:100,ticks:{callback:v=>v+'%'}}
    }
  }
});

// Challenge frequency
new Chart(document.getElementById('challengeChart'), {
  type:'bar',
  data:{
    labels:models.map(m=>D.short_names[m]),
    datasets:[
      {label:'BS Calls',data:models.map(m=>(D.challenge_counts[m]||{}).calls||0),backgroundColor:models.map(m=>D.colors[m]),borderRadius:4},
      {label:'Passes',data:models.map(m=>(D.challenge_counts[m]||{}).passes||0),backgroundColor:models.map(m=>D.colors[m]+'30'),borderRadius:4}
    ]
  },
  options:{
    responsive:true,maintainAspectRatio:false,
    plugins:{legend:{position:'top',labels:{usePointStyle:true,font:{size:10}}}},
    scales:{x:{stacked:true,grid:{display:false},ticks:{font:{size:10}}},y:{stacked:true,grid:{color:'#1e1e2e'},title:{display:true,text:'Count',font:{size:11}}}}
  }
});

// Custom bars helper
function renderBars(id, data, unit) {
  const el = document.getElementById(id);
  const max = Math.max(...data.map(d=>d.value));
  data.forEach(({model,value,striped}) => {
    const pct = max ? (value/max)*100 : 0;
    const row = document.createElement('div');
    row.className = 'bar-row';
    row.innerHTML = `
      <div class="bar-label"><span class="dot" style="background:${D.colors[model]}"></span>${D.short_names[model]}</div>
      <div class="bar-track"><div class="bar-fill ${striped?'striped':''}" style="width:${pct}%;background:${D.colors[model]}"></div></div>
      <div class="bar-value">${Number.isInteger(value)?value:Math.round(value)}${unit}</div>`;
    el.appendChild(row);
  });
}

// Bluff-with-truth bars
const bwtData = models.map(m=>({model:m,value:(D.suboptimal_summary[m]||{}).total||0,striped:true})).sort((a,b)=>b.value-a.value);
renderBars('bluffTruthBars', bwtData, '\u00d7');

// Latency bars
const latData = models.map(m=>({model:m,value:D.stats[m].avg_latency_ms})).sort((a,b)=>b.value-a.value);
renderBars('latencyBars', latData, 'ms');

// Verbosity bars
const verbData = models.map(m=>({model:m,value:D.stats[m].avg_output_tokens})).sort((a,b)=>b.value-a.value);
renderBars('verbosityBars', verbData, ' tok');
</script>
</body>
</html>"""
