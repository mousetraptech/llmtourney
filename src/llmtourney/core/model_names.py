"""Model name normalization for consistent analytics.

Maps the various model identifiers found across YAML configs, JSONL
telemetry, and MongoDB documents to canonical display names.

Usage:
    from llmtourney.core.model_names import normalize

    normalize("anthropic/claude-sonnet-4.5")  # → "claude-sonnet-4.5"
    normalize("sonnet")                        # → "claude-sonnet-4.5"
    normalize("sonnet-a")                      # → "claude-sonnet-4.5"
    normalize("gemini-flash")                  # → "gemini-2.5-flash"

The canonical name is the short, human-readable form used in the
latest tier configs (heavyweight/midtier/budget brackets).

To add new aliases: just add entries to _ALIASES below.
"""

from __future__ import annotations

# ------------------------------------------------------------------
# Canonical names → list of known aliases
# ------------------------------------------------------------------
# The key is the canonical display name.
# The values are all known variants (YAML keys, OpenRouter model_ids,
# short names from older configs, etc.)
#
# Matching is case-insensitive. The canonical name itself is always
# included implicitly — you don't need to list it as an alias.

_CANONICAL: dict[str, list[str]] = {
    # --- Anthropic ---
    "claude-opus-4.6": [
        "anthropic/claude-opus-4.6",
        "opus-4.6", "opus",
    ],
    "claude-sonnet-4.5": [
        "anthropic/claude-sonnet-4.5",
        "anthropic/claude-sonnet-4-6",  # note: sonnet-4-6 is a different version string
        "sonnet-4.5", "sonnet", "sonnet-a",
        "claude-sonnet-4-6", "sonnet-4-6",
    ],
    "haiku-3.5": [
        "anthropic/claude-3.5-haiku",
        "haiku-3.5", "haiku",
    ],
    "haiku-4.5": [
        "anthropic/claude-haiku-4.5",
        "anthropic/claude-haiku-4-5",
        "haiku-4-5", "haiku-4.5",
    ],

    # --- OpenAI ---
    "gpt-5": [
        "openai/gpt-5",
    ],
    "gpt-4o": [
        "openai/gpt-4o",
    ],
    "gpt-4o-mini": [
        "openai/gpt-4o-mini",
    ],
    "o4-mini": [
        "openai/o4-mini",
    ],

    # --- Google ---
    "gemini-2.5-pro": [
        "google/gemini-2.5-pro",
    ],
    "gemini-2.5-flash": [
        "google/gemini-2.5-flash",
        "gemini-flash",
    ],
    "gemini-2.0-flash": [
        "google/gemini-2.0-flash-001",
        "google/gemini-2.0-flash",
    ],

    # --- DeepSeek ---
    "deepseek-r1": [
        "deepseek/deepseek-r1",
    ],
    "deepseek-v3.2": [
        "deepseek/deepseek-v3.2",
    ],
    "deepseek-v3": [
        "deepseek/deepseek-chat",
    ],

    # --- xAI ---
    "grok-3": [
        "x-ai/grok-3",
    ],
    "grok-3-mini": [
        "x-ai/grok-3-mini",
        "x-ai/grok-3-mini-beta",
    ],

    # --- Meta ---
    "llama-4-maverick": [
        "meta-llama/llama-4-maverick",
    ],
    "llama-4-scout": [
        "meta-llama/llama-4-scout",
        "meta-llama/llama-4-scout-instruct",
        "llama-scout",
    ],

    # --- Mistral ---
    "mistral-large-3": [
        "mistralai/mistral-large-2512",
        "mistral-large", "mistral",
    ],
    "mistral-medium-3.1": [
        "mistralai/mistral-medium-3.1",
    ],
    "mistral-small": [
        "mistralai/mistral-small-3.1-24b-instruct",
    ],

    # --- NVIDIA ---
    "nemotron-ultra": [
        "nvidia/llama-3.1-nemotron-ultra-253b-v1",
    ],

    # --- Amazon ---
    "nova-lite": [
        "amazon/nova-lite-v1",
    ],
    "nova-pro": [
        "amazon/nova-pro-v1",
    ],

    # --- Qwen ---
    "qwen3-235b": [
        "qwen/qwen3-235b-a22b",
    ],
    "qwen3-80b": [
        "qwen/qwen3-next-80b-a3b-instruct",
        "qwen3-next-80b",
    ],

    # --- Perplexity ---
    "sonar": [
        "perplexity/sonar",
    ],

    # --- Other ---
    "palmyra-x5": [
        "writer/palmyra-x5",
    ],
    "glm-4.7": [
        "thudm/glm-4.7",
    ],
}

# ------------------------------------------------------------------
# Build reverse lookup (alias → canonical) at import time
# ------------------------------------------------------------------

_ALIAS_MAP: dict[str, str] = {}

for canonical, aliases in _CANONICAL.items():
    _ALIAS_MAP[canonical.lower()] = canonical
    for alias in aliases:
        _ALIAS_MAP[alias.lower()] = canonical


def normalize(model_name: str) -> str:
    """Normalize a model identifier to its canonical display name.

    Returns the input unchanged if no mapping is found.
    """
    return _ALIAS_MAP.get(model_name.lower(), model_name)


def normalize_all(names: list[str]) -> list[str]:
    """Normalize a list of model names."""
    return [normalize(n) for n in names]


def canonical_names() -> list[str]:
    """Return all known canonical model names, sorted."""
    return sorted(_CANONICAL.keys())


def aliases_for(canonical: str) -> list[str]:
    """Return all known aliases for a canonical name."""
    return _CANONICAL.get(canonical, [])
