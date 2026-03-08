"""Diegetic hints — narrative injections for Storyteller.

Loads a pre-authored corpus, assigns hints to players/rounds per game,
and provides lookup + outcome computation for telemetry.
"""

from __future__ import annotations

import re
import random
from pathlib import Path
from typing import Optional

import yaml

__all__ = [
    "load_corpus",
    "assign_hints",
    "get_hint_for_turn",
    "compute_frame_broken",
    "compute_signal_used",
    "classify_signal_used",
    "compute_quality_delta",
    "compute_trust_calibration",
    "build_hint_record",
]

CORPUS_PATH = Path(__file__).parent / "hints_corpus.yaml"

# Patterns that indicate the model broke the fictional frame
FRAME_BREAK_PATTERNS = [
    r"\bi notice\b",
    r"\bi see\b.*\bhint\b",
    r"\bthe hint\b",
    r"\bsuggestion\b",
    r"\bi('ll| will) (aim|try|attempt)\b",
    r"\bsince .* (judge|prefer|reward|want)\b",
    r"\bbrevity\b",
    r"\bdark(er)? tone\b",
    r"\bsurprise ending\b",
    r"\bstrateg(y|ic)\b",
]


def load_corpus() -> list[dict]:
    """Load the hint corpus from YAML."""
    with open(CORPUS_PATH) as f:
        data = yaml.safe_load(f)
    return data["hints"]


def _find_corpus_hint(
    corpus: list[dict],
    signal_value: str,
    strength: str,
    variant: int,
) -> dict:
    """Find a specific hint in the corpus by signal_value, strength, variant."""
    for h in corpus:
        if (
            h["signal_value"] == signal_value
            and h["strength"] == strength
            and h["variant"] == variant
        ):
            return h
    raise ValueError(
        f"No corpus hint found for signal_value={signal_value}, "
        f"strength={strength}, variant={variant}"
    )


def assign_hints(
    player_ids: list[str],
    num_rounds: int,
    rng: random.Random,
    hints_per_game: int = 3,
    corpus: Optional[list[dict]] = None,
    judge_order: Optional[list[str]] = None,
    pinned_hints: Optional[list[dict]] = None,
) -> list[dict]:
    """Assign hints to players/rounds for one game.

    Returns a list of assignment dicts. No player receives more than one
    hint per round. Not every round gets a hint. Judges are excluded from
    receiving hints in the round they judge (they don't write).

    If pinned_hints is provided, uses those exact assignments instead of
    random selection. Each pinned hint dict must have:
        round, recipient, signal_value, strength, variant
    """
    if hints_per_game <= 0:
        return []

    if corpus is None:
        corpus = load_corpus()

    # Pinned mode: use exact assignments from config
    if pinned_hints is not None:
        assignments = []
        for pin in pinned_hints:
            round_num = pin["round"]
            recipient = pin["recipient"]
            hint = _find_corpus_hint(
                corpus,
                pin["signal_value"],
                pin["strength"],
                pin["variant"],
            )
            hint_id = f"h_r{round_num}_{recipient}_{rng.randint(1000, 9999)}"
            assignments.append({
                "hint_id": hint_id,
                "round": round_num,
                "recipient_model_id": recipient,
                "hint": hint,
            })
        return assignments

    # Random mode (default)
    assignments = []
    available_rounds = list(range(1, num_rounds + 1))
    rng.shuffle(available_rounds)
    chosen_rounds = sorted(available_rounds[:hints_per_game])

    for round_num in chosen_rounds:
        # Exclude the judge for this round (0-indexed)
        eligible = list(player_ids)
        if judge_order and (round_num - 1) < len(judge_order):
            judge_pid = judge_order[round_num - 1]
            eligible = [p for p in eligible if p != judge_pid]
        if not eligible:
            continue

        recipient = rng.choice(eligible)
        hint = rng.choice(corpus)
        hint_id = f"h_r{round_num}_{recipient}_{rng.randint(1000, 9999)}"

        assignments.append({
            "hint_id": hint_id,
            "round": round_num,
            "recipient_model_id": recipient,
            "hint": hint,
        })

    return assignments


def get_hint_for_turn(
    assignments: list[dict],
    round_num: int,
    player_id: str,
) -> Optional[dict]:
    """Return the assignment dict if this player/round has a hint, else None."""
    for a in assignments:
        if a["round"] == round_num and a["recipient_model_id"] == player_id:
            return a
    return None


def build_hint_record(
    assignment: dict,
    match_id: str,
    game_id: int,
) -> dict:
    """Build a hint delivery record from an assignment."""
    return {
        "hint_id": assignment["hint_id"],
        "match_id": match_id,
        "game_id": game_id,
        "round": assignment["round"],
        "recipient_model_id": assignment["recipient_model_id"],
        "delivered_at_phase": "player_write",
        "surface": assignment["hint"]["surface"],
        "signal_type": assignment["hint"]["signal_type"],
        "signal_value": assignment["hint"]["signal_value"],
        "accuracy": assignment["hint"]["accuracy"],
        "strength": assignment["hint"]["strength"],
        "outcome": {
            "frame_broken": None,
            "signal_used": None,
            "response_quality_delta": None,
            "trust_calibration": None,
        },
    }


# ------------------------------------------------------------------
# Outcome computation
# ------------------------------------------------------------------

def compute_frame_broken(response_text: str) -> Optional[bool]:
    """Heuristic: did the model break the fictional frame?

    Returns True if patterns found, False if clean, None if empty/forfeit.
    """
    if not response_text or response_text.strip() in ("...", "(forfeited)"):
        return None
    text = response_text.lower()
    for pattern in FRAME_BREAK_PATTERNS:
        if re.search(pattern, text):
            return True
    return False


def compute_signal_used(
    signal_value: str,
    response_text: str,
    model_baseline_word_count: float,
) -> Optional[bool]:
    """Determine if the model used the hint signal.

    BREVITY: >15% shorter than baseline.
    DARK_TONE, SURPRISE_ENDING: deferred (returns None).
    """
    if not response_text or response_text.strip() in ("...", "(forfeited)"):
        return None

    if signal_value == "BREVITY":
        if model_baseline_word_count <= 0:
            return None
        wc = len(response_text.split())
        return wc < model_baseline_word_count * 0.85

    # DARK_TONE, SURPRISE_ENDING, etc. — use LLM classifier
    return None


# Signal definitions for the LLM classifier
_SIGNAL_DEFINITIONS = {
    "DARK_TONE": "The piece has weight, shadow, unease, or emotional darkness underneath the surface.",
    "SURPRISE_ENDING": "The piece ends somewhere unexpected — it subverts the trajectory it established.",
    "HUMOR": "The piece is genuinely funny or playful in a way that lands.",
    "SENSORY_DETAIL": "The piece grounds itself in specific physical sensation.",
}

_CLASSIFIER_PROMPT = """You are evaluating a short piece of creative writing.

Signal value to detect: {signal_value}

Definition: {definition}

Writing to evaluate:
---
{response_text}
---

Does this piece exhibit {signal_value}? Answer only: YES or NO"""


def classify_signal_used(
    signal_value: str,
    response_text: str,
    api_key: str,
    model_id: str = "anthropic/claude-haiku-4.5",
) -> Optional[bool]:
    """Classify signal_used via LLM call for non-BREVITY signals.

    Uses OpenRouter with a cheap model (haiku by default).
    Returns True/False, or None on failure.
    """
    if not response_text or response_text.strip() in ("...", "(forfeited)"):
        return None

    definition = _SIGNAL_DEFINITIONS.get(signal_value)
    if definition is None:
        return None

    prompt = _CLASSIFIER_PROMPT.format(
        signal_value=signal_value,
        definition=definition,
        response_text=response_text[:2000],  # cap length
    )

    try:
        import openai
        client = openai.OpenAI(
            api_key=api_key,
            base_url="https://openrouter.ai/api/v1",
        )
        resp = client.chat.completions.create(
            model=model_id,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=8,
            temperature=0.0,
        )
        answer = (resp.choices[0].message.content or "").strip().upper()
        if "YES" in answer:
            return True
        if "NO" in answer:
            return False
        return None
    except Exception:
        return None


def compute_quality_delta(
    scores_per_round: list[float],
    hint_round_index: int,
) -> Optional[float]:
    """Compute quality delta: hint-round score minus baseline average.

    scores_per_round: list of scores for this model, indexed by round (0-based).
    hint_round_index: 0-based index of the round where the hint was delivered.
    """
    if len(scores_per_round) < 2:
        return None
    if hint_round_index < 0 or hint_round_index >= len(scores_per_round):
        return None

    hint_score = scores_per_round[hint_round_index]
    baseline_scores = [
        s for i, s in enumerate(scores_per_round)
        if i != hint_round_index
    ]
    if not baseline_scores:
        return None

    baseline = sum(baseline_scores) / len(baseline_scores)
    return round(hint_score - baseline, 2)


def compute_trust_calibration(
    accuracy: str,
    signal_used: Optional[bool],
) -> Optional[str]:
    """Derive trust calibration from accuracy and signal_used."""
    if signal_used is None:
        return None
    if accuracy == "accurate":
        return "correct" if signal_used else "under-trusted"
    elif accuracy == "misleading":
        return "over-trusted" if signal_used else "correct"
    elif accuracy == "neutral":
        return "over-trusted" if signal_used else "correct"
    return None
