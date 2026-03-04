#!/usr/bin/env python3
"""S2 Champions Bracket — comprehensive telemetry analysis."""

import json
import os
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import seaborn as sns

ROOT = Path(__file__).resolve().parent.parent
TEL = ROOT / "output" / "telemetry"
OUT = ROOT / "output" / "analysis" / "s2-champions"
OUT.mkdir(parents=True, exist_ok=True)

# ── Telemetry file map ──────────────────────────────────────────────
ROUNDS = {
    "R1_Holdem": TEL / "holdem-grok-3-mini-vs-claude-opus-4.6-vs-claude-sonnet-4.5-vs-deepseek-chat-vs-grok-3-vs-gpt-4o-vs-gpt-4o-mini-vs-haiku-4.5-8a302f.jsonl",
    "R2_Storyteller": TEL / "storyteller-grok-3-mini-vs-claude-opus-4.6-vs-claude-sonnet-4.5-vs-deepseek-chat-vs-grok-3-vs-gpt-4o-vs-gpt-4o-mini-vs-haiku-4.5-e55536.jsonl",
    "R3_RollerDerby": TEL / "rollerderby-grok-3-mini-vs-claude-opus-4.6-vs-claude-sonnet-4.5-vs-deepseek-chat-vs-grok-3-vs-gpt-4o-vs-gpt-4o-mini-vs-haiku-4.5-641789.jsonl",
    "R4_Gauntlet": TEL / "gauntlet-grok-3-mini-vs-claude-opus-4.6-vs-claude-sonnet-4.5-vs-deepseek-chat-vs-grok-3-vs-gpt-4o-vs-gpt-4o-mini-vs-haiku-4.5-a1c437.jsonl",
    "R5_LiarsDice": TEL / "liarsdice-grok-3-mini-vs-claude-opus-4.6-vs-claude-sonnet-4.5-vs-deepseek-chat-vs-grok-3-vs-gpt-4o-vs-gpt-4o-mini-vs-haiku-4.5-24b697.jsonl",
    "R6_Holdem_Finale": TEL / "holdem-grok-3-mini-vs-claude-opus-4.6-vs-claude-sonnet-4.5-vs-deepseek-chat-vs-grok-3-vs-gpt-4o-vs-gpt-4o-mini-vs-haiku-4.5-9055e7.jsonl",
}

# Model display names (strip provider prefixes)
MODEL_NAMES = {
    "xai/grok-3-mini": "grok-3-mini",
    "xai/grok-3": "grok-3",
    "openai/gpt-4o": "gpt-4o",
    "openai/gpt-4o-mini": "gpt-4o-mini",
    "anthropic/claude-sonnet-4.5": "sonnet-4.5",
    "anthropic/claude-opus-4.6": "opus-4.6",
    "deepseek/deepseek-chat": "deepseek",
    "anthropic/haiku-4.5": "haiku-4.5",
    # With version suffixes
    "anthropic/claude-haiku-4-5": "haiku-4.5",
    "claude-haiku-4-5": "haiku-4.5",
    # Fallbacks without provider
    "grok-3-mini": "grok-3-mini",
    "grok-3": "grok-3",
    "gpt-4o": "gpt-4o",
    "gpt-4o-mini": "gpt-4o-mini",
    "claude-sonnet-4.5": "sonnet-4.5",
    "claude-opus-4.6": "opus-4.6",
    "deepseek-chat": "deepseek",
    "haiku-4.5": "haiku-4.5",
}

MODEL_COLORS = {
    "sonnet-4.5": "#E07B39",
    "opus-4.6": "#D4533B",
    "haiku-4.5": "#F5B041",
    "gpt-4o": "#10A37F",
    "gpt-4o-mini": "#6BCB77",
    "grok-3": "#1DA1F2",
    "grok-3-mini": "#7EC8E3",
    "deepseek": "#9B59B6",
}

MODEL_ORDER = ["sonnet-4.5", "opus-4.6", "haiku-4.5", "gpt-4o", "gpt-4o-mini", "grok-3", "grok-3-mini", "deepseek"]


def clean_model(raw: str) -> str:
    return MODEL_NAMES.get(raw, raw.split("/")[-1] if "/" in raw else raw)


def load_telemetry(path: Path) -> tuple[list[dict], dict | None]:
    """Load JSONL, return (turns, match_summary)."""
    turns = []
    summary = None
    with open(path) as f:
        for line in f:
            entry = json.loads(line)
            if entry.get("record_type") == "match_summary":
                summary = entry
            else:
                turns.append(entry)
    return turns, summary


def load_all() -> dict[str, tuple[list[dict], dict]]:
    """Load all round telemetry."""
    data = {}
    for rnd, path in ROUNDS.items():
        if path.exists():
            turns, summary = load_telemetry(path)
            data[rnd] = (turns, summary)
            print(f"  Loaded {rnd}: {len(turns)} turns")
        else:
            print(f"  MISSING {rnd}: {path}")
    return data


# ═══════════════════════════════════════════════════════════════════
# 1. CHIP STACK TIME SERIES — R6 Hold'em Finale
# ═══════════════════════════════════════════════════════════════════
def chip_stack_time_series(data: dict):
    print("\n[1] Chip Stack Time Series — R6 Hold'em Finale")
    turns, summary = data["R6_Holdem_Finale"]
    player_models = summary["player_models"]

    # Extract stacks at start of each hand (first turn entry per hand)
    hand_stacks = {}  # hand_number -> {player_id: chips}
    seen_hands = set()
    for t in turns:
        hand = t.get("hand_number", 0)
        if hand not in seen_hands:
            snap = t.get("state_snapshot", {})
            stacks = snap.get("stacks", {})
            if stacks:
                hand_stacks[hand] = dict(stacks)
                seen_hands.add(hand)

    if not hand_stacks:
        print("  No stack data found!")
        return

    max_hand = max(hand_stacks.keys())
    hands = sorted(hand_stacks.keys())

    # Also extract final stacks from match_summary
    final_scores = summary.get("final_scores", {})

    # Build plotly figure
    fig = go.Figure()
    for pid, model_raw in sorted(player_models.items(), key=lambda x: x[1]):
        model = clean_model(model_raw)
        color = MODEL_COLORS.get(model, "#888888")
        y_vals = []
        x_vals = []
        for h in hands:
            chips = hand_stacks[h].get(pid, 0)
            x_vals.append(h)
            y_vals.append(chips)
        fig.add_trace(go.Scatter(
            x=x_vals, y=y_vals,
            mode='lines+markers',
            name=model,
            line=dict(color=color, width=2.5),
            marker=dict(size=3),
            hovertemplate=f"<b>{model}</b><br>Hand %{{x}}<br>Chips: %{{y:,}}<extra></extra>"
        ))

    fig.update_layout(
        title=dict(text="S2 Champions R6 — Hold'em Finale Chip Stacks", font=dict(size=20)),
        xaxis_title="Hand Number",
        yaxis_title="Chip Count",
        template="plotly_dark",
        width=1200, height=600,
        legend=dict(x=1.02, y=1, font=dict(size=12)),
        hovermode="x unified",
    )
    fig.add_hline(y=0, line_dash="dash", line_color="red", opacity=0.3)

    out_path = OUT / "r6-chip-stacks.html"
    fig.write_html(str(out_path), include_plotlyjs='cdn')
    print(f"  Saved: {out_path}")

    # Also do R1 for comparison
    turns1, summary1 = data["R1_Holdem"]
    pm1 = summary1["player_models"]
    hand_stacks1 = {}
    seen1 = set()
    for t in turns1:
        hand = t.get("hand_number", 0)
        if hand not in seen1:
            snap = t.get("state_snapshot", {})
            stacks = snap.get("stacks", {})
            if stacks:
                hand_stacks1[hand] = dict(stacks)
                seen1.add(hand)

    hands1 = sorted(hand_stacks1.keys())
    fig1 = go.Figure()
    for pid, model_raw in sorted(pm1.items(), key=lambda x: x[1]):
        model = clean_model(model_raw)
        color = MODEL_COLORS.get(model, "#888888")
        y_vals = [hand_stacks1[h].get(pid, 0) for h in hands1]
        fig1.add_trace(go.Scatter(
            x=hands1, y=y_vals,
            mode='lines+markers',
            name=model,
            line=dict(color=color, width=2.5),
            marker=dict(size=3),
            hovertemplate=f"<b>{model}</b><br>Hand %{{x}}<br>Chips: %{{y:,}}<extra></extra>"
        ))

    fig1.update_layout(
        title=dict(text="S2 Champions R1 — Hold'em (75 hands, equal stacks)", font=dict(size=20)),
        xaxis_title="Hand Number",
        yaxis_title="Chip Count",
        template="plotly_dark",
        width=1200, height=600,
        legend=dict(x=1.02, y=1, font=dict(size=12)),
        hovermode="x unified",
    )
    fig1.write_html(str(OUT / "r1-chip-stacks.html"), include_plotlyjs='cdn')
    print(f"  Saved: {OUT / 'r1-chip-stacks.html'}")


# ═══════════════════════════════════════════════════════════════════
# 2. DECISION TIME ANALYSIS
# ═══════════════════════════════════════════════════════════════════
def decision_time_analysis(data: dict):
    print("\n[2] Decision Time Analysis")
    rows = []
    for rnd, (turns, summary) in data.items():
        pm = summary["player_models"] if summary else {}
        for t in turns:
            lat = t.get("latency_ms")
            pid = t.get("player_id", "")
            model_raw = t.get("model_id", pm.get(pid, "unknown"))
            if lat and lat > 0:
                rows.append({
                    "round": rnd,
                    "model": clean_model(model_raw),
                    "latency_ms": lat,
                })

    df = pd.DataFrame(rows)
    if df.empty:
        print("  No latency data!")
        return

    # Stats table
    stats = df.groupby(["model", "round"])["latency_ms"].agg(
        mean="mean", median="median", p95=lambda x: np.percentile(x, 95), count="count"
    ).reset_index()
    stats = stats.round(0)

    # Pivot for display
    mean_pivot = stats.pivot(index="model", columns="round", values="mean").reindex(
        index=MODEL_ORDER
    ).reindex(columns=sorted(ROUNDS.keys()))
    mean_pivot.to_csv(str(OUT / "latency-mean-by-model-event.csv"))

    p95_pivot = stats.pivot(index="model", columns="round", values="p95").reindex(
        index=MODEL_ORDER
    ).reindex(columns=sorted(ROUNDS.keys()))
    p95_pivot.to_csv(str(OUT / "latency-p95-by-model-event.csv"))

    # Heatmap — mean latency
    fig, axes = plt.subplots(1, 2, figsize=(20, 6))
    for ax, pivot, title in [
        (axes[0], mean_pivot, "Mean Latency (ms)"),
        (axes[1], p95_pivot, "P95 Latency (ms)")
    ]:
        sns.heatmap(
            pivot.astype(float), annot=True, fmt=".0f", cmap="YlOrRd",
            ax=ax, linewidths=0.5, cbar_kws={"label": "ms"}
        )
        ax.set_title(title, fontsize=14)
        ax.set_xlabel("")
        ax.set_ylabel("")
        plt.setp(ax.get_xticklabels(), rotation=30, ha='right')

    plt.suptitle("S2 Champions — Decision Time by Model × Event", fontsize=16, y=1.02)
    plt.tight_layout()
    plt.savefig(str(OUT / "latency-heatmap.png"), dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  Saved: latency-heatmap.png, latency-mean-by-model-event.csv, latency-p95-by-model-event.csv")

    # Overall model latency summary
    overall = df.groupby("model")["latency_ms"].agg(
        mean="mean", median="median", p95=lambda x: np.percentile(x, 95),
        p99=lambda x: np.percentile(x, 99), count="count"
    ).round(0).reindex(MODEL_ORDER)
    overall.to_csv(str(OUT / "latency-overall-by-model.csv"))
    print(f"  Saved: latency-overall-by-model.csv")
    print(overall.to_string())


# ═══════════════════════════════════════════════════════════════════
# 3. VIOLATION ANALYSIS
# ═══════════════════════════════════════════════════════════════════
def violation_analysis(data: dict):
    print("\n[3] Violation Analysis")
    rows = []
    for rnd, (turns, summary) in data.items():
        pm = summary["player_models"] if summary else {}
        total_turns_in_round = len(turns)
        for i, t in enumerate(turns):
            viol = t.get("violation")
            if viol:
                pid = t.get("player_id", "")
                model_raw = t.get("model_id", pm.get(pid, "unknown"))
                turn_num = t.get("turn_number", i)
                hand_num = t.get("hand_number", 0)
                # Classify timing: early/mid/late (by position in round)
                progress = i / max(total_turns_in_round, 1)
                phase = "early" if progress < 0.33 else ("mid" if progress < 0.66 else "late")
                rows.append({
                    "round": rnd,
                    "model": clean_model(model_raw),
                    "violation_type": viol,
                    "turn_number": turn_num,
                    "hand_number": hand_num,
                    "phase": phase,
                })

    if not rows:
        print("  No violations found!")
        return

    df = pd.DataFrame(rows)

    # Violations per model per event
    viol_counts = df.groupby(["model", "round"]).size().reset_index(name="violations")
    viol_pivot = viol_counts.pivot(index="model", columns="round", values="violations").fillna(0).astype(int)
    viol_pivot = viol_pivot.reindex(index=MODEL_ORDER, fill_value=0).reindex(columns=sorted(ROUNDS.keys()), fill_value=0)
    viol_pivot["TOTAL"] = viol_pivot.sum(axis=1)
    viol_pivot.to_csv(str(OUT / "violations-by-model-event.csv"))

    # Violation types
    viol_types = df.groupby(["model", "violation_type"]).size().reset_index(name="count")
    viol_type_pivot = viol_types.pivot(index="model", columns="violation_type", values="count").fillna(0).astype(int)
    viol_type_pivot.to_csv(str(OUT / "violations-by-type.csv"))

    # Violations by phase
    phase_counts = df.groupby(["model", "phase"]).size().reset_index(name="count")
    phase_pivot = phase_counts.pivot(index="model", columns="phase", values="count").fillna(0).astype(int)
    phase_pivot = phase_pivot.reindex(columns=["early", "mid", "late"], fill_value=0)
    phase_pivot.to_csv(str(OUT / "violations-by-phase.csv"))

    # Plot
    fig, axes = plt.subplots(1, 2, figsize=(16, 6))

    # Violations by event
    sns.heatmap(
        viol_pivot.drop(columns=["TOTAL"]).astype(float), annot=True, fmt=".0f",
        cmap="Reds", ax=axes[0], linewidths=0.5
    )
    axes[0].set_title("Violations by Model × Event", fontsize=13)
    axes[0].set_xlabel("")
    plt.setp(axes[0].get_xticklabels(), rotation=30, ha='right')

    # Violations by phase
    phase_reindexed = phase_pivot.reindex(index=MODEL_ORDER, fill_value=0)
    sns.heatmap(
        phase_reindexed.astype(float), annot=True, fmt=".0f",
        cmap="Oranges", ax=axes[1], linewidths=0.5
    )
    axes[1].set_title("Violations by Model × Phase", fontsize=13)
    axes[1].set_xlabel("")

    plt.suptitle("S2 Champions — Violation Analysis", fontsize=16, y=1.02)
    plt.tight_layout()
    plt.savefig(str(OUT / "violations-heatmap.png"), dpi=150, bbox_inches="tight")
    plt.close()

    print(f"  Saved: violations-by-model-event.csv, violations-by-type.csv, violations-by-phase.csv, violations-heatmap.png")
    print(viol_pivot.to_string())


# ═══════════════════════════════════════════════════════════════════
# 4. HOLD'EM BEHAVIORAL SIGNATURES
# ═══════════════════════════════════════════════════════════════════
def holdem_behavioral_signatures(data: dict):
    print("\n[4] Hold'em Behavioral Signatures")

    results = {}
    for rnd_name in ["R1_Holdem", "R6_Holdem_Finale"]:
        turns, summary = data[rnd_name]
        pm = summary["player_models"]

        # Per-model accumulators
        model_stats = defaultdict(lambda: {
            "preflop_decisions": 0,
            "preflop_folds": 0,
            "bets_raises": 0,
            "calls": 0,
            "checks": 0,
            "folds_total": 0,
            "total_actions": 0,
            "pots_involved": [],  # pot sizes when model acted
            "showdown_losses_with_aggression": 0,  # proxy for bluffs
            "latencies": [],
        })

        for t in turns:
            pid = t.get("player_id", "")
            model = clean_model(pm.get(pid, t.get("model_id", "unknown")))
            action = t.get("parsed_action", {})
            street = t.get("street", "")
            snap = t.get("state_snapshot", {})
            lat = t.get("latency_ms", 0)

            if not action or not isinstance(action, dict):
                continue

            act_type = action.get("action", "").lower()
            stats = model_stats[model]
            stats["total_actions"] += 1
            if lat > 0:
                stats["latencies"].append(lat)

            pot = snap.get("pot", 0)
            if pot > 0:
                stats["pots_involved"].append(pot)

            if street == "preflop":
                stats["preflop_decisions"] += 1
                if act_type == "fold":
                    stats["preflop_folds"] += 1

            if act_type in ("bet", "raise"):
                stats["bets_raises"] += 1
            elif act_type == "call":
                stats["calls"] += 1
            elif act_type == "check":
                stats["checks"] += 1
            elif act_type == "fold":
                stats["folds_total"] += 1

        results[rnd_name] = model_stats

    # Build summary table
    rows = []
    for rnd_name, model_stats in results.items():
        for model in MODEL_ORDER:
            s = model_stats.get(model, {
                "preflop_decisions": 0, "preflop_folds": 0,
                "bets_raises": 0, "calls": 0, "folds_total": 0,
                "total_actions": 0, "pots_involved": [],
            })
            pf_dec = s.get("preflop_decisions", 0)
            pf_fold = s.get("preflop_folds", 0)
            bets = s.get("bets_raises", 0)
            calls = s.get("calls", 0)
            total = s.get("total_actions", 0)
            pots = s.get("pots_involved", [])

            fold_rate = (pf_fold / pf_dec * 100) if pf_dec > 0 else 0
            agg_factor = (bets / calls) if calls > 0 else bets  # AF = (bets+raises)/calls
            avg_pot = np.mean(pots) if pots else 0
            vpip = ((pf_dec - pf_fold) / pf_dec * 100) if pf_dec > 0 else 0

            rows.append({
                "round": rnd_name.replace("_", " "),
                "model": model,
                "preflop_fold_%": round(fold_rate, 1),
                "VPIP_%": round(vpip, 1),
                "aggression_factor": round(agg_factor, 2),
                "bets_raises": bets,
                "calls": calls,
                "avg_pot_involved": round(avg_pot, 0),
                "total_actions": total,
            })

    df = pd.DataFrame(rows)
    df.to_csv(str(OUT / "holdem-behavioral-signatures.csv"), index=False)

    # Plot: grouped bar chart for key metrics
    fig = make_subplots(
        rows=2, cols=2,
        subplot_titles=["Preflop Fold %", "VPIP %", "Aggression Factor", "Avg Pot When Involved"],
        vertical_spacing=0.15, horizontal_spacing=0.1
    )

    for rnd_name in ["R1 Holdem", "R6 Holdem Finale"]:
        rdf = df[df["round"] == rnd_name]
        color = "#E07B39" if "R1" in rnd_name else "#1DA1F2"
        dash = None if "R1" in rnd_name else "dash"

        metrics = [
            (1, 1, "preflop_fold_%"),
            (1, 2, "VPIP_%"),
            (2, 1, "aggression_factor"),
            (2, 2, "avg_pot_involved"),
        ]
        for row, col, metric in metrics:
            fig.add_trace(go.Bar(
                x=rdf["model"], y=rdf[metric],
                name=rnd_name,
                marker_color=color,
                opacity=0.8,
                showlegend=(row == 1 and col == 1),
            ), row=row, col=col)

    fig.update_layout(
        title="S2 Champions — Hold'em Behavioral Signatures (R1 vs R6)",
        template="plotly_dark",
        width=1200, height=800,
        barmode="group",
    )
    fig.write_html(str(OUT / "holdem-behavioral-signatures.html"), include_plotlyjs='cdn')
    print(f"  Saved: holdem-behavioral-signatures.csv, holdem-behavioral-signatures.html")
    print(df.to_string(index=False))


# ═══════════════════════════════════════════════════════════════════
# 5. CROSS-EVENT CORRELATION MATRIX
# ═══════════════════════════════════════════════════════════════════
def cross_event_correlation(data: dict):
    print("\n[5] Cross-Event Correlation Matrix")

    # Collect hybrid scores from match summaries
    score_table = {}  # model -> {round -> score}
    for rnd, (turns, summary) in data.items():
        if not summary:
            continue
        pm = summary["player_models"]
        scores = summary.get("final_scores", {})
        for pid, model_raw in pm.items():
            model = clean_model(model_raw)
            score = scores.get(pid, 0)
            if model not in score_table:
                score_table[model] = {}
            score_table[model][rnd] = score

    df = pd.DataFrame(score_table).T
    df = df.reindex(index=MODEL_ORDER, columns=sorted(ROUNDS.keys()))
    df.to_csv(str(OUT / "cross-event-scores.csv"))

    # Compute pairwise event correlations
    corr = df.corr()
    corr.to_csv(str(OUT / "event-correlation-matrix.csv"))

    # Heatmap
    fig, axes = plt.subplots(1, 2, figsize=(18, 6))

    # Score table
    sns.heatmap(
        df.astype(float), annot=True, fmt=".0f", cmap="YlGnBu",
        ax=axes[0], linewidths=0.5, cbar_kws={"label": "Score"}
    )
    axes[0].set_title("Raw Scores by Model × Event", fontsize=13)
    axes[0].set_xlabel("")
    plt.setp(axes[0].get_xticklabels(), rotation=30, ha='right')

    # Correlation matrix
    mask = np.triu(np.ones_like(corr, dtype=bool), k=1)
    sns.heatmap(
        corr, annot=True, fmt=".2f", cmap="RdBu_r", center=0,
        ax=axes[1], linewidths=0.5, vmin=-1, vmax=1,
        mask=mask
    )
    axes[1].set_title("Event Pairwise Correlation", fontsize=13)
    plt.setp(axes[1].get_xticklabels(), rotation=30, ha='right')

    plt.suptitle("S2 Champions — Cross-Event Analysis", fontsize=16, y=1.02)
    plt.tight_layout()
    plt.savefig(str(OUT / "cross-event-correlation.png"), dpi=150, bbox_inches="tight")
    plt.close()

    # Cumulative standings
    cumulative = df.sum(axis=1).sort_values(ascending=False)
    cumulative.name = "cumulative_score"
    cumulative.to_csv(str(OUT / "cumulative-standings.csv"))

    print(f"  Saved: cross-event-scores.csv, event-correlation-matrix.csv, cross-event-correlation.png, cumulative-standings.csv")
    print("\nCumulative Standings:")
    print(cumulative.to_string())
    print("\nEvent Correlations:")
    print(corr.to_string())


# ═══════════════════════════════════════════════════════════════════
# SUMMARY REPORT
# ═══════════════════════════════════════════════════════════════════
def generate_summary(data: dict):
    print("\n[Summary] Generating markdown report")

    lines = ["# S2 Champions Bracket — Telemetry Analysis\n"]
    lines.append(f"Generated: 2026-03-04\n")
    lines.append("## Rounds\n")
    lines.append("| Round | Event | Status |")
    lines.append("|-------|-------|--------|")
    for rnd in sorted(ROUNDS.keys()):
        status = "Complete" if rnd in data else "Missing"
        lines.append(f"| {rnd} | {rnd.split('_',1)[1]} | {status} |")

    # Cumulative standings from scores
    score_table = {}
    hybrid_scores = {}
    for rnd, (turns, summary) in data.items():
        if not summary:
            continue
        pm = summary["player_models"]
        scores = summary.get("final_scores", {})
        for pid, model_raw in pm.items():
            model = clean_model(model_raw)
            score_table.setdefault(model, {})[rnd] = scores.get(pid, 0)

    # Also compute hybrid normalized for this summary
    for rnd in sorted(ROUNDS.keys()):
        rnd_scores = {}
        for model in MODEL_ORDER:
            rnd_scores[model] = score_table.get(model, {}).get(rnd, 0)
        # hybrid_normalize: 50 placement + 50 proportion
        sorted_models = sorted(rnd_scores.items(), key=lambda x: -x[1])
        n = len(sorted_models)
        total_raw = sum(v for _, v in sorted_models)
        for rank, (model, raw) in enumerate(sorted_models):
            placement_pts = 50 * (n - rank) / n if n > 0 else 0
            proportion_pts = 50 * (raw / total_raw) if total_raw > 0 else 0
            hybrid = placement_pts + proportion_pts
            hybrid_scores.setdefault(model, {})[rnd] = round(hybrid, 1)

    lines.append("\n## Cumulative Standings (Hybrid Scores)\n")
    lines.append("| Model | " + " | ".join(sorted(ROUNDS.keys())) + " | TOTAL |")
    lines.append("|-------|" + "|".join(["------"] * (len(ROUNDS) + 1)) + "|")

    cumulative = {}
    for model in MODEL_ORDER:
        scores = hybrid_scores.get(model, {})
        total = sum(scores.values())
        cumulative[model] = total
        row = f"| {model} | " + " | ".join(str(scores.get(r, 0)) for r in sorted(ROUNDS.keys())) + f" | **{total:.1f}** |"
        lines.append(row)

    # Sort by total
    champion = max(cumulative, key=cumulative.get)
    lines.append(f"\n**Champion: {champion}** ({cumulative[champion]:.1f} pts)\n")

    lines.append("\n## Output Files\n")
    for f in sorted(OUT.glob("*")):
        lines.append(f"- `{f.name}`")

    report = "\n".join(lines)
    report_path = OUT / "REPORT.md"
    report_path.write_text(report)
    print(f"  Saved: {report_path}")
    return report


# ═══════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════
def main():
    print("S2 Champions Bracket — Telemetry Analysis")
    print("=" * 50)

    print("\nLoading telemetry...")
    data = load_all()

    if not data:
        print("No data found!")
        sys.exit(1)

    chip_stack_time_series(data)
    decision_time_analysis(data)
    violation_analysis(data)
    holdem_behavioral_signatures(data)
    cross_event_correlation(data)
    report = generate_summary(data)

    print("\n" + "=" * 50)
    print("Analysis complete! Output in:", OUT)
    print("=" * 50)


if __name__ == "__main__":
    main()
