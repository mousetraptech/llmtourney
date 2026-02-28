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
    blind_schedule: list[tuple[int, int, int]] | None = None  # [(hand, small, big), ...]
    rounds: int = 1
    games_per_match: int = 9
    mode: str = "attrition"


@dataclass
class ComputeCaps:
    max_output_tokens: int = 256
    timeout_s: float = 30.0


@dataclass
class ShotClockConfig:
    default_ms: int  # e.g. 30000
    model_overrides: dict[str, int] = field(default_factory=dict)


@dataclass
class ForfeitEscalationConfig:
    turn_forfeit_threshold: int = 1  # 1 = no retries
    match_forfeit_threshold: int = 3  # turn forfeits → match forfeit
    strike_violations: list[str] = field(
        default_factory=lambda: ["timeout", "empty_response"]
    )
    match_forfeit_scaling: bool = True  # scale threshold up for 7+ players


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
    shot_clock: ShotClockConfig | None = None
    forfeit_escalation: ForfeitEscalationConfig | None = None


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
        # Parse blind schedule: {hand_number: [small, big], ...}
        blind_schedule = None
        bs_raw = e.get("blind_schedule")
        if bs_raw:
            blind_schedule = sorted(
                (int(hand), sb, bb) for hand, (sb, bb) in bs_raw.items()
            )
        events[name] = EventConfig(
            name=name,
            weight=e["weight"],
            hands_per_match=e.get("hands_per_match", 100),
            starting_stack=e.get("starting_stack", 200),
            blinds=blinds,
            blind_schedule=blind_schedule,
            rounds=e.get("rounds", 1),
            games_per_match=e.get("games_per_match", 9),
            mode=e.get("mode", "attrition"),
        )

    # Parse optional shot clock config
    shot_clock = None
    sc_raw = raw.get("shot_clock")
    if sc_raw:
        shot_clock = ShotClockConfig(
            default_ms=sc_raw["default_ms"],
            model_overrides=sc_raw.get("model_overrides", {}),
        )

    # Parse optional forfeit escalation config
    forfeit_escalation = None
    fe_raw = raw.get("forfeit_escalation")
    if fe_raw:
        forfeit_escalation = ForfeitEscalationConfig(
            turn_forfeit_threshold=fe_raw.get("turn_forfeit_threshold", 1),
            match_forfeit_threshold=fe_raw.get("match_forfeit_threshold", 3),
            strike_violations=fe_raw.get(
                "strike_violations",
                ["timeout", "empty_response"],
            ),
            match_forfeit_scaling=fe_raw.get("match_forfeit_scaling", True),
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
        shot_clock=shot_clock,
        forfeit_escalation=forfeit_escalation,
    )
