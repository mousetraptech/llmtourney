"""Text sanitization and prompt injection detection.

All model outputs pass through sanitize_text before entering any game engine.
Injection detection flags suspicious patterns but never blocks — the flag
is logged and the action is still processed if otherwise valid.
"""

import re

# Control chars to strip (keep \t=0x09, \n=0x0a, \r=0x0d)
_CONTROL_RE = re.compile(
    r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]"
)

# Zero-width and BOM characters
_ZERO_WIDTH_RE = re.compile(
    r"[\u200b\u200c\u200d\u2060\ufeff\u00ad]"
)

# Injection patterns — case-insensitive
_INJECTION_PATTERNS = [
    re.compile(r"ignore\s+previous\s+instructions", re.IGNORECASE),
    re.compile(r"<\s*system\s*>", re.IGNORECASE),
    re.compile(r"\[\s*INST\s*\]", re.IGNORECASE),
    re.compile(r'"role"\s*:\s*"system"', re.IGNORECASE),
    re.compile(r"you\s+are\s+now\s+(a|an|the|free|unbound)", re.IGNORECASE),
    re.compile(r"new\s+instructions?\s*:", re.IGNORECASE),
    re.compile(r"disregard\s+(all\s+)?previous", re.IGNORECASE),
    re.compile(r"<\s*/?\s*human\s*>", re.IGNORECASE),
    re.compile(r"<\s*/?\s*assistant\s*>", re.IGNORECASE),
]


def sanitize_text(text: str) -> str:
    """Strip control characters and zero-width chars. Preserves normal unicode."""
    text = _CONTROL_RE.sub("", text)
    text = _ZERO_WIDTH_RE.sub("", text)
    return text


def detect_injection(text: str) -> bool:
    """Check if text contains prompt injection patterns.

    Returns True if suspicious, False if clean.
    This is a heuristic — false positives are possible but rare.
    """
    return any(p.search(text) for p in _INJECTION_PATTERNS)
