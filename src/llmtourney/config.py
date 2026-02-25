"""Tournament configuration loader."""

import yaml
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ModelConfig:
    name: str
    provider: str  # "mock", "openai", "anthropic", "openrouter"
    model_id: str | None = None
    strategy: str | None = None  # for mock provider
    api_key_env: str | None = None      # env var name for API key
    base_url: str | None = None         # custom API base URL
    site_url: str | None = None         # OpenRouter attribution
    app_name: str | None = None         # OpenRouter attribution
    temperature: float = 0.0
    max_output_tokens: int = 256
    timeout_s: float = 30.0


@dataclass
class EventConfig:
    name: str
    weight: int
    hands_per_match: int = 100
    starting_stack: int = 200
    blinds: tuple[int, int] = (1, 2)
    rounds: int = 1
    games_per_match: int = 9


@dataclass
class ComputeCaps:
    max_output_tokens: int = 256
    timeout_s: float = 30.0


@dataclass
class TournamentConfig:
    name: str
    seed: int
    version: str
    format: str = "round_robin"
    models: dict[str, ModelConfig] = field(default_factory=dict)
    events: dict[str, EventConfig] = field(default_factory=dict)
    compute_caps: ComputeCaps = field(default_factory=ComputeCaps)
    output_dir: Path | None = None


def load_config(path: Path) -> TournamentConfig:
    """Load tournament config from YAML file."""
    with open(path) as f:
        raw = yaml.safe_load(f)

    t = raw["tournament"]
    compute = raw.get("compute_caps", {})

    models = {}
    for name, m in raw.get("models", {}).items():
        models[name] = ModelConfig(
            name=name,
            provider=m["provider"],
            model_id=m.get("model_id"),
            strategy=m.get("strategy"),
            api_key_env=m.get("api_key_env"),
            base_url=m.get("base_url"),
            site_url=m.get("site_url"),
            app_name=m.get("app_name"),
            temperature=m.get("temperature", 0.0),
            max_output_tokens=m.get(
                "max_output_tokens", compute.get("max_output_tokens", 256)
            ),
            timeout_s=m.get("timeout_s", compute.get("timeout_s", 30.0)),
        )

    events = {}
    for name, e in raw.get("events", {}).items():
        blinds = tuple(e["blinds"]) if "blinds" in e else (1, 2)
        events[name] = EventConfig(
            name=name,
            weight=e["weight"],
            hands_per_match=e.get("hands_per_match", 100),
            starting_stack=e.get("starting_stack", 200),
            blinds=blinds,
            rounds=e.get("rounds", 1),
            games_per_match=e.get("games_per_match", 9),
        )

    return TournamentConfig(
        name=t["name"],
        seed=t["seed"],
        version=t["version"],
        format=t.get("format", "round_robin"),
        models=models,
        events=events,
        compute_caps=ComputeCaps(
            max_output_tokens=compute.get("max_output_tokens", 256),
            timeout_s=compute.get("timeout_s", 30.0),
        ),
    )
