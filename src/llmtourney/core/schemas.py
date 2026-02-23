"""Schema loading utility."""

import json
from pathlib import Path


def load_schema(path: Path) -> dict:
    """Load a JSON Schema file and return as dict."""
    with open(path) as f:
        return json.load(f)
