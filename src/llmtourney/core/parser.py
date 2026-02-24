"""ActionParser — extract and validate JSON actions from raw model output.

Finds the last valid JSON object in raw text, validates it against
a per-event JSON Schema, and flags prompt injection attempts.

Uses last-wins semantics: models that self-correct mid-output
(outputting a second JSON after "Wait, let me reconsider...") get
their final answer used, not their first draft.
"""

import json
import re
from dataclasses import dataclass

import jsonschema

from llmtourney.core.sanitizer import detect_injection

# Regex to find JSON objects in text — matches outermost { ... }
_JSON_OBJECT_RE = re.compile(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}")


@dataclass(frozen=True)
class ParseResult:
    """Result of parsing a model's raw output."""

    success: bool
    action: dict | None
    raw_json: str | None
    error: str | None
    injection_detected: bool


class ActionParser:
    """Extract last valid JSON object from text and validate against schema.

    Last-wins: when a model self-corrects mid-output, the final JSON
    is its intended action, not the first draft.
    """

    def parse(self, raw_text: str, schema: dict) -> ParseResult:
        injection = detect_injection(raw_text)

        candidates = _JSON_OBJECT_RE.findall(raw_text)

        if not candidates:
            return ParseResult(
                success=False,
                action=None,
                raw_json=None,
                error="No JSON object found in output",
                injection_detected=injection,
            )

        last_error = None
        best = None  # last valid (action, raw_json) pair

        for candidate in candidates:
            try:
                parsed = json.loads(candidate)
            except json.JSONDecodeError as e:
                last_error = f"JSON parse error: {e}"
                continue

            if not isinstance(parsed, dict):
                last_error = "JSON value is not an object"
                continue

            try:
                jsonschema.validate(parsed, schema)
            except jsonschema.ValidationError as e:
                last_error = f"Schema validation: {e.message}"
                continue

            best = (parsed, candidate)

        if best:
            return ParseResult(
                success=True,
                action=best[0],
                raw_json=best[1],
                error=None,
                injection_detected=injection,
            )

        return ParseResult(
            success=False,
            action=None,
            raw_json=candidates[0] if candidates else None,
            error=last_error,
            injection_detected=injection,
        )
